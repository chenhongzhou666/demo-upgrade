#!/usr/bin/env python3
"""旋律指纹提取 — 命令行工具

用法:
  python3 extract_fingerprint.py <audio_or_midi_path>       # 提取指纹 JSON
  python3 extract_fingerprint.py --midi <midi_file>          # 从 MIDI 直接提取 (快速，不需要引擎)

输出 (stdout):
  {"intervals": [...], "hash_count": N, "ngram_size": 3}
"""

import hashlib
import json
import sys
from pathlib import Path
from collections import Counter

NGRAM_SIZE = 2  # n=2: 高召回(侦测错误容忍度高), 低特异性(需 indexing 验证)


def extract_from_midi(midi_path: str) -> list[int]:
    """从 MIDI 文件提取音程序列"""
    import mido
    mid = mido.MidiFile(midi_path)
    notes = []
    current_time = 0.0
    active: dict[int, float] = {}
    tempo = 500000
    ticks_per_beat = mid.ticks_per_beat

    for msg in mid:
        current_time += msg.time
        if msg.type == "set_tempo":
            tempo = msg.tempo
        if msg.type == "note_on" and msg.velocity > 0:
            active[msg.note] = current_time
        elif msg.type in ("note_off", "note_on") and msg.velocity == 0:
            if msg.note in active:
                start_tick = active.pop(msg.note)
                start_sec = start_tick * tempo / (ticks_per_beat * 1_000_000)
                notes.append({"midi": msg.note, "start_sec": start_sec})

    notes.sort(key=lambda n: n["start_sec"])
    midis = [n["midi"] for n in notes]
    if len(midis) < 2:
        return []
    return [midis[i + 1] - midis[i] for i in range(len(midis) - 1)]


def extract_from_audio(audio_path: str) -> list[int]:
    """通过引擎提取音符 → 音程序列"""
    import subprocess
    engine_dir = Path(__file__).parent
    venv_python = str(engine_dir / ".venv-p2" / "bin" / "python3")
    engine_script = str(engine_dir / "verify_pipeline.py")

    proc = subprocess.run(
        [venv_python, engine_script, audio_path, "--json", "--eval-notes",
         "--output-dir", "/tmp/fingerprint"],
        cwd=str(engine_dir), capture_output=True, text=True, timeout=300)

    stdout = proc.stdout
    begin = stdout.find("__JSON_BEGIN__")
    end = stdout.find("__JSON_END__")
    if begin == -1 or end == -1:
        print("ERROR: engine output parse failed", file=sys.stderr)
        return []

    data = json.loads(stdout[begin + 14:end])
    notes = data.get("detected_notes", [])
    midis = [n["midi"] for n in notes if n.get("midi")]
    if len(midis) < 2:
        return []
    return [midis[i + 1] - midis[i] for i in range(len(midis) - 1)]


def intervals_to_fingerprint(intervals: list[int], n: int = NGRAM_SIZE) -> dict:
    """音程序列 → n-gram 指纹"""
    hashes = []
    for i in range(len(intervals) - n + 1):
        window = intervals[i:i + n]
        key = ",".join(str(x) for x in window)
        digest = hashlib.sha256(key.encode()).digest()
        h = int.from_bytes(digest[:8], "big")
        hashes.append({"index": i, "hash": h})

    return {
        "intervals": intervals,
        "total_notes": len(intervals) + 1,
        "ngram_size": n,
        "hash_count": len(hashes),
        "hashes": hashes,  # [(index, hash), ...]
    }


def main():
    if len(sys.argv) < 2:
        print("用法: extract_fingerprint.py [--midi] <文件路径>", file=sys.stderr)
        sys.exit(1)

    use_midi = sys.argv[1] == "--midi"
    filepath = sys.argv[2] if use_midi else sys.argv[1]

    if use_midi:
        intervals = extract_from_midi(filepath)
    else:
        intervals = extract_from_audio(filepath)

    if not intervals:
        print(json.dumps({"error": "no notes extracted"}))
        sys.exit(1)

    fp = intervals_to_fingerprint(intervals)
    fp["source"] = filepath
    print(json.dumps(fp, ensure_ascii=False))


if __name__ == "__main__":
    main()
