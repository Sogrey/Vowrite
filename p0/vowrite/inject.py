# -*- coding: utf-8 -*-
"""剪贴板注入。"""

from __future__ import annotations

import time
from typing import Optional

from .logutil import log


class Injector:
    """写剪贴板 + 模拟 Ctrl+V；默认粘贴后恢复原剪贴板。"""

    def __init__(self, inject_cfg: dict, enabled_override: Optional[bool] = None) -> None:
        self.enabled: bool = enabled_override if enabled_override is not None \
            else bool(inject_cfg.get("enabled", True))
        self.pause_ms: float = float(inject_cfg.get("pause_ms", 120))
        self.restore_clipboard: bool = bool(inject_cfg.get("restore_clipboard", True))
        self.restore_delay_ms: float = float(inject_cfg.get("restore_delay_ms", 80))

    def inject(self, text: str) -> bool:
        import pyperclip

        backup = None
        if self.enabled and self.restore_clipboard:
            try:
                backup = pyperclip.paste()
            except Exception as e:  # noqa: BLE001
                log("INJ", f"备份剪贴板失败（将跳过恢复）: {e}")

        try:
            pyperclip.copy(text)
        except Exception as e:  # noqa: BLE001
            log("INJ", f"写入剪贴板失败: {e}")
            return False
        log("INJ", f"已写入剪贴板（{len(text)} 字）")

        if not self.enabled:
            log("INJ", "注入已关闭（--no-inject），仅保留在剪贴板")
            return True

        try:
            import pyautogui

            time.sleep(max(0.0, self.pause_ms / 1000.0))
            pyautogui.hotkey("ctrl", "v")
            log("INJ", "已模拟 Ctrl+V 注入光标处")
        except Exception as e:  # noqa: BLE001
            log("INJ", f"模拟粘贴失败（结果已留在剪贴板，可手动 Ctrl+V）: {e}")
            return False

        if self.restore_clipboard and backup is not None:
            time.sleep(max(0.0, self.restore_delay_ms / 1000.0))
            try:
                pyperclip.copy(backup)
                log("INJ", "已恢复注入前的剪贴板内容")
            except Exception as e:  # noqa: BLE001
                log("INJ", f"恢复剪贴板失败（当前仍为注入文本）: {e}")
        return True
