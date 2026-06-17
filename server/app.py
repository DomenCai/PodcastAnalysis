import json
import os
import re
import shutil
import tempfile
import threading
import uuid
import webbrowser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel

from server.config import LLM_API_KEY, MIMO_API_KEY
from server.pipeline import regenerate_episode, run_pipeline
from server.scraper import extract_episode_id
from server.summarizer import summary_to_markdown

OUTPUT_ROOT = Path("output")
WEB_DIST = Path("web/dist")
ID_PATTERN = r"^[a-f0-9]+$"

TaskStatus = Literal["running", "done", "error"]

app = FastAPI(title="PodcastAnalysis Web")


class CreateEpisodeRequest(BaseModel):
    url: str
    summary: bool = False


class RegenerateEpisodeRequest(BaseModel):
    transcript: bool = False
    summary: bool = False


@dataclass
class TaskState:
    task_id: str
    episode_id: str | None
    stage: str
    done: int | None
    total: int | None
    status: TaskStatus
    error: str | None


_tasks: dict[str, TaskState] = {}
_tasks_lock = threading.Lock()
_running_task_id: str | None = None


def _validate_id(value: str) -> str:
    if not value or not re.fullmatch(ID_PATTERN, value):
        raise HTTPException(status_code=400, detail="invalid id")
    return value


def _episode_dir(episode_id: str) -> Path:
    return OUTPUT_ROOT / _validate_id(episode_id)


def _read_meta(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _summary_path(root: Path) -> Path:
    return root / "summary.json"


def _episode_item(episode_id: str, root: Path, meta: dict) -> dict:
    return {
        "id": episode_id,
        "title": meta.get("title", ""),
        "podcast_title": meta.get("podcast_title", ""),
        "duration": meta.get("duration", 0),
        "has_transcript": (root / "transcript.txt").exists(),
        "has_summary": _summary_path(root).exists(),
    }


def _output_writable() -> bool:
    try:
        OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=OUTPUT_ROOT, prefix=".health-", delete=True):
            pass
        return True
    except OSError:
        return False


def _response_text(path: Path, media_type: str) -> Response:
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    return Response(path.read_text(encoding="utf-8"), media_type=media_type)


@app.get("/api/health")
def health() -> dict:
    return {
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ffprobe": shutil.which("ffprobe") is not None,
        "output_writable": _output_writable(),
        "mimo_key": bool(MIMO_API_KEY),
        "llm_key": bool(LLM_API_KEY),
    }


@app.get("/api/episodes")
def list_episodes() -> list[dict]:
    if not OUTPUT_ROOT.exists():
        return []

    episodes: list[dict] = []
    for root in sorted(OUTPUT_ROOT.iterdir()):
        if not root.is_dir():
            continue
        if not re.fullmatch(ID_PATTERN, root.name):
            continue
        meta = _read_meta(root / "meta.json")
        if not meta:
            continue
        episodes.append(_episode_item(root.name, root, meta))
    return episodes


@app.get("/api/episodes/{episode_id}")
def get_episode(episode_id: str) -> dict:
    root = _episode_dir(episode_id)
    meta = _read_meta(root / "meta.json")
    if not meta:
        raise HTTPException(status_code=404, detail="episode not found")
    return {
        **meta,
        "has_audio": (root / "audio.m4a").exists(),
        "has_transcript": (root / "transcript.txt").exists(),
        "has_summary": _summary_path(root).exists(),
    }


@app.get("/api/episodes/{episode_id}/transcript")
def get_transcript(episode_id: str) -> Response:
    return _response_text(_episode_dir(episode_id) / "transcript.txt", "text/plain")


@app.get("/api/episodes/{episode_id}/summary")
def get_summary(episode_id: str) -> Response:
    return _response_text(_summary_path(_episode_dir(episode_id)), "application/json")


@app.get("/api/episodes/{episode_id}/summary.md")
def download_summary(episode_id: str) -> Response:
    path = _summary_path(_episode_dir(episode_id))
    if not path.exists():
        raise HTTPException(status_code=404, detail="file not found")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Response(summary_to_markdown(data), media_type="text/markdown")


@app.get("/api/episodes/{episode_id}/audio")
def get_audio(episode_id: str) -> FileResponse:
    path = _episode_dir(episode_id) / "audio.m4a"
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(path, media_type="audio/mp4")


@app.delete("/api/episodes/{episode_id}", status_code=204)
def delete_episode(episode_id: str) -> Response:
    global _running_task_id

    root = _episode_dir(episode_id)
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="episode not found")

    with _tasks_lock:
        if _running_task_id and _tasks[_running_task_id].status == "running":
            raise HTTPException(status_code=409, detail="已有任务进行中")

    shutil.rmtree(root)
    return Response(status_code=204)


