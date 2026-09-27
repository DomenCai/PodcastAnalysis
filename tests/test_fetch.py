from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

import fetch
from fetch import FetchError, fetch_episode, fetch_episode_info

EPISODE_ID = "6a2d134143a22a6955830bfe"
EPISODE_URL = f"https://www.xiaoyuzhoufm.com/episode/{EPISODE_ID}"


class Response:
    def __init__(
        self, body: bytes, *, status: int = 200, headers: dict[str, str] | None = None
    ):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {}
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def close(self) -> None:
        self.closed = True


def _next_data_html(**overrides: object) -> bytes:
    episode = {
        "eid": EPISODE_ID,
        "title": "来自 Next Data 的标题 &amp; 后续",
        "description": "介绍 &amp; 详情",
        "duration": 3661,
        "pubDate": "2026-09-01T10:20:30.000Z",
        "isPrivateMedia": False,
        "payType": "FREE",
        "podcast": {"title": "测试播客 &amp; 朋友"},
        "media": {
            "source": {
                "mode": "PUBLIC",
                "url": "https://media.xyzcdn.net/episode.m4a",
            }
        },
    }
    episode.update(overrides)
    payload = {"props": {"pageProps": {"episode": episode}}}
    return (
        '<html><head><meta property="og:title" content="不应覆盖 Next Data">'
        '<meta property="og:audio" content="https://media.xyzcdn.net/fallback.mp3">'
        f'<script type="application/json" id="__NEXT_DATA__">{json.dumps(payload, ensure_ascii=False)}</script>'
        "</head></html>"
    ).encode()


def test_fetch_episode_info_prefers_next_data_and_decodes_entities():
    response = Response(_next_data_html())
    with patch("fetch._urlopen", return_value=response) as urlopen:
        info = fetch_episode_info(EPISODE_URL + "/?ignored=1")

    assert info == {
        "id": EPISODE_ID,
        "title": "来自 Next Data 的标题 & 后续",
        "description": "介绍 & 详情",
        "podcast_title": "测试播客 & 朋友",
        "duration": 3661,
        "published_at": "2026-09-01T10:20:30.000Z",
        "url": EPISODE_URL,
        "audio_url": "https://media.xyzcdn.net/episode.m4a",
        "media_mode": "PUBLIC",
        "is_private": False,
        "pay_type": "FREE",
    }
    request = urlopen.call_args.args[0]
    assert request.full_url == EPISODE_URL
    assert urlopen.call_args.kwargs["timeout"] == fetch.PAGE_TIMEOUT_SECONDS
    assert response.closed


def test_fetch_episode_info_og_fallback_handles_attribute_order_and_entities():
    page = b"""
    <html><head>
      <meta content="Meta &amp; title" property="og:title">
      <meta content="Description &amp; details" property="og:description">
      <meta content="Podcast &amp; Co" property="og:site_name">
      <meta content="2026-08-01T00:00:00Z" property="article:published_time">
      <meta content="180" property="music:duration">
      <meta content="https://media.xyzcdn.net/meta.m4a?x=1&amp;y=2" property="og:audio">
    </head></html>
    """
    with patch("fetch._urlopen", return_value=Response(page)):
        info = fetch_episode_info(EPISODE_URL)

    assert info["title"] == "Meta & title"
    assert info["description"] == "Description & details"
    assert info["podcast_title"] == "Podcast & Co"
    assert info["published_at"] == "2026-08-01T00:00:00Z"
    assert info["duration"] == "180"
    assert info["audio_url"] == "https://media.xyzcdn.net/meta.m4a?x=1&y=2"


def test_invalid_host_and_path_are_rejected_without_network_access():
    with patch("fetch._urlopen") as urlopen:
        with pytest.raises(ValueError):
            fetch_episode_info(f"https://example.com/episode/{EPISODE_ID}")
        with pytest.raises(ValueError):
            fetch_episode_info(f"https://www.xiaoyuzhoufm.com/podcast/{EPISODE_ID}")
    urlopen.assert_not_called()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"isPrivateMedia": True}, "私密"),
        ({"payType": "PAID"}, "付费"),
        (
            {
                "media": {
                    "source": {
                        "mode": "PRIVATE",
                        "url": "https://media.xyzcdn.net/a.m4a",
                    }
                }
            },
            "私密",
        ),
    ],
)
def test_private_paid_and_missing_audio_are_rejected(overrides: dict, message: str):
    with patch("fetch._urlopen", return_value=Response(_next_data_html(**overrides))):
        with pytest.raises(FetchError, match=message):
            fetch_episode_info(EPISODE_URL)


def test_missing_audio_in_next_data_and_og_is_rejected():
    page = _next_data_html(media={"source": {"mode": "PUBLIC", "url": ""}}).replace(
        b'<meta property="og:audio" content="https://media.xyzcdn.net/fallback.mp3">',
        b"",
    )
    with patch("fetch._urlopen", return_value=Response(page)):
        with pytest.raises(FetchError, match="没有可公开下载"):
            fetch_episode_info(EPISODE_URL)


