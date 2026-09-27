"""Read-only index of completed manual and subscription articles."""

from __future__ import annotations

import json
import re
from pathlib import Path

from server.jobs import JOBS_ROOT
from server.subscriptions import DATA_ROOT

JOB_ID = re.compile(r"[0-9a-f]{32}")
PUBLIC_FILES = ("article.md", "notes.md", "mindmap.md", "transcript.txt")


def _inside_data(path: Path) -> bool:
    try:
        path.resolve().relative_to(DATA_ROOT)
        return True
    except ValueError:
        return False


def completed_jobs() -> list[dict]:
    items = []
    if not JOBS_ROOT.is_dir():
        return items
    for folder in JOBS_ROOT.iterdir():
        if not folder.is_dir() or not JOB_ID.fullmatch(folder.name):
            continue
        state = folder / "job.json"
        if not state.is_file() or state.is_symlink():
            continue
        try:
            job = json.loads(state.read_text(encoding="utf-8"))
            if job.get("id") != folder.name or job.get("status") != "done":
                continue
            result = Path(job.get("result_dir") or folder)
            if not _inside_data(result):
                continue
            available = [name for name in PUBLIC_FILES if (result / name).is_file() and not (result / name).is_symlink()]
            if not available:
                continue
            episode = job.get("episode") or {}
            items.append({
                "id": job["id"], "title": episode.get("title") or job.get("filename") or job["id"],
                "podcast_title": episode.get("podcast_title") or "其他音频",
                "description": episode.get("description") or "",
                "published_at": episode.get("published_at") or job.get("created_at"),
                "episode_url": job.get("episode_url"), "available_files": available,
                "result_dir": str(result),
            })
        except (OSError, ValueError, TypeError, AttributeError):
            continue
    return items


def job(job_id: str) -> dict | None:
    if not JOB_ID.fullmatch(job_id):
        return None
    return next((item for item in completed_jobs() if item["id"] == job_id), None)


def library(store) -> list[dict]:
    selected: dict[str, tuple[str, dict]] = {}
    subscription_titles: dict[str, str] = {}
    for subscription in store.list_subscriptions():
        for episode in store.list_episodes(subscription["id"], limit=500):
            if episode["status"] != "done" or not episode.get("result_dir"):
                continue
            result = Path(episode["result_dir"])
            if not _inside_data(result):
                continue
            available = [name for name in PUBLIC_FILES if (result / name).is_file() and not (result / name).is_symlink()]
            if not available:
                continue
            subscription_titles[episode["episode_url"]] = subscription["title"]
            article = {
                "kind": "episode", "id": episode["id"], "title": episode["title"],
                "published_at": episode["published_at"], "description": episode.get("description") or "",
                "available_files": available, "url": f"/episodes/{episode['id']}/transcript",
            }
            selected[f"source:{episode['episode_url']}"] = (subscription["title"], article)
    for item in completed_jobs():
        article = {key: item[key] for key in ("id", "title", "published_at", "description", "available_files")}
        article.update(kind="job", url=f"/jobs/{item['id']}")
        identity = f"source:{item['episode_url']}" if item["episode_url"] else f"job:{item['id']}"
        previous = selected.get(identity)
        if previous and "article.md" in previous[1]["available_files"] and "article.md" not in item["available_files"]:
            continue
        selected[identity] = (subscription_titles.get(item["episode_url"], item["podcast_title"]), article)
    groups: dict[str, list[dict]] = {}
    for title, article in selected.values():
        groups.setdefault(title, []).append(article)
    return [
        {"title": title, "articles": sorted(articles, key=lambda item: item["published_at"] or "", reverse=True)}
        for title, articles in sorted(groups.items()) if articles
    ]
