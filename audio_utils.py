import os
import re
import subprocess

SEGMENT_BITRATE = "32k"
SILENCE_NOISE_DB = -30.0
SILENCE_MIN_DURATION = 0.5


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
    log = result.stderr
    starts: list[float] = []
    ends: list[float] = []
    for line in log.splitlines():
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
    target: float = 390.0,
    lo: float = 300.0,
    hi: float = 480.0,
) -> list[float]:
    """在静音点附近把音频切成 ~target 秒的段，每段限定在 [lo, hi] 秒。"""
    cut_points: list[float] = []
    cursor = 0.0
    while duration - cursor > hi:
        ideal = cursor + target
        window_start = cursor + lo
        window_end = min(cursor + hi, duration)
        best = ideal
        best_dist = float("inf")
        for s, e in silences:
            if e < window_start or s > window_end:
                continue
            mid = max(window_start, min(window_end, (s + e) / 2))
            dist = abs(mid - ideal)
            if dist < best_dist:
                best_dist = dist
                best = mid
        cut_points.append(best)
        cursor = best
    return cut_points


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


def convert_and_split(
    input_path: str,
    out_dir: str,
    target_minutes: float = 6.5,
    min_minutes: float = 5.0,
    max_minutes: float = 8.0,
) -> list[str]:
    """把音频转码为 mp3 并按静音切片。短音频不切，直接整段转码。"""
    duration = probe_duration(input_path)
    if duration <= max_minutes * 60:
        out = os.path.join(out_dir, "segment_000.mp3")
        return [extract_segment(input_path, 0, duration, out)]

    silences = detect_silences(input_path)
    cut_points = compute_cut_points(
        duration, silences,
        target=target_minutes * 60,
        lo=min_minutes * 60,
        hi=max_minutes * 60,
    )
    boundaries = [0.0, *cut_points, duration]
    paths: list[str] = []
    for i in range(len(boundaries) - 1):
        out = os.path.join(out_dir, f"segment_{i:03d}.mp3")
        paths.append(extract_segment(input_path, boundaries[i], boundaries[i + 1], out))
    return paths
