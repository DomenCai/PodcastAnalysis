import base64
from unittest.mock import patch, MagicMock

import pytest

import server.stt as stt
from server.stt import transcribe_segment, transcribe_audio


def _mock_completion(text: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def test_audio_to_data_url(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"hello")
    url = stt._audio_to_data_url(str(audio))
    assert url.startswith("data:audio/mpeg;base64,")
    encoded = url.split(",", 1)[1]
    assert base64.b64decode(encoded) == b"hello"


def test_transcribe_segment_calls_chat_completions():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("你好世界")

    with patch("server.stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        result = transcribe_segment(client, "/fake/seg.mp3", model="mimo-v2.5-asr", language="zh")

    assert result == "你好世界"
    call = client.chat.completions.create.call_args
    assert call.kwargs["model"] == "mimo-v2.5-asr"
    assert call.kwargs["extra_body"] == {"asr_options": {"language": "zh"}}


def test_transcribe_audio_single_segment_has_timestamp():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("单段文本")

    segments = [("/tmp/seg.mp3", 0.0, 80.0)]
    with patch("server.stt.OpenAI", return_value=client), \
         patch("server.stt.convert_and_split", return_value=segments), \
         patch("server.stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        result = transcribe_audio("/fake/a.m4a", api_key="k")

    assert result.startswith("[00:00:00]")
    assert "单段文本" in result


def test_transcribe_audio_multi_segment_timestamps_ordered():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("段落")

    segments = [
        ("/s1.mp3", 0.0, 100.0),
        ("/s2.mp3", 100.0, 200.0),
        ("/s3.mp3", 200.0, 300.0),
    ]
    with patch("server.stt.OpenAI", return_value=client), \
         patch("server.stt.convert_and_split", return_value=segments), \
         patch("server.stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        result = transcribe_audio("/fake/a.m4a", api_key="k")

    # 时间戳按段顺序，每段标记存在
    assert "[00:00:00]" in result
    assert "[00:01:40]" in result  # 100s
    assert "[00:03:20]" in result  # 200s
    assert result.count("段落") == 3


def test_transcribe_audio_missing_api_key_raises():
    with patch("server.stt.MIMO_API_KEY", None):
        with pytest.raises(ValueError, match="MIMO_API_KEY"):
            transcribe_audio("/fake/a.m4a")


def test_transcribe_audio_parallel_invokes_all_segments():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("x")

    segments = [(f"/s{i}.mp3", i * 100.0, (i + 1) * 100.0) for i in range(4)]
    with patch("server.stt.OpenAI", return_value=client), \
         patch("server.stt.convert_and_split", return_value=segments), \
         patch("server.stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        transcribe_audio("/fake/a.m4a", api_key="k", max_workers=4)

    assert client.chat.completions.create.call_count == 4



def test_transcribe_audio_keep_splits_copies_files(tmp_path):
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("x")

    # 创建假的源分段文件
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    seg_paths = []
    for i in range(2):
        p = src_dir / f"segment_{i:04d}.mp3"
        p.write_bytes(b"audio")
        seg_paths.append((str(p), i * 45.0, (i + 1) * 45.0))

    split_dir = tmp_path / "split"
    with patch("server.stt.OpenAI", return_value=client), \
         patch("server.stt.convert_and_split", return_value=seg_paths), \
         patch("server.stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        transcribe_audio("/fake/a.m4a", api_key="k", keep_splits_dir=str(split_dir))

    files = sorted(p.name for p in split_dir.iterdir())
    assert files == ["00000-00045.mp3", "00045-00130.mp3"]
