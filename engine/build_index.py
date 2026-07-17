#!/usr/bin/env python3
"""构建旋律指纹索引 — 从音频 WAV 用引擎提取指纹，输出 JSON 索引

用法:
  python3 build_index.py output_index.json track1.wav "曲名" "作曲家" "C major"
  python3 build_index.py index.json track1.wav ... trackN.wav  # 批量

输出: JSON 数组，每个元素为 {"track": {...}, "total_notes": N, "hashes": [...]}
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).parent
VENV_PYTHON = str(ENGINE_DIR / ".venv-p2" / "bin" / "python3")
ENGINE_SCRIPT = str(ENGINE_DIR / "verify_pipeline.py")
NGRAM_SIZE = 2


def extract_notes_from_audio(audio_path: str) -> list[dict]:
    """通过引擎提取音符"""
    proc = subprocess.run(
        [VENV_PYTHON, ENGINE_SCRIPT, audio_path,
         "--json", "--eval-notes", "--output-dir", "/tmp/fp-index-build"],
        cwd=str(ENGINE_DIR), capture_output=True, text=True, timeout=300)

    stdout = proc.stdout
    begin = stdout.find("__JSON_BEGIN__")
    end = stdout.find("__JSON_END__")
    if begin == -1 or end == -1:
        raise RuntimeError(f"Engine output parse failed for {audio_path}")

    data = json.loads(stdout[begin + 14:end])
    return data.get("detected_notes", [])


def notes_to_fingerprint(notes: list[dict], n: int = NGRAM_SIZE) -> dict:
    """音符 → 音程 n-gram 指纹"""
    midis = [n["midi"] for n in notes if n.get("midi")]
    intervals = [midis[i + 1] - midis[i] for i in range(len(midis) - 1)]

    hashes = []
    for i in range(len(intervals) - n + 1):
        window = intervals[i:i + n]
        key = ",".join(str(x) for x in window)
        digest = hashlib.sha256(key.encode()).digest()
        h = int.from_bytes(digest[:8], "big")
        hashes.append({"index": i, "hash": h})

    return {
        "total_notes": len(midis),
        "ngram_size": n,
        "hash_count": len(hashes),
        "hashes": hashes,
    }


def main():
    if len(sys.argv) < 4:
        print("用法: build_index.py <output.json> <audio1.wav> <title> <composer> <key> [audio2.wav ...]")
        print("  或: build_index.py <output.json> <audio1.wav> [audio2.wav ...] (track info 从文件名推断)")
        sys.exit(1)

    output_path = sys.argv[1]
    args = sys.argv[2:]
    tracks = []

    # 如果剩余参数是 4 的倍数 + 有 title/composer/key → 按组处理
    # 否则每个参数一个音频文件
    i = 0
    while i < len(args):
        audio = args[i]
        if i + 3 < len(args) and not args[i + 1].endswith('.wav'):
            # 带 metadata 的格式: audio title composer key
            title, composer, key_name = args[i + 1], args[i + 2], args[i + 3]
            i += 4
        else:
            # 从文件名推断
            stem = Path(audio).stem
            title = stem
            composer = "Unknown"
            key_name = "?"
            i += 1

        if not os.path.exists(audio):
            print(f"  ⚠️ 跳过: {audio} (不存在)")
            continue

        print(f"  处理: {title} ({audio}) ...", end=" ", flush=True)
        notes = extract_notes_from_audio(audio)
        fp = notes_to_fingerprint(notes)
        fp["track"] = {
            "id": Path(audio).stem,
            "title": title,
            "composer": composer,
            "key_name": key_name,
        }
        tracks.append(fp)
        print(f"{fp['total_notes']} notes → {fp['hash_count']} hashes")

    with open(output_path, "w") as f:
        json.dump(tracks, f, ensure_ascii=False, indent=2)
    print(f"\n索引已保存: {output_path} ({len(tracks)} tracks)")


if __name__ == "__main__":
    main()
