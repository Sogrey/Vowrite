# -*- coding: utf-8 -*-
"""录音。"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .logutil import log


@dataclass
class Recorder:
    """16kHz 单声道录音；start/stop 线程安全，超时自动收尾。"""

    sample_rate: int
    channels: int
    max_duration: float
    on_timeout: Callable[[], None]

    _stream: object = field(default=None, repr=False)
    _frames: list = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _recording: bool = field(default=False, repr=False)

    def start(self) -> None:
        import sounddevice as sd

        with self._lock:
            if self._recording:
                return
            self._frames = []
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                callback=self._on_data,
            )
            self._stream.start()
            self._recording = True

    def _on_data(self, data, frames: int, time_info, status) -> None:
        if status:
            log("AUD", f"音频流警告: {status}")
        with self._lock:
            if self._recording:
                self._frames.append(data.copy())
            total = sum(len(f) for f in self._frames)
        if total / self.sample_rate >= self.max_duration:
            if not self._recording:
                return
            self._recording = False
            log("AUD", f"已达最长录音 {self.max_duration}s，自动收尾")
            try:
                self.on_timeout()
            except Exception:
                pass

    def stop(self):
        """停止录音并返回音频数组；未在录音时返回 None。"""
        import numpy as np

        with self._lock:
            if not self._recording:
                return None
            self._recording = False
            stream, self._stream = self._stream, None

        try:
            stream.stop()
            stream.close()
        except Exception:
            pass

        with self._lock:
            frames, self._frames = self._frames, []
        if not frames:
            return None
        audio = np.concatenate(frames)
        return audio.reshape(-1) if audio.ndim > 1 else audio

    @property
    def is_recording(self) -> bool:
        with self._lock:
            return self._recording
