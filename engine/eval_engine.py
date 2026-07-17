#!/usr/bin/env python3
"""识谱引擎评估脚本

遍历 test_set/ 中的 ground truth，对每个测试用例跑引擎，对比检测结果与真值。

用法:
    python3 eval_engine.py                    # 跑全部测试
    python3 eval_engine.py --piece bach       # 只跑巴赫
    python3 eval_engine.py --tolerance 0.08   # 调匹配容差

指标:
    - 音符 Recall:  真值中多少被检测到 (onset ± 容差)
    - 音符 Precision: 检测到的音中有多少匹配真值
    - 音高准确率: 匹配成功的音符中，MIDI 正确的比例
    - 调性: 是否与真值一致
    - BPM 误差: |detected - gt|
"""

import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent
VENV_PYTHON = str(ENGINE_DIR / ".venv-p2" / "bin" / "python3")
ENGINE_SCRIPT = str(ENGINE_DIR / "verify_pipeline.py")
TEST_SET_DIR = ENGINE_DIR / "test_set"

# test_set 中的测试用例
TEST_CASES = [
    {
        "name": "bach_bwv846",
        "wav": "bach_bwv846_original.wav",
        "gt_json": "bach_bwv846_ground_truth.json",
    },
    {
        "name": "chopin_mazurka",
        "wav": "chopin_mazurka_original.wav",
        "gt_json": "chopin_mazurka_ground_truth.json",
    },
    {
        "name": "schumann_polonaise1",
        "wav": "schumann_polonaise1_original.wav",
        "gt_json": "schumann_polonaise1_ground_truth.json",
    },
    {
        "name": "schumann_polonaise2",
        "wav": "schumann_polonaise2_original.wav",
        "gt_json": "schumann_polonaise2_ground_truth.json",
    },
]


def load_ground_truth(json_path: Path) -> dict:
    with open(json_path) as f:
        gt = json.load(f)
    # Normalize: music21 TimeSignature objects → string
    ts = gt.get("time_sig", "")
    if hasattr(ts, "ratioString"):
        ts = ts.ratioString
    elif hasattr(ts, "numerator"):
        ts = f"{ts.numerator}/{ts.denominator}"
    gt["time_sig_str"] = str(ts)
    return gt


def run_engine(wav_path: Path) -> dict | None:
    """Run engine with --eval-notes --json and parse output."""
    result_path = Path("/tmp/demoupgrade-eval-output.json")
    cmd = [
        VENV_PYTHON, ENGINE_SCRIPT,
        str(wav_path),
        "--json", "--eval-notes",
        "--output-dir", "/tmp/demoupgrade-eval",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ENGINE_DIR),
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        print(f"  ⚠️  超时 (5分钟)")
        return None

    stdout = proc.stdout
    # 提取 __JSON_BEGIN__ / __JSON_END__ 之间的内容
    begin = stdout.find("__JSON_BEGIN__")
    end = stdout.find("__JSON_END__")
    if begin == -1 or end == -1:
        print(f"  ⚠️  JSON 解析失败 (stderr: {proc.stderr[:200]})")
        return None

    try:
        return json.loads(stdout[begin + 14:end])
    except json.JSONDecodeError as e:
        print(f"  ⚠️  JSON 解析失败: {e}")
        return None


def match_notes(gt_notes: list[dict], det_notes: list[dict],
                tolerance: float = 0.1) -> tuple[int, int, int, int]:
    """Greedy nearest-neighbor onset alignment.

    Args:
        gt_notes: [{'midi', 'start', ...}]
        det_notes: [{'midi', 'start_sec', ...}]
        tolerance: max onset difference in seconds

    Returns:
        (matched, pitch_correct, false_neg, false_pos)
    """
    gt_used = [False] * len(gt_notes)
    det_used = [False] * len(det_notes)
    matched = 0
    pitch_correct = 0

    # 对每个真值音符，找最近的未匹配检测音符
    for gi, g in enumerate(gt_notes):
        best_j = -1
        best_dist = tolerance
        for dj, d in enumerate(det_notes):
            if det_used[dj]:
                continue
            dist = abs(d["start_sec"] - g["start"])
            if dist < best_dist:
                best_dist = dist
                best_j = dj

        if best_j >= 0:
            matched += 1
            gt_used[gi] = True
            det_used[best_j] = True
            if det_notes[best_j]["midi"] == g["midi"]:
                pitch_correct += 1

    false_neg = len(gt_notes) - matched
    false_pos = len(det_notes) - matched
    return matched, pitch_correct, false_neg, false_pos


