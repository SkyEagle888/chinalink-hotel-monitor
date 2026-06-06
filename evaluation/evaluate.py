"""
評估腳本 — 在黃金集上驗證預篩選邏輯（T9.5.x）

執行方式：
    python -m evaluation.evaluate

退出碼：
    0 — 所有指標達標
    1 — 任一指標未達標或運行錯誤
"""

import json
import os
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import scrape_and_notify as san

GOLDEN_PATH = Path(__file__).resolve().parent / "golden_set.jsonl"
MIN_ACCURACY = float(os.environ.get("EVAL_MIN_ACCURACY", "0.85"))


def load_golden() -> list[dict]:
    entries: list[dict] = []
    with open(GOLDEN_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))
    return entries


def predict(promo: dict) -> str:
    """套用預篩選規則，預測該優惠是否會被 LLM 處理。"""
    filtered, _ = san.prefilter([promo])
    return "include" if filtered else "exclude"


def evaluate(entries: list[dict]) -> dict:
    tp = fp = tn = fn = 0
    errors: list[dict] = []

    for e in entries:
        actual = predict(e)
        expected = e["expected"]
        if actual == expected:
            if actual == "include":
                tp += 1
            else:
                tn += 1
        else:
            if actual == "include":
                fp += 1
                errors.append({
                    "title": e["title"],
                    "expected": expected,
                    "actual": actual,
                    "reason": "false_positive",
                })
            else:
                fn += 1
                errors.append({
                    "title": e["title"],
                    "expected": expected,
                    "actual": actual,
                    "reason": "false_negative",
                })

    total = tp + tn + fp + fn
    accuracy = (tp + tn) / total if total else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall)
        else 0.0
    )

    return {
        "total": total,
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": accuracy,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "errors": errors,
    }


def main() -> int:
    if not GOLDEN_PATH.exists():
        print(f"[ERROR] 黃金集不存在：{GOLDEN_PATH}")
        return 1

    entries = load_golden()
    print(f"[INFO] 載入 {len(entries)} 條黃金樣本")

    results = evaluate(entries)

    print()
    print("=" * 50)
    print("評估結果")
    print("=" * 50)
    print(f"總計：       {results['total']}")
    print(f"正確 (TP+TN):{results['tp'] + results['tn']}")
    print(f"誤判 FP:     {results['fp']}  （應排除但納入）")
    print(f"漏判 FN:     {results['fn']}  （應納入但排除）")
    print(f"Accuracy:    {results['accuracy']:.2%}")
    print(f"Precision:   {results['precision']:.2%}")
    print(f"Recall:      {results['recall']:.2%}")
    print(f"F1:          {results['f1']:.2%}")

    if results["errors"]:
        print()
        print("錯誤詳情：")
        for err in results["errors"]:
            print(
                f"  - [{err['reason']}] "
                f"{err['title'][:40]} "
                f"(expected={err['expected']}, actual={err['actual']})"
            )

    print(f"\n[INFO] 閾值：accuracy >= {MIN_ACCURACY:.0%}")
    if results["accuracy"] < MIN_ACCURACY:
        print(f"[FAIL] Accuracy {results['accuracy']:.2%} 低於閾值")
        return 1

    print("[PASS] 評估通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
