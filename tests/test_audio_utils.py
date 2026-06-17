from unittest.mock import patch, MagicMock

from server.audio_utils import (
    probe_duration,
    detect_silences,
    compute_cut_points,
    extract_segment,
    convert_and_split,
    mmss,
    hms,
    SEGMENT_TARGET,
    SEGMENT_MAX,
)


def test_probe_duration():
    mock = MagicMock()
    mock.stdout = "  123.456\n"
    with patch("server.audio_utils.subprocess.run", return_value=mock):
        assert probe_duration("/fake/a.m4a") == 123.456


def test_probe_duration_calls_ffprobe():
    mock = MagicMock()
    mock.stdout = "10.0\n"
    with patch("server.audio_utils.subprocess.run", return_value=mock) as run:
        probe_duration("/fake/a.m4a")
    cmd = run.call_args.args[0]
    assert cmd[0] == "ffprobe"
    assert "/fake/a.m4a" in cmd


def test_detect_silences_parses_log():
    fake_result = MagicMock()
    fake_result.stderr = (
        "[silencedetect] silence_start: 5.0\n"
        "[silencedetect] silence_end: 5.5 | silence_duration: 0.5\n"
        "[silencedetect] silence_start: 102.0\n"
        "[silencedetect] silence_end: 102.6 | silence_duration: 0.6\n"
    )
    with patch("server.audio_utils.subprocess.run", return_value=fake_result):
        silences = detect_silences("/fake/a.m4a")
    assert silences == [(5.0, 5.5), (102.0, 102.6)]


def test_detect_silences_empty():
    fake_result = MagicMock()
    fake_result.stderr = "no silence detected\n"
    with patch("server.audio_utils.subprocess.run", return_value=fake_result):
        assert detect_silences("/fake/a.m4a") == []


def test_compute_cut_points_short_audio_no_cut():
    assert compute_cut_points(SEGMENT_MAX, []) == []


def test_compute_cut_points_prefers_silence_in_window():
    duration = 500.0
    silences = [
        (50.0, 50.5),
        (105.0, 105.5),
        (112.0, 114.0),    # 在 [100, 120] 窗口内，最长静音中点 113
        (300.0, 301.0),
    ]
    cuts = compute_cut_points(duration, silences, target=100, max_sec=120)
    assert len(cuts) >= 1
    assert abs(cuts[0] - 113.0) < 0.1


def test_compute_cut_points_hard_cut_when_no_silence():
    cuts = compute_cut_points(500.0, [], target=100, max_sec=120)
    assert cuts[0] == 120.0
    assert cuts[1] == 240.0


def test_compute_cut_points_ignores_silence_outside_window():
    duration = 500.0
    silences = [(125.0, 126.0)]  # 超出 [100, 120] 窗口
    cuts = compute_cut_points(duration, silences, target=100, max_sec=120)
    assert cuts[0] == 120.0


def test_mmss():
    assert mmss(0) == "00000"
    assert mmss(72) == "00112"
    assert mmss(100) == "00140"
    assert mmss(3684) == "06124"
    assert mmss(6000) == "10000"


def test_hms():
    assert hms(0) == "00:00:00"
    assert hms(72) == "00:01:12"
    assert hms(3684) == "01:01:24"


def test_extract_segment_uses_t_duration():
    with patch("server.audio_utils.subprocess.run") as run:
        extract_segment("/in.m4a", 100.0, 250.0, "/out.mp3")
    cmd = run.call_args.args[0]
    assert "-ss" in cmd and "100.0" in cmd
    assert "-t" in cmd and "150.0" in cmd
    assert "libmp3lame" in cmd


def test_convert_and_split_short_audio_single_segment(tmp_path):
    fake_input = "/fake/short.m4a"
    with patch("server.audio_utils.probe_duration", return_value=15.0), \
         patch("server.audio_utils.extract_segment", side_effect=lambda i, s, e, o: o):
        segments = convert_and_split(fake_input, str(tmp_path))
    assert len(segments) == 1
    path, start, end = segments[0]
    assert path == str(tmp_path / "segment_0000.mp3")
    assert start == 0 and end == 15.0


def test_convert_and_split_uses_silence_detection(tmp_path):
    fake_input = "/fake/long.m4a"
    silences = [(12.0, 14.0), (32.0, 33.0)]
    with patch("server.audio_utils.probe_duration", return_value=200.0), \
         patch("server.audio_utils.detect_silences", return_value=silences), \
         patch("server.audio_utils.extract_segment", side_effect=lambda i, s, e, o: o):
        segments = convert_and_split(fake_input, str(tmp_path))
    starts = [s for _, s, _ in segments]
    assert starts[0] == 0.0
    assert abs(starts[1] - 13.0) < 0.1


def test_convert_and_split_no_silence_hard_cuts(tmp_path):
    fake_input = "/fake/long.m4a"
    with patch("server.audio_utils.probe_duration", return_value=200.0), \
         patch("server.audio_utils.detect_silences", return_value=[]), \
         patch("server.audio_utils.extract_segment", side_effect=lambda i, s, e, o: o):
        segments = convert_and_split(fake_input, str(tmp_path))
    assert segments[0] == (str(tmp_path / "segment_0000.mp3"), 0.0, SEGMENT_MAX)
    assert segments[1] == (str(tmp_path / "segment_0001.mp3"), SEGMENT_MAX, SEGMENT_MAX * 2)
    assert segments[-1][2] == 200.0


def test_convert_and_split_each_segment_within_max(tmp_path):
    assert SEGMENT_TARGET == 10
    assert SEGMENT_MAX == 20
    fake_input = "/fake/x.m4a"
    with patch("server.audio_utils.probe_duration", return_value=600.0), \
         patch("server.audio_utils.detect_silences", return_value=[]), \
         patch("server.audio_utils.extract_segment", side_effect=lambda i, s, e, o: o):
        segments = convert_and_split(fake_input, str(tmp_path))
    for _, start, end in segments:
        assert end - start <= SEGMENT_MAX
