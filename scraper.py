import json
import re

import requests
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def extract_episode_id(url: str) -> str:
    match = re.search(r"/episode/([a-f0-9]+)", url)
    if not match:
        raise ValueError(f"Invalid xiaoyuzhou URL: {url}")
    return match.group(1)


def fetch_episode_info(url: str) -> dict:
    episode_id = extract_episode_id(url)
    page_url = f"https://www.xiaoyuzhoufm.com/episode/{episode_id}"

    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(page_url, headers=headers, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")

    script_tag = soup.find("script", id="__NEXT_DATA__")
    if script_tag and script_tag.string:
        data = json.loads(script_tag.string)
        episode = (
            data.get("props", {}).get("pageProps", {}).get("episode", {})
        )
        return {
            "id": episode_id,
            "title": episode.get("title", ""),
            "description": episode.get("description", ""),
            "audio_url": episode.get("media", {}).get("source", ""),
            "duration": episode.get("duration", 0),
            "podcast_title": episode.get("podcast", {}).get("title", ""),
        }

    audio_meta = soup.find("meta", property="og:audio")
    title_meta = soup.find("meta", property="og:title")
    return {
        "id": episode_id,
        "title": title_meta["content"] if title_meta else "",
        "audio_url": audio_meta["content"] if audio_meta else "",
        "description": "",
        "duration": 0,
        "podcast_title": "",
    }
