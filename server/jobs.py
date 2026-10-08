"""Persistent jobs; all manual, subscription and CLI work uses one executor.

Audio is task-local temporary data. Analysis always consumes the saved transcript
and produces Markdown via the configured analysis CLI; it never invokes the legacy JSON note generator.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

from server.job_options import ProcessingOptions
from server.llm_postprocessor import process_turns
from server.obsidian_export import export_job
from server.processing_lock import processing_lock
from server.transcript_output import add_speaker_labels, build_formatted_text
from server.transcription_client import transcribe as transcribe_remote

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("PODCAST_DATA_DIR", ROOT / "data")).expanduser().resolve()
JOBS_ROOT = DATA_ROOT / "jobs"
UPLOAD_ROOT = DATA_ROOT / "uploads"
READABLE_FILES = {"transcript.txt", "article.md", "notes.md", "mindmap.md"}
ACTIVE_STATUSES = {"queued", "running"}


def analyze_markdown(*args, **kwargs):
    from server.analyzer import analyze

    return analyze(*args, **kwargs)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def merge_episode_metadata(previous: dict | None, incoming: dict | None) -> dict:
    """An incomplete OG fallback must not erase richer subscription/old metadata."""
    merged = dict(previous or {})
    for key, value in (incoming or {}).items():
        if value is None or value == "" or value == [] or value == {}:
            continue
        if key == "duration" and not value:
            continue
        merged[key] = value
    return merged


def _safe_error(exc: Exception) -> str:
    from urllib.parse import quote

    message = str(exc)
    for name in ("MIMO_API_KEY", "WHISPER_LLM_API_KEY", "OPENAI_API_KEY", "HF_TOKEN"):
        secret = os.getenv(name)
        if secret:
            message = message.replace(secret, "[REDACTED]").replace(
                quote(secret, safe=""), "[REDACTED]"
            )
    return message[:4000]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


@dataclass
class Job:
    id: str
    filename: str
    status: str = "queued"
    stage: str = "queued"
    error: str | None = None
    result_url: str | None = None
    backend: str = "qwen"
    num_speakers: int | None = None
    skip_diarization: bool = True
    episode_url: str | None = None
    episode: dict | None = field(default=None, repr=False)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    done: int | None = None
    total: int | None = None
    # Internal state is persisted but never returned from the public DTO.
    result_dir: str | None = field(default=None, repr=False)
    operation: str = "transcribe"
    archive_pending: str | None = field(default=None, repr=False)


def result_directory(job: Job) -> Path:
    return Path(job.result_dir) if job.result_dir else JOBS_ROOT / job.id


def serialize_job(job: Job) -> dict:
    value = asdict(job)
    value.pop("result_dir", None)
    value.pop("archive_pending", None)
    if value.get("episode"):
        value["episode"] = {
            key: item
            for key, item in value["episode"].items()
            if key
            in {
                "id",
                "title",
                "description",
                "podcast_title",
                "duration",
                "published_at",
                "url",
            }
        }
    value["can_resume_transcription"] = (
        job.status == "error" and job.operation == "transcribe"
        and (result_directory(job) / "transcription-job.json").is_file()
    )
    value["available_files"] = sorted(
        name for name in READABLE_FILES if (result_directory(job) / name).is_file()
    )
    return value


class JobManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="podcast")
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._started = False
        self._closed = False
        self._upload_sources: dict[str, Path] = {}

    def _load(self) -> None:
        if not JOBS_ROOT.is_dir():
            return
        for directory in JOBS_ROOT.iterdir():
            if not directory.is_dir() or len(directory.name) != 32:
                continue
            if any(c not in "0123456789abcdef" for c in directory.name):
                continue
            if directory.name in self._jobs:
                continue
            try:
                state = directory / "job.json"
                if state.is_file():
                    data = json.loads(state.read_text(encoding="utf-8"))
                    data.setdefault("backend", "whisper")
                    data.setdefault("updated_at", data.get("created_at") or datetime.fromtimestamp(state.stat().st_mtime, UTC).isoformat())
                    if data.get("id") != directory.name:
                        continue
                    allowed = {f.name for f in fields(Job)}
                    job = Job(**{k: v for k, v in data.items() if k in allowed})
                else:
                    # Read-only import of historical data/jobs results; no file move.
                    transcript = directory / "transcript.txt"
                    if not transcript.is_file():
                        continue
                    meta_path = directory / "meta.json"
                    meta = (
                        json.loads(meta_path.read_text()) if meta_path.is_file() else {}
                    )
                    ep_path = directory / "episode.json"
                    ep = json.loads(ep_path.read_text()) if ep_path.is_file() else {}
                    job = Job(
                        id=directory.name,
                        backend="whisper",
                        filename=ep.get("title")
                        or meta.get("filename", directory.name),
                        status="done",
                        stage="done",
                        episode=ep,
                        episode_url=ep.get("url"),
                        created_at=datetime.fromtimestamp(
                            transcript.stat().st_mtime, UTC
                        ).isoformat(),
                    )
                self._jobs[job.id] = job
            except (OSError, ValueError, TypeError):
                continue

    def start(self) -> None:
        """Recover URL jobs; interrupted uploads require re-upload, never guessed paths."""
        with self._lock:
            if self._started:
                return
            self._started = True
            self._load()
            for job in sorted(self._jobs.values(), key=lambda item: item.created_at):
                if job.status == "done":
                    self._export_to_obsidian(job)
                if job.status not in ACTIVE_STATUSES:
                    continue
                directory = result_directory(job)
                if job.operation == "analyze" or job.stage == "analyzing":
                    if (directory / "transcript.txt").is_file():
                        self._update(
                            job.id, status="queued", stage="queued", operation="analyze"
                        )
                        self._executor.submit(self._run_analysis, job.id)
                        continue
                if job.episode_url:
                    self._update(job.id, status="queued", stage="queued")
                    self._executor.submit(self._run_url, job.id)
                elif (directory / "transcription-job.json").is_file():
                    self._update(job.id, status="queued", stage="queued")
                    self._executor.submit(self._run, job.id, directory / "remote-source")
                else:
                    self._update(
                        job.id,
                        status="error",
                        stage="error",
                        error="服务中断，临时音频已清理；请重新上传",
                    )

    def shutdown(self) -> None:
        self._closed = True
        # Drain only the current task (so its audio cleanup runs), NOT the whole
        # persisted queue. Queued URL jobs recover at the next service startup;
        # queued uploads are marked for re-upload by start() after cleanup.
        self._executor.shutdown(wait=True, cancel_futures=True)
        with self._lock:
            for job_id, source in list(self._upload_sources.items()):
                if self._jobs[job_id].status != "queued":
                    continue
                try:
                    source.resolve().relative_to(UPLOAD_ROOT.resolve())
                except ValueError:
                    pass  # Caller-owned original: never remove it.
                else:
                    source.unlink(missing_ok=True)
                    if source.parent != UPLOAD_ROOT:
                        shutil.rmtree(source.parent, ignore_errors=True)
                self._update(
                    job_id,
                    status="error",
                    stage="error",
                    error="服务停止，临时音频已清理；请重新上传",
                )
            self._upload_sources.clear()

    def _persist(self, job: Job) -> None:
        _write_json(JOBS_ROOT / job.id / "job.json", asdict(job))

    def _update(self, job_id: str, **changes) -> None:
        with self._lock:
            job = self._jobs[job_id]
            for name, value in changes.items():
                setattr(job, name, value)
            job.updated_at = _now()
            self._persist(job)

    def _new(self, filename: str, **options) -> Job:
        if self._closed:
            raise RuntimeError("服务正在停止")
        job = Job(id=uuid.uuid4().hex, filename=filename, **options)
        self._jobs[job.id] = job
        self._persist(job)
        return Job(**asdict(job))

    def create(
        self,
        filename: str,
        source: Path,
        *,
        num_speakers: int | None = None,
        episode_url: str | None = None,
        skip_diarization: bool = True,
        backend: str = "qwen",
    ) -> Job:
        options = ProcessingOptions(backend, skip_diarization, num_speakers)
        if not source.is_file():
            raise ValueError("音频文件不存在")
        with self._lock:
            job = self._new(filename, episode_url=episode_url, **options.to_dict())
            self._upload_sources[job.id] = source
            self._executor.submit(self._run, job.id, source)
            return job

    def create_from_url(
        self,
        episode_url: str,
        *,
        num_speakers: int | None = None,
        skip_diarization: bool = True,
        backend: str = "qwen",
        episode_metadata: dict | None = None,
    ) -> Job:
        from server.podcast_feed import normalize_episode_url

        episode_url, _ = normalize_episode_url(episode_url)
        options = ProcessingOptions(backend, skip_diarization, num_speakers)
        with self._lock:
            self._load()
            # One episode, one durable task, shared between subscriptions and manual input.
            for existing in self._jobs.values():
                if existing.episode_url == episode_url:
                    if any(
                        getattr(existing, key) != value
                        for key, value in options.to_dict().items()
                    ):
                        raise ValueError(
                            "此单集已有不同配置的任务，请打开原任务选择重新转写并更换后端"
                        )
                    if episode_metadata:
                        # Existing fetched metadata wins, discovery fills missing values.
                        self._update(
                            existing.id,
                            episode=merge_episode_metadata(
                                episode_metadata, existing.episode
                            ),
                        )
                    return Job(**asdict(existing))
            seed = merge_episode_metadata(episode_metadata, {"url": episode_url})
            job = self._new(
                seed.get("title") or episode_url,
                episode_url=episode_url,
                episode=seed,
                **options.to_dict(),
            )
            self._executor.submit(self._run_url, job.id)
            return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            self._load()
            job = self._jobs.get(job_id)
            return Job(**asdict(job)) if job else None

    def list(self) -> list[Job]:
        with self._lock:
            self._load()
            return [
                Job(**asdict(job))
                for job in sorted(
                    self._jobs.values(), key=lambda item: item.created_at, reverse=True
                )
            ]

    def retry(self, job_id: str, *, before_requeue=None, **changes) -> Job:
        with self._lock:
            job = self.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status in ACTIVE_STATUSES:
                raise ValueError("任务正在排队或处理中")
            if self._closed:
                raise ValueError("服务正在停止")
            if not job.episode_url:
                reference = result_directory(job) / "transcription-job.json"
                if reference.is_file() and job.status == "error" and not changes:
                    self._update(job_id, status="queued", stage="queued", error=None)
                    self._executor.submit(self._run, job_id, reference.parent / "remote-source", resume=True)
                    return self.get(job_id)
                raise ValueError("音频未保留，请重新上传；已有逐字稿可以单独重新分析")
            options = ProcessingOptions(
                **{
                    key: changes.get(key, getattr(job, key))
                    for key in ("backend", "skip_diarization", "num_speakers")
                }
            )
            if self._closed:
                raise ValueError("服务正在停止")
            planned = Job(**{**asdict(job), **options.to_dict()})
            if before_requeue:
                before_requeue(planned)
            # Persist intent BEFORE moving any artifact. Archive is resumable if
            # a crash/disk error interrupts it; never leave job.json saying done.
            self._update(
                job_id,
                **options.to_dict(),
                status="queued",
                stage="queued",
                error=None,
                operation="transcribe",
                done=None,
                total=None,
                archive_pending=job.archive_pending or uuid.uuid4().hex,
            )
            self._executor.submit(self._run_url, job_id)
            return self.get(job_id)

    def reanalyze(self, job_id: str, *, before_requeue=None) -> Job:
        with self._lock:
            job = self.get(job_id)
            if not job:
                raise KeyError(job_id)
            if job.status in ACTIVE_STATUSES:
                raise ValueError("任务正在排队或处理中")
            if self._closed:
                raise ValueError("服务正在停止")
            if job.archive_pending:
                raise ValueError("上次转写归档尚未完成，请重试转写")
            transcript = result_directory(job) / "transcript.txt"
            if not transcript.is_file() or not transcript.stat().st_size:
                raise ValueError("没有可用逐字稿，请先完成转写")
            if before_requeue:
                before_requeue(job)
            self._update(
                job_id,
                status="queued",
                stage="queued",
                error=None,
                operation="analyze",
                done=None,
                total=None,
            )
            self._executor.submit(self._run_analysis, job_id)
            return self.get(job_id)

    def import_result(self, directory: Path, episode: dict) -> Job:
        """Register legacy out/agy artifacts in place so analysis needs no audio."""
        directory = directory.resolve()
        job_id = uuid.uuid5(uuid.NAMESPACE_URL, str(directory)).hex
        with self._lock:
            self._load()
            if job_id not in self._jobs:
                job = Job(
                    id=job_id,
                    filename=episode.get("title", directory.name),
                    status="done",
                    stage="done",
                    episode=episode,
                    episode_url=episode.get("episode_url") or episode.get("url"),
                    result_dir=str(directory),
                    backend=episode.get("backend", "whisper"),
                    skip_diarization=bool(episode.get("skip_diarization", True)),
                    num_speakers=episode.get("num_speakers"),
                )
                self._jobs[job_id] = job
                self._persist(job)
            return self.get(job_id)

    def _progress(self, job_id: str):
        def progress(stage, done=None, total=None):
            self._update(job_id, stage=stage, done=done, total=total)

        return progress

    def _archive_previous(self, job_id: str) -> None:
        job = self._jobs[job_id]
        if not job.archive_pending:
            return
        self._update(job_id, status="running", stage="archiving")
        directory = result_directory(job)
        archive = directory / "history" / job.archive_pending
        archive.mkdir(parents=True, exist_ok=True)
        for name in READABLE_FILES | {
            "transcript.raw.json",
            "transcription-job.json",
            "transcript.diarized.json",
            "transcript.json",
            "corrections.json",
            "meta.json",
        }:
            source = directory / name
            if source.is_file():
                source.replace(archive / name)
        self._update(job_id, archive_pending=None)

    def _run_url(self, job_id: str) -> None:
        # URL downloads also use task-local directories, never shared title paths.
        UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            from fetch import fetch_episode

            self._archive_previous(job_id)
            with tempfile.TemporaryDirectory(
                prefix="job-", dir=UPLOAD_ROOT
            ) as temporary:
                self._update(job_id, status="running", stage="fetching", error=None)
                episode = fetch_episode(
                    self._jobs[job_id].episode_url, download_dir=Path(temporary)
                )
                source = Path(episode.pop("audio_path"))
                episode = merge_episode_metadata(self._jobs[job_id].episode, episode)
                episode["url"] = self._jobs[job_id].episode_url
                self._update(
                    job_id,
                    episode=episode,
                    filename=episode.get("title") or self._jobs[job_id].filename,
                )
                self._run(job_id, source, episode=episode)
        except Exception as exc:
            self._update(job_id, status="error", stage="error", error=_safe_error(exc))

    def _run(
        self,
        job_id: str,
        source: Path,
        episode: dict | None = None,
        cleanup_parent: bool = True,
        resume: bool = False,
    ) -> None:
        cleaned = False

        def cleanup():
            nonlocal cleaned
            if cleaned:
                return
            # Never delete arbitrary caller directories or user-owned original audio.
            try:
                source.resolve().relative_to(UPLOAD_ROOT.resolve())
            except ValueError:
                cleaned = True
                return
            source.unlink(missing_ok=True)
            if cleanup_parent and source.parent != UPLOAD_ROOT:
                shutil.rmtree(source.parent, ignore_errors=True)
            cleaned = True

        try:
            with processing_lock(JOBS_ROOT.parent / ".pipeline.lock"):
                self._update(job_id, status="running", stage="starting", error=None)
                job = self._jobs[job_id]
                result_dir = result_directory(job)
                result_dir.mkdir(parents=True, exist_ok=True)
                ep = (
                    episode
                    or job.episode
                    or {"title": job.filename, "url": job.episode_url or ""}
                )
                _write_json(result_dir / "episode.json", ep)
                self._update(job_id, episode=ep)
                raw = transcribe_remote(
                    source, result_dir=result_dir, backend=job.backend,
                    skip_diarization=job.skip_diarization, num_speakers=job.num_speakers,
                    on_progress=self._progress(job_id),
                    retry_failed=resume,
                )
                _write_json(result_dir / "transcript.raw.json", raw)
                cleanup()
                diarized = raw
                turns = raw.get("turns", raw.get("segments", []))
                audit = {"corrections": [], "meta": {"skipped": job.backend}}
                if job.backend == "whisper":
                    self._update(job_id, stage="postprocessing")
                    turns, audit = process_turns(turns)
                labelled = add_speaker_labels(turns)
                formatted = build_formatted_text(labelled)
                if not formatted.strip():
                    raise RuntimeError("转写没有生成可用文字")
                final = {
                    **diarized,
                    "turns": labelled,
                    "formatted_text": formatted,
                    "text": "".join(t.get("text", "") for t in labelled),
                    "backend": job.backend,
                    "schema_version": 2,
                    "postprocess": audit.get("meta", {}),
                }
                _write_json(result_dir / "transcript.json", final)
                (result_dir / "transcript.txt").write_text(formatted, encoding="utf-8")
                _write_json(result_dir / "corrections.json", audit)
                _write_json(
                    result_dir / "meta.json",
                    {
                        "job_id": job_id,
                        "filename": job.filename,
                        "backend": job.backend,
                        "language": final.get("language"),
                        "turns": len(labelled),
                        "characters": len(final["text"]),
                        "corrections": len(audit.get("corrections", [])),
                    },
                )
                self._analyze(job_id)
        except Exception as exc:
            cleanup()
            self._update(job_id, status="error", stage="error", error=_safe_error(exc))
        finally:
            cleanup()
            with self._lock:
                self._upload_sources.pop(job_id, None)

    def _analyze(self, job_id: str) -> None:
        job = self._jobs[job_id]
        self._update(
            job_id,
            status="running",
            stage="analyzing",
            operation="analyze",
            done=None,
            total=None,
        )
        analyze_markdown(
            result_directory(job), job.episode, on_progress=self._progress(job_id)
        )
        self._update(
            job_id,
            status="done",
            stage="done",
            error=None,
            result_url=f"/jobs/{job_id}",
            done=None,
            total=None,
        )

        self._export_to_obsidian(self._jobs[job_id])

    def _export_to_obsidian(self, job: Job) -> None:
        export_job(asdict(job), result_directory(job), JOBS_ROOT.parent / "obsidian-export.json")

    def _run_analysis(self, job_id: str) -> None:
        try:
            with processing_lock(JOBS_ROOT.parent / ".pipeline.lock"):
                self._analyze(job_id)
        except Exception as exc:
            self._update(job_id, status="error", stage="error", error=_safe_error(exc))


def _configured_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 true/false")


def _configured_float(name: str, default: float) -> float:
    import math

    value = float(os.getenv(name, str(default)))
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} 必须是非负数字")
    return value


def _configured_speaker_count() -> int | None:
    value = os.getenv("WHISPER_NUM_SPEAKERS", "").strip()
    if not value:
        return None
    try:
        count = int(value)
        if count < 1:
            raise ValueError()
        return count
    except ValueError as exc:
        raise ValueError("WHISPER_NUM_SPEAKERS 必须是正整数") from exc


manager = JobManager()


def save_upload(stream, filename: str) -> tuple[str, Path]:
    ensure_roots()
    safe_name = Path(filename or "audio").name
    suffix = Path(safe_name).suffix[:12] or ".audio"
    directory = Path(tempfile.mkdtemp(prefix="job-", dir=UPLOAD_ROOT))
    target = directory / f"source{suffix}"
    try:
        with target.open("wb") as output:
            shutil.copyfileobj(stream, output)
        if not target.stat().st_size:
            raise ValueError("音频文件为空")
        return safe_name, target
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def ensure_roots() -> None:
    # Called per upload: MUST NOT delete other queued/in-flight upload directories.
    JOBS_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)


def cleanup_interrupted_uploads() -> None:
    """Only at exclusive service startup, before any new work is submitted."""
    ensure_roots()
    for child in UPLOAD_ROOT.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
