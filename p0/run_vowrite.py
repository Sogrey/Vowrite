#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""兼容入口：python p0/run_vowrite.py（实现在 p0/vowrite/ 包）。

等价于在 p0 目录执行: python -m vowrite
"""

from __future__ import annotations

import sys
from pathlib import Path

_P0 = Path(__file__).resolve().parent
if str(_P0) not in sys.path:
    sys.path.insert(0, str(_P0))

from vowrite.__main__ import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
