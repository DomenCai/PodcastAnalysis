import base64
from unittest.mock import patch, MagicMock

import pytest

import stt
from stt import transcribe_segment, transcribe_audio


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

    seg = "/fake/seg.mp3"
    with patch("stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        result = transcribe_segment(client, seg, model="mimo-v2.5-asr", language="zh")

    assert result == "你好世界"
    call = client.chat.completions.create.call_args
    assert call.kwargs["model"] == "mimo-v2.5-asr"
    assert call.kwargs["extra_body"] == {"asr_options": {"language": "zh"}}
    msg = call.kwargs["messages"][0]
    assert msg["content"][0]["type"] == "input_audio"
    assert msg["content"][0]["input_audio"]["data"].startswith("data:audio/mpeg")


def test_transcribe_audio_single_segment():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("单段文本")

    with patch("stt.OpenAI", return_value=client), \
         patch("stt.convert_and_split", return_value=["/tmp/seg.mp3"]), \
         patch("stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        result = transcribe_audio("/fake/a.m4a", api_key="k")

    assert result == "单段文本"


def test_transcribe_audio_multi_segment_concatenates():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("段落")

    with patch("stt.OpenAI", return_value=client), \
         patch("stt.convert_and_split", return_value=["s1.mp3", "s2.mp3", "s3.mp3"]), \
         patch("stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        result = transcribe_audio("/fake/a.m4a", api_key="k")

    # 并行执行，顺序不保证；验证三段都被转录并以换行拼接
    parts = result.split("\n")
    assert parts == ["段落", "段落", "段落"]
    assert client.chat.completions.create.call_count == 3


def test_transcribe_audio_missing_api_key_raises():
    with patch("stt.MIMO_API_KEY", None):
        with pytest.raises(ValueError, match="MIMO_API_KEY"):
            transcribe_audio("/fake/a.m4a")


def test_transcribe_audio_parallel_invokes_all_segments():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("x")

    with patch("stt.OpenAI", return_value=client), \
         patch("stt.convert_and_split", return_value=["s1.mp3", "s2.mp3", "s3.mp3", "s4.mp3"]), \
         patch("stt._audio_to_data_url", return_value="data:audio/mpeg;base64,AAAA"):
        transcribe_audio("/fake/a.m4a", api_key="k", max_workers=4)

    assert client.chat.completions.create.call_count == 4
