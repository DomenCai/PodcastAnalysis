"""Private localhost podcast management API and React application.

Never expose this app through the public tunnel; use server.public_app instead.
"""

from __future__ import annotations

import fcntl
import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from server.jobs import (
    JOBS_ROOT,
    READABLE_FILES,
    cleanup_interrupted_uploads,
    ensure_roots,
    manager,
    result_directory,
    save_upload,
    serialize_job,
)
from server.job_options import ProcessingOptions
from server.podcast_feed import normalize_episode_url
from server.subscriptions import subscription_service
from server import web_ui
from server.transcription_client import capabilities

WEB_ROOT = Path(__file__).resolve().parent.parent / "web"
JOB_ID_RE = re.compile(r"^[a-f0-9]{32}$")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_roots()
    # Prevent multiple uvicorn workers/reload processes from recovering the same
    # queue or deleting one another's audio. CLI submits via HTTP, not another daemon.
    with (JOBS_ROOT.parent / ".service.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("已有管理服务运行；请使用单个 uvicorn worker") from exc
        cleanup_interrupted_uploads()
        manager.start()
        subscription_service.start()
        try:
            yield
        finally:
            subscription_service.stop()
            manager.shutdown()
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


app = FastAPI(title="Podcast Notes — private", lifespan=lifespan)


@app.get("/api/health")
def health() -> dict:
    from server.analysis_runner import AnalysisConfig
    from server import analysis_fallback
    from server.analyzer import deai_config

    analysis = AnalysisConfig.from_env()
    return {
        "ok": True,
        "read_only": False,
        "worker": "single",
        "ffmpeg": bool(shutil.which("ffmpeg")),
        "analysis": {
            "backend": analysis.backend,
            "model": analysis.model,
            "thinking": analysis.thinking,
            "available": bool(shutil.which(analysis.backend)),
            "fallback": ({"backend": "codex", "model": "gpt-6.1-sol", "thinking": "high",
                          "available": bool(shutil.which("codex")),
                          "cooldown_seconds": analysis_fallback.COOLDOWN_SECONDS,
                          **analysis_fallback.cooldown_status()} if analysis.fallback_backend else None),
            "deai": ({"backend": deai.backend, "model": deai.model, "available": bool(shutil.which("agy"))}
                     if (deai := deai_config(analysis)) else None),
        },
        "subscriptions": True,
        "backends": capabilities(),
        "whisper_cleaning": bool(
            os.getenv("WHISPER_LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
        ),
    }


@app.get("/api/jobs")
def list_jobs() -> list[dict]:
    return [serialize_job(job) for job in manager.list()]


@app.post("/api/jobs", status_code=202)
def create_job(
    file: UploadFile | None = File(None),
    url: str | None = Form(None),
    backend: str = Form("qwen"),
    num_speakers: int | None = Form(None),
    skip_diarization: bool = Form(True),
) -> dict:
    ensure_roots()
    try:
        options = ProcessingOptions(backend, skip_diarization, num_speakers)
        if url and file:
            raise ValueError("file 和 url 只能选择一个")
        if url:
            normalized, _ = normalize_episode_url(url)
            # Index an already-published legacy subscription result in place,
            # rather than downloading/transcribing the same episode again.
            existing = subscription_service.store.find_episode(normalized)
            if existing and existing["status"] == "done" and existing.get("result_dir"):
                if not existing.get("job_id"):
                    imported = manager.import_result(
                        Path(existing["result_dir"]), existing
                    )
                    subscription_service.store.attach_job(
                        existing["id"], imported.id, result_directory(imported)
                    )
            job = manager.create_from_url(normalized, **options.to_dict())
        else:
            if not file or not file.filename:
                raise ValueError("缺少 file 或 url")
            filename, source = save_upload(file.file, file.filename)
            try:
                job = manager.create(filename, source, **options.to_dict())
            except Exception:
                shutil.rmtree(source.parent, ignore_errors=True)
                raise
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"job_id": job.id, "status_url": f"/api/jobs/{job.id}"}


def _get_job(job_id: str):
    if not JOB_ID_RE.fullmatch(job_id):
        raise HTTPException(status_code=400, detail="invalid job id")
    job = manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    return job


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    return serialize_job(_get_job(job_id))


class OptionsUpdate(BaseModel):
    backend: Literal["qwen", "whisper", "mimo"] | None = None
    skip_diarization: bool | None = None
    num_speakers: int | None = Field(None, ge=1, le=32)

    def changes(self) -> dict:
        result = self.model_dump(exclude_unset=True)
        for key in ("backend", "skip_diarization"):
            if key in result and result[key] is None:
                raise ValueError(f"{key} 不能为 null")
        return result


@app.post("/api/jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: str, payload: OptionsUpdate | None = None) -> dict:
    _get_job(job_id)
    try:
        job = manager.retry(
            job_id,
            before_requeue=_notify_job_requeued,
            **(payload.changes() if payload else {}),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job.id, "status_url": f"/api/jobs/{job.id}"}


@app.post("/api/jobs/{job_id}/analyze", status_code=202)
def analyze_job(job_id: str) -> dict:
    _get_job(job_id)
    try:
        job = manager.reanalyze(job_id, before_requeue=_notify_job_requeued)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job.id, "status_url": f"/api/jobs/{job.id}"}


def _notify_job_requeued(job) -> None:
    subscription_service.store.requeue_linked_job(
        job.id,
        {
            name: getattr(job, name)
            for name in ("backend", "skip_diarization", "num_speakers")
        },
    )
    subscription_service._wake.set()


JOB_FILES = {
    **{
        name: "text/plain" if name.endswith(".txt") else "text/markdown"
        for name in READABLE_FILES
    },
    **{
        name: "application/json"
        for name in (
            "transcript.json",
            "transcript.raw.json",
            "transcript.diarized.json",
            "corrections.json",
            "meta.json",
            "episode.json",
        )
    },
    "episode.md": "text/markdown",
}


def _job_file(job_id: str, filename: str, *, not_ready_status: int = 404) -> Response:
    job = _get_job(job_id)
    if filename not in JOB_FILES:
        raise HTTPException(status_code=404, detail="file not found")
    path = result_directory(job) / filename
    if not path.is_file() or path.is_symlink():
        raise HTTPException(status_code=not_ready_status, detail="file not ready")
    return FileResponse(
        path,
        media_type=JOB_FILES[filename],
        filename=filename,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/jobs/{job_id}/files/{filename}")
def get_job_file(job_id: str, filename: str) -> Response:
    return _job_file(job_id, filename)


class SubscriptionCreate(BaseModel):
    url: str
    poll_interval_minutes: int = Field(30, ge=5, le=10080)
    initial_backfill: int = Field(1, ge=0, le=15)
    backend: Literal["qwen", "whisper", "mimo"] = "qwen"
    skip_diarization: bool = True
    num_speakers: int | None = Field(None, ge=1, le=32)
    auto_process: bool = True


class SubscriptionEnabled(BaseModel):
    enabled: bool


class SubscriptionAutoProcess(BaseModel):
    auto_process: bool


@app.get("/api/subscriptions")
def list_subscriptions() -> list[dict]:
    return subscription_service.store.list_subscriptions()


@app.post("/api/subscriptions", status_code=201)
def create_subscription(payload: SubscriptionCreate) -> dict:
    try:
        return subscription_service.add_subscription(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=409 if "已经订阅" in str(exc) else 400, detail=str(exc)
        ) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"读取播客主页失败: {exc}") from exc


@app.post("/api/subscriptions/{subscription_id}/check", status_code=202)
def check_subscription(subscription_id: int) -> dict:
    if not subscription_service.store.request_check(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    subscription_service._wake.set()
    return {"queued": True}


@app.put("/api/subscriptions/{subscription_id}/enabled")
def set_subscription_enabled(
    subscription_id: int, payload: SubscriptionEnabled
) -> dict:
    if not subscription_service.store.set_enabled(subscription_id, payload.enabled):
        raise HTTPException(status_code=404, detail="subscription not found")
    subscription_service._wake.set()
    return {"enabled": payload.enabled}


@app.put("/api/subscriptions/{subscription_id}/auto-process")
def set_subscription_auto_process(
    subscription_id: int, payload: SubscriptionAutoProcess
) -> dict:
    if not subscription_service.store.set_auto_process(
        subscription_id, payload.auto_process
    ):
        raise HTTPException(status_code=404, detail="subscription not found")
    return {"auto_process": payload.auto_process}


@app.put("/api/subscriptions/{subscription_id}/options")
def set_subscription_options(subscription_id: int, payload: OptionsUpdate) -> dict:
    try:
        if not subscription_service.store.set_options(
            subscription_id, **payload.changes()
        ):
            raise HTTPException(status_code=404, detail="subscription not found")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return subscription_service.store.get_subscription(subscription_id)


@app.delete("/api/subscriptions/{subscription_id}", status_code=204)
def delete_subscription(subscription_id: int) -> Response:
    if not subscription_service.store.delete_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    return Response(status_code=204)


@app.get("/api/subscriptions/{subscription_id}/episodes")
def list_subscription_episodes(subscription_id: int, limit: int = 100) -> list[dict]:
    if not subscription_service.store.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    if not 1 <= limit <= 500:
        raise HTTPException(status_code=400, detail="limit 必须在 1 到 500 之间")
    return [
        {
            **episode,
            "available_files": web_ui.available_files(episode.get("result_dir")),
        }
        for episode in subscription_service.store.list_episodes(
            subscription_id, limit=limit
        )
    ]


def _queue_subscription_episode(
    episode_id: int, *, analyze_only: bool = False, changes: dict | None = None
) -> dict:
    try:
        if not subscription_service.store.retry_episode(
            episode_id, analyze_only=analyze_only, **(changes or {})
        ):
            if not subscription_service.store.get_episode(episode_id):
                raise HTTPException(status_code=404, detail="episode not found")
            raise HTTPException(status_code=409, detail="当前状态不能重试")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    subscription_service._wake.set()
    return {"queued": True}


@app.post("/api/subscription-episodes/{episode_id}/retry", status_code=202)
def retry_subscription_episode(
    episode_id: int, payload: OptionsUpdate | None = None
) -> dict:
    try:
        changes = payload.changes() if payload else {}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _queue_subscription_episode(episode_id, changes=changes)


@app.get("/api/subscription-episodes/awaiting")
def list_awaiting_episodes(
    subscription_id: int | None = None, limit: int = 50
) -> list[dict]:
    if not 1 <= limit <= 200:
        raise HTTPException(status_code=400, detail="limit 必须在 1 到 200 之间")
    return subscription_service.store.list_awaiting_episodes(subscription_id, limit)


@app.post("/api/subscription-episodes/{episode_id}/transcribe", status_code=202)
def transcribe_subscription_episode(
    episode_id: int, payload: OptionsUpdate | None = None
) -> dict:
    try:
        changes = payload.changes() if payload else {}
        if not subscription_service.store.approve_episode(episode_id, **changes):
            if not subscription_service.store.get_episode(episode_id):
                raise HTTPException(status_code=404, detail="episode not found")
            raise HTTPException(status_code=409, detail="只有待确认或已忽略的单集可以开始转写")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    subscription_service._wake.set()
    return {"queued": True}


@app.post("/api/subscription-episodes/{episode_id}/dismiss")
def dismiss_subscription_episode(episode_id: int) -> dict:
    if not subscription_service.store.dismiss_episode(episode_id):
        if not subscription_service.store.get_episode(episode_id):
            raise HTTPException(status_code=404, detail="episode not found")
        raise HTTPException(status_code=409, detail="只有待确认的单集可以忽略")
    return {"status": "ignored"}


@app.post("/api/subscription-episodes/{episode_id}/analyze", status_code=202)
def analyze_subscription_episode(episode_id: int) -> dict:
    return _queue_subscription_episode(episode_id, analyze_only=True)


SUBSCRIPTION_FILES = {
    name: JOB_FILES[name] for name in READABLE_FILES | {"episode.json", "episode.md"}
}


@app.get("/api/episodes/{episode_id}")
def get_episode_metadata(episode_id: int) -> dict:
    episode = subscription_service.store.get_episode(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="episode not found")
    return web_ui.episode_metadata(episode)


@app.get("/api/episodes/{episode_id}/files/{filename}")
@app.get("/api/subscription-episodes/{episode_id}/files/{filename}")
def get_subscription_episode_file(episode_id: int, filename: str) -> Response:
    media_type = SUBSCRIPTION_FILES.get(filename)
    if not media_type:
        raise HTTPException(status_code=404, detail="file not found")
    episode = subscription_service.store.get_episode(episode_id)
    if not episode:
        raise HTTPException(status_code=404, detail="episode not found")
    if not episode.get("result_dir"):
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


@app.get("/episodes/{episode_id}/transcript")
def transcript_page(episode_id: int) -> Response:
    episode = subscription_service.store.get_episode(episode_id)
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


@app.get("/jobs/{job_id}")
def job_page(job_id: str):
    _get_job(job_id)
    return web_ui.page()


@app.get("/podcasts/{subscription_id}")
def podcast_page(subscription_id: int):
    if not subscription_service.store.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="subscription not found")
    return web_ui.page()


@app.get("/")
@app.get("/jobs")
@app.get("/new")
@app.get("/subscriptions")
def index() -> Response:
    return web_ui.page()


if __name__ == "__main__":
    uvicorn.run(
        app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "18000"))
    )
