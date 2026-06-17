from unittest.mock import patch, MagicMock

import pytest

from server.summarizer import summarize_transcript


def _mock_completion(text: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def test_summarize_transcript_returns_parsed_json():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion(
        '{"overview": [{"time": "00:00", "title": null, "text": "开场"}], '
        '"mindmap": {"note": null, "nodes": []}, "worth_following": []}'
    )

    with patch("server.summarizer.OpenAI", return_value=client):
        result = summarize_transcript("很长的一段逐字稿...", api_key="sk-test")

    assert result["overview"][0]["text"] == "开场"
    assert result["mindmap"]["nodes"] == []


def test_summarize_transcript_sends_prompt_with_transcript():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion(
        '{"overview": [], "mindmap": {"note": null, "nodes": []}, "worth_following": []}'
    )

    with patch("server.summarizer.OpenAI", return_value=client):
        summarize_transcript("某段内容XYZ", api_key="sk-test", model="gpt-4o-mini")

    call = client.chat.completions.create.call_args
    assert call.kwargs["model"] == "gpt-4o-mini"
    messages = call.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "某段内容XYZ" in messages[1]["content"]
    assert call.kwargs["temperature"] == 0.3
    assert call.kwargs["response_format"] == {"type": "json_object"}


def test_summarize_transcript_strips_code_fence():
    fenced = (
        "这是你要的 JSON：\n```json\n"
        '{"overview": [], "mindmap": {"note": "闲聊", "nodes": []}, "worth_following": []}'
        "\n```"
    )
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion(fenced)

    with patch("server.summarizer.OpenAI", return_value=client):
        result = summarize_transcript("内容", api_key="sk-test")

    assert result["mindmap"]["note"] == "闲聊"


def test_summarize_transcript_missing_api_key_raises():
    with patch("server.summarizer.LLM_API_KEY", None):
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            summarize_transcript("x")
