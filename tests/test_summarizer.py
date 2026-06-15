from unittest.mock import patch, MagicMock

import pytest

from summarizer import summarize_transcript


def _mock_completion(text: str) -> MagicMock:
    completion = MagicMock()
    completion.choices = [MagicMock(message=MagicMock(content=text))]
    return completion


def test_summarize_transcript_returns_content():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("这是摘要")

    with patch("summarizer.OpenAI", return_value=client):
        result = summarize_transcript("很长的一段逐字稿...", api_key="sk-test")

    assert result == "这是摘要"


def test_summarize_transcript_sends_prompt_with_transcript():
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_completion("摘要")

    with patch("summarizer.OpenAI", return_value=client):
        summarize_transcript("某段内容XYZ", api_key="sk-test", model="gpt-4o-mini")

    call = client.chat.completions.create.call_args
    assert call.kwargs["model"] == "gpt-4o-mini"
    messages = call.kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    assert "某段内容XYZ" in messages[1]["content"]
    assert call.kwargs["temperature"] == 0.3


def test_summarize_transcript_missing_api_key_raises():
    with patch("summarizer.LLM_API_KEY", None):
        with pytest.raises(ValueError, match="LLM_API_KEY"):
            summarize_transcript("x")
