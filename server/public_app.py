"""Read-only public view for Cloudflare Tunnel.

This application intentionally registers GET routes only.  Subscription
management, uploads, retries and all other writes remain on the private app.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response

from server.public_store import ReadOnlySubscriptionStore
from server import public_catalog
from server import web_ui

ROOT = Path(__file__).resolve().parent.parent
WEB_ROOT = ROOT / "web"
store = ReadOnlySubscriptionStore()

app = FastAPI(
    title="Podcast Notes (read only)",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.exception_handler(sqlite3.Error)
async def database_unavailable(_request, _error):
    return Response(
        "播客索引尚未就绪，请先启动管理服务完成初始化。",
        status_code=503,
        media_type="text/plain",
        headers={"Cache-Control": "no-cache"},
    )


@app.middleware("http")
async def get_only(request: Request, call_next):
    if request.method != "GET":
        return Response(
            "public endpoint is read-only",
            status_code=405,
            headers={"Allow": "GET"},
            media_type="text/plain",
        )
    return await call_next(request)


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "read_only": True}


@app.get("/api/subscriptions")
def list_subscriptions() -> list[dict]:
    return [
        {
            "id": item["id"],
            "podcast_id": item["podcast_id"],
            "source_url": item["source_url"],
            "title": item["title"],
            "author": item["author"],
            "description": item["description"],
            "episode_count": item["episode_count"],
            "latest_episode_at": item["latest_episode_at"],
            "enabled": item["enabled"],
            "done_count": item["done_count"],
            "processing_count": item["processing_count"],
            "pending_count": item["pending_count"],
        }
        for item in store.list_subscriptions()
    ]


@app.get("/api/library")
def library() -> list[dict]:
    return public_catalog.library(store)


@app.get("/api/jobs/{job_id}")
def public_job(job_id: str) -> dict:
    item = public_catalog.job(job_id)
    if not item:
        raise HTTPException(status_code=404, detail="article not found")
    return {key: value for key, value in item.items() if key != "result_dir"}


@app.get("/api/jobs/{job_id}/files/{filename}")
def public_job_file(job_id: str, filename: str) -> Response:
    if filename not in PUBLIC_FILES:
        raise HTTPException(status_code=404, detail="file not found")
    item = public_catalog.job(job_id)
    if not item or filename not in item["available_files"]:
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(Path(item["result_dir"]) / filename, media_type=PUBLIC_FILES[filename], headers={"Cache-Control": "no-cache"})


@app.get("/api/subscriptions/{subscription_id}/episodes")
def list_episodes(subscription_id: int, limit: int = 100) -> list[dict]:
    if not store.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit 必须在 1 到 200 之间")
    allowed_statuses = {"pending", "processing", "done"}
    return [
        {
            "id": item["id"],
            "eid": item["eid"],
            "episode_url": item["episode_url"],
            "title": item["title"],
            "published_at": item["published_at"],
            "duration": item["duration"],
            "status": item["status"],
            "has_result": item["status"] == "done" and bool(item["result_dir"]),
        }
        for item in store.list_episodes(subscription_id, limit=limit)
        if item["status"] in allowed_statuses
    ]


@app.get("/api/episodes/{episode_id}")
def get_episode_metadata(episode_id: int) -> dict:
    episode = store.get_episode(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="episode not found")
    return web_ui.episode_metadata(episode)


PUBLIC_FILES = {
    "transcript.txt": "text/plain",
    "article.md": "text/markdown",
    "notes.md": "text/markdown",
    "mindmap.md": "text/markdown",
}


@app.get("/api/episodes/{episode_id}/files/{filename}")
def get_episode_file(episode_id: int, filename: str) -> Response:
    media_type = PUBLIC_FILES.get(filename)
    if not media_type:
        raise HTTPException(status_code=404, detail="file not found")
    episode = store.get_episode(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="episode not found")
    if episode["status"] != "done" or not episode.get("result_dir"):
        raise HTTPException(status_code=409, detail="episode not ready")
    path = Path(episode["result_dir"]) / filename
    if not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/podcasts/{subscription_id}")
def podcast_page(subscription_id: int) -> Response:
    if not store.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    return web_ui.page()


@app.get("/podcasts")
def library_page() -> Response:
    return web_ui.page()


@app.get("/jobs/{job_id}")
def job_page(job_id: str) -> Response:
    if not public_catalog.job(job_id):
        raise HTTPException(status_code=404, detail="article not found")
    return web_ui.page()


@app.get("/episodes/{episode_id}/transcript")
def transcript_page(episode_id: int) -> Response:
    episode = store.get_episode(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="episode not found")
    if episode["status"] != "done" or not episode.get("result_dir"):
        raise HTTPException(status_code=409, detail="episode not ready")
    if not (Path(episode["result_dir"]) / "transcript.txt").is_file():
        raise HTTPException(status_code=404, detail="transcript not found")
    return web_ui.page()


@app.get("/assets/{path:path}")
def static_asset(path: str):
    return web_ui.asset(path)


@app.get("/")
def index() -> Response:
    raise HTTPException(status_code=404, detail="not found")


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=os.getenv("PUBLIC_HOST", "127.0.0.1"),
        port=int(os.getenv("PUBLIC_PORT", "8001")),
    )
