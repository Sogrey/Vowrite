# -*- coding: utf-8 -*-
"""CLI：python -m vowrite  （工作目录需包含本包，通常为 p0/）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .app import Vowrite
from .config import DEFAULT_CONFIG_NAME, SCRIPT_DIR, load_config
from .selftest import self_test


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="vowrite",
        description="Vowrite P0 — 按住快捷键说话：polish / chat / raw",
    )
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / DEFAULT_CONFIG_NAME,
                        help="配置文件路径（默认: p0/config.toml）")
    parser.add_argument("--self-test", action="store_true", help="运行自检")
    parser.add_argument("--full", action="store_true",
                        help="配合 --self-test：加载模型做完整链路验证")
    parser.add_argument("--message", type=str, default=None,
                        help="跳过录音，直接润色并注入给定文本")
    parser.add_argument("--mode", choices=["polish", "chat", "raw"], default=None,
                        help="临时覆盖输出模式")
    parser.add_argument("--no-inject", action="store_true",
                        help="不模拟粘贴，仅写剪贴板/打印")
    parser.add_argument("--style", choices=["light", "heavy"], default=None,
                        help="临时覆盖润色强度")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.self_test:
        return 0 if self_test(cfg, full=args.full, inject_enabled=not args.no_inject) else 1

    inject_enabled = None if not args.no_inject else False
    need_asr = args.message is None
    app = Vowrite(cfg, inject_enabled=inject_enabled, style_override=args.style,
                  need_asr=need_asr, mode_override=args.mode)

    if args.message is not None:
        app.process_text(args.message)
        return 0

    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