def compute_metrics(gt: dict, engine_result: dict,
                    tolerance: float = 0.1) -> dict:
    """Compute all metrics for one test case."""
    gt_notes = gt["notes"]
    det_notes = engine_result.get("detected_notes", [])

    matched, pitch_correct, false_neg, false_pos = match_notes(
        gt_notes, det_notes, tolerance
    )

    total_gt = len(gt_notes)
    total_det = len(det_notes)
    recall = matched / total_gt if total_gt > 0 else 0
    precision = matched / total_det if total_det > 0 else 0
    f1 = 2 * recall * precision / (recall + precision) if (recall + precision) > 0 else 0
    pitch_acc = pitch_correct / matched if matched > 0 else 0

    # Key
    gt_key = f"{gt['key'].split()[0] if ' ' in gt['key'] else gt['key']} {gt['key'].split()[1] if ' ' in gt['key'] else 'major'}"
    detected_key = f"{engine_result.get('key_name', '?')} {engine_result.get('mode', 'major')}"
    key_ok = engine_result.get("key_name", "") == (gt["key"].split()[0] if " " in gt["key"] else gt["key"])

    # BPM
    bpm_error = abs(engine_result.get("bpm", 0) - gt.get("tempo", 0))

    # 拍号 (ground truth)
    gt_ts = gt.get("time_sig_str", "?")

    return {
        "recall": recall,
        "precision": precision,
        "f1": f1,
        "pitch_accuracy": pitch_acc,
        "matched": matched,
        "false_neg": false_neg,
        "false_pos": false_pos,
        "total_gt": total_gt,
        "total_det": total_det,
        "gt_key": gt["key"],
        "detected_key": detected_key,
        "key_ok": key_ok,
        "bpm_error": bpm_error,
        "gt_bpm": gt.get("tempo", 0),
        "detected_bpm": engine_result.get("bpm", 0),
        "gt_ts": gt_ts,
        "detected_ts": engine_result.get("time_sig", "?"),
    }


