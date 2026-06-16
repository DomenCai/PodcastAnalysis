from unittest.mock import patch, MagicMock

from server.downloader import download_audio


def _make_stream_response(chunks: list[bytes]) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.iter_content.return_value = iter(chunks)
    return resp


def test_download_audio_writes_file(tmp_path):
    chunks = [b"abcd", b"efgh", b"ijkl"]
    output = tmp_path / "audio.m4a"

    with patch("server.downloader.requests.get", return_value=_make_stream_response(chunks)):
        result = download_audio("https://example.com/audio.m4a", str(output))

    assert result == str(output)
    assert output.read_bytes() == b"abcdefghijkl"


def test_download_audio_empty_response(tmp_path):
    output = tmp_path / "empty.bin"

    with patch("server.downloader.requests.get", return_value=_make_stream_response([])):
        download_audio("https://example.com/empty", str(output))

    assert output.exists()
    assert output.read_bytes() == b""


def test_download_audio_uses_user_agent(tmp_path):
    output = tmp_path / "x.bin"
    mock_resp = _make_stream_response([b"data"])

    with patch("server.downloader.requests.get", return_value=mock_resp) as mock_get:
        download_audio("https://example.com/x", str(output))

    _, kwargs = mock_get.call_args
    assert "User-Agent" in kwargs["headers"]
    assert kwargs["stream"] is True
    assert kwargs["timeout"] == 60
