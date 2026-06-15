from unittest.mock import patch, MagicMock

import json

import pytest

from scraper import extract_episode_id, fetch_episode_info


def test_extract_episode_id_normal():
    url = "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe"
    assert extract_episode_id(url) == "6a2d134143a22a6955830bfe"


def test_extract_episode_id_with_query():
    url = "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe?from=app"
    assert extract_episode_id(url) == "6a2d134143a22a6955830bfe"


def test_extract_episode_id_invalid():
    with pytest.raises(ValueError):
        extract_episode_id("https://example.com/not-an-episode")


def _make_response(text: str) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status.return_value = None
    return resp


def _next_data_html(episode: dict) -> str:
    payload = {"props": {"pageProps": {"episode": episode}}}
    return (
        '<html><head>'
        f'<script id="__NEXT_DATA__" type="application/json">'
        f'{json.dumps(payload, ensure_ascii=False)}'
        '</script></head><body></body></html>'
    )


EPISODE_PAYLOAD = {
    "title": "测试标题",
    "description": "测试描述",
    "media": {"source": {"mode": "PUBLIC", "url": "https://audio.example.com/ep.m4a"}},
    "duration": 3600,
    "podcast": {"title": "测试播客"},
}

META_HTML = """
<html>
<head>
<meta property="og:title" content="Meta标题">
<meta property="og:audio" content="https://audio.example.com/meta.m4a">
</head><body></body>
</html>
"""


def test_fetch_episode_info_from_next_data():
    html = _next_data_html(EPISODE_PAYLOAD)
    with patch("scraper.requests.get", return_value=_make_response(html)):
        info = fetch_episode_info(
            "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe"
        )
    assert info["id"] == "6a2d134143a22a6955830bfe"
    assert info["title"] == "测试标题"
    assert info["audio_url"] == "https://audio.example.com/ep.m4a"
    assert info["duration"] == 3600
    assert info["podcast_title"] == "测试播客"


def test_fetch_episode_info_fallback_to_meta():
    with patch("scraper.requests.get", return_value=_make_response(META_HTML)):
        info = fetch_episode_info(
            "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe"
        )
    assert info["title"] == "Meta标题"
    assert info["audio_url"] == "https://audio.example.com/meta.m4a"
    assert info["description"] == ""