def test_private_audio_host_is_rejected():
    with patch(
        "fetch._urlopen",
        return_value=Response(
            _next_data_html(
                media={"source": {"mode": "PUBLIC", "url": "https://127.0.0.1/a.m4a"}}
            )
        ),
    ):
        with pytest.raises(FetchError, match="非公开"):
            fetch_episode_info(EPISODE_URL)


def test_fetch_episode_uses_unique_paths(tmp_path: Path):
    metadata = {
        "id": EPISODE_ID,
        "title": "同一个标题",
        "audio_url": "https://media.xyzcdn.net/audio.mp3?token=secret",
    }

    def write_audio(_url: str, destination: Path) -> None:
        destination.write_bytes(b"audio")

    with (
        patch("fetch.fetch_episode_info", return_value=metadata),
        patch("fetch._download_audio", side_effect=write_audio),
    ):
        first = fetch_episode(EPISODE_URL, download_dir=tmp_path)
        second = fetch_episode(EPISODE_URL, download_dir=tmp_path)

    assert first["audio_path"] != second["audio_path"]
    assert first["audio_path"].parent == tmp_path
    assert first["audio_path"].name.startswith(f"{EPISODE_ID}-")
    assert first["audio_path"].suffix == ".mp3"
    assert first["audio_path"].read_bytes() == b"audio"


def test_fetch_episode_deletes_partial_file_on_download_error(tmp_path: Path):
    metadata = {
        "id": EPISODE_ID,
        "title": "标题",
        "audio_url": "https://media.xyzcdn.net/audio.m4a",
    }

    def fail_after_write(_url: str, destination: Path) -> None:
        destination.write_bytes(b"partial")
        raise FetchError("broken stream")

    with (
        patch("fetch.fetch_episode_info", return_value=metadata),
        patch("fetch._download_audio", side_effect=fail_after_write),
        pytest.raises(FetchError, match="broken stream"),
    ):
        fetch_episode(EPISODE_URL, download_dir=tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_non_success_http_status_is_checked():
    with patch("fetch._urlopen", return_value=Response(b"no", status=503)):
        with pytest.raises(FetchError, match="HTTP 503"):
            fetch_episode_info(EPISODE_URL)


@pytest.mark.parametrize(
    "redirect_url",
    [
        "http://media.xyzcdn.net/audio.m4a",
        "https://localhost/audio.m4a",
        "https://127.0.0.1/audio.m4a",
    ],
)
def test_audio_redirect_rejects_insecure_and_private_targets(redirect_url: str):
    handler = fetch._ValidatingRedirectHandler(fetch._audio_redirect_validator)
    request = fetch.urllib.request.Request("https://media.xyzcdn.net/original.m4a")
    with pytest.raises(FetchError):
        handler.redirect_request(request, None, 302, "Found", {}, redirect_url)


def test_audio_redirect_allows_another_public_https_cdn():
    fetch._audio_redirect_validator(
        "https://audio.cdn-example.com/path/episode.m4a?signature=x"
    )


def test_page_redirect_must_remain_on_same_episode():
    validator = fetch._page_redirect_validator(EPISODE_URL)
    validator(EPISODE_URL + "?from=redirect")
    with pytest.raises(FetchError, match="其他单集"):
        validator("https://www.xiaoyuzhoufm.com/episode/" + "a" * 24)
    with pytest.raises(FetchError, match="不受支持"):
        validator("https://localhost/episode/" + EPISODE_ID)


def test_network_exception_does_not_expose_url_credentials():
    secret = "https://media.example/audio.m4a?access_key=super-secret"
    with patch("fetch._urlopen", side_effect=urllib.error.URLError(secret)):
        with pytest.raises(FetchError) as captured:
            fetch_episode_info(EPISODE_URL)
    assert "super-secret" not in str(captured.value)


def test_cli_prints_safe_metadata_without_downloading(capsys):
    info = {
        "id": EPISODE_ID,
        "title": "标题",
        "podcast_title": "播客",
        "published_at": "2026-09-01T00:00:00Z",
        "duration": 60,
        "url": EPISODE_URL,
        "audio_url": "https://media.xyzcdn.net/a.m4a?access_key=super-secret",
    }
    with (
        patch("fetch.fetch_episode_info", return_value=info) as fetch_info,
        patch("fetch.fetch_episode") as download,
    ):
        assert fetch._main([EPISODE_URL]) == 0

    fetch_info.assert_called_once_with(EPISODE_URL)
    download.assert_not_called()
    output = capsys.readouterr().out
    assert "标题" in output
    assert EPISODE_URL in output
    assert "super-secret" not in output
