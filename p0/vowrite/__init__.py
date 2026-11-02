# -*- coding: utf-8 -*-
"""Vowrite 核心包：录音 → ASR → LLM → 注入。"""

from .app import STATE_IDLE, STATE_PROCESSING, STATE_RECORDING, Vowrite
from .asr import HALLUCINATION_FINGERPRINTS, build_transcriber
from .config import SCRIPT_DIR, load_config
from .llm import FEWSHOT_FINGERPRINTS, Polisher
from .logutil import __version__, log, set_log_file
from .selftest import self_test

__all__ = [
    "STATE_IDLE",
    "STATE_PROCESSING",
    "STATE_RECORDING",
    "Vowrite",
    "HALLUCINATION_FINGERPRINTS",
    "FEWSHOT_FINGERPRINTS",
    "Polisher",
    "SCRIPT_DIR",
    "build_transcriber",
    "load_config",
    "log",
    "set_log_file",
    "self_test",
    "__version__",
]
