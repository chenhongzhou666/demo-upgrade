#!/usr/bin/env python3
"""批量构建旋律指纹索引 — 从 music21 corpus 渲染 WAV → 引擎提取 → 指纹入库

用法:
  python3 batch_index.py                          # 默认 15 首巴赫精选
  python3 batch_index.py --count 30               # 30 首
  python3 batch_index.py --composer beethoven --count 10
  python3 batch_index.py --output my_index.json   # 自定义输出路径
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Config ──
ENGINE_DIR = Path(__file__).parent
VENV_PYTHON = str(ENGINE_DIR / ".venv-p2" / "bin" / "python3")
ENGINE_SCRIPT = str(ENGINE_DIR / "verify_pipeline.py")
SF2_PATH = str(ENGINE_DIR / "FluidR3_GM.sf2")
DEFAULT_OUTPUT = str(ENGINE_DIR / "fingerprint_index.json")
NGRAM_SIZE = 2

# ── 巴赫精选曲目（不同调性、不同体裁、不同 BWV 编号范围）──
BACH_SELECTION = [
    # 众赞歌（短小、4声部、和声清晰）
    "bwv1.6", "bwv10.7", "bwv66.6", "bwv101.7", "bwv102.7",
    "bwv103.6", "bwv104.6", "bwv105.6", "bwv106.4", "bwv107.7",
    # 不同年份/编号范围
    "bwv232.1", "bwv232.3", "bwv232.5",  # B小调弥撒选段
    "bwv245.1",  # 约翰受难曲开头
    "bwv248.1",  # 圣诞神曲
]

MOZART_SELECTION = [
    "k155/movement1", "k155/movement2", "k155/movement3",
    "k279/movement1", "k279/movement2", "k279/movement3",
]

BEETHOVEN_SELECTION = [
    "opus132",  # 晚期弦乐四重奏
]


def midi_to_wav(midi_path: str, wav_path: str, sample_rate: int = 22050) -> bool:
    """fluidsynth 渲染 MIDI → WAV"""
    result = subprocess.run(
        ["fluidsynth", "-ni", "-r", str(sample_rate), "-g", "2",
         "-F", wav_path, SF2_PATH, midi_path],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0 and os.path.getsize(wav_path) > 1000


def engine_extract_notes(wav_path: str) -> list[dict]:
    """运行引擎 Pipeline 提取音符"""
    output_dir = tempfile.mkdtemp(prefix="fp-batch-")
    proc = subprocess.run(
        [VENV_PYTHON, ENGINE_SCRIPT, wav_path,
         "--json", "--eval-notes", "--output-dir", output_dir],
        cwd=str(ENGINE_DIR), capture_output=True, text=True, timeout=600,
    )
    stdout = proc.stdout
    begin = stdout.find("__JSON_BEGIN__")
    end = stdout.find("__JSON_END__")
    if begin == -1 or end == -1:
        raise RuntimeError(f"引擎输出解析失败:\nSTDERR: {proc.stderr[-500:]}")
    return json.loads(stdout[begin + 14:end]).get("detected_notes", [])


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


def get_corpus_works(composer: str) -> list[str]:
    """获取 music21 corpus 中的作曲家作品名"""
    import music21
    return [str(p) for p in music21.corpus.getComposer(composer)]


def infer_track_name(work_name: str, composer: str) -> tuple[str, str]:
    """从文件名推断曲名和调性"""
    name = work_name.replace("/", " ")
    # 简单处理：用 work name 作为 title
    title = f"{composer.title()} {name}"
    key_name = "unknown"  # 需要解析 music21 score 才知道
    return title, key_name


def process_work(work_name: str, work_path: str, composer: str, tmp_base: str) -> dict | None:
    """处理单个作品：渲染 → 引擎 → 指纹"""
    import music21

    safe_name = work_name.replace("/", "_").replace(".", "_").replace(" ", "_")
    work_dir = os.path.join(tmp_base, safe_name)
    os.makedirs(work_dir, exist_ok=True)

    midi_path = os.path.join(work_dir, "input.mid")
    wav_path = os.path.join(work_dir, "input.wav")

    try:
        # 1. music21 → MIDI
        print(f"  [1/4] 解析乐谱: {work_name}")
        score = music21.converter.parse(work_path)

        # 提取调性信息
        key_name = "unknown"
        for ks in score.recurse().getElementsByClass("KeySignature"):
            if ks.sharps != 0 or ks.mode != "major":
                if ks.sharps >= 0:
                    keys = ["C", "G", "D", "A", "E", "B", "F#", "C#"]
                    idx = min(ks.sharps, 7)
                    k = keys[idx]
                else:
                    keys = ["C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"]
                    idx = min(-ks.sharps, 7)
                    k = keys[idx]
                key_name = f"{k} {ks.mode}"
            break

        # 统计音符数
        note_count = len(list(score.recurse().notesAndRests))
        if note_count < 10:
            print(f"  ⏭  跳过（音符太少: {note_count}）")
            return None

        # 写 MIDI
        mf = music21.midi.translate.music21ObjectToMidiFile(score)
        mf.open(midi_path, "wb")
        mf.write()
        mf.close()

        # 2. MIDI → WAV
        print(f"  [2/4] 渲染 WAV (fluidsynth)")
        if not midi_to_wav(midi_path, wav_path):
            print(f"  ❌ 渲染失败")
            return None

        # 3. 引擎提取音符
        print(f"  [3/4] 引擎提取音符...")
        notes = engine_extract_notes(wav_path)
        if len(notes) < 4:
            print(f"  ⏭  跳过（检测音符太少: {len(notes)}）")
            return None

        # 4. 提取指纹
        print(f"  [4/4] 指纹提取...")
        fp = notes_to_fingerprint(notes)
        title, _ = infer_track_name(work_name, composer)

        print(f"  ✅ {len(notes)} 音符, {fp['hash_count']} 哈希, 调性: {key_name}")

        return {
            "track": {
                "id": safe_name,
                "title": title,
                "composer": composer.title(),
                "key_name": key_name,
            },
            **fp,
        }

    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return None


def main():
    import argparse

    parser = argparse.ArgumentParser(description="批量构建旋律指纹索引")
    parser.add_argument("--composer", default="bach", help="music21 corpus 作曲家名 (默认 bach)")
    parser.add_argument("--count", type=int, default=15, help="处理曲目数量 (默认 15)")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="输出 JSON 路径")
    parser.add_argument("--append", action="store_true", help="追加到已有索引 (默认覆盖)")
    parser.add_argument("--max-notes", type=int, default=1500, help="跳过音符数过多的曲目 (默认 1500)")
    args = parser.parse_args()

    print(f"━━━ 批量构建指纹索引 ━━━")
    print(f"作曲家: {args.composer}")
    print(f"目标数量: {args.count}")
    print(f"输出: {args.output}")
    print()

    # 获取曲目列表
    works = get_corpus_works(args.composer)
    print(f"可用曲目: {len(works)} 首")

    # 过滤：只选 .mxl 格式，跳过过大曲目
    candidates = []
    for w in works:
        name = Path(w).stem
        if w.endswith(".mxl"):
            candidates.append((name, w))

    print(f".mxl 曲目: {len(candidates)} 首")

    # 如果是指定的精选列表，按精选来
    if args.composer == "bach":
        selected = [(n, w) for n, w in candidates if any(s in n for s in BACH_SELECTION)]
        if len(selected) < args.count:
            # 补充其他曲目
            existing_names = {s[0] for s in selected}
            for n, w in candidates:
                if len(selected) >= args.count:
                    break
                if n not in existing_names:
                    selected.append((n, w))
                    existing_names.add(n)
    else:
        selected = candidates[:args.count]

    selected = selected[:args.count]
    print(f"选中: {len(selected)} 首")
    print()

    # 加载已有索引（如果 append 模式）
    existing_tracks = []
    if args.append and os.path.exists(args.output):
        with open(args.output) as f:
            existing_tracks = json.load(f)
        print(f"已有索引: {len(existing_tracks)} 首曲目")
        print()

    # 批量处理
    tmp_base = tempfile.mkdtemp(prefix="fp-batch-")
    new_tracks = []

    for i, (name, path) in enumerate(selected):
        print(f"[{i+1}/{len(selected)}] {name}")
        result = process_work(name, path, args.composer, tmp_base)
        if result:
            new_tracks.append(result)
        print()

    # 合并并写入
    all_tracks = existing_tracks + new_tracks if args.append else new_tracks

    with open(args.output, "w") as f:
        json.dump(all_tracks, f, indent=2, ensure_ascii=False)

    print(f"━━━ 完成 ━━━")
    print(f"新增: {len(new_tracks)} 首")
    print(f"总计: {len(all_tracks)} 首")
    print(f"输出: {args.output}")
    print()

    # 统计
    total_hashes = sum(t["hash_count"] for t in all_tracks)
    print(f"索引规模: {total_hashes} 个哈希 → ~{total_hashes * 8 / 1024:.0f} KB 内存")


if __name__ == "__main__":
    main()
