# -*- coding: utf-8 -*-
"""日志与版本。"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

__version__ = "0.1.0-p0"

# Windows 控制台 UTF-8 保险
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_LOG_FILE: Optional[str] = None
_LOCK = threading.Lock()


def set_log_file(path) -> None:
    global _LOG_FILE
    _LOG_FILE = str(path) if path else None


def _write_log_file(line: str) -> None:
    if not _LOG_FILE:
        return
    try:
        Path(_LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:  # noqa: BLE001
        pass


def log(tag: str, msg: str, seconds: Optional[float] = None) -> None:
    """带时间戳的阶段日志；seconds 非空则附耗时；GUI 模式同时写文件。"""
    t = time.strftime("%H:%M:%S")
    suffix = f" ({seconds:.2f}s)" if seconds is not None else ""
    line = f"[{t}] [{tag:<3}] {msg}{suffix}"
    if sys.stdout is not None:
        try:
            with _LOCK:
                print(line, flush=True)
        except Exception:  # noqa: BLE001
            pass
    _write_log_file(line)
