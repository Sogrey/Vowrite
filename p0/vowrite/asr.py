# -*- coding: utf-8 -*-
"""ASR：本地 faster-whisper / 云端 API。"""

from __future__ import annotations

import io
import os
import time
import wave
from pathlib import Path
from typing import Optional

from .logutil import log

HALLUCINATION_FINGERPRINTS = (
    "优优独播", "独播剧场", "yoyo television", "字幕由", "字幕制作", "字幕提供",
    "字幕志愿者", "听译", "校对", "时间轴", "仅供学习", "禁止商用",
    "明镜需要您的支持", "收看订阅明镜", "欢迎收看订阅",
    "follow us", "please subscribe", "subscribe to", "thank you for watching",
    "thanks for watching", "enjoy the video", "like and subscribe",
    "谢谢观看", "请订阅", "关注我们", "百度百科", "维基百科",
    "amara.org", "opensubtitles", "原始发布",
)
MAX_SPEECH_RATE = 12.0


def _hallucination_check(text: str, seg, fingerprints: tuple) -> tuple:
    low = text.lower()
    for fp in fingerprints:
        if fp in low:
            return True, f"命中幻觉指纹「{fp}」"
    span = max(0.3, float(getattr(seg, "end", 1.0)) - float(getattr(seg, "start", 0.0)))
    rate = len(text) / span
    if rate > MAX_SPEECH_RATE:
        return True, f"语速异常({rate:.1f}字/秒, 时长{span:.1f}s)"
    return False, ""


def _inject_cuda_dll_dirs(asr_cfg: dict) -> list:
    dirs = asr_cfg.get("cuda_dll_dirs") or []
    injected = []
    for d in dirs:
        p = Path(d)
        if p.is_dir():
            try:
                os.add_dll_directory(str(p))
                os.environ["PATH"] = str(p) + os.pathsep + os.environ.get("PATH", "")
                injected.append(str(p))
            except Exception as e:  # noqa: BLE001
                log("ASR", f"注入 DLL 目录失败 {d}: {e}")
        else:
            log("ASR", f"cuda_dll_dirs 目录不存在，已跳过: {d}")
    if dirs:
        log("ASR", f"已注入 {len(injected)}/{len(dirs)} 个 CUDA DLL 目录")
    return injected