@app.post("/api/episodes")
def create_episode(payload: CreateEpisodeRequest) -> dict:
    global _running_task_id

    try:
        episode_id = extract_episode_id(payload.url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_id = uuid.uuid4().hex
    with _tasks_lock:
        if _running_task_id and _tasks[_running_task_id].status == "running":
            raise HTTPException(status_code=409, detail="已有任务进行中")
        _running_task_id = task_id
        _tasks[task_id] = TaskState(
            task_id=task_id,
            episode_id=episode_id,
            stage="fetching_info",
            done=None,
            total=None,
            status="running",
            error=None,
        )

    thread = threading.Thread(
        target=_run_task,
        args=(task_id, payload.url, payload.summary),
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id}


@app.post("/api/episodes/{episode_id}/regenerate")
def regenerate_episode_endpoint(episode_id: str, payload: RegenerateEpisodeRequest) -> dict:
    global _running_task_id

    episode_id = _validate_id(episode_id)
    if not payload.transcript and not payload.summary:
        raise HTTPException(status_code=400, detail="请选择需要重新生成的内容")
    if not _read_meta(_episode_dir(episode_id) / "meta.json"):
        raise HTTPException(status_code=404, detail="episode not found")

    task_id = uuid.uuid4().hex
    with _tasks_lock:
        if _running_task_id and _tasks[_running_task_id].status == "running":
            raise HTTPException(status_code=409, detail="已有任务进行中")
        _running_task_id = task_id
        _tasks[task_id] = TaskState(
            task_id=task_id,
            episode_id=episode_id,
            stage="transcribing" if payload.transcript else "summarizing",
            done=None,
            total=None,
            status="running",
            error=None,
        )

    thread = threading.Thread(
        target=_run_regenerate_task,
        args=(task_id, episode_id, payload.transcript, payload.summary),
        daemon=True,
    )
    thread.start()
    return {"task_id": task_id}


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str) -> dict:
    _validate_id(task_id)
    with _tasks_lock:
        task = _tasks.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        return asdict(task)


def _run_task(task_id: str, url: str, summary: bool) -> None:
    global _running_task_id

    def _on_event(stage: str, done: int | None, total: int | None) -> None:
        with _tasks_lock:
            task = _tasks[task_id]
            task.stage = stage
            task.done = done
            task.total = total

    try:
        result = run_pipeline(
            url,
            summary=summary,
            output_root=str(OUTPUT_ROOT),
            on_event=_on_event,
        )
        with _tasks_lock:
            task = _tasks[task_id]
            task.episode_id = result.episode_id
            task.stage = "done"
            task.done = None
            task.total = None
            task.status = "done"
    except Exception as exc:
        with _tasks_lock:
            task = _tasks[task_id]
            task.stage = "error"
            task.status = "error"
            task.error = str(exc)
    finally:
        with _tasks_lock:
            if _running_task_id == task_id:
                _running_task_id = None


def _run_regenerate_task(task_id: str, episode_id: str, transcript: bool, summary: bool) -> None:
    global _running_task_id

    def _on_event(stage: str, done: int | None, total: int | None) -> None:
        with _tasks_lock:
            task = _tasks[task_id]
            task.stage = stage
            task.done = done
            task.total = total

    try:
        regenerate_episode(
            episode_id,
            transcript=transcript,
            summary=summary,
            output_root=str(OUTPUT_ROOT),
            on_event=_on_event,
        )
        with _tasks_lock:
            task = _tasks[task_id]
            task.stage = "done"
            task.done = None
            task.total = None
            task.status = "done"
    except Exception as exc:
        with _tasks_lock:
            task = _tasks[task_id]
            task.stage = "error"
            task.status = "error"
            task.error = str(exc)
    finally:
        with _tasks_lock:
            if _running_task_id == task_id:
                _running_task_id = None


@app.get("/")
def root() -> Response:
    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return HTMLResponse("<h1>PodcastAnalysis Web</h1><p>web/dist not found.</p>")


@app.get("/{path:path}")
def static_asset(path: str) -> Response:
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")

    file_path = WEB_DIST / path
    if file_path.is_file():
        return FileResponse(file_path)

    index = WEB_DIST / "index.html"
    if index.exists():
        return FileResponse(index)

    raise HTTPException(status_code=404, detail="not found")


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    url = f"http://127.0.0.1:{port}"
    opener = threading.Timer(1.0, webbrowser.open, args=(url,))
    opener.daemon = True
    opener.start()
    uvicorn.run("server.app:app", host="127.0.0.1", port=port)
