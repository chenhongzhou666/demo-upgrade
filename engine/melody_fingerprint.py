#!/usr/bin/env python3
"""旋律查重原型 — 音程序列 n-gram 指纹 + Jaccard 相似度

技术路线选择：
  为什么不用 Shazam 式频谱峰值哈希？
  → 我们已经有了检测到的音符（符号域），不需要走 FFT→频谱→峰值路线。
    直接从 MIDI 序列提取音程（interval）n-gram 即可，天然移调不变。

  为什么用音程（interval）而非绝对音高？
  → C-E-G 和 D-F#-A 是不同的绝对音高，但音程序列「+4 +3」完全相同。
    移调和抄袭的区别就在于绝对音高变了但音程没变。用音程做指纹天然移调不变。

算法：
  1. 音符 → MIDI pitch 序列 → 相邻音程（半音差）序列
  2. 滑动窗口 n-gram (n=3/4/5) → hash
  3. 两首曲子的指纹集合 Jaccard 系数 = |A∩B| / |A∪B|
  4. 高 Jaccard (>0.3) = 疑似相似/抄袭

用法：
  python3 melody_fingerprint.py                    # 跑全部对比
  python3 melody_fingerprint.py --demo             # 演示：同一首歌前半 vs 后半
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

ENGINE_DIR = Path(__file__).parent
VENV_PYTHON = str(ENGINE_DIR / ".venv-p2" / "bin" / "python3")
ENGINE_SCRIPT = str(ENGINE_DIR / "verify_pipeline.py")
TEST_SET_DIR = ENGINE_DIR / "test_set"


class MelodyFingerprint(NamedTuple):
    """一首曲子的旋律指纹"""
    name: str
    ngram_size: int
    hashes: set[int]           # n-gram hash 集合
    total_notes: int           # 原始音符数
    hash_count: int            # distinct hash 数


def extract_notes(audio_path: str | Path) -> list[dict] | None:
    """跑引擎提取检测到的音符列表"""
    cmd = [
        VENV_PYTHON, ENGINE_SCRIPT,
        str(audio_path),
        "--json", "--eval-notes",
        "--output-dir", "/tmp/melody-fingerprint",
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(ENGINE_DIR),
            capture_output=True, text=True, timeout=300,
        )
    except subprocess.TimeoutExpired:
        print(f"  ⚠️ 超时: {audio_path}")
        return None

    stdout = proc.stdout
    begin = stdout.find("__JSON_BEGIN__")
    end = stdout.find("__JSON_END__")
    if begin == -1 or end == -1:
        return None

    try:
        result = json.loads(stdout[begin + 14:end])
        return result.get("detected_notes", [])
    except json.JSONDecodeError:
        return None


def notes_to_intervals(notes: list[dict]) -> list[int]:
    """音符 → 音程序列（相邻 MIDI 半音差）"""
    midis = [n["midi"] for n in notes if n.get("midi")]
    if len(midis) < 2:
        return []
    return [midis[i + 1] - midis[i] for i in range(len(midis) - 1)]


def intervals_to_ngram_hashes(intervals: list[int], n: int = 4) -> set[int]:
    """滑动窗口 n-gram → SHA-256 哈希集合（取前 64 bit 防碰撞）"""
    hashes = set()
    for i in range(len(intervals) - n + 1):
        window = intervals[i:i + n]
        key = ",".join(str(x) for x in window)
        # 每次 new 新对象，避免累积
        digest = hashlib.sha256(key.encode()).digest()
        hashes.add(int.from_bytes(digest[:8], "big"))
    return hashes


def fingerprint_from_notes(notes: list[dict], name: str, ngram_size: int = 4) -> MelodyFingerprint:
    """完整流程：音符 → 指纹"""
    intervals = notes_to_intervals(notes)
    hashes = intervals_to_ngram_hashes(intervals, ngram_size)
    return MelodyFingerprint(
        name=name,
        ngram_size=ngram_size,
        hashes=hashes,
        total_notes=len(notes),
        hash_count=len(hashes),
    )


def fingerprint_from_midi_file(midi_path: str | Path, name: str, ngram_size: int = 4) -> MelodyFingerprint:
    """从 MIDI 文件直接读音符（不用引擎，纯 ground truth）"""
    import mido
    mid = mido.MidiFile(midi_path)
    notes = []
    current_time = 0.0
    active_notes: dict[int, float] = {}  # note -> start_time

    ticks_per_beat = mid.ticks_per_beat
    # Assume 120 BPM for ground truth MIDI (the actual tempo is in the file)
    tempo = 500000  # microseconds per beat (120 BPM default)

    for msg in mid:
        current_time += msg.time

        if msg.type == "set_tempo":
            tempo = msg.tempo

        if msg.type == "note_on" and msg.velocity > 0:
            active_notes[msg.note] = current_time
        elif (msg.type == "note_off") or (msg.type == "note_on" and msg.velocity == 0):
            if msg.note in active_notes:
                start_tick = active_notes.pop(msg.note)
                dur_ticks = current_time - start_tick
                dur_sec = dur_ticks * tempo / (ticks_per_beat * 1_000_000)
                start_sec = start_tick * tempo / (ticks_per_beat * 1_000_000)
                notes.append({
                    "midi": msg.note,
                    "start_sec": start_sec,
                    "duration_sec": dur_sec,
                })

    notes.sort(key=lambda n: n["start_sec"])
    return fingerprint_from_notes(notes, name, ngram_size)


def jaccard(a: MelodyFingerprint, b: MelodyFingerprint) -> float:
    """Jaccard 相似系数"""
    if not a.hashes or not b.hashes:
        return 0.0
    intersection = len(a.hashes & b.hashes)
    union = len(a.hashes | b.hashes)
    return intersection / union if union > 0 else 0.0


def containment(a: MelodyFingerprint, b: MelodyFingerprint) -> float:
    """Containment: a 有多少哈希在 b 中（非对称，检测短片段是否在长曲中）"""
    if not a.hashes:
        return 0.0
    return len(a.hashes & b.hashes) / len(a.hashes)


# ─── Demo & Test ───


def demo_self_similarity():
    """演示：同一首歌的前半 vs 后半相似度（应该高）vs 不同歌曲（应该低）"""
    print("=" * 70)
    print("旋律指纹查重 · 原型验证")
    print("=" * 70)

    # Extract notes from Bach
    print("\n[1] 提取巴赫前奏曲音符 (用引擎)...")
    wav = TEST_SET_DIR / "bach_bwv846_original.wav"
    notes = extract_notes(wav)
    if not notes:
        print("  ⚠️ 引擎提取失败，改用 MIDI ground truth")
        notes = None

    # Also use MIDI ground truth for comparison
    print("[2] 从 MIDI ground truth 提取音符...")
    midi_paths = [
        ("bach_bwv846", TEST_SET_DIR / "bach_bwv846_original.mid"),
        ("chopin_mazurka", TEST_SET_DIR / "chopin_mazurka_original.mid"),
        ("schumann_pol1", TEST_SET_DIR / "schumann_polonaise1_original.mid"),
        ("schumann_pol2", TEST_SET_DIR / "schumann_polonaise2_original.mid"),
    ]

    fps: list[MelodyFingerprint] = []
    for name, midi_path in midi_paths:
        if midi_path.exists():
            fp = fingerprint_from_midi_file(midi_path, name, ngram_size=4)
            fps.append(fp)
            print(f"  {name}: {fp.total_notes} 音符 → {fp.hash_count} 个 hash (4-gram)")

    if len(fps) < 2:
        print("需要至少 2 首曲子对比")
        return

    # Self-similarity: split same piece
    print("\n[3] 同曲自相似 (巴赫前半 vs 巴赫后半)...")
    bach = fps[0]
    mid = int(bach.total_notes / 2)
    import mido
    midi = mido.MidiFile(str(midi_paths[0][1]))
    all_notes = []
    current_time = 0.0
    active = {}
    tempo = 500000
    ticks_per_beat = midi.ticks_per_beat

    for msg in midi:
        current_time += msg.time
        if msg.type == "set_tempo":
            tempo = msg.tempo
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = current_time
        elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
            if msg.note in active:
                start_tick = active.pop(msg.note)
                dur_sec = (current_time - start_tick) * tempo / (ticks_per_beat * 1_000_000)
                start_sec = start_tick * tempo / (ticks_per_beat * 1_000_000)
                all_notes.append({"midi": msg.note, "start_sec": start_sec, "duration_sec": dur_sec})

    all_notes.sort(key=lambda n: n["start_sec"])
    half = len(all_notes) // 2
    first_half = all_notes[:half]
    second_half = all_notes[half:]

    # Test multiple n-gram sizes
    for n in [2, 3, 4]:
        fp_a = fingerprint_from_notes(first_half, "first", ngram_size=n)
        fp_b = fingerprint_from_notes(second_half, "second", ngram_size=n)
        sim = jaccard(fp_a, fp_b)
        print(f"  n={n}: Jaccard={sim:.4f}  (hashes: {fp_a.hash_count} vs {fp_b.hash_count})")

    # Show actual interval sequences for understanding
    intervals = notes_to_intervals(all_notes)
    print(f"\n  巴赫前 30 个音程序列 (半音差):")
    print(f"  {intervals[:30]}")
    print(f"  Distinct intervals used: {sorted(set(intervals))}")
    from collections import Counter
    print(f"  Top 5 interval patterns: {Counter(intervals).most_common(5)}")
    print(f"  Total unique 3-interval windows: {len(set(tuple(intervals[i:i+3]) for i in range(len(intervals)-2)))}")
    print(f"  Total unique 4-interval windows: {len(set(tuple(intervals[i:i+4]) for i in range(len(intervals)-3)))}")

    # Cross-piece similarity with n=3
    print(f"\n[4] 交叉相似度矩阵 (Jaccard, n=3):")
    for fp in fps:
        print(f"{fp.name:>18}", end="")
    print()

    for fp_a in fps:
        print(f"  {fp_a.name:>18}", end="")
        for fp_b in fps:
            if fp_a.name == fp_b.name:
                print(f"      {'—':>10}", end="")
            else:
                sim = jaccard(fp_a, fp_b)
                bar = "🟢" if sim > 0.1 else ("🟡" if sim > 0.03 else "🔴")
                print(f"  {bar}{sim:.4f}", end="")
        print()

    # Containment: can we find a short excerpt in the full piece?
    print("\n[5] 片段查全曲 (Containment):")
    print("  从巴赫取 30 个音符片段，查是否在完整巴赫中...")
    excerpt = all_notes[100:130]  # 30 notes from measure ~4
    fp_excerpt = fingerprint_from_notes(excerpt, "excerpt", ngram_size=4)
    fp_full = fingerprint_from_notes(all_notes, "bach_full", ngram_size=4)
    contain = containment(fp_excerpt, fp_full)
    print(f"  Excerpt ({fp_excerpt.total_notes}音) in Bach Full: containment = {contain:.4f}")
    if contain > 0.5:
        print(f"  ✅ 成功检出! 只需 {fp_excerpt.hash_count} 个 hash 即可匹配全曲")

    # 用不同曲测试：查巴赫片段在肖邦中
    fp_chopin = fps[1] if len(fps) > 1 else None
    if fp_chopin:
        contain_chopin = containment(fp_excerpt, fp_chopin)
        print(f"  Excerpt ({fp_excerpt.total_notes}音) in Chopin: containment = {contain_chopin:.4f}")
        if contain_chopin < 0.1:
            print(f"  ✅ 正确: 巴赫片段在肖邦中匹配率极低 (无假阳性)")

    # Notes count estimate for DB
    print("\n[6] 规模估算:")
    print(f"  每首 ~{fps[0].hash_count} distinct hashes (n=4)")
    print(f"  10,000 首曲子 ≈ {fps[0].hash_count * 10000 / 1_000_000:.0f}M hashes")
    print(f"  每个 hash 8 bytes → ~{fps[0].hash_count * 10000 * 8 / 1_000_000:.0f} MB")
    print(f"  Python set 查重 O(1), 内存完全放得下")
    print(f"  真正需要的是倒排索引: hash → [曲ID列表] 用于快速 Top-K 检索")


if __name__ == "__main__":
    if "--demo" in sys.argv or len(sys.argv) == 1:
        demo_self_similarity()
    else:
        # Quick compare two files
        pass
