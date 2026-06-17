import os
import re
import subprocess
from collections.abc import Callable

SEGMENT_BITRATE = "64k"
SEGMENT_TARGET = 10
SEGMENT_MAX = 20
SILENCE_NOISE_DB = -30.0
SILENCE_MIN_DURATION = 0.2


def probe_duration(input_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            input_path,
        ],
        capture_output=True, text=True, check=True,
    )
    return float(result.stdout.strip())


def detect_silences(
    input_path: str,
    noise_db: float = SILENCE_NOISE_DB,
    min_duration: float = SILENCE_MIN_DURATION,
) -> list[tuple[float, float]]:
    result = subprocess.run(
        [
            "ffmpeg", "-i", input_path,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True,
    )
    starts: list[float] = []
    ends: list[float] = []
    for line in result.stderr.splitlines():
        m = re.search(r"silence_start:\s*([\d.]+)", line)
        if m:
            starts.append(float(m.group(1)))
        m = re.search(r"silence_end:\s*([\d.]+)", line)
        if m:
            ends.append(float(m.group(1)))
    return list(zip(starts, ends))


def compute_cut_points(
    duration: float,
    silences: list[tuple[float, float]],
    target: float = SEGMENT_TARGET,
    max_sec: float = SEGMENT_MAX,
) -> list[float]:
    """在 [cursor+target, cursor+max_sec] 窗口内选最长静音切割，找不到则在 max_sec 处硬切。"""
    cuts: list[float] = []
    cursor = 0.0
    while duration - cursor > max_sec:
        window_start = cursor + target
        window_end = min(cursor + max_sec, duration)
        best = window_end
        best_silence_duration = 0.0
        for s, e in silences:
            overlap_start = max(s, window_start)
            overlap_end = min(e, window_end)
            silence_duration = overlap_end - overlap_start
            if silence_duration <= 0:
                continue
            if silence_duration > best_silence_duration:
                best_silence_duration = silence_duration
                best = (overlap_start + overlap_end) / 2
        cuts.append(best)
        cursor = best
    return cuts


def extract_segment(
    input_path: str, start: float, end: float, output_path: str
) -> str:
    subprocess.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", str(start), "-i", input_path,
            "-t", str(end - start),
            "-c:a", "libmp3lame", "-b:a", SEGMENT_BITRATE, "-ac", "1",
            output_path,
        ],
        check=True, capture_output=True,
    )
    return output_path


def mmss(t: float) -> str:
    """把秒数格式化为 MMMSS（如 72.0 -> '00112'）。用于文件名。"""
    total = int(round(t))
    minutes, seconds = divmod(total, 60)
    return f"{minutes:03d}{seconds:02d}"


def hms(t: float) -> str:
    """把秒数格式化为 HH:MM:SS。"""
    total = int(round(t))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def convert_and_split(
    input_path: str,
    out_dir: str,
    target: float = SEGMENT_TARGET,
    max_sec: float = SEGMENT_MAX,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[tuple[str, float, float]]:
    """把音频转码为 mp3 并切片。在 target~max_sec 窗口内优先选静音点切割。

    on_progress(done, total) 在每个切片完成时回调。
    返回 [(path, start, end), ...]。
    """
    duration = probe_duration(input_path)
    if duration <= max_sec:
        out = os.path.join(out_dir, "segment_0000.mp3")
        extract_segment(input_path, 0, duration, out)
        if on_progress:
            on_progress(1, 1)
        return [(out, 0.0, duration)]

    silences = detect_silences(input_path)
    cut_points = compute_cut_points(duration, silences, target, max_sec)
    boundaries = [0.0, *cut_points, duration]
    total = len(boundaries) - 1
    segments: list[tuple[str, float, float]] = []
    for i in range(total):
        out = os.path.join(out_dir, f"segment_{i:04d}.mp3")
        extract_segment(input_path, boundaries[i], boundaries[i + 1], out)
        segments.append((out, boundaries[i], boundaries[i + 1]))
        if on_progress:
            on_progress(i + 1, total)
    return segments
