# -*- coding: utf-8 -*-
"""延迟埋点：追加写入 .temp/latency.jsonl。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from .config import PROJECT_ROOT
from .logutil import log

DEFAULT_LATENCY_PATH = PROJECT_ROOT / ".temp" / "latency.jsonl"


def record_latency(
    *,
    asr_s: Optional[float] = None,
    llm_s: Optional[float] = None,
    inject_s: Optional[float] = None,
    total_s: Optional[float] = None,
    mode: str = "",
    audio_s: Optional[float] = None,
    ok: bool = True,
    extra: Optional[dict[str, Any]] = None,
    path: Optional[Path] = None,
) -> None:
    """追加一条端到端分段耗时记录（失败不影响主流程）。"""
    target = path or DEFAULT_LATENCY_PATH
    row: dict[str, Any] = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok": ok,
        "mode": mode,
        "asr_s": None if asr_s is None else round(asr_s, 4),
        "llm_s": None if llm_s is None else round(llm_s, 4),
        "inject_s": None if inject_s is None else round(inject_s, 4),
        "total_s": None if total_s is None else round(total_s, 4),
        "audio_s": None if audio_s is None else round(audio_s, 4),
    }
    if extra:
        row.update(extra)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception as e:  # noqa: BLE001
        log("MET", f"写入延迟埋点失败: {e}")
