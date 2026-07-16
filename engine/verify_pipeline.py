#!/usr/bin/env python3
"""
Demo 独自升级 · 识谱 Pipeline v10
全流程：音高检测 → 音乐分析 → 和弦识别 → 简谱 → 音色 → MIDI → 五线谱

v10 修复 (2026-07-16):
  - 调性检测: 低音加权 (MIDI<48 权重 3x) + 终止式确认破平局
  - 拍号推断: 音符起音计数替代频谱通量 (连奏钢琴不可靠)
  - 置信度阈值: 0.50→0.40

v9 修复 (2026-07-16):
  - Basic Pitch 泛音碎片过滤 (dur < 0.04s)
  - identify_chord 完全重写 (sorted rotation + 正确 root_pc)
  - 简谱: 小调用关系大调首调 (tonic=la=6), 八度点参考有效 do
  - 简谱: 增加节奏记号 (- 延长, · 附点)
  - 音色: 去掉过度激进的 Bass/Synth 硬规则
  - analyse_tsdt: 小调级数映射修正
  - 运行后自动清理测试文件 (--keep 保留)
"""
import os, sys, tempfile, subprocess, warnings, json, argparse, glob
try:
    import pkg_resources
except ImportError:
    import importlib.resources
    import types
    mod = types.ModuleType('pkg_resources')
    class _FakeProvider:
        @staticmethod
        def get_resource_filename(pkg, name): return str(importlib.resources.files(pkg) / name)
    mod.resource_filename = _FakeProvider.get_resource_filename
    sys.modules['pkg_resources'] = mod
import numpy as np

warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════════════════════════
# 共享常量
# ══════════════════════════════════════════════════════════════════