class LocalWhisperTranscriber:
    """本地 faster-whisper。DLL 注入 → 预热 → CUDA 失败降 CPU。"""

    def __init__(self, asr_cfg: dict) -> None:
        self._injected_dll_dirs = _inject_cuda_dll_dirs(asr_cfg)
        hf_endpoint = asr_cfg.get("hf_endpoint") or ""
        if hf_endpoint:
            os.environ.setdefault("HF_ENDPOINT", hf_endpoint)
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

        from faster_whisper import WhisperModel

        self._asr_cfg = asr_cfg
        self.language: str = asr_cfg.get("language", "zh")
        extra = asr_cfg.get("hallucination_fingerprints") or []
        self.fingerprints = tuple(HALLUCINATION_FINGERPRINTS) + tuple(
            str(x).strip().lower() for x in extra if str(x).strip())
        model_size: str = asr_cfg.get("model", "small")
        device: str = asr_cfg.get("device", "auto")
        compute_type: str = asr_cfg.get("compute_type", "auto")

        if device == "auto":
            if compute_type == "auto":
                candidates = [("cuda", "float16"), ("cpu", "int8")]
            else:
                candidates = [("cuda", compute_type), ("cpu", "int8")]
        else:
            ct = ("float16" if device == "cuda" else "int8") \
                if compute_type == "auto" else compute_type
            candidates = [(device, ct)]

        self.model = None
        self.device = self.compute_type = ""
        last_err: Optional[Exception] = None
        for dev, ct in candidates:
            try:
                t0 = time.perf_counter()
                model = WhisperModel(model_size, device=dev, compute_type=ct)
                self._warmup(model)
                self.model, self.device, self.compute_type = model, dev, ct
                log("ASR", f"faster-whisper [{model_size}] 就绪: device={dev}, compute={ct}",
                    time.perf_counter() - t0)
                break
            except Exception as e:  # noqa: BLE001
                last_err = e
                log("ASR", f"初始化/预热失败 device={dev}: {e}，尝试回退…")
        if self.model is None:
            raise RuntimeError(f"本地 ASR 引擎初始化失败: {last_err}")

    @staticmethod
    def _warmup(model) -> None:
        import numpy as np

        sr = 16000
        t = np.arange(int(sr * 0.6)) / sr
        tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")
        model.transcribe(tone, beam_size=1)

    def _rebuild_cpu(self) -> None:
        from faster_whisper import WhisperModel

        model_size = self._asr_cfg.get("model", "small")
        t0 = time.perf_counter()
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self.device, self.compute_type = "cpu", "int8"
        log("ASR", "已降级重建 CPU int8 引擎", time.perf_counter() - t0)

    def transcribe(self, audio) -> str:
        try:
            return self._do_transcribe(audio)
        except Exception as e:  # noqa: BLE001
            if self.device == "cuda":
                log("ASR", f"CUDA 推理失败（{e}），降级 CPU 重试")
                self._rebuild_cpu()
                return self._do_transcribe(audio)
            raise

    def _do_transcribe(self, audio) -> str:
        duration_s = float(len(audio)) / 16000.0 if hasattr(audio, "__len__") else 0.0
        beam = 3 if duration_s < 4.0 else 5
        kwargs = {"vad_filter": True, "beam_size": beam}
        if self.language and self.language != "auto":
            kwargs["language"] = self.language
        segments, _info = self.model.transcribe(audio, **kwargs)
        parts = []
        for seg in segments:
            text = seg.text.strip()
            if seg.avg_logprob < -1.25:
                log("ASR", f"丢弃低置信片段({seg.avg_logprob:.2f}): {text}")
                continue
            if getattr(seg, "no_speech_prob", 0.0) > 0.6 and seg.avg_logprob < -0.8:
                log("ASR", f"丢弃无语音片段(prob={seg.no_speech_prob:.2f}): {text}")
                continue
            bad, reason = _hallucination_check(text, seg, self.fingerprints)
            if bad:
                log("ASR", f"丢弃幻觉片段({reason}): {text}")
                continue
            parts.append(text)
        return "".join(parts).strip()


class ApiTranscriber:
    """OpenAI 兼容 /audio/transcriptions。"""

    def __init__(self, asr_cfg: dict) -> None:
        api = asr_cfg.get("api", {})
        self.base_url: str = (api.get("base_url") or "").rstrip("/")
        self.api_key: str = api.get("api_key") or ""
        self.model: str = api.get("model") or "whisper-1"
        self.language: str = asr_cfg.get("language", "zh")
        if not self.base_url:
            raise ValueError("engine='api' 需要在 [asr.api] 配置 base_url")

    @staticmethod
    def _to_wav_bytes(audio, sample_rate: int) -> bytes:
        import numpy as np

        pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2")
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sample_rate)
            w.writeframes(pcm.tobytes())
        return buf.getvalue()

    def transcribe(self, audio, sample_rate: int = 16000) -> str:
        import requests

        data = {"model": self.model}
        if self.language and self.language != "auto":
            data["language"] = self.language
        resp = requests.post(
            f"{self.base_url}/audio/transcriptions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            files={"file": ("audio.wav", self._to_wav_bytes(audio, sample_rate), "audio/wav")},
            data=data,
            timeout=60,
        )
        resp.raise_for_status()
        body = resp.json()
        if "text" in body:
            return str(body["text"]).strip()
        return "".join(s.get("text", "") for s in body.get("segments", [])).strip()


def build_transcriber(asr_cfg: dict):
    engine = (asr_cfg.get("engine") or "local").lower()
    if engine == "local":
        return LocalWhisperTranscriber(asr_cfg)
    if engine == "api":
        return ApiTranscriber(asr_cfg)
    raise ValueError(f"未知 ASR 引擎: {engine}（可选 local / api）")
