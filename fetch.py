"""Fetch public Xiaoyuzhou episode metadata and, when requested, its audio."""

from __future__ import annotations

import html as html_module
import ipaddress
import json
import os
import stat
import tempfile
import urllib.error
import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from server.podcast_feed import normalize_episode_url

AUDIO_DIR = Path(__file__).parent / "audio"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
)
PAGE_TIMEOUT_SECONDS = 30.0
AUDIO_TIMEOUT_SECONDS = 60.0
MAX_PAGE_BYTES = 5 * 1024 * 1024
MAX_AUDIO_BYTES = 2 * 1024 * 1024 * 1024
DOWNLOAD_CHUNK_BYTES = 64 * 1024
_AUDIO_SUFFIXES = {".aac", ".flac", ".m4a", ".mp3", ".mp4", ".ogg", ".opus", ".wav"}


class FetchError(RuntimeError):
    """A public episode page or its audio could not be fetched safely."""


RedirectValidator = Callable[[str], None]


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, validator: RedirectValidator) -> None:
        super().__init__()
        self._validator = validator

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        self._validator(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _EpisodePageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_next_data = False
        self._next_data_parts: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "script" and values.get("id") == "__NEXT_DATA__":
            self._in_next_data = True
        if tag.lower() != "meta":
            return
        key = values.get("property") or values.get("name")
        content = values.get("content")
        if key and content is not None:
            self.meta.setdefault(key.lower(), html_module.unescape(content))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._in_next_data:
            self._in_next_data = False

    def handle_data(self, data: str) -> None:
        if self._in_next_data:
            self._next_data_parts.append(data)

    @property
    def next_data(self) -> str:
        return "".join(self._next_data_parts)


def _response_status(response: Any) -> int | None:
    status = getattr(response, "status", None)
    if status is None and hasattr(response, "getcode"):
        status = response.getcode()
    return int(status) if status is not None else None


def _check_response_status(response: Any, label: str) -> None:
    status = _response_status(response)
    if status is not None and not 200 <= status < 300:
        raise FetchError(f"{label}返回 HTTP {status}")


def _read_bounded(response: Any, limit: int, label: str) -> bytes:
    content_length = None
    headers = getattr(response, "headers", None)
    if headers is not None:
        try:
            content_length = headers.get("Content-Length")
        except AttributeError:
            content_length = None
    if content_length:
        try:
            if int(content_length) > limit:
                raise FetchError(f"{label}响应过大")
        except ValueError:
            pass
    data = response.read(limit + 1)
    if len(data) > limit:
        raise FetchError(f"{label}响应过大")
    return data


def _urlopen(
    request: urllib.request.Request,
    *,
    timeout: float,
    redirect_validator: RedirectValidator,
) -> Any:
    opener = urllib.request.build_opener(_ValidatingRedirectHandler(redirect_validator))
    return opener.open(request, timeout=timeout)


def _open(
    request: urllib.request.Request,
    *,
    timeout: float,
    label: str,
    redirect_validator: RedirectValidator,
) -> Any:
    try:
        response = _urlopen(
            request,
            timeout=timeout,
            redirect_validator=redirect_validator,
        )
    except urllib.error.HTTPError as exc:
        raise FetchError(f"{label}返回 HTTP {exc.code}") from exc
    except FetchError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError(f"{label}连接失败") from exc
    try:
        _check_response_status(response, label)
        final_url = response.geturl() if hasattr(response, "geturl") else None
        if final_url:
            redirect_validator(final_url)
    except Exception:
        response.close()
        raise
    return response


def _clean_text(value: Any) -> str:
    return html_module.unescape(str(value or "")).strip()


def _episode_from_next_data(raw: str) -> dict[str, Any] | None:
    if not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    try:
        episode = data["props"]["pageProps"]["episode"]
    except (KeyError, TypeError):
        return None
    return episode if isinstance(episode, dict) else None


def _audio_source(episode: dict[str, Any]) -> tuple[str, Any]:
    media = episode.get("media") if isinstance(episode.get("media"), dict) else {}
    source = media.get("source") if isinstance(media.get("source"), dict) else {}
    enclosure = (
        episode.get("enclosure") if isinstance(episode.get("enclosure"), dict) else {}
    )
    audio_url = source.get("url") or enclosure.get("url") or episode.get("audioUrl")
    return _clean_text(audio_url), source.get("mode")


def _is_paid(pay_type: Any, episode: dict[str, Any]) -> bool:
    if episode.get("isPaid") is True:
        return True
    if pay_type is None:
        return False
    if isinstance(pay_type, bool):
        return pay_type
    return str(pay_type).strip().upper() not in {"", "FREE", "NONE", "0"}


def _validate_audio_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    try:
        port = parsed.port
    except ValueError as exc:
        raise FetchError("音频链接端口无效") from exc
    if (
        parsed.scheme != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or port not in {None, 443}
    ):
        raise FetchError("音频链接必须是无凭据的标准 HTTPS 地址")
    if hostname == "localhost" or hostname.endswith(
        (".localhost", ".local", ".internal")
    ):
        raise FetchError("音频链接指向非公开主机")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise FetchError("音频链接指向非公开地址")
    return url


def _page_redirect_validator(expected_url: str) -> RedirectValidator:
    def validate(url: str) -> None:
        try:
            normalized_url, _ = normalize_episode_url(url)
        except ValueError as exc:
            raise FetchError("小宇宙页面重定向到了不受支持的地址") from exc
        if normalized_url != expected_url:
            raise FetchError("小宇宙页面重定向到了其他单集")

    return validate


def _audio_redirect_validator(url: str) -> None:
    _validate_audio_url(url)


def _parse_episode_html(
    page_html: str, normalized_url: str, episode_id: str
) -> dict[str, Any]:
    parser = _EpisodePageParser()
    parser.feed(page_html)
    episode = _episode_from_next_data(parser.next_data)
    meta = parser.meta

    if episode is not None:
        audio_url, media_mode = _audio_source(episode)
        podcast = (
            episode.get("podcast") if isinstance(episode.get("podcast"), dict) else {}
        )
        title = _clean_text(episode.get("title")) or _clean_text(meta.get("og:title"))
        description = _clean_text(episode.get("description")) or _clean_text(
            meta.get("og:description") or meta.get("description")
        )
        podcast_title = _clean_text(podcast.get("title")) or _clean_text(
            meta.get("og:site_name")
        )
        duration = episode.get("duration")
        published_at = episode.get("pubDate") or episode.get("publishedAt")
        is_private = bool(episode.get("isPrivateMedia"))
        pay_type = episode.get("payType")
        if is_private or str(media_mode or "").upper() in {
            "PRIVATE",
            "PAID",
            "PAYWALL",
        }:
            raise FetchError("该单集音频为私密内容，无法下载")
        if _is_paid(pay_type, episode):
            raise FetchError("该单集音频为付费内容，无法下载")
        if not audio_url:
            audio_url = _clean_text(meta.get("og:audio") or meta.get("og:audio:url"))
    else:
        audio_url = _clean_text(meta.get("og:audio") or meta.get("og:audio:url"))
        title = _clean_text(meta.get("og:title"))
        description = _clean_text(meta.get("og:description") or meta.get("description"))
        podcast_title = _clean_text(meta.get("og:site_name"))
        duration = meta.get("music:duration") or meta.get("og:audio:duration") or 0
        published_at = meta.get("article:published_time")
        media_mode = None
        is_private = False
        pay_type = None

    if not audio_url:
        raise FetchError("页面中没有可公开下载的音频链接，单集可能已下架或受限")
    audio_url = _validate_audio_url(audio_url)
    return {
        "id": episode_id,
        "title": title or episode_id,
        "description": description,
        "podcast_title": podcast_title,
        "duration": duration if duration is not None else 0,
        "published_at": published_at,
        "url": normalized_url,
        "audio_url": audio_url,
        "media_mode": media_mode,
        "is_private": is_private,
        "pay_type": pay_type,
    }


def fetch_episode_info(url: str) -> dict[str, Any]:
    """Return public episode metadata without downloading audio."""
    normalized_url, episode_id = normalize_episode_url(url)
    request = urllib.request.Request(
        normalized_url,
        headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"},
    )
    response = _open(
        request,
        timeout=PAGE_TIMEOUT_SECONDS,
        label="小宇宙页面",
        redirect_validator=_page_redirect_validator(normalized_url),
    )
    try:
        raw = _read_bounded(response, MAX_PAGE_BYTES, "小宇宙页面")
    finally:
        response.close()
    page_html = raw.decode("utf-8", errors="replace")
    return _parse_episode_html(page_html, normalized_url, episode_id)


def _audio_suffix(audio_url: str) -> str:
    suffix = Path(urlparse(audio_url).path).suffix.lower()
    return suffix if suffix in _AUDIO_SUFFIXES else ".m4a"


def _download_audio(audio_url: str, destination: Path) -> None:
    request = urllib.request.Request(
        audio_url,
        headers={"User-Agent": UA, "Accept": "audio/*,application/octet-stream;q=0.9"},
    )
    response = _open(
        request,
        timeout=AUDIO_TIMEOUT_SECONDS,
        label="音频服务器",
        redirect_validator=_audio_redirect_validator,
    )
    total = 0
    try:
        headers = getattr(response, "headers", None)
        content_length = headers.get("Content-Length") if headers is not None else None
        if content_length:
            try:
                if int(content_length) > MAX_AUDIO_BYTES:
                    raise FetchError("音频文件过大")
            except ValueError:
                pass
        with destination.open("wb") as output:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_AUDIO_BYTES:
                    raise FetchError("音频文件过大")
                output.write(chunk)
        if total == 0:
            raise FetchError("音频服务器返回了空文件")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise FetchError("音频下载失败") from exc
    finally:
        response.close()


def fetch_episode(url: str, *, download_dir: Path | None = None) -> dict[str, Any]:
    """Return episode metadata plus a unique local ``audio_path``."""
    episode = fetch_episode_info(url)
    target_dir = Path(download_dir) if download_dir is not None else AUDIO_DIR
    target_dir.mkdir(parents=True, exist_ok=True)
    if not stat.S_ISDIR(target_dir.stat().st_mode):
        raise FetchError(f"下载目录无效: {target_dir}")
    descriptor, raw_path = tempfile.mkstemp(
        prefix=f"{episode['id']}-",
        suffix=_audio_suffix(episode["audio_url"]),
        dir=target_dir,
    )
    os.close(descriptor)
    audio_path = Path(raw_path)
    try:
        _download_audio(episode["audio_url"], audio_path)
    except Exception:
        audio_path.unlink(missing_ok=True)
        raise
    return {**episode, "audio_path": audio_path}


def fetch(episode_url: str) -> Path:
    """Compatibility helper returning only the downloaded audio path."""
    return fetch_episode(episode_url)["audio_path"]


def _main(argv: list[str] | None = None) -> int:
    if argv is None:
        import sys

        argv = sys.argv[1:]
    if len(argv) != 1:
        raise SystemExit(
            "用法: python fetch.py https://www.xiaoyuzhoufm.com/episode/<id>"
        )
    info = fetch_episode_info(argv[0])
    print(f"标题: {info['title']}")
    if info["podcast_title"]:
        print(f"播客: {info['podcast_title']}")
    if info["published_at"]:
        print(f"发布: {info['published_at']}")
    if info["duration"]:
        print(f"时长: {info['duration']} 秒")
    print(f"链接: {info['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