def main():
    tolerance = 0.1
    filter_piece = None

    for arg in sys.argv[1:]:
        if arg.startswith("--tolerance="):
            tolerance = float(arg.split("=")[1])
        elif arg.startswith("--piece="):
            filter_piece = arg.split("=")[1]

    test_cases = TEST_CASES
    if filter_piece:
        test_cases = [t for t in TEST_CASES if filter_piece in t["name"]]
        if not test_cases:
            print(f"未找到匹配的测试: {filter_piece}")
            sys.exit(1)

    # Collect results
    results = {}
    for tc in test_cases:
        name = tc["name"]
        wav = TEST_SET_DIR / tc["wav"]
        gt_json = TEST_SET_DIR / tc["gt_json"]

        if not wav.exists():
            print(f"[{name}] ⚠️  WAV 不存在: {wav}")
            continue
        if not gt_json.exists():
            print(f"[{name}] ⚠️  GT JSON 不存在: {gt_json}")
            continue

        print(f"[{name}] 运行引擎...", end=" ", flush=True)
        gt = load_ground_truth(gt_json)
        engine_result = run_engine(wav)
        if engine_result is None:
            print("失败")
            continue
        metrics = compute_metrics(gt, engine_result, tolerance)
        results[name] = metrics
        print(f"OK ({metrics['matched']}/{metrics['total_gt']} matched)")

    if not results:
        print("\n无可用结果")
        sys.exit(1)

    # Print table
    print()
    print("=" * 110)
    print(f"{'曲目':<25} {'Recall':>7} {'Prec':>7} {'F1':>7} {'音高':>7} "
          f"{'匹配':>6} {'FN':>5} {'FP':>5} {'调性':>10} {'调性对':>4} {'BPM err':>8}")
    print("-" * 110)

    totals = {"recall": 0, "precision": 0, "f1": 0, "pitch_accuracy": 0,
              "matched": 0, "false_neg": 0, "false_pos": 0,
              "total_gt": 0, "total_det": 0, "key_ok": 0, "bpm_error": 0}

    for name, m in results.items():
        totals["recall"] += m["recall"]
        totals["precision"] += m["precision"]
        totals["f1"] += m["f1"]
        totals["pitch_accuracy"] += m["pitch_accuracy"]
        totals["matched"] += m["matched"]
        totals["false_neg"] += m["false_neg"]
        totals["false_pos"] += m["false_pos"]
        totals["total_gt"] += m["total_gt"]
        totals["total_det"] += m["total_det"]
        totals["key_ok"] += (1 if m["key_ok"] else 0)
        totals["bpm_error"] += m["bpm_error"]

        key_mark = "✅" if m["key_ok"] else "❌"
        print(f"{name:<25} {m['recall']:6.1%} {m['precision']:6.1%} {m['f1']:6.1%} "
              f"{m['pitch_accuracy']:6.1%} "
              f"{m['matched']:4d}/{m['total_gt']:<4d} {m['false_neg']:4d} {m['false_pos']:4d} "
              f"{m['detected_key']:>10} {key_mark:>6} {m['bpm_error']:5.0f}")

    n = len(results)
    print("-" * 110)
    recall_avg = totals["recall"] / n
    prec_avg = totals["precision"] / n
    f1_avg = totals["f1"] / n
    pitch_avg = totals["pitch_accuracy"] / n

    # Weighted F1 (micro-average)
    total_matched = totals["matched"]
    micro_recall = total_matched / totals["total_gt"] if totals["total_gt"] > 0 else 0
    micro_prec = total_matched / totals["total_det"] if totals["total_det"] > 0 else 0
    micro_f1 = 2 * micro_recall * micro_prec / (micro_recall + micro_prec) if (micro_recall + micro_prec) > 0 else 0

    print(f"{'总平均 ' + str(n) + ' 首':<25} {recall_avg:6.1%} {prec_avg:6.1%} {f1_avg:6.1%} "
          f"{pitch_avg:6.1%} "
          f"{totals['matched']:4d}/{totals['total_gt']:<4d} {totals['false_neg']:4d} {totals['false_pos']:4d} "
          f"           {totals['key_ok']}/{n}")
    print(f"{'微平均 (加权)':<25} {micro_recall:6.1%} {micro_prec:6.1%} {micro_f1:6.1%}")
    print(f"{'BPM 平均误差':>41}: {totals['bpm_error']/n:5.0f}")
    print("=" * 110)
    print(f"\n容差: ±{tolerance*1000:.0f}ms onset matching")
    print(f"{' '.join(gt.get('gt_key', '') or '' for gt in results.values() if 'gt_key' in results)}")

    # Detail: per-piece metrics with gt vs detected comparison
    print("\n─── 详细对比 ───")
    for name, m in results.items():
        ts_ok = "✅" if m["detected_ts"] == m["gt_ts"] else "⚠️"
        print(f"  {name}:")
        print(f"    调性: {m['gt_key']} → {m['detected_key']}  "
              f"拍号: {m['gt_ts']} → {m['detected_ts']} {ts_ok}  "
              f"BPM: {m['gt_bpm']:.0f} → {m['detected_bpm']:.0f}  (Δ={m['bpm_error']:.0f})")
        print(f"    音符: GT={m['total_gt']} 检测={m['total_det']}  "
              f"匹配={m['matched']} FN={m['false_neg']} FP={m['false_pos']}  "
              f"Recall={m['recall']:.1%}  Prec={m['precision']:.1%}  "
              f"音高正确率={m['pitch_accuracy']:.1%}")


if __name__ == "__main__":
    main()
