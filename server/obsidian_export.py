"""Append completed podcast bundles to a configured Obsidian vault."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import tempfile
import unicodedata
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from server.processing_lock import processing_lock

FILES = {
    "article.md": "文章.md",
    "notes.md": "笔记.md",
    "mindmap.md": "思维导图.md",
    "transcript.txt": "逐字稿.md",
}
logger = logging.getLogger(__name__)


def _folder_name(title: str) -> str:
    title = re.sub(r"\.(m4a|mp3|wav|mp4)$", "", title, flags=re.I)
    title = "".join(c if unicodedata.category(c)[0] in "LN" else "-" for c in title)
    title = re.sub("-+", "-", title).strip("-")
    if not re.search(r"[\u3400-\u9fff]", title):
        title = "播客-" + title
    while len(title.encode("utf-8")) > 210:
        title = title[:-1]
    return title


def _date_prefix(published_at: str | None, created_at: str | None, now: datetime) -> str:
    zone = ZoneInfo("Asia/Shanghai")
    for value in (published_at, created_at):
        if not value:
            continue
        try:
            timestamp = datetime.fromisoformat(value)
        except (TypeError, ValueError):
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=zone)
        return timestamp.astimezone(zone).strftime("%y%m%d-%H%M")
    return now.astimezone(zone).strftime("%y%m%d-%H%M")


def _source(path: Path) -> dict:
    result = {}
    with path.open(encoding="utf-8") as stream:
        if stream.readline().strip() != "---":
            return result
        for line in stream:
            if line.strip() == "---":
                break
            key, separator, value = line.partition(":")
            if separator and key in {"source_id", "source_url"}:
                try:
                    result[key] = json.loads(value)
                except ValueError:
                    pass
    return result


def _inside(vault: Path, path: Path) -> Path:
    if not path.resolve().is_relative_to(vault):
        raise ValueError("知识库目标路径超出 vault")
    return path


def _export(job: dict, directory: Path, vault: Path) -> Path | None:
    if not vault.is_dir():
        raise FileNotFoundError("知识库目录不存在")
    episode = job.get("episode") or {}
    source_id = "job:" + job["id"]
    source_url = job.get("episode_url") or episode.get("episode_url") or episode.get("url") or ""
    root = _inside(vault, vault / "_raw/podcast")
    meta = _inside(vault, vault / ".meta")
    meta.mkdir(exist_ok=True)
    with processing_lock(_inside(vault, meta / "podcast-export.lock")):
        for article in root.glob("*/*/文章.md"):
            _inside(vault, article)
            previous = _source(article)
            if previous.get("source_id") == source_id or (
                source_url and previous.get("source_url") == source_url
            ):
                # _raw is immutable, including user edits and later reanalysis.
                return None

        content = {}
        for name in FILES:
            source = directory / name
            if source.is_symlink() or not source.is_file():
                return None
            data = source.read_bytes()
            if not data.decode("utf-8").strip():
                return None
            content[name] = data

        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        podcast = episode.get("podcast_title") or "其他音频"
        group = _inside(vault, root / _folder_name(podcast))
        group.mkdir(parents=True, exist_ok=True)
        title = episode.get("title") or job.get("filename") or "未命名播客"
        prefix = _date_prefix(episode.get("published_at"), job.get("created_at"), now)
        target = group / (prefix + "-" + _folder_name(title))
        if target.exists() or target.is_symlink():
            suffix = hashlib.sha256((source_url or source_id).encode()).hexdigest()[:10]
            target = group / (target.name + "-" + suffix)
        if target.exists() or target.is_symlink():
            raise FileExistsError("知识库目标已存在，拒绝覆盖")
        log = _inside(vault, meta / "log.md")
        with tempfile.TemporaryDirectory(prefix=".podcast-", dir=group) as temporary:
            staging = Path(temporary) / "bundle"
            staging.mkdir()
            for name, destination in FILES.items():
                data = content[name]
                header = {
                    "title": title + " · " + destination[:-3],
                    "date": now.date().isoformat(),
                    "podcast": podcast,
                    "published_at": episode.get("published_at") or job.get("created_at"),
                    "source_url": source_url,
                    "reading_url": "https://podcast.fullai.top/jobs/" + job["id"],
                    "source_id": source_id,
                    "source_sha256": hashlib.sha256(data).hexdigest(),
                }
                frontmatter = "---\n" + "\n".join(
                    key + ": " + json.dumps(value, ensure_ascii=False)
                    for key, value in header.items()
                ) + "\n---\n\n"
                body = data.decode("utf-8")
                if name == "transcript.txt":
                    body = "\n\n".join(line for line in body.splitlines() if line.strip()) + "\n"
                with (staging / destination).open("w", encoding="utf-8") as stream:
                    stream.write(frontmatter + body)
                    stream.flush()
                    os.fsync(stream.fileno())
            staging.rename(target)
        with log.open("a", encoding="utf-8") as stream:
            stream.write(
                f"\n- {now.isoformat(timespec='seconds')} podcast: 自动入库 "
                f"{target.relative_to(vault)}，4个Markdown，来源{source_id}。\n"
            )
        logger.info("播客已入库: %s", target)
        return target


def export_job(job: dict, directory: Path, config_path: Path) -> Path | None:
    """Export failure must not change job status or notification timestamps."""
    try:
        if job.get("status") != "done" or not config_path.is_file():
            return None
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if not config.get("enabled", True):
            return None
        return _export(job, directory, Path(config["vault"]).expanduser().resolve())
    except Exception as exc:
        logger.warning("播客 %s 入库失败（%s），重启管理服务时补试", job.get("id"), type(exc).__name__)
        return None
