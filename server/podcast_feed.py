"""Discover public episodes from a Xiaoyuzhou podcast page.

Xiaoyuzhou self-hosted podcasts do not expose a native RSS URL.  The public
podcast page contains an embedded Next.js JSON payload with the latest 15
episodes, including public enclosure URLs.  Polling that payload is sufficient
for incremental subscriptions.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

PODCAST_PATH_RE = re.compile(r"^/podcast/([0-9a-f]{24})/?$")
EPISODE_PATH_RE = re.compile(r"^/episode/([0-9a-f]{24})/?$")
ALLOWED_HOSTS = {"xiaoyuzhoufm.com", "www.xiaoyuzhoufm.com"}
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
)
MAX_PAGE_BYTES = 5 * 1024 * 1024


class PodcastFeedError(RuntimeError):
    """The podcast page was invalid or unavailable."""


class _NextDataParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._inside = False
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self._inside = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._inside:
            self._inside = False

    def handle_data(self, data: str) -> None:
        if self._inside:
            self._parts.append(data)

    @property
    def value(self) -> str:
        return "".join(self._parts)


def normalize_podcast_url(url: str) -> tuple[str, str]:
    """Validate a public Xiaoyuzhou podcast URL and return URL plus podcast id."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("只支持 https://www.xiaoyuzhoufm.com/podcast/<id>")
    match = PODCAST_PATH_RE.fullmatch(parsed.path)
    if not match:
        raise ValueError("只支持小宇宙播客主页 /podcast/<id>")
    podcast_id = match.group(1)
    return f"https://www.xiaoyuzhoufm.com/podcast/{podcast_id}", podcast_id


def normalize_episode_url(url: str) -> tuple[str, str]:
    """Validate a public Xiaoyuzhou episode URL and return URL plus episode id."""
    parsed = urlparse(url.strip())
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("只支持 https://www.xiaoyuzhoufm.com/episode/<id>")
    match = EPISODE_PATH_RE.fullmatch(parsed.path)
    if not match:
        raise ValueError("只支持小宇宙单集链接 /episode/<id>")
    episode_id = match.group(1)
    return f"https://www.xiaoyuzhoufm.com/episode/{episode_id}", episode_id


def parse_podcast_html(html: str, source_url: str) -> dict[str, Any]:
    """Parse the embedded Next.js podcast payload into a small feed model."""
    parser = _NextDataParser()
    parser.feed(html)
    if not parser.value:
        raise PodcastFeedError("播客主页中没有找到 __NEXT_DATA__")
    try:
        next_data = json.loads(parser.value)
        podcast = next_data["props"]["pageProps"]["podcast"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise PodcastFeedError("播客主页中的节目数据格式无效") from exc
    if not isinstance(podcast, dict) or not isinstance(podcast.get("episodes"), list):
        raise PodcastFeedError("播客主页没有返回单集列表")

    episodes: list[dict[str, Any]] = []
    for item in podcast["episodes"]:
        if not isinstance(item, dict) or not item.get("eid"):
            continue
        enclosure = item.get("enclosure") if isinstance(item.get("enclosure"), dict) else {}
        media = item.get("media") if isinstance(item.get("media"), dict) else {}
        source = media.get("source") if isinstance(media.get("source"), dict) else {}
        audio_url = enclosure.get("url") or source.get("url")
        media_mode = source.get("mode")
        is_private = bool(item.get("isPrivateMedia"))
        processable = bool(
            audio_url
            and not is_private
            and media_mode in {None, "PUBLIC"}
        )
        episode_id = str(item["eid"])
        episodes.append(
            {
                "eid": episode_id,
                "episode_url": f"https://www.xiaoyuzhoufm.com/episode/{episode_id}",
                "title": str(item.get("title") or episode_id),
                "description": str(item.get("description") or ""),
                "published_at": item.get("pubDate"),
                "duration": item.get("duration"),
                "audio_url": str(audio_url) if audio_url else None,
                "media_mode": media_mode,
                "is_private": is_private,
                "pay_type": item.get("payType"),
                "processable": processable,
            }
        )

    return {
        "podcast_id": str(podcast.get("pid") or normalize_podcast_url(source_url)[1]),
        "source_url": source_url,
        "title": str(podcast.get("title") or "未命名播客"),
        "author": str(podcast.get("author") or ""),
        "description": str(podcast.get("description") or ""),
        "episode_count": podcast.get("episodeCount"),
        "latest_episode_at": podcast.get("latestEpisodePubDate"),
        "sync_mode": podcast.get("syncMode"),
        "pay_type": podcast.get("payType"),
        "episodes": episodes,
    }


def fetch_podcast(url: str, *, timeout: float = 30.0) -> dict[str, Any]:
    """Fetch a Xiaoyuzhou podcast homepage and return its latest episodes."""
    normalized_url, _ = normalize_podcast_url(url)
    request = urllib.request.Request(normalized_url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_PAGE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise PodcastFeedError(f"小宇宙返回 HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise PodcastFeedError(f"连接小宇宙失败: {exc.reason}") from exc
    if len(raw) > MAX_PAGE_BYTES:
        raise PodcastFeedError("小宇宙播客页面过大")
    html = raw.decode("utf-8", errors="replace")
    return parse_podcast_html(html, normalized_url)
