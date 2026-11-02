# -*- coding: utf-8 -*-
"""主管线：按住录音 → 队列处理 → ASR → LLM → 注入。"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from typing import Callable, Optional

from .asr import build_transcriber
from .audio import Recorder
from .inject import Injector
from .llm import Polisher
from .logutil import __version__, log
from .metrics import record_latency

STATE_IDLE = "IDLE"
STATE_RECORDING = "RECORDING"
STATE_PROCESSING = "PROCESSING"


class Vowrite:
    def __init__(self, cfg: dict, inject_enabled: Optional[bool] = None,
                 style_override: Optional[str] = None, need_asr: bool = True,
                 mode_override: Optional[str] = None) -> None:
        self.cfg = cfg
        self._phase = STATE_IDLE  # IDLE | RECORDING（录音互斥）
        self._state_lock = threading.Lock()
        self._t_press: float = 0.0
        self._worker_busy = False
        self._audio_queue: queue.Queue = queue.Queue()
        self._worker_started = False
        self._hook = None
        self._hook_installed = False

        audio_cfg = cfg["audio"]
        self.recorder = Recorder(
            sample_rate=int(audio_cfg["sample_rate"]),
            channels=int(audio_cfg["channels"]),
            max_duration=float(audio_cfg["max_duration"]),
            on_timeout=self._handle_release,
        )
        self.min_duration = float(audio_cfg["min_duration"])
        self.transcriber = build_transcriber(cfg["asr"]) if need_asr else None
        self.polisher = Polisher(cfg["llm"], style_override=style_override,
                                 mode_override=mode_override)
        self.injector = Injector(cfg["inject"], enabled_override=inject_enabled)
        self.trigger_key: str = str(cfg["trigger"]["key"]).strip().lower()
        self.on_notify: Optional[Callable[[str, str], None]] = None

    # -- 对外状态（GUI 读 self.state）------------------------------------------

    @property
    def state(self) -> str:
        with self._state_lock:
            if self._phase == STATE_RECORDING:
                return STATE_RECORDING
            if self._worker_busy or not self._audio_queue.empty():
                return STATE_PROCESSING
            return STATE_IDLE

    @state.setter
    def state(self, value: str) -> None:
        # 兼容旧代码直接赋值；仅映射录音相位
        with self._state_lock:
            if value == STATE_RECORDING:
                self._phase = STATE_RECORDING
            else:
                self._phase = STATE_IDLE

    def _notify(self, title: str, message: str) -> None:
        if self.on_notify is None:
            return
        try:
            self.on_notify(title, message)
        except Exception:  # noqa: BLE001
            pass

    def _set_phase(self, phase: str) -> None:
        with self._state_lock:
            self._phase = phase

    def _get_phase(self) -> str:
        with self._state_lock:
            return self._phase

    # -- 键盘 ----------------------------------------------------------------

    def on_key_down(self, event) -> None:
        if event.event_type != "down":
            return
        if not self._key_matches(event):
            return
        # 处理中仍可叠录下一段；仅禁止重复进入录音
        if self._get_phase() == STATE_RECORDING:
            return
        self._set_phase(STATE_RECORDING)
        self._t_press = time.perf_counter()
        log("TRG", f"按下 {self.trigger_key}，开始录音（松开结束）…")
        try:
            self.recorder.start()
        except Exception as e:  # noqa: BLE001
            log("TRG", f"启动录音失败: {e}")
            self._set_phase(STATE_IDLE)

    def on_key_up(self, event) -> None:
        if event.event_type != "up":
            return
        if not self._key_matches(event):
            return
        if self._get_phase() != STATE_RECORDING:
            return
        self._handle_release()

    def _key_matches(self, event) -> bool:
        name = (getattr(event, "name", "") or "").strip().lower()
        return name == self.trigger_key

    def _handle_release(self) -> None:
        if self._get_phase() != STATE_RECORDING:
            return
        hold_s = time.perf_counter() - self._t_press
        audio = None
        try:
            audio = self.recorder.stop()
        except Exception as e:  # noqa: BLE001
            log("AUD", f"停止录音异常: {e}")
        self._set_phase(STATE_IDLE)

        if audio is None:
            log("TRG", "未采集到音频，复位")
            return
        duration = len(audio) / self.recorder.sample_rate
        log("TRG", f"松开（按住 {hold_s:.1f}s，有效语音 {duration:.1f}s）")
        if duration < self.min_duration:
            log("TRG", f"时长不足 {self.min_duration}s，视为误触，已忽略")
            return
        self._audio_queue.put(audio)
        qsize = self._audio_queue.qsize()
        if qsize > 1:
            log("TRG", f"已入队，当前队列 {qsize} 段")
        self._ensure_worker()

    def _ensure_worker(self) -> None:
        with self._state_lock:
            if self._worker_started:
                return
            self._worker_started = True
        threading.Thread(target=self._worker_loop, daemon=True).start()

    def _worker_loop(self) -> None:
        while True:
            audio = self._audio_queue.get()
            try:
                with self._state_lock:
                    self._worker_busy = True
                self._process(audio)
            finally:
                with self._state_lock:
                    self._worker_busy = False
                self._audio_queue.task_done()

    def _process(self, audio) -> None:
        t_all = time.perf_counter()
        asr_s = llm_s = inject_s = None
        audio_s = len(audio) / self.recorder.sample_rate
        ok_all = False
        try:
            t0 = time.perf_counter()
            raw = self.transcriber.transcribe(audio)
            asr_s = time.perf_counter() - t0
            log("ASR", f"转写: {raw or '（空）'}", asr_s)
            if not raw:
                log("TRG", "未识别到有效语音内容（可能被置信度过滤），本次跳过")
                return

            t1 = time.perf_counter()
            polished = self.polisher.polish(raw)
            llm_s = time.perf_counter() - t1
            if polished != raw and raw:
                log("OUT", f"结果: {polished}")

            t2 = time.perf_counter()
            ok = self.injector.inject(polished)
            inject_s = time.perf_counter() - t2
            if not ok:
                self._notify("Vowrite", "注入失败，文字已留在剪贴板，请手动 Ctrl+V")
            ok_all = bool(ok)
            log("END", "本次完成", time.perf_counter() - t_all)
        except Exception:  # noqa: BLE001
            log("ERR", "处理失败: " + traceback.format_exc(limit=3))
            self._notify("Vowrite", "处理失败，详见日志")
        finally:
            record_latency(
                asr_s=asr_s, llm_s=llm_s, inject_s=inject_s,
                total_s=time.perf_counter() - t_all,
                mode=self.polisher.mode, audio_s=audio_s, ok=ok_all,
            )

    def process_text(self, text: str) -> None:
        t_all = time.perf_counter()
        t1 = time.perf_counter()
        polished = self.polisher.polish(text)
        llm_s = time.perf_counter() - t1
        log("OUT", f"结果: {polished}")
        t2 = time.perf_counter()
        ok = self.injector.inject(polished)
        inject_s = time.perf_counter() - t2
        if not ok:
            self._notify("Vowrite", "注入失败，文字已留在剪贴板，请手动 Ctrl+V")
        record_latency(
            asr_s=None, llm_s=llm_s, inject_s=inject_s,
            total_s=time.perf_counter() - t_all,
            mode=self.polisher.mode, audio_s=None, ok=bool(ok),
            extra={"source": "message"},
        )

    def start(self) -> None:
        if self._hook_installed:
            return
        import keyboard

        if self.polisher.mode == "chat":
            mode_desc = "口述问题，AI 答案落光标"
        elif self.polisher.mode == "raw":
            mode_desc = "纯转写落光标（LLM 不参与，零幻觉零延迟）"
        else:
            mode_desc = "把你说的话打成干净文字（替代打字）"
        log("APP", f"Vowrite v{__version__} 监听中 [mode={self.polisher.mode}] — "
                  f"按住 [{self.trigger_key}] 说话，{mode_desc}")
        self._hook = keyboard.hook(self._on_keyboard_event, suppress=False)
        self._hook_installed = True

    def stop(self) -> None:
        if not self._hook_installed:
            return
        try:
            import keyboard

            if self._hook is not None:
                keyboard.unhook(self._hook)
            else:
                keyboard.unhook_all()
        except Exception:  # noqa: BLE001
            pass
        self._hook = None
        self._hook_installed = False

    def apply_runtime_config(self) -> None:
        self.trigger_key = str(self.cfg["trigger"]["key"]).strip().lower()
        self.polisher.style = self.cfg["llm"].get("style", self.polisher.style)
        self.polisher.mode = self.cfg["llm"].get("mode", self.polisher.mode)
        self.polisher.timeout = float(self.cfg["llm"].get("timeout", self.polisher.timeout))
        self.injector.enabled = bool(self.cfg["inject"].get("enabled", True))
        self.injector.pause_ms = float(self.cfg["inject"].get("pause_ms", 120))
        self.injector.restore_clipboard = bool(
            self.cfg["inject"].get("restore_clipboard", True))
        self.injector.restore_delay_ms = float(
            self.cfg["inject"].get("restore_delay_ms", 80))
        log("APP", f"热更新生效：trigger={self.trigger_key}, mode={self.polisher.mode}, "
                  f"style={self.polisher.style}")

    def run(self) -> None:
        self.start()
        try:
            while True:
                time.sleep(0.5)
        except KeyboardInterrupt:
            log("APP", "收到退出信号，清理…")
        finally:
            self.stop()

    def _on_keyboard_event(self, event) -> None:
        etype = getattr(event, "event_type", "")
        if etype == "down":
            self.on_key_down(event)
        elif etype == "up":
            self.on_key_up(event)
