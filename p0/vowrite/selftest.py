# -*- coding: utf-8 -*-
"""自检。"""

from __future__ import annotations

import time

from .asr import build_transcriber
from .llm import Polisher
from .logutil import __version__, log


def self_test(cfg: dict, full: bool, inject_enabled: bool) -> bool:
    log("TEST", f"Vowrite v{__version__} 自检{'（完整模式）' if full else ''} 开始")
    ok = True

    try:
        import keyboard  # noqa: F401
        import numpy  # noqa: F401
        import pyautogui  # noqa: F401
        import pyperclip  # noqa: F401
        import requests  # noqa: F401
        import sounddevice  # noqa: F401
        log("TEST", "PASS — 依赖导入（keyboard/sounddevice/numpy/pyperclip/pyautogui/requests）")
    except Exception as e:  # noqa: BLE001
        ok = False
        log("TEST", f"FAIL — 依赖导入: {e}")
        return ok

    asr_cfg, llm_cfg = cfg["asr"], cfg["llm"]
    log("TEST", f"配置: engine={asr_cfg['engine']}, model={asr_cfg.get('model')}, "
                f"lang={asr_cfg['language']}, mode={llm_cfg.get('mode', 'polish')}, "
                f"style={llm_cfg['style']}, llm={llm_cfg['base_url']}, "
                f"inject={'on' if inject_enabled else 'off'}")

    try:
        import sounddevice as sd

        dev = sd.query_devices(kind="input")
        log("TEST", f"PASS — 输入设备: {dev['name']}（默认 {dev['default_samplerate']}Hz）")
    except Exception as e:  # noqa: BLE001
        ok = False
        log("TEST", f"FAIL — 未找到可用输入设备: {e}")

    try:
        import pyperclip

        backup = pyperclip.paste()
        token = f"vowrite-selftest-{int(time.time())}"
        pyperclip.copy(token)
        passed = pyperclip.paste() == token
        if isinstance(backup, str) and backup:
            pyperclip.copy(backup)
        log("TEST", "PASS — 剪贴板读写" if passed else "FAIL — 剪贴板写入后读回不一致")
        ok = ok and passed
    except Exception as e:  # noqa: BLE001
        ok = False
        log("TEST", f"FAIL — 剪贴板: {e}")

    polisher = Polisher(llm_cfg)
    if polisher.enabled:
        reachable, detail = polisher.probe()
        log("TEST", f"{'PASS' if reachable else 'WARN'} — LLM {polisher.base_url}: {detail}")
    else:
        log("TEST", "SKIP — LLM 已关闭（enabled=false），输出将不做润色")

    if full:
        try:
            import numpy as np

            t0 = time.perf_counter()
            transcriber = build_transcriber(asr_cfg)
            log("TEST", "PASS — ASR 引擎加载", time.perf_counter() - t0)
            sr = int(cfg["audio"]["sample_rate"])
            t = np.arange(int(sr * 1.5)) / sr
            tone = (0.2 * np.sin(2 * np.pi * 440 * t)).astype("float32")
            t1 = time.perf_counter()
            text = transcriber.transcribe(tone)
            log("TEST", f"PASS — 合成音频转写链路（输出: {text or '（空，符合预期）'}）",
                time.perf_counter() - t1)
        except Exception as e:  # noqa: BLE001
            ok = False
            log("TEST", f"FAIL — ASR 引擎: {e}")

    log("TEST", "自检结束：" + ("有失败项，请先处理再使用" if not ok else "全部通过"))
    return ok
