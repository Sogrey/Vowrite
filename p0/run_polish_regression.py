#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""polish 回归：批跑 fixtures/polish_samples.json，验收 light 档采纳率。

用法:
  .venv\\Scripts\\python.exe p0\\run_polish_regression.py
  .venv\\Scripts\\python.exe p0\\run_polish_regression.py --threshold 0.8
  .venv\\Scripts\\python.exe p0\\run_polish_regression.py --offline   # 不调 LLM，只跑守卫/透传逻辑不可用时跳过

退出码: 0 = 通过率 ≥ 阈值；1 = 未达标或运行失败。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from vowrite import (  # noqa: E402
    FEWSHOT_FINGERPRINTS,
    Polisher,
    load_config,
    log,
)

SAMPLES_PATH = SCRIPT_DIR / "fixtures" / "polish_samples.json"
DEFAULT_THRESHOLD = 0.8


def _eval_one(sample: dict, out: str) -> tuple[bool, list[str]]:
    """启发式验收：保留必含词、禁止污染、长度不过度膨胀。"""
    reasons: list[str] = []
    src = sample["input"]
    if not out or not str(out).strip():
        return False, ["输出为空"]

    for kw in sample.get("must_keep") or []:
        if kw not in out:
            reasons.append(f"缺少必留「{kw}」")

    for bad in sample.get("must_not") or []:
        if bad and bad in out:
            reasons.append(f"出现禁止片段「{bad}」")

    for fp in FEWSHOT_FINGERPRINTS:
        if fp in out and fp not in src:
            reasons.append(f"示例指纹吸附「{fp}」")

    allowance = 6 + max(0, int(len(src) * 0.2))
    if len(out) > len(src) + allowance + 20:
        # 比生产守卫略宽，避免标点/列表整理误杀；仍拦明显扩写
        reasons.append(f"输出过长({len(out)}>{len(src)}+{allowance + 20})")

    return len(reasons) == 0, reasons


def main() -> int:
    parser = argparse.ArgumentParser(description="Vowrite polish 回归批跑")
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / "config.toml")
    parser.add_argument("--samples", type=Path, default=SAMPLES_PATH)
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help="通过率门槛（默认 0.8）")
    parser.add_argument("--style", choices=["light", "heavy"], default="light")
    args = parser.parse_args()

    samples = json.loads(args.samples.read_text(encoding="utf-8"))
    if len(samples) < 10:
        log("TEST", f"FAIL — 样例不足 10 条（当前 {len(samples)}）")
        return 1

    cfg = load_config(args.config)
    llm_cfg = dict(cfg["llm"])
    llm_cfg["mode"] = "polish"
    llm_cfg["style"] = args.style
    polisher = Polisher(llm_cfg)

    reachable, detail = polisher.probe() if polisher.enabled else (False, "disabled")
    if not reachable:
        log("TEST", f"WARN — LLM 不可用（{detail}），回归无法验收润色质量")
        log("TEST", "请先启动 llama-server 或配置可用 base_url 后再跑")
        return 1

    log("TEST", f"polish 回归开始：{len(samples)} 条 · style={args.style} · "
                f"threshold={args.threshold:.0%} · llm={polisher.base_url}")

    passed = 0
    rows = []
    t_all = time.perf_counter()
    for sample in samples:
        sid = sample["id"]
        src = sample["input"]
        t0 = time.perf_counter()
        try:
            out = polisher.polish(src)
        except Exception as e:  # noqa: BLE001
            out = ""
            ok, reasons = False, [f"异常: {e}"]
            elapsed = time.perf_counter() - t0
        else:
            ok, reasons = _eval_one(sample, out)
            elapsed = time.perf_counter() - t0
        if ok:
            passed += 1
            log("TEST", f"PASS {sid} ({elapsed:.2f}s) ← {src[:24]}…")
        else:
            log("TEST", f"FAIL {sid} ({elapsed:.2f}s): {'; '.join(reasons)}")
            log("TEST", f"       in : {src}")
            log("TEST", f"       out: {out}")
        rows.append({"id": sid, "ok": ok, "reasons": reasons, "out": out})

    rate = passed / len(samples)
    log("TEST", f"结果: {passed}/{len(samples)} = {rate:.0%} "
                f"（门槛 {args.threshold:.0%}）", time.perf_counter() - t_all)

    report_dir = SCRIPT_DIR.parent / ".temp"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "polish-regression-last.json"
    report_path.write_text(
        json.dumps({"rate": rate, "passed": passed, "total": len(samples),
                    "style": args.style, "rows": rows},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log("TEST", f"明细已写入 {report_path}")

    if rate + 1e-9 < args.threshold:
        log("TEST", "未达标")
        return 1
    log("TEST", "达标")
    return 0


if __name__ == "__main__":
    sys.exit(main())
