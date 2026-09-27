"""HTTP boundary: PodcastAnalysis never imports or loads an ASR model."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx


def service_url():
    return os.getenv("TRANSCRIPTION_API_URL", "http://127.0.0.1:18010").rstrip("/")


def capabilities():
    try:
        response = httpx.get(service_url() + "/health", timeout=3)
        response.raise_for_status()
        return response.json()["backends"]
    except (httpx.HTTPError, ValueError, KeyError):
        return {"qwen": False, "whisper": False, "mimo": False}


def _get(client, path):
    # Model loading can stall the local server long enough to expire keep-alive.
    # Only reads are replayed; replaying an upload could create duplicate work.
    for attempt in range(3):
        try:
            response = client.get(path)
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == 2:
                raise
            time.sleep(1)


def transcribe(source: Path, *, result_dir: Path, backend="qwen",
               skip_diarization=True, num_speakers=None, on_progress=None, retry_failed=False):
    options = {"backend": backend, "skip_diarization": skip_diarization,
               "num_speakers": num_speakers}
    reference = result_dir / "transcription-job.json"
    base = service_url()
    with httpx.Client(base_url=base, timeout=120) as client:
        job_id = None
        if reference.is_file():
            saved = json.loads(reference.read_text())
            if saved["service"] != base or saved["options"] != options:
                raise ValueError("转录服务或配置已改变，请重新转写以创建新任务")
            job_id = saved["id"]
            if retry_failed:
                state = _get(client, f"/v1/transcriptions/{job_id}").json()
                if state["status"] in {"error", "cancelled"}:
                    response = client.post(f"/v1/transcriptions/{job_id}/retry")
                    response.raise_for_status()
        if job_id is None:
            with source.open("rb") as stream:
                response = client.post("/v1/transcriptions",
                    files={"file": (source.name, stream, "application/octet-stream")},
                    data={"options": json.dumps(options)})
            response.raise_for_status()
            job_id = response.json()["id"]
            temporary = reference.with_suffix(".tmp")
            temporary.write_text(json.dumps({"id": job_id, "service": base, "options": options}))
            temporary.replace(reference)
        while True:
            response = _get(client, f"/v1/transcriptions/{job_id}")
            state = response.json()
            if on_progress:
                on_progress(state["stage"], state.get("done"), state.get("total"))
            if state["status"] == "done":
                response = _get(client, f"/v1/transcriptions/{job_id}/result")
                return response.json()
            if state["status"] in {"error", "cancelled"}:
                raise RuntimeError(state.get("error") or "转录已取消")
            time.sleep(1)
