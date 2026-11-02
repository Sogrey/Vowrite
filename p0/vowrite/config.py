# -*- coding: utf-8 -*-
"""配置加载。"""

from __future__ import annotations

import shutil
from pathlib import Path

from .logutil import log

PACKAGE_DIR = Path(__file__).resolve().parent
# p0/ 目录：config.toml、fixtures、GUI 同级
ROOT_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = ROOT_DIR.parent

DEFAULT_CONFIG_NAME = "config.toml"
EXAMPLE_CONFIG_NAME = "config.example.toml"
# 兼容旧代码：SCRIPT_DIR == p0/
SCRIPT_DIR = ROOT_DIR


def _resolve_example_config() -> Path:
    for base in (ROOT_DIR, PROJECT_ROOT):
        p = base / EXAMPLE_CONFIG_NAME
        if p.exists():
            return p
    return PROJECT_ROOT / EXAMPLE_CONFIG_NAME


def load_config(path: Path) -> dict:
    """加载 TOML 配置；不存在时自动从 example 复制一份。"""
    import tomllib

    if not path.exists():
        example = _resolve_example_config()
        if example.exists():
            shutil.copy(example, path)
            log("CFG", f"未找到 {path}，已从 {example} 复制，请按需修改")
        else:
            raise FileNotFoundError(f"找不到配置文件: {path}")

    with open(path, "rb") as f:
        raw = tomllib.load(f)

    raw.setdefault("trigger", {"key": "right ctrl", "mode": "hold"})
    raw.setdefault("audio", {"sample_rate": 16000, "channels": 1,
                             "min_duration": 0.4, "max_duration": 120})
    raw.setdefault("asr", {"engine": "local", "language": "zh", "model": "small",
                           "device": "auto", "compute_type": "auto",
                           "hf_endpoint": "https://hf-mirror.com",
                           "cuda_dll_dirs": []})
    raw["asr"].setdefault("api", {"base_url": "", "api_key": "", "model": "whisper-1"})
    raw.setdefault("llm", {"enabled": True, "base_url": "http://127.0.0.1:8090/v1",
                           "api_key": "sk-no-key", "model": "qwen",
                           "mode": "polish", "style": "light", "timeout": 20})
    raw["llm"].setdefault("server", {"enabled": False, "auto_start": False,
                                     "exe": "", "model": "", "args": "-ngl 99 -c 2048",
                                     "host": "127.0.0.1", "port": 8090})
    raw.setdefault("inject", {"enabled": True, "pause_ms": 120,
                              "restore_clipboard": True, "restore_delay_ms": 80})
    raw["inject"].setdefault("restore_clipboard", True)
    raw["inject"].setdefault("restore_delay_ms", 80)
    return raw