VIDEO_EXTENSIONS = {'.mp4', '.mov', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v'}

LETTER_PC: dict[str, int] = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

NAME_TO_PC: dict[str, int] = {
    'C': 0, 'C#': 1, 'Db': 1, 'D': 2, 'D#': 3, 'Eb': 3, 'E': 4,
    'F': 5, 'F#': 6, 'Gb': 6, 'G': 7, 'G#': 8, 'Ab': 8,
    'A': 9, 'A#': 10, 'Bb': 10, 'B': 11, 'Cb': 11,
}

PC_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
_FLAT_PC_NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']

SHARP_ORDER = ['F', 'C', 'G', 'D', 'A', 'E', 'B']
FLAT_ORDER  = ['B', 'E', 'A', 'D', 'G', 'C', 'F']

FIFTHS_MAP: dict[str, int] = {
    'C': 0, 'G': 1, 'D': 2, 'A': 3, 'E': 4, 'B': 5, 'F#': 6, 'C#': 7,
    'F': -1, 'Bb': -2, 'Eb': -3, 'Ab': -4, 'Db': -5, 'Gb': -6, 'Cb': -7,
    'a': 0, 'e': 1, 'b': 2, 'f#': 3, 'c#': 4, 'g#': 5, 'd#': 6, 'a#': 7,
    'd': -1, 'g': -2, 'c': -3, 'f': -4, 'bb': -5, 'eb': -6,
}

KEY_MAP: dict[tuple[int, str], tuple[str, int]] = {
    # 大调: (tonic_pc, 'major') → (key_name, fifths)
    (0, 'major'): ('C', 0),   (1, 'major'): ('Db', -5), (2, 'major'): ('D', 2),
    (3, 'major'): ('Eb', -3), (4, 'major'): ('E', 4),   (5, 'major'): ('F', -1),
    (6, 'major'): ('F#', 6),  (7, 'major'): ('G', 1),   (8, 'major'): ('Ab', -4),
    (9, 'major'): ('A', 3),   (10, 'major'): ('Bb', -2), (11, 'major'): ('B', 5),
    # 小调: (tonic_pc, 'minor') → (key_name, fifths) — tonic_pc 是小调自身主音
    (0, 'minor'): ('c', -3),  (1, 'minor'): ('c#', 4),  (2, 'minor'): ('d', -1),
    (3, 'minor'): ('eb', -6), (4, 'minor'): ('e', 1),   (5, 'minor'): ('f', -4),
    (6, 'minor'): ('f#', 3),  (7, 'minor'): ('g', -2),  (8, 'minor'): ('g#', 5),
    (9, 'minor'): ('a', 0),   (10, 'minor'): ('bb', -7),(11, 'minor'): ('b', 2),
}

_METER_TEMPLATES: dict[str, list[float]] = {
    '2/4': [1.0, 0.4], '3/4': [1.0, 0.4, 0.4],
    '4/4': [1.0, 0.4, 0.7, 0.4], '6/8': [1.0, 0.3, 0.3, 0.6, 0.3, 0.3],
}
_CANDIDATE_NUMERATORS = [2, 3, 4, 6]

MAJOR_OFFSETS = [0, 2, 4, 5, 7, 9, 11]
MINOR_OFFSETS = [0, 2, 3, 5, 7, 8, 10]

# 和弦模板: pitch class set (sorted) → (type_name, root_offset, inversion_base)
_CHORD_TEMPLATES: dict[tuple[int, ...], tuple[str, int, int]] = {
    (0, 4, 7): ('大三和弦', 0, 0), (0, 3, 7): ('小三和弦', 0, 0),
    (0, 4, 8): ('增三和弦', 0, 0), (0, 3, 6): ('减三和弦', 0, 0),
    (0, 4, 7, 11): ('大七和弦', 0, 0), (0, 4, 7, 10): ('属七和弦', 0, 0),
    (0, 3, 7, 10): ('小七和弦', 0, 0), (0, 3, 6, 10): ('半减七和弦', 0, 0),
    (0, 3, 6, 9): ('减七和弦', 0, 0),
}

_CHORD_SYMBOL_MAP = {
    '大三和弦': '', '小三和弦': 'm', '增三和弦': 'aug', '减三和弦': 'dim',
    '大七和弦': 'M7', '属七和弦': '7', '小七和弦': 'm7',
    '半减七和弦': 'm7b5', '减七和弦': 'dim7',
}

# TSDT 功能映射
_MAJOR_TSD: dict[int, str] = {1: 'T', 2: 'Sii', 3: 'TSvi', 4: 'S', 5: 'D', 6: 'TSvi', 7: 'Dvii°'}
_MINOR_TSD: dict[int, str] = {1: 't', 2: 'sii°', 3: 'tSIII', 4: 's', 5: 'D', 6: 'tsVI', 7: 'Dvii°'}

# 级数映射: (root_pc - tonic_pc) % 12 → scale degree
_MAJOR_DEGREE_MAP: dict[int, int] = {0: 1, 2: 2, 4: 3, 5: 4, 7: 5, 9: 6, 11: 7}
_MINOR_DEGREE_MAP: dict[int, int] = {0: 1, 2: 2, 3: 3, 5: 4, 7: 5, 8: 6, 10: 7}

# 乐器族模板
_INSTRUMENT_TEMPLATES: dict[str, dict[str, float]] = {
    'Piano':      {'centroid': 0.35, 'bandwidth': 0.45, 'rolloff': 0.40, 'zcr': 0.12, 'flatness': 0.08, 'attack_ms': 0.15, 'duration_ms': 0.35, 'harmonic_ratio': 0.85},
    'Guitar':     {'centroid': 0.45, 'bandwidth': 0.48, 'rolloff': 0.48, 'zcr': 0.18, 'flatness': 0.15, 'attack_ms': 0.10, 'duration_ms': 0.30, 'harmonic_ratio': 0.75},
    'Violin':     {'centroid': 0.55, 'bandwidth': 0.38, 'rolloff': 0.55, 'zcr': 0.14, 'flatness': 0.10, 'attack_ms': 0.30, 'duration_ms': 0.50, 'harmonic_ratio': 0.82},
    'Flute':      {'centroid': 0.65, 'bandwidth': 0.22, 'rolloff': 0.60, 'zcr': 0.08, 'flatness': 0.04, 'attack_ms': 0.25, 'duration_ms': 0.40, 'harmonic_ratio': 0.92},
    'Trumpet':    {'centroid': 0.60, 'bandwidth': 0.42, 'rolloff': 0.58, 'zcr': 0.13, 'flatness': 0.08, 'attack_ms': 0.08, 'duration_ms': 0.30, 'harmonic_ratio': 0.78},
    'Voice':      {'centroid': 0.42, 'bandwidth': 0.40, 'rolloff': 0.45, 'zcr': 0.18, 'flatness': 0.16, 'attack_ms': 0.28, 'duration_ms': 0.45, 'harmonic_ratio': 0.68},
    'Bass':       {'centroid': 0.12, 'bandwidth': 0.28, 'rolloff': 0.22, 'zcr': 0.10, 'flatness': 0.05, 'attack_ms': 0.18, 'duration_ms': 0.40, 'harmonic_ratio': 0.65},
    'Percussion': {'centroid': 0.38, 'bandwidth': 0.75, 'rolloff': 0.70, 'zcr': 0.55, 'flatness': 0.60, 'attack_ms': 0.03, 'duration_ms': 0.08, 'harmonic_ratio': 0.08},
    'Synth':      {'centroid': 0.32, 'bandwidth': 0.15, 'rolloff': 0.30, 'zcr': 0.06, 'flatness': 0.02, 'attack_ms': 0.12, 'duration_ms': 0.35, 'harmonic_ratio': 0.96},
}

# ══════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════

def is_video(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() in VIDEO_EXTENSIONS

def is_wav(filepath: str) -> bool:
    return os.path.splitext(filepath)[1].lower() in {'.wav', '.flac', '.ogg'}

def extract_audio(video_path: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.close()
    cmd = ['ffmpeg', '-y', '-i', video_path, '-vn', '-acodec', 'pcm_s16le', '-ar', '22050', '-ac', '1', tmp.name]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[1/5] 视频音频已提取: {video_path} → {tmp.name}")
    return tmp.name

def ensure_wav(input_path: str) -> str:
    tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    tmp.close()
    cmd = ['ffmpeg', '-y', '-i', input_path, '-acodec', 'pcm_s16le', '-ar', '22050', '-ac', '1', tmp.name]
    subprocess.run(cmd, capture_output=True, check=True)
    print(f"[预转换] {input_path} → {tmp.name} (FFmpeg)")
    return tmp.name

# ══════════════════════════════════════════════════════════════════
# 测试音频生成
# ══════════════════════════════════════════════════════════════════

def generate_test_audio(output_path: str, chords: bool = False, ts: str | None = None,
                        band: bool = False, test_key: str = 'C') -> str:
    import librosa
    sr = 22050
    if band:
        return _generate_band_test_audio(output_path, sr)
    elif ts:
        return _generate_ts_test_audio(output_path, ts, chords, sr)
    return _generate_scale_test_audio(output_path, chords, sr, test_key)

def _make_note(freq: float, dur: float, sr: int, attack_ms: float = 20.0, release_ms: float = 30.0, harmonics: list[float] | None = None):
    t = np.linspace(0, dur, int(dur * sr), endpoint=False)
    sig = np.sin(2 * np.pi * freq * t)
    if harmonics:
        for i, amp in enumerate(harmonics):
            sig += amp * np.sin(2 * np.pi * freq * (i + 2) * t)
    attack_n = int(attack_ms / 1000 * sr)
    release_n = int(release_ms / 1000 * sr)
    if attack_n > 0:
        sig[:attack_n] *= 0.5 * (1 - np.cos(np.pi * np.arange(attack_n) / attack_n))
    if release_n > 0:
        sig[-release_n:] *= 0.5 * (1 + np.cos(np.pi * np.arange(release_n) / release_n))
    return sig

def _generate_scale_test_audio(output_path: str, chords: bool, sr: int, tonic_name: str = 'C') -> str:
    """生成指定调性的音阶测试音频"""
    # 统一键名格式: 'a'→'A', 'bb'→'Bb', 'c#'→'C#'
    lookup = tonic_name[0].upper() + tonic_name[1:] if tonic_name[0].islower() else tonic_name
    tonic_pc = NAME_TO_PC.get(lookup, 0)
    is_minor = tonic_name[0].islower()

    if is_minor:
        # 自然小调音阶: 全半全全半全全
        intervals = [0, 2, 3, 5, 7, 8, 10, 12]
        # 和弦: i, ii°, III, iv, v, VI, VII, i
        chord_types = [(0,3,7), (0,3,6), (0,4,7), (0,3,7), (0,3,7), (0,4,7), (0,4,7), (0,3,7)]
    else:
        # 自然大调音阶: 全全半全全全半
        intervals = [0, 2, 4, 5, 7, 9, 11, 12]
        # 和弦: I, ii, iii, IV, V, vi, vii°, I
        chord_types = [(0,4,7), (0,3,7), (0,3,7), (0,4,7), (0,4,7), (0,3,7), (0,3,6), (0,4,7)]

    midi_notes = [tonic_pc + 60 + iv for iv in intervals]  # tonic octave 4
    duration = 0.5
    pieces = []
    for i, m in enumerate(midi_notes):
        freq = 440.0 * (2 ** ((m - 69) / 12.0))
        if chords:
            off = chord_types[i % 8]
            c_notes = (m + off[0], m + off[1], m + off[2])
            sig = np.zeros(int(duration * sr))
            for n in c_notes:
                sig += _make_note(440.0 * (2 ** ((n - 69) / 12.0)), duration, sr)
            sig /= len(c_notes)
        else:
            sig = _make_note(freq, duration, sr, harmonics=[0.3, 0.15])
        pieces.append(sig)
        pieces.append(np.zeros(int(0.05 * sr)))
    audio = np.concatenate(pieces)
    import soundfile as sf
    sf.write(output_path, audio, sr)
    mode_label = '小调' if is_minor else '大调'
    print(f"[测试音频] {tonic_name} {mode_label}音阶 ({len(midi_notes)}音, {'和弦' if chords else '单音'})")
    return output_path

def _generate_ts_test_audio(output_path: str, ts: str, chords: bool, sr: int) -> str:
    num = int(ts.split('/')[0])
    patterns = {'2/4': [60, 60, 57, 60], '3/4': [60, 57, 60, 57, 60, 57],
                '4/4': [60, 57, 60, 57, 60, 57, 60, 57], '6/8': [60, 60, 57, 57, 60, 60, 57, 57, 60, 60, 60, 60]}
    notes = patterns.get(ts, [60]*4)
    beat_dur = 60.0 / 120
    pieces = []
    for i, m in enumerate(notes):
        freq = 440.0 * (2 ** ((m - 69) / 12.0))
        vel = 0.3 if i % num == 0 else 0.7 if (num == 4 and i % num == 2) else 0.5
        sig = _make_note(freq, beat_dur * vel, sr)
        pieces.append(sig)
    audio = np.concatenate(pieces)
    import soundfile as sf
    sf.write(output_path, audio, sr)
    print(f"[测试音频] {ts} 拍号 - 已生成: {output_path}")
    return output_path

def _generate_band_test_audio(output_path: str, sr: int) -> str:
    dur = 4.0
    t = np.linspace(0, dur, int(dur * sr), endpoint=False)
    bass = np.sin(2 * np.pi * 110 * t) + 0.5 * np.sin(2 * np.pi * 165 * t)
    keys = 0.3 * (np.sin(2 * np.pi * 262 * t) + np.sin(2 * np.pi * 330 * t) + np.sin(2 * np.pi * 392 * t))
    noise = 0.1 * np.random.randn(len(t))
    audio = bass + keys + noise
    audio /= np.max(np.abs(audio)) + 1e-10
    import soundfile as sf
    sf.write(output_path, audio, sr)
    print(f"[测试音频] 多乐器混合 - 已生成: {output_path}")
    return output_path

# ══════════════════════════════════════════════════════════════════
# Step 2: 音高检测
# ══════════════════════════════════════════════════════════════════

def detect_pitches(audio_path: str, use_pyin: bool = False) -> tuple[list[dict], np.ndarray, int]:
    if use_pyin:
        return detect_pitches_pyin(audio_path)
    return detect_pitches_basic_pitch(audio_path)

def detect_pitches_pyin(audio_path: str) -> tuple[list[dict], np.ndarray, int]:
    import librosa
    audio, sr = librosa.load(audio_path, sr=22050, mono=True)
    f0, voicing, _ = librosa.pyin(audio, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr)
    onsets = librosa.onset.onset_detect(y=audio, sr=sr, backtrack=True)
    onsets = np.unique(np.concatenate([[0], onsets, [len(f0)-1]]))
    notes = []
    for i in range(len(onsets)-1):
        lo, hi = onsets[i], onsets[i+1]
        seg = f0[lo:hi]
        valid = seg[~np.isnan(seg)]
        if len(valid) < 5:
            continue
        hz = np.median(valid)
        midi = int(round(librosa.hz_to_midi(hz)))
        notes.append({'start_sec': lo * 512 / sr, 'end_sec': hi * 512 / sr, 'midi': midi, 'hz': hz, 'velocity': 80})
    print(f"      PYIN 检测: {len(notes)} 个音符")
    return notes, audio, sr

def detect_pitches_basic_pitch(audio_path: str) -> tuple[list[dict], np.ndarray, int]:
    import librosa
    from basic_pitch.inference import predict, ICASSP_2022_MODEL_PATH

    audio, sr = librosa.load(audio_path, sr=22050, mono=True)
    print(f"[3/5] 音频加载: {len(audio)/sr:.1f}s, sr={sr} (Basic Pitch 多音检测)")

    model_output, midi_data, note_events = predict(
        audio_path, model_or_model_path=ICASSP_2022_MODEL_PATH,
        onset_threshold=0.5, frame_threshold=0.3, minimum_note_length=0.05)

    MIN_DUR = 0.04  # 过滤泛音碎片 (40ms 以下不可能是真实音符)
    notes = []
    filtered = 0
    for ne in note_events:
        start_t, end_t, pitch, amplitude, bends = ne
        dur = float(end_t) - float(start_t)
        if dur < MIN_DUR:
            filtered += 1
            continue
        vel = int(float(amplitude) * 127) if amplitude else 80
        notes.append({'start_sec': float(start_t), 'end_sec': float(end_t),
                      'midi': int(float(pitch)), 'velocity': vel})

    notes.sort(key=lambda n: n['start_sec'])

    # 合并同 onset 的同音高泛音 (harmonics dup)
    i = 0
    merged = 0
    while i < len(notes) - 1:
        a = notes[i]
        j = i + 1
        while j < len(notes) and notes[j]['start_sec'] - a['start_sec'] < 0.06:
            if notes[j]['midi'] % 12 == a['midi'] % 12:
                # 同音名泛音: 保留低音（基音），取最长时长
                if notes[j]['end_sec'] > a['end_sec']:
                    a['end_sec'] = notes[j]['end_sec']
                notes.pop(j)
                merged += 1
            else:
                j += 1
        i += 1

    print(f"      多音检测: {len(notes)} 个音符" +
          (f"  (过滤 {filtered} 泛音碎片" + (f", 合并 {merged} 泛音重复" if merged else "") + ")" if (filtered or merged) else ""))

    # 过滤八度离群点: 远离中位音高 2 个八度以上的音符大概率是 Basic Pitch 虚假检测
    if len(notes) > 3:
        midis = [n['midi'] for n in notes]
        median_midi = float(np.median(midis))
        before = len(notes)
        notes = [n for n in notes if abs(n['midi'] - median_midi) <= 24]
        if len(notes) < before:
            print(f"      过滤 {before - len(notes)} 个八度离群点")

    # 打印前 12 个音符用于诊断
    for n in notes[:12]:
        pc = PC_NAMES[n['midi'] % 12]
        octv = n['midi'] // 12 - 1
        print(f"          {pc}{octv}  MIDI={n['midi']:3d}  {n['start_sec']:.2f}s-{n['end_sec']:.2f}s  ({n['end_sec']-n['start_sec']:.2f}s)")
    if len(notes) > 12:
        print(f"        ... 还有 {len(notes)-12} 个音符")
    return notes, audio, sr

# ══════════════════════════════════════════════════════════════════
# Step 3: 音乐分析
# ══════════════════════════════════════════════════════════════════

def analyse_music(notes: list[dict], audio: np.ndarray, sr: int) -> dict:
    import librosa

    onset_env = librosa.onset.onset_strength(y=audio, sr=sr)

    # BPM 检测 v12: 去重起音 IOI + tactus 折半 + librosa 多点起跑择优
    # 乐理依据: 拍子(tactus) 55-140 BPM (基础乐理第49-50课)。
    # 核心洞察: 去重复音起音(onset detect, delta=0.3)的IOI中位数直接给出
    # 主导节奏单元。单旋律/人声/和弦进行的主导节奏单元=拍子。
    # 只有在极密集音符(如巴赫十六分音符流)时IOI才缩到细分单元，
    # 此时折半(tactus范围)即可恢复真BPM。
    hop_length = 512

    # 1. 去重起音检测 + IOI 中位数
    onset_frames = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, hop_length=hop_length, delta=0.3)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    if len(onset_times) >= 3:
        iois = np.diff(onset_times)
        iois = iois[(iois > 0.08) & (iois < 2.5)]
        ioi_median = float(np.median(iois)) if len(iois) >= 2 else 0.0
        bpm_ioi = 60.0 / ioi_median if ioi_median > 0 else 0.0
    else:
        ioi_median = 0.0
        bpm_ioi = 0.0

    # 2. tactus 折半
    if 55 <= bpm_ioi <= 140:
        bpm = bpm_ioi
    elif bpm_ioi > 140 and 55 <= bpm_ioi / 2 <= 130:
        bpm = bpm_ioi / 2
    elif bpm_ioi > 140 and 55 <= bpm_ioi / 3 <= 130:
        bpm = bpm_ioi / 3
    elif 0 < bpm_ioi < 55 and 55 <= bpm_ioi * 2 <= 140:
        bpm = bpm_ioi * 2
    else:
        bpm = 0.0  # 不可靠，回退 librosa

    # 3. librosa 多点择优 (仅 IOI 不可靠时回退)
    if bpm == 0.0 or bpm > 180 or bpm < 35:
        best_lib_bpm = 120.0
        best_lib_score = -999.0
        for start_bpm in [40, 60, 80, 100, 120]:
            tempo, beats = librosa.beat.beat_track(
                onset_envelope=onset_env, sr=sr,
                start_bpm=start_bpm, tightness=100, hop_length=hop_length)
            bpm_raw = float(np.asarray(tempo).item())
            if bpm_raw < 35 or bpm_raw > 215 or len(beats) < 4:
                continue
            beat_t = librosa.frames_to_time(beats, sr=sr, hop_length=hop_length)
            ibis = np.diff(beat_t)
            if len(ibis) < 2:
                continue
            cv = float(np.std(ibis) / (np.mean(ibis) + 1e-10))
            # 在 0.5x/1x/2x 中选 tactus 内 CV 最佳者
            for mult in [0.5, 1.0, 2.0]:
                test_bpm = bpm_raw * mult
                if not (40 <= test_bpm <= 180):
                    continue
                tactus_w = 1.0 if 55 <= test_bpm <= 140 else 0.6
                score = -cv * tactus_w
                if score > best_lib_score:
                    best_lib_score = score
                    best_lib_bpm = test_bpm
        bpm = best_lib_bpm

    # 安全网
    if bpm > 200:
        bpm /= 2 if bpm / 2 >= 40 else 120
    elif bpm < 35:
        bpm *= 2 if bpm * 2 <= 200 else 120
    print(f"      [速度] 检测 BPM = {bpm:.0f}")

    beat_interval = 60.0 / bpm
    beat_times = np.arange(notes[0]['start_sec'], notes[-1]['end_sec'] + beat_interval, beat_interval)

    midi_list = [n['midi'] for n in notes]
    key_name, mode, fifths = _detect_key_krumhansl_kessler(midi_list)
    print(f"      [调性] {key_name} {mode} 调  (调号={'+' + str(fifths) if fifths > 0 else str(fifths)})")

    hop_length = 512
    ts_result = _infer_time_signature(notes, onset_env, beat_times, sr, hop_length, bpm)
    time_sig = ts_result['time_sig']
    beats_per_measure = ts_result['numerator']
    ts_confidence = ts_result['confidence']
    if ts_confidence < 0.40:
        print(f"      [拍号] {time_sig} 置信度过低 ({ts_confidence:.2f} < 0.40)，回退 4/4")
        time_sig = '4/4'
        beats_per_measure = 4
    else:
        print(f"      [拍号] {time_sig}  (置信度={ts_confidence:.2f})")

    quantized, _, tatum_sec, tatums_per_beat = _quantize_rhythm(notes, bpm, beat_times)

    before = len(quantized)
    quantized = _merge_fragmented_notes(quantized, bpm)
    if len(quantized) < before:
        print(f"      [合并] 合并了 {before - len(quantized)} 个碎片音符")

    quantized = _respell_notes(quantized, key_name, mode)
    quantized = _insert_bar_lines(quantized, time_sig)

    # 最后一音补齐到小节末尾 (音值组合法需要知道准确时长)
    if quantized:
        last = quantized[-1]
        measure_end_beat = last['measure'] * beats_per_measure
        needed = measure_end_beat - last['beat_pos']
        if needed > last['duration_beats']:
            last['duration_beats'] = needed
            last['end_sec'] = last['start_sec'] + needed * (60.0 / bpm)

    max_m = max(n.get('measure', 1) for n in quantized)
    print(f"      [小节] {max_m} 个小节, 拍号 {time_sig}")

    return {'notes': quantized, 'bpm': round(bpm), 'key_name': key_name, 'mode': mode,
            'fifths': fifths, 'time_sig': time_sig, 'beats_per_measure': beats_per_measure,
            'ts_confidence': ts_confidence, 'tatum_sec': tatum_sec, 'tatums_per_beat': tatums_per_beat}


def _detect_key_krumhansl_kessler(midi_notes: list[int]) -> tuple[str, str, int]:
    """音阶命中率法 v10：直接数「哪个调的音阶包含了最多的音」。

    比 KK 相关法更简单、更可解释。
    乐理依据：C大调 = 白键 CDEFGAB，G大调 = 升F... 每个调的标志就是
    升降号模式不同。数一数曲子里哪些音出现得多，匹配到对应的升降号模式即可。

    特殊处理：
    - 大调 vs 关系小调（同音阶）靠导音区分 (V-i vs V-I，和声笔记第2课)
    - 同名大小调：大三度 vs 小三度计数

    已知局限: 半音化程度高的音乐 (肖邦) 可能误判。KK 相关法更适合但
    对合成音频也不稳定。暂接受此局限。
    """
    # 阶梯式低音加权：低音区决定和声功能
    weights = np.array([5.0 if m < 48 else 2.5 if m < 60 else 1.0 for m in midi_notes])
    pc_counts = np.bincount([m % 12 for m in midi_notes], weights=weights, minlength=12).astype(float)
    total_weight = np.sum(pc_counts)
    if total_weight == 0:
        return 'C', 'major', 0

    # 候选调：12 个大调 + 12 个小调，每个评分 = 音阶内音符占比
    # 小调用自然小调7音打分。升VII级(导音)不加入音阶——太激进会导致
    # C大调误判为a小调(PC 11=B天然在C大调中，加入小调评分=给a小调送分)。
    # 升VII级只在关系大小调鉴别时作为破平局线索。
    candidates = []
    for tonic in range(12):
        for mode, offsets in [('major', MAJOR_OFFSETS), ('minor', MINOR_OFFSETS)]:
            scale_pcs = set((tonic + off) % 12 for off in offsets)
            in_key = sum(pc_counts[pc] for pc in scale_pcs)
            candidates.append((in_key / total_weight, tonic, mode))

    candidates.sort(reverse=True)
    best_score, best_tonic, best_mode = candidates[0]

    # ── 关系大小调鉴别 ──
    for cand_score, cand_tonic, cand_mode in candidates[:4]:
        if cand_score < best_score - 0.02:
            break
        if cand_tonic == best_tonic and cand_mode == best_mode:
            continue

        if best_mode == 'major' and cand_mode == 'minor' and cand_tonic == (best_tonic + 9) % 12:
            major_tonic, minor_tonic = best_tonic, cand_tonic
        elif best_mode == 'minor' and cand_mode == 'major' and best_tonic == (cand_tonic + 9) % 12:
            major_tonic, minor_tonic = cand_tonic, best_tonic
        else:
            continue

        raised_7th = pc_counts[(minor_tonic + 11) % 12]
        natural_7th = pc_counts[(minor_tonic + 10) % 12]

        if raised_7th > natural_7th * 1.3 and raised_7th > 0:
            best_score, best_tonic, best_mode = cand_score, minor_tonic, 'minor'
        else:
            best_score, best_tonic, best_mode = cand_score, major_tonic, 'major'
        break

    # ── 同名大小调鉴别 ──
    if abs(best_score - candidates[1][0]) < 0.06 and best_tonic == candidates[1][1] and best_mode != candidates[1][2]:
        maj_3rd = pc_counts[(best_tonic + 4) % 12]
        min_3rd = pc_counts[(best_tonic + 3) % 12]
        if best_mode == 'major' and min_3rd > maj_3rd * 1.5:
            best_mode = 'minor'
        elif best_mode == 'minor' and maj_3rd > min_3rd * 1.5:
            best_mode = 'major'

    name, fifths = KEY_MAP[(best_tonic, best_mode)]
    return name, best_mode, fifths

def _quantize_rhythm(notes: list[dict], bpm: float, beat_times: np.ndarray | None = None) -> tuple[list[dict], float, float, float]:
    """v12 BPM网格锚定。不再用IOI中位数推导tatum——复音音乐(Basic Pitch
    多音检测+真实钢琴)产生大量接近零的起音间隔，IOI中位数坍塌导致
    小节数疯狂膨胀(贝多芬73小节→316小节)。

    乐理依据：拍号描述拍的分组方式(基础乐理第49-50课)，量化网格
    应从BPM推导而非音符密度推导。16分音符(每拍4份)是通用分辨率。
    """
    beat_dur = 60.0 / bpm
    origin_sec = notes[0]['start_sec']

    # 16分音符：一拍分4份，tatum_sec = 16分音符时长
    tatums_per_beat = 4
    tatum_sec = beat_dur / tatums_per_beat

    quantized = []
    for i, n in enumerate(notes):
        q = dict(n)
        offset = n['start_sec'] - origin_sec
        snapped = round(offset / tatum_sec)
        q['beat_pos'] = snapped / tatums_per_beat

        if i < len(notes) - 1:
            next_offset = notes[i + 1]['start_sec'] - origin_sec
            next_snapped = round(next_offset / tatum_sec)
            dur_tatums = max(1, next_snapped - snapped)
        else:
            dur_tatums = tatums_per_beat
        q['duration_beats'] = dur_tatums / tatums_per_beat
        q['duration_sec'] = q['duration_beats'] * beat_dur
        quantized.append(q)

    return quantized, bpm, tatum_sec, tatums_per_beat

def _merge_fragmented_notes(notes: list[dict], bpm: float) -> list[dict]:
    eighth = (60.0 / bpm) / 2
    i = 0
    while i < len(notes) - 1:
        a, b = notes[i], notes[i+1]
        if a['midi'] == b['midi'] and (b['start_sec'] - a['end_sec']) < eighth:
            a['end_sec'] = b['end_sec']
            a['duration_beats'] = (a['end_sec'] - a['start_sec']) / (60.0 / bpm)
            notes.pop(i+1)
        else:
            i += 1
    return notes

def _infer_time_signature(notes: list[dict], onset_env: np.ndarray, beat_times: np.ndarray, sr: int, hop_length: int, bpm: float) -> dict:
    """拍号推断 v10：IOI自相关 + 音符起音计数。

    v10a: 不再依赖 librosa BPM 的 beat_times（对 rubato 古典钢琴不可靠）。
    直接从 deduped note onsets 计算 IOI 中位数作为 beat period，
    生成独立 beat grid，上面计数 note onsets → 模板匹配。
    """
    if len(notes) < 4:
        return {'numerator': 4, 'denominator': 4, 'time_sig': '4/4', 'confidence': 0.0}

    # 1. 从 BPM 推导节拍周期 (v11: 替代 IOI 中位数)
    #    十六分音符密集琶音下 IOI 中位数 ≈ 0.2s，但拍子可能在 0.8s。
    #    用 BPM 推导符合「拍号描述拍的分组而非音符密度」这一乐理事实。
    beat_period = 60.0 / max(bpm, 30)

    # 2. 节拍网格 + 动态加权起音计数: 力度大的音更可能落在强拍上
    onset_secs = [n['start_sec'] for n in notes]
    grid = np.arange(min(onset_secs), max(onset_secs) + beat_period, beat_period)
    if len(grid) < 8:
        return {'numerator': 4, 'denominator': 4, 'time_sig': '4/4', 'confidence': 0.0}

    # 3. 动态加权拍内起音计数: 力度大的音更可能是强拍音 (和声笔记第33课)
    window = beat_period * 0.35
    counts = np.zeros(len(grid))
    for n in notes:
        vel_w = 1.0 + n.get('velocity', 80) / 255.0
        best = int(np.argmin(np.abs(grid - n['start_sec'])))
        if best < len(counts) and abs(grid[best] - n['start_sec']) < window:
            counts[best] += vel_w
    mean_c = np.mean(counts)
    if mean_c < 0.05:
        return {'numerator': 4, 'denominator': 4, 'time_sig': '4/4', 'confidence': 0.0}
    accents = counts / mean_c

    # 3.5 自相关: lag=3 有峰→3/4(圆舞曲循环), lag=6 有峰→6/8(复合二拍)
    #     乐理: 3/4 每三拍重复强弱模式, 6/8 每六拍(两组三拍)重复
    centered = accents - np.mean(accents)
    ac = np.correlate(centered, centered, mode='full')
    ac = ac[len(ac)//2:] / (ac[len(ac)//2] + 1e-10)
    ac3 = float(ac[3]) if len(ac) > 3 else 0.0
    ac6 = float(ac[6]) if len(ac) > 6 else 0.0

    # 4. 模板匹配 + 自相关先验
    best_score = -999.0
    best_num = 4
    for num in _CANDIDATE_NUMERATORS:
        if num > len(accents) // 2:
            continue
        template = np.array(_METER_TEMPLATES[f'{num}/4' if num != 6 else '6/8'])
        pattern = np.tile(template, len(accents) // num + 1)[:len(accents)]
        corr = np.corrcoef(accents, pattern)[0, 1]
        if np.isnan(corr):
            continue
        downbeat_ratio = np.mean(accents[::num]) / (np.mean(accents) + 1e-10)
        score = corr * 0.5 + downbeat_ratio * 0.5
        # 自相关先验加分
        if num == 3 and ac3 > 0.3 and ac3 > ac6 * 1.2:
            score += 0.15
        elif num == 6 and ac6 > 0.3 and ac6 > ac3 * 1.2:
            score += 0.15
        elif num == 4 and ac3 < 0.2 and ac6 < 0.2:
            score += 0.10
        if score > best_score:
            best_score = score
            best_num = num

    denom = 8 if best_num == 6 else 4
    confidence = round(min(max(best_score, 0.0), 1.0), 2)
    return {'numerator': best_num, 'denominator': denom, 'time_sig': f'{best_num}/{denom}', 'confidence': confidence}

def _insert_bar_lines(notes: list[dict], time_sig: str) -> list[dict]:
    numerator = int(time_sig.split('/')[0])
    for n in notes:
        bp = n.get('beat_pos', 0)
        measure = int(bp / numerator) + 1
        beat_in_measure = round((bp % numerator) + 1, 2)
        n['measure'] = measure
        n['beat_in_measure'] = beat_in_measure
    return notes

def _respell_pc(pc: int, key_name: str, mode: str) -> str:
    """根据调性上下文返回等音正确的音名。降号调用 flat 名，升号/C调用 sharp 名。"""
    fifths = FIFTHS_MAP.get(key_name.lower() if mode == 'minor' else key_name, 0)
    if fifths >= 0:
        return PC_NAMES[pc % 12]
    else:
        return _FLAT_PC_NAMES[pc % 12]


def _respell_notes(notes: list[dict], key_name: str, mode: str) -> list[dict]:
    for n in notes:
        pc = n['midi'] % 12
        n['pitch_name'] = f"{_respell_pc(pc, key_name, mode)}{n['midi']//12 - 1}"
    return notes

# ══════════════════════════════════════════════════════════════════
# 和弦分析
# ══════════════════════════════════════════════════════════════════

def identify_chord(pitches: list[int], key_name: str = 'C', mode: str = 'major') -> dict | None:
    """pitch class set → 和弦类型 + 根音 + 转位 (v9 重写, v10a: 等音拼写)"""
    if len(pitches) < 3:
        return None

    sorted_pitches = sorted(pitches)
    pcs = sorted(set(p % 12 for p in sorted_pitches))

    for root_offset in range(12):
        rotated = tuple(sorted((pc - root_offset) % 12 for pc in pcs))
        if rotated in _CHORD_TEMPLATES:
            type_name, _, _ = _CHORD_TEMPLATES[rotated]

            # 找到 root_pc 对应的实际 MIDI 音高
            root_midi = None
            for p in sorted_pitches:
                if p % 12 == root_offset:
                    root_midi = p
                    break
            if root_midi is None:
                root_midi = sorted_pitches[0]

            bass_pc = sorted_pitches[0] % 12

            # 转位 = bass note 在 chord pc set 中的位置
            inversion = 0
            for i, pc in enumerate(pcs):
                if pc == bass_pc:
                    inversion = i
                    break

            # 等音拼写: 根据调性上下文选择正确的音名 (Ab ≠ G#)
            root_name = _respell_pc(root_offset, key_name, mode)
            symbol = root_name + _CHORD_SYMBOL_MAP.get(type_name, '')

            return {
                'type': type_name,
                'root_pc': root_offset,
                'root_midi': root_midi,
                'root_name': root_name,
                'symbol': symbol,
                'inversion': inversion,
                'bass_pc': bass_pc,
            }

    return None


def group_notes_into_chords(notes: list[dict], tolerance: float = 0.12) -> list[tuple[list[dict], float]]:
    """按 onset 分组，组内按 MIDI 音高排序"""
    groups = []
    i = 0
    while i < len(notes):
        g = [notes[i]]
        onset = notes[i]['start_sec']
        j = i + 1
        while j < len(notes) and notes[j]['start_sec'] - onset < tolerance:
            g.append(notes[j])
            j += 1
        g.sort(key=lambda n: n['midi'])  # 低音在前
        groups.append((g, onset))
        i = j
    return groups


def _resolve_tonic_pc(key_name: str) -> int:
    """统一键名解析: 'a'→'A', 'bb'→'Bb', 'c#'→'C#'"""
    if not key_name:
        return 0
    lookup = key_name[0].upper() + key_name[1:] if key_name[0].islower() else key_name
    return NAME_TO_PC.get(lookup, 0)


def analyse_tsdt(chord_sequence: list[dict], key_name: str, mode: str) -> list[dict]:
    """TSDT 功能分析 (v9: 修正小调级数映射)"""
    tonic_pc = _resolve_tonic_pc(key_name)
    degree_map = _MINOR_DEGREE_MAP if mode == 'minor' else _MAJOR_DEGREE_MAP
    func_map = _MINOR_TSD if mode == 'minor' else _MAJOR_TSD

    results = []
    prev_func = None
    for ch in chord_sequence:
        root_pc = ch.get('root_pc', 0)
        semitone_dist = (root_pc - tonic_pc) % 12
        deg = degree_map.get(semitone_dist, 0)
        func = func_map.get(deg, '?')

        warning = ''
        if prev_func and 'D' in str(prev_func) and 'S' in str(func) and 's' in str(func):
            warning = '⚠ D→S 反功能进行'

        results.append({**ch, 'degree': str(deg), 'function': func, 'warning': warning})
        prev_func = func
    return results

# ══════════════════════════════════════════════════════════════════
# 首调简谱 (v9 重写)
# ══════════════════════════════════════════════════════════════════

def notes_to_jianpu(notes: list[dict], key_name: str, mode: str) -> list[dict]:
    """音名 → 首调唱名。小调用关系大调首调法 (tonic = la = 6)"""
    tonic_pc = _resolve_tonic_pc(key_name)

    if mode == 'minor':
        # 关系大调首调法: 小调主音 = la(6)
        relative_major_pc = (tonic_pc + 3) % 12
        effective_do_pc = relative_major_pc
        pc_to_degree: dict[int, int] = {}
        for d, off in enumerate(MAJOR_OFFSETS):
            pc_to_degree[(relative_major_pc + off) % 12] = d + 1
    else:
        effective_do_pc = tonic_pc
        pc_to_degree = {}
        for d, off in enumerate(MAJOR_OFFSETS):
            pc_to_degree[(tonic_pc + off) % 12] = d + 1

    # 八度参考: 有效 do 在 octave 4 (MIDI = effective_do_pc + 60)
    do_midi_4 = effective_do_pc + 60

    result = []
    for n in notes:
        pc = n['midi'] % 12
        if pc in pc_to_degree:
            degree = pc_to_degree[pc]
            acc = ''
        else:
            degree, acc = _find_nearest_degree(pc, pc_to_degree)

        oct_offset = (n['midi'] - do_midi_4) // 12
        jianpu = str(degree)
        if oct_offset > 0:
            jianpu += '̇' * oct_offset          # U+0307 combining dot above
        elif oct_offset < 0:
            jianpu += '̣' * abs(oct_offset)     # U+0323 combining dot below
        if acc:
            jianpu = acc + jianpu

        result.append({**n, 'jianpu': jianpu, 'jp_degree': degree, 'jp_octave': oct_offset})
    return result


def _find_nearest_degree(pc: int, pc_to_degree: dict[int, int]) -> tuple[int, str]:
    """找最近的调内音级，返回 (degree, accidental)"""
    for d_pc, deg in sorted(pc_to_degree.items(), key=lambda x: (pc - x[0]) % 12):
        dist = (pc - d_pc) % 12
        if dist == 1:
            return deg, '#'
        elif dist == 11:
            return deg, 'b'
    return 1, '#'


def format_jianpu(jianpu_notes: list[dict], key_name: str, mode: str, time_sig: str = '4/4') -> str:
    """音值组合法格式化简谱: 以拍为组、长音增时线、半小节分隔、休止符 0"""
    from collections import defaultdict

    numerator = int(time_sig.split('/')[0])
    lines = [f"     [简谱] 1 = {key_name}  {time_sig}"]

    measures = defaultdict(list)
    for n in jianpu_notes:
        measures[n.get('measure', 1)].append(n)

    for m_num in sorted(measures.keys()):
        # 以拍为单位建立网格
        beat_slots = [[] for _ in range(numerator)]

        for n in measures[m_num]:
            jp = n.get('jianpu', '?')
            beat_in_meas = n.get('beat_in_measure', 1)  # 1-indexed
            dur = n.get('duration_beats', 1)

            bi = int(beat_in_meas) - 1  # 0-indexed beat
            if 0 <= bi < numerator:
                beat_slots[bi].append(jp)

            # 增时线: 跨拍延长
            for d in range(1, min(int(dur), numerator - bi)):
                beat_slots[bi + d].append('-')

        # 每拍渲染为一个 token
        beat_tokens = []
        for b in range(numerator):
            non_dash = [x for x in beat_slots[b] if x != '-']
            dashes = [x for x in beat_slots[b] if x == '-']

            if not beat_slots[b]:
                beat_tokens.append('0')              # 休止符
            elif len(non_dash) <= 1:
                # 单音或单音+增时线
                beat_tokens.append(beat_slots[b][0])
            else:
                # 同拍内多音: 去重同音级泛音，和弦用 / 分隔
                seen_base = set()
                unique = []
                for x in non_dash:
                    base = x.lstrip('#b')[0]  # 提取音级数字 (去除升降号和八度点)
                    if base not in seen_base:
                        seen_base.add(base)
                        unique.append(x)
                beat_tokens.append('/'.join(unique))

        # 音值组合: 半小节分隔 (4/4 在 2-3 拍间加宽间距)
        if numerator >= 4 and numerator % 2 == 0:
            half = numerator // 2
            left = '  '.join(beat_tokens[:half])
            right = '  '.join(beat_tokens[half:])
            line = f"  | {left}    {right}  |"
        elif numerator == 3:
            line = "  | " + "  ".join(beat_tokens) + "  |"
        else:
            line = "  | " + "  ".join(beat_tokens) + "  |"

        lines.append(line)

    return '\n'.join(lines)

# ══════════════════════════════════════════════════════════════════
# 音色识别 (v9: 去掉过度激进的硬规则)
# ══════════════════════════════════════════════════════════════════

def _extract_note_features(audio: np.ndarray, sr: int, start_sec: float, end_sec: float) -> dict | None:
    import librosa
    ss = max(0, int(start_sec * sr))
    ee = min(len(audio), int(end_sec * sr))
    dur_ms = (end_sec - start_sec) * 1000
    if ee - ss < sr * 0.02:
        return None
    seg = audio[ss:ee]
    n_fft = min(2048, len(seg))
    hop = max(n_fft // 8, 64)
    if len(seg) < n_fft:
        seg = np.pad(seg, (0, n_fft - len(seg)))
    S = np.abs(librosa.stft(seg, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    centroid = float(librosa.feature.spectral_centroid(S=S, freq=freqs).mean())
    bandwidth = float(librosa.feature.spectral_bandwidth(S=S, freq=freqs).mean())
    rolloff = float(librosa.feature.spectral_rolloff(S=S, freq=freqs).mean())
    zcr = float(librosa.feature.zero_crossing_rate(seg).mean())
    flatness = float(librosa.feature.spectral_flatness(S=S).mean())
    rms_env = np.array([np.sqrt(np.mean(seg[max(0, t-hop):t+hop] ** 2)) for t in range(0, len(seg), hop)])
    if len(rms_env) > 3 and rms_env.max() > 1e-8:
        env_norm = rms_env / (rms_env.max() + 1e-10)
        lo = int(np.argmax(env_norm > 0.10))
        hi = int(np.argmax(env_norm > 0.90))
        attack_ms = max(0, hi - lo) * hop / sr * 1000 if hi > 0 else dur_ms * 0.15
    else:
        attack_ms = dur_ms * 0.10
    if len(seg) > n_fft:
        ac = np.correlate(seg[:n_fft], seg[:n_fft], mode='full')
        ac = ac[len(ac)//2:]
        harmonic_ratio = min(float(np.max(ac[max(1, len(ac)//12):])) / (float(ac[0]) + 1e-10), 1.0) if ac[0] > 1e-10 else 0.0
    else:
        harmonic_ratio = 0.5
    return {'centroid': min(centroid / 4000, 1.0), 'bandwidth': min(bandwidth / 3200, 1.0),
            'rolloff': min(rolloff / 4000, 1.0), 'zcr': zcr, 'flatness': flatness,
            'attack_ms': min(attack_ms / 100, 1.0), 'duration_ms': min(dur_ms / 1000, 1.0),
            'harmonic_ratio': harmonic_ratio}


def classify_timbre(features: dict) -> tuple[str, float, list[tuple[str, float]]]:
    """余弦距离匹配最相似乐器族 (v9: 去掉硬规则，纯模板匹配)"""
    best_label, best_sim = 'Synth', -1.0
    scores = []
    for label, tmpl in _INSTRUMENT_TEMPLATES.items():
        dot = sum(features[k] * tmpl[k] for k in features)
        norm_f = np.sqrt(sum(features[k]**2 for k in features))
        norm_t = np.sqrt(sum(tmpl[k]**2 for k in features))
        sim = dot / (norm_f * norm_t + 1e-10)
        scores.append((label, sim))
        if sim > best_sim:
            best_sim, best_label = sim, label

    scores.sort(key=lambda x: -x[1])
    return best_label, best_sim, scores[:3]


def _run_timbre_analysis(audio: np.ndarray, sr: int, notes: list[dict]) -> dict:
    """逐音符分类 + 汇总分布"""
    from collections import Counter
    labels = []
    for n in notes:
        f = _extract_note_features(audio, sr, n['start_sec'], n['end_sec'])
        if f is None:
            n['timbre_label'], n['timbre_confidence'] = '—', 0.0
            continue
        label, conf, _ = classify_timbre(f)
        n['timbre_label'], n['timbre_confidence'] = label, conf
        labels.append(label)
    if not labels:
        return {'instrument_counts': {}, 'primary_instrument': '未知'}
    cnt = Counter(labels)
    primary = cnt.most_common(1)[0][0]
    return {'instrument_counts': dict(cnt), 'primary_instrument': primary}


def _print_timbre_summary(timbre: dict, prefix: str = '      '):
    if not timbre.get('instrument_counts'):
        return
    cnt = timbre['instrument_counts']
    total = sum(cnt.values())
    primary = timbre['primary_instrument']
    perc = cnt[primary] / total * 100 if total > 0 else 0
    print(f"\n{prefix}[音色] {total} 个音符分布: ", end='')
    items = sorted(cnt.items(), key=lambda x: -x[1])
    parts = [f"{k} {v}个({v/total*100:.0f}%)" for k, v in items]
    print(', '.join(parts))
    if total <= 20:
        print(f"{prefix}        ⚠ 合成音频/短片段分类仅供参考，真乐器需 MFCC 增强")

# ══════════════════════════════════════════════════════════════════
# Step 4: MIDI 生成
# ══════════════════════════════════════════════════════════════════

def notes_to_midi(analysis: dict, output_path: str):
    import pretty_midi
    bpm = analysis['bpm']
    notes = analysis['notes']
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    num, den = analysis['time_sig'].split('/')
    pm.time_signature_changes.append(pretty_midi.TimeSignature(int(num), int(den), 0.0))
    # 嵌入调号到 MIDI（music21 解析时需要）
    ks_name = analysis['key_name'] if analysis['mode'] == 'major' else analysis['key_name'].lower()
    pm.key_signature_changes.append(pretty_midi.KeySignature(pretty_midi.key_name_to_key_number(ks_name), 0.0))
    piano = pretty_midi.Instrument(program=0, name='Piano')
    beat_dur = 60.0 / bpm
    for note in notes:
        start = note['beat_pos'] * beat_dur
        end = (note['beat_pos'] + note['duration_beats']) * beat_dur
        midi = note['midi']
        if 0 <= midi <= 127:
            piano.notes.append(pretty_midi.Note(velocity=80, pitch=midi, start=start, end=end))
    pm.instruments.append(piano)
    pm.write(output_path)
    print(f"[4/5] MIDI 已生成: {output_path}  (tempo={bpm:.1f} BPM)")

# ══════════════════════════════════════════════════════════════════
# Step 5: 五线谱生成
# ══════════════════════════════════════════════════════════════════

def _respell_score_notes(score, key_name: str, mode: str):
    """根据调号重拼五线谱中所有音符的等音（MIDI 只有 pitch number，默认升号拼写）。
    乐理依据：等音正确拼写取决于调号上下文（基础乐理第1-16课）。"""
    from music21 import pitch as m21pitch

    # 构建每个 pitch class 在目标调中的首选拼写
    # 大调音阶半音偏移 [0,2,4,5,7,9,11]，小调用关系大调
    if mode == 'minor':
        effective_tonic = (NAME_TO_PC.get(key_name.capitalize(), 0) + 3) % 12
    else:
        effective_tonic = NAME_TO_PC.get(key_name, 0)

    # 大调音阶的 pitch class 集合
    major_offsets = [0, 2, 4, 5, 7, 9, 11]
    scale_pcs = set((effective_tonic + o) % 12 for o in major_offsets)

    # 为 scale 中的每个 pc 分配标准音名
    letter_pool = ['C', 'D', 'E', 'F', 'G', 'A', 'B']
    # 从主音出发，按大调音阶分配字母（每个字母只用一次）
    tonic_idx = letter_pool.index(_respell_pc(effective_tonic, key_name, mode)[0])

    preferred = {}  # pc -> (step, alter)
    for i, offset in enumerate(major_offsets):
        pc = (effective_tonic + offset) % 12
        letter = letter_pool[(tonic_idx + i) % 7]
        # 这个字母的声音在 12-TET 中对应的默认 PC
        default_pc = NAME_TO_PC.get(letter, 0)
        alter = pc - default_pc
        # 标准化 alter 到 [-2, 2]
        if alter > 6:
            alter -= 12
        elif alter < -6:
            alter += 12
        if alter not in (-1, 0, 1, 2, -2):
            alter = alter % 12
            if alter > 6:
                alter -= 12
        preferred[pc] = (letter, alter)

    # 遍历所有音符，必要时重拼
    for el in score.recurse().notes:
        if el.isChord:
            for p in el.pitches:
                pc = p.midi % 12
                if pc in preferred:
                    target_step, target_alter = preferred[pc]
                    cur_alter = p.accidental.alter if p.accidental else 0
                    if p.step != target_step or cur_alter != target_alter:
                        # 找到等效的拼写
                        target = m21pitch.Pitch(target_step + ('#' if target_alter > 0 else '-' if target_alter < 0 else ''))
                        if target.ps != p.ps:
                            target = target.getEnharmonic()
                        if abs(target.ps - p.ps) < 0.01:
                            p.step = target.step
                            p.accidental = target.accidental
        elif el.isNote and el.pitch:
            p = el.pitch
            pc = p.midi % 12
            if pc in preferred:
                target_step, target_alter = preferred[pc]
                # 构建目标 pitch name
                alter_str = '#' * target_alter if target_alter > 0 else '-' * abs(target_alter) if target_alter < 0 else ''
                target_name = target_step + alter_str
                try:
                    target = m21pitch.Pitch(target_name)
                except Exception:
                    continue
                cur_alter = p.accidental.alter if p.accidental else 0
                if abs(target.ps - p.ps) < 0.01 and (p.step != target_step or cur_alter != target_alter):
                    p.step = target.step
                    p.accidental = target.accidental


def midi_to_sheet(midi_path: str, output_dir: str, analysis: dict):
    from music21 import converter, metadata, key, meter, clef

    key_name = analysis['key_name']
    mode = analysis['mode']
    bpm = analysis['bpm']
    time_sig = analysis['time_sig']

    score = converter.parse(midi_path)

    all_midis = []
    for p in score.parts:
        for el in p.recurse().notes:
            if el.isChord:
                all_midis.extend(pitch.midi for pitch in el.pitches)
            elif el.isNote and el.pitch:
                all_midis.append(el.pitch.midi)

    if not all_midis:
        xml_path = os.path.join(output_dir, "output.musicxml")
        score.write('musicxml', fp=xml_path)
        return

    median_midi = int(np.median(np.array(all_midis)))
    use_treble = median_midi >= 55
    clef_label = "高音谱号" if use_treble else "低音谱号"
    print(f"      [谱号] 音域{max(all_midis)-min(all_midis)}半音 中位数={median_midi} → {clef_label}")

    for part in score.parts:
        part.insert(0, clef.TrebleClef() if use_treble else clef.BassClef())

    # MIDI 只存 pitch number，music21 默认用升号拼写。根据调号重拼所有音符
    _respell_score_notes(score, key_name, mode)

    score.metadata = metadata.Metadata()
    score.metadata.title = f"识谱 — {key_name} {mode}调  {bpm:.0f} BPM"
    score.metadata.composer = "Demo 独自升级"

    xml_path = os.path.join(output_dir, "output.musicxml")
    score.write('musicxml', fp=xml_path)

    # XML 后处理: 字符串替换谱号
    new_sign = "G" if use_treble else "F"
    with open(xml_path, 'r') as f:
        xml = f.read()

    # 修复谱号 (music21 write() 强制调用 makeNotation 覆盖手动插入的谱号)
    idx = xml.find('<sign>')
    if idx > 0:
        end_idx = xml.find('</sign>', idx)
        xml = xml[:idx] + f'<sign>{new_sign}</sign>' + xml[end_idx+7:]

    with open(xml_path, 'w') as f:
        f.write(xml)

    print(f"[5/5] MusicXML 已生成: {xml_path}  ({clef_label})")
    ks_sharps = FIFTHS_MAP.get(key_name if mode == 'major' else key_name.lower(), 0)
    nr = abs(ks_sharps)
    sharps_or_flats = f"{'+' + str(ks_sharps) + ' 升号' if ks_sharps > 0 else (str(nr) + ' 降号' if ks_sharps < 0 else '无升降号')}"
    print(f"\n  调号: {sharps_or_flats}")

# ══════════════════════════════════════════════════════════════════
# 声源分离 (P3)
# ══════════════════════════════════════════════════════════════════

_demucs_model = None

def _get_demucs_model():
    global _demucs_model
    if _demucs_model is None:
        from demucs import pretrained
        _demucs_model = pretrained.get_model('htdemucs')
        _demucs_model.eval()
    return _demucs_model

def separate_sources(audio_path: str, output_dir: str, device: str = 'cpu') -> list[dict]:
    import torch, scipy
    import librosa
    model = _get_demucs_model()
    wav, sr = librosa.load(audio_path, sr=44100, mono=False)
    if wav.ndim == 1:
        wav = np.stack([wav, wav])
    wav_tensor = torch.from_numpy(wav).float()
    if device == 'mps' and torch.backends.mps.is_available():
        wav_tensor = wav_tensor.to('mps')
        model = model.to('mps')
    with torch.no_grad():
        sources = model(wav_tensor.unsqueeze(0))[0]
    stem_names = ['drums', 'bass', 'other', 'vocals']
    stems = []
    for i, name in enumerate(stem_names):
        src = sources[i].cpu().numpy()
        mono = src.mean(axis=0)
        if sr != 22050:
            mono = scipy.signal.resample(mono, int(len(mono) * 22050 / sr))
        rms = np.sqrt(np.mean(mono ** 2))
        if rms < 1e-5:
            print(f"      [分离] {name}: 静音，跳过")
            stems.append({'name': name, 'path': None, 'silent': True})
            continue
        path = os.path.join(output_dir, f"stem_{name}.wav")
        import soundfile as sf
        sf.write(path, mono.astype(np.float32), 22050)
        print(f"      [分离] {name}: {path} (RMS={rms:.4f})")
        stems.append({'name': name, 'path': path, 'silent': False})
    return stems

# ══════════════════════════════════════════════════════════════════
# Pipeline 编排
# ══════════════════════════════════════════════════════════════════

def _cleanup_generated_files(output_dir: str, keep: bool, was_auto_test: bool):
    """清理自动生成的测试/中间文件"""
    if keep:
        return
    patterns = ['test_*.wav', 'stem_*.wav']
    for pat in patterns:
        for f in glob.glob(os.path.join(output_dir, pat)):
            os.remove(f)
            print(f"[清理] {os.path.basename(f)}")

    # 非用户输入的运行: 也清理输出产物
    if was_auto_test:
        for fname in ['output.mid', 'output.musicxml', 'output.pdf']:
            fp = os.path.join(output_dir, fname)
            if os.path.exists(fp):
                os.remove(fp)


def _run_pipeline_stem(audio_path: str, label: str, output_dir: str, use_pyin: bool) -> dict:
    """单轨完整 Pipeline"""
    print(f"\n{'='*50}\n  {label}\n{'='*50}")
    notes, audio, sr = detect_pitches(audio_path, use_pyin)
    if not notes:
        print(f"  ⚠ 未检测到音符")
        return {}

    analysis = analyse_music(notes, audio, sr)

    # 和弦分组 + 识别 (传入调性上下文做等音拼写)
    groups = group_notes_into_chords(analysis['notes'])
    chords_raw = []
    for g, onset in groups:
        mids = [n['midi'] for n in g]
        ch = identify_chord(mids, analysis['key_name'], analysis['mode'])
        if ch:
            chords_raw.append({
                'onset': onset,
                'root_pc': ch['root_pc'],
                'root_name': ch['root_name'],
                'type': ch['type'],
                'symbol': ch['symbol'],
                'inversion': ch['inversion'],
            })
    analysis['chords'] = analyse_tsdt(chords_raw, analysis['key_name'], analysis['mode'])

    # 简谱
    jp = notes_to_jianpu(analysis['notes'], analysis['key_name'], analysis['mode'])
    analysis['jianpu_text'] = format_jianpu(jp, analysis['key_name'], analysis['mode'], analysis['time_sig'])

    # 音色
    analysis['timbre'] = _run_timbre_analysis(audio, sr, analysis['notes'])
    _print_timbre_summary(analysis['timbre'])

    # MIDI + 五线谱
    midi_path = os.path.join(output_dir, "output.mid")
    notes_to_midi(analysis, midi_path)
    midi_to_sheet(midi_path, output_dir, analysis)

    return analysis


def _build_json_summary(analysis: dict, output_dir: str = '') -> dict:
    chords_json = []
    for c in analysis.get('chords', []):
        chords_json.append({
            'symbol': c.get('symbol', '?'),
            'root_name': c.get('root_name', '?'),
            'degree': str(c.get('degree', '0')),
            'function': str(c.get('function', '?')),
            'inversion': c.get('inversion', 0),
            'warning': c.get('warning', ''),
        })

    timbre_data = analysis.get('timbre', {})
    return {
        'key_name': analysis.get('key_name', '?'),
        'mode': analysis.get('mode', 'major'),
        'bpm': analysis.get('bpm', 0),
        'time_sig': analysis.get('time_sig', '4/4'),
        'chords': chords_json,
        'jianpu': analysis.get('jianpu_text', ''),
        'timbre': {
            'primary': timbre_data.get('primary_instrument', 'Unknown'),
            'distribution': timbre_data.get('instrument_counts', {}),
        },
        'files': {
            'midi': os.path.join(output_dir, "output.mid") if output_dir else '',
            'musicxml': os.path.join(output_dir, "output.musicxml") if output_dir else '',
        },
    }


def _print_json_summary(analysis: dict, output_dir: str = ''):
    summary = _build_json_summary(analysis, output_dir)
    print("\n__JSON_BEGIN__")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("__JSON_END__")


def _print_separate_json_summary(stem_results: list[dict]):
    stems_out = []
    for sr in stem_results:
        a = sr.get('analysis', {})
        timbre_data = a.get('timbre', {})
        stems_out.append({
            'stem': sr['label'],
            'key_name': a.get('key_name', '?'),
            'mode': a.get('mode', 'major'),
            'bpm': a.get('bpm', 0),
            'time_sig': a.get('time_sig', '4/4'),
            'chords': [{
                'symbol': c.get('symbol', '?'),
                'degree': c.get('degree', '0'),
                'function': c.get('function', '?'),
                'inversion': c.get('inversion', 0),
            } for c in a.get('chords', [])],
            'jianpu': a.get('jianpu_text', ''),
            'timbre': {
                'primary': timbre_data.get('primary_instrument', 'Unknown'),
                'distribution': timbre_data.get('instrument_counts', {}),
            },
        })
    print("\n__JSON_BEGIN__")
    print(json.dumps({'stems': stems_out}, indent=2, ensure_ascii=False))
    print("__JSON_END__")

# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='Demo 独自升级 · 识谱 Pipeline')
    parser.add_argument('input', nargs='?', help='音频/视频文件路径')
    parser.add_argument('--pyin', action='store_true', help='PYIN 单音检测 (兼容模式)')
    parser.add_argument('--chords', action='store_true', help='生成和弦测试音频')
    parser.add_argument('--ts', help='拍号测试 (2/4|3/4|4/4|6/8)')
    parser.add_argument('--band', action='store_true', help='多乐器混合测试')
    parser.add_argument('--separate', nargs='?', const='cpu', help='demucs 声源分离')
    parser.add_argument('--output-dir', default=os.path.dirname(os.path.abspath(__file__)),
                        help='输出目录')
    parser.add_argument('--json', action='store_true', help='输出 JSON 摘要')
    parser.add_argument('--keep', action='store_true', help='保留生成的测试文件')
    parser.add_argument('--test-key', default='C', help='测试调性: C, G, F, D, Bb, a, e, d 等 (默认 C)')
    args = parser.parse_args()

    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    use_pyin = args.pyin
    separate_mode = args.separate is not None
    was_auto_test = not args.input  # 没有用户输入 = 自动测试模式

    print("━━━ Demo 独自升级 · 识谱 Pipeline v10 ━━━")
    print(f"检测后端: {'PYIN (单音)' if use_pyin else 'Basic Pitch (多音)'}")

    # 输入
    if args.input:
        input_path = args.input
        if not os.path.exists(input_path):
            print(f"文件不存在: {input_path}")
            sys.exit(1)
        if is_video(input_path):
            audio_path = extract_audio(input_path)
        elif not is_wav(input_path):
            audio_path = ensure_wav(input_path)
        else:
            audio_path = input_path
        print(f"使用输入: {input_path}\n")
    elif args.band and separate_mode:
        audio_path = _generate_band_test_audio(os.path.join(output_dir, "test_band.wav"), 22050)
    else:
        audio_path = generate_test_audio(
            os.path.join(output_dir, "test_c_major.wav"),
            args.chords, args.ts, test_key=args.test_key)

    if separate_mode:
        if use_pyin:
            print("PYIN + demucs 不兼容，自动切换 Basic Pitch")
            use_pyin = False
        device = args.separate or 'cpu'
        stems = separate_sources(audio_path, output_dir, device)
        stem_results = []
        for s in stems:
            if not s['silent']:
                a = _run_pipeline_stem(s['path'], s['name'].upper(), output_dir, use_pyin)
                stem_results.append({'label': s['name'], 'analysis': a})

        print(f"\n{'='*50}\n  汇总")
        for sr in stem_results:
            a = sr['analysis']
            print(f"  {sr['label']:<8} {a.get('key_name','?'):>4} {a.get('mode','?')}调  "
                  f"{a.get('bpm','?'):.0f} BPM  {a.get('time_sig','?')}")
        if args.json:
            _print_separate_json_summary(stem_results)
    else:
        analysis = _run_pipeline_stem(audio_path, '总谱', output_dir, use_pyin)
        if analysis:
            bpm = analysis.get('bpm', 0)
            chords_list = analysis.get('chords', [])
            chord_str = ' → '.join(
                f"{c.get('symbol','?')}({c.get('function','?')})"
                for c in chords_list[:20])
            print(f"\n检测结果: {analysis.get('key_name','?')} {analysis.get('mode','?')}调, "
                  f"{bpm:.0f} BPM, {analysis.get('time_sig','?')}" +
                  (f"\n和弦进行: {chord_str}" if chord_str else ""))
            if analysis.get('jianpu_text'):
                print(analysis['jianpu_text'])

            if args.json:
                _print_json_summary(analysis, output_dir)

    # 清理
    _cleanup_generated_files(output_dir, args.keep, was_auto_test)
    if not args.keep and was_auto_test:
        print(f"[清理] 测试生成文件已删除 (--keep 可保留)")

if __name__ == '__main__':
    main()
