from unittest.mock import patch, MagicMock

import pytest

from audio_utils import (
    probe_duration,
    detect_silences,
    compute_cut_points,
    extract_segment,
    convert_and_split,
)


def test_probe_duration():
    mock = MagicMock()
    mock.stdout = "  123.456\n"
    with patch("audio_utils.subprocess.run", return_value=mock):
        assert probe_duration("/fake/a.m4a") == 123.456
    args = mock.stdout  # sanity


def test_probe_duration_calls_ffprobe():
    mock = MagicMock()
    mock.stdout = "10.0\n"
    with patch("audio_utils.subprocess.run", return_value=mock) as run:
        probe_duration("/fake/a.m4a")
    cmd = run.call_args.args[0]
    assert cmd[0] == "ffprobe"
    assert "/fake/a.m4a" in cmd


def test_detect_silences_parses_log():
    fake_result = MagicMock()
    fake_result.stderr = (
        "[silencedetect] silence_start: 5.0\n"
        "[silencedetect] silence_end: 5.5 | silence_duration: 0.5\n"
        "[silencedetect] silence_start: 300.0\n"
        "[silencedetect] silence_end: 300.6 | silence_duration: 0.6\n"
    )
    with patch("audio_utils.subprocess.run", return_value=fake_result):
        silences = detect_silences("/fake/a.m4a")
    assert silences == [(5.0, 5.5), (300.0, 300.6)]


def test_detect_silences_empty():
    fake_result = MagicMock()
    fake_result.stderr = "no silence detected\n"
    with patch("audio_utils.subprocess.run", return_value=fake_result):
        assert detect_silences("/fake/a.m4a") == []


def test_compute_cut_points_short_audio_no_cut():
    # 8 分钟 = 480s，恰好 == hi，不切
    assert compute_cut_points(480.0, []) == []


def test_compute_cut_points_prefers_silence_near_target():
    duration = 2400.0  # 40 分钟
    silences = [
        (100.0, 100.5),   # 太早（在第一段窗口的 lo 之前附近）
        (388.0, 392.0),   # 接近 target=390，中点 390
        (780.0, 785.0),
    ]
    cuts = compute_cut_points(duration, silences, target=390, lo=300, hi=480)
    assert len(cuts) >= 1
    assert abs(cuts[0] - 390.0) < 2.0


def test_compute_cut_points_hard_cut_when_no_silence():
    cuts = compute_cut_points(2400.0, [], target=390, lo=300, hi=480)
    assert len(cuts) > 0
    assert cuts[0] == 390.0
    # 后续应从 cursor 继续推进
    assert cuts[1] == 780.0


def test_compute_cut_points_respects_hi_bound():
    # 如果静音点都超出 hi 范围，应在 hi 内硬切
    duration = 1000.0
    cuts = compute_cut_points(duration, [], target=390, lo=300, hi=480)
    # 每段 390s，1000s -> 切在 390 和 780
    assert cuts == [390.0, 780.0]


def test_compute_cut_points_last_segment_kept():
    # 500s: > hi(480)，切一刀后剩 110s < hi，结束
    cuts = compute_cut_points(500.0, [], target=390, lo=300, hi=480)
    assert len(cuts) == 1
    # 边界 = [0, 390, 500]，最后段 110s


def test_extract_segment_uses_t_duration():
    with patch("audio_utils.subprocess.run") as run:
        extract_segment("/in.m4a", 100.0, 250.0, "/out.mp3")
    cmd = run.call_args.args[0]
    assert "-ss" in cmd and "100.0" in cmd
    assert "-t" in cmd and "150.0" in cmd  # 250-100
    assert "libmp3lone" not in cmd
    assert "libmp3lame" in cmd


def test_convert_and_split_short_audio_single_segment(tmp_path):
    fake_input = "/fake/short.m4a"
    with patch("audio_utils.probe_duration", return_value=300.0), \
         patch("audio_utils.extract_segment", return_value="OK") as ex:
        paths = convert_and_split(fake_input, str(tmp_path))
    assert len(paths) == 1
    expected_out = str(tmp_path / "segment_000.mp3")
    ex.assert_called_once_with(fake_input, 0, 300.0, expected_out)


def test_convert_and_split_long_audio_multiple_segments(tmp_path):
    fake_input = "/fake/long.m4a"
    with patch("audio_utils.probe_duration", return_value=2400.0), \
         patch("audio_utils.detect_silences", return_value=[(388, 392)]), \
         patch("audio_utils.extract_segment", side_effect=lambda i, s, e, o: o):
        paths = convert_and_split(fake_input, str(tmp_path))
    assert len(paths) >= 2
    assert all(p.startswith(str(tmp_path)) for p in paths)
