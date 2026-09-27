import json

import pytest

from server.podcast_feed import (
    PodcastFeedError,
    normalize_episode_url,
    normalize_podcast_url,
    parse_podcast_html,
)


def _html(episodes):
    payload = {
        "buildId": "test-build",
        "props": {
            "pageProps": {
                "podcast": {
                    "pid": "670f3da40d2f24f28978736f",
                    "title": "测试播客",
                    "author": "主播",
                    "description": "简介",
                    "episodeCount": 20,
                    "latestEpisodePubDate": "2026-01-02T00:00:00Z",
                    "syncMode": "SELF_HOSTING",
                    "episodes": episodes,
                }
            }
        },
    }
    return (
        '<html><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload, ensure_ascii=False)
        + "</script></html>"
    )


def _episode(eid, *, private=False, public=True):
    return {
        "eid": eid,
        "title": "第 " + eid,
        "description": "内容",
        "pubDate": "2026-01-02T00:00:00Z",
        "duration": 60,
        "isPrivateMedia": private,
        "payType": "FREE",
        "enclosure": {"url": "https://media.xyzcdn.net/audio.m4a"} if public else {},
        "media": {"source": {"mode": "PUBLIC" if public else "PRIVATE"}},
    }


def test_parse_podcast_page_payload_and_public_audio():
    feed = parse_podcast_html(
        _html([_episode("a" * 24), _episode("b" * 24, private=True)]),
        "https://www.xiaoyuzhoufm.com/podcast/670f3da40d2f24f28978736f",
    )
    assert feed["title"] == "测试播客"
    assert feed["episode_count"] == 20
    assert feed["episodes"][0]["processable"] is True
    assert feed["episodes"][1]["processable"] is False
    assert feed["episodes"][0]["episode_url"].endswith("a" * 24)


def test_normalize_urls_reject_other_hosts_and_paths():
    url, podcast_id = normalize_podcast_url(
        "https://www.xiaoyuzhoufm.com/podcast/670f3da40d2f24f28978736f/"
    )
    assert podcast_id == "670f3da40d2f24f28978736f"
    assert url.endswith(podcast_id)

    episode_url, episode_id = normalize_episode_url(
        "https://www.xiaoyuzhoufm.com/episode/" + "a" * 24
    )
    assert episode_id == "a" * 24
    assert episode_url.endswith(episode_id)

    with pytest.raises(ValueError):
        normalize_podcast_url("https://example.com/podcast/" + "a" * 24)
    with pytest.raises(ValueError):
        normalize_episode_url("https://www.xiaoyuzhoufm.com/podcast/" + "a" * 24)


def test_missing_next_data_is_an_error():
    with pytest.raises(PodcastFeedError):
        parse_podcast_html("<html></html>", "https://www.xiaoyuzhoufm.com/podcast/" + "a" * 24)
