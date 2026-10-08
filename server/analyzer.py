"""Generate skill-based podcast artifacts with pi/K3 or agy/Gemini."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from server.analysis_runner import AnalysisConfig, AnalysisError, invoke
from server.podcast_feed import normalize_episode_url
from server.processing_lock import processing_lock

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts/analysis.md"
SKILL_PATH = ROOT / "skills/podcast-to-article"
SKILL_FILES = ("SKILL.md", "references/style-rules.md", "references/example.md",
               "scripts/prep_transcript.py", "scripts/check_style.py")
ARTIFACT_NAMES = ("article.md", "notes.md", "mindmap.md")
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024
RETRY_DELAY_SECONDS = 10.0
ProgressCallback = Callable[[str, int | None, int | None], None]


def _single_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def _people(value: Any) -> str:
    if isinstance(value, str):
        return _single_line(value)
    if not isinstance(value, (list, tuple)):
        return ""
    names: list[str] = []
    for item in value:
        if isinstance(item, Mapping):
            name = item.get("name") or item.get("title")
        else:
            name = item
        if cleaned := _single_line(name):
            names.append(cleaned)
    return "、".join(names)


def _duration(value: Any) -> str:
    try:
        total = max(0, int(float(value)))
    except (TypeError, ValueError):
        return _single_line(value)
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _render_episode_markdown(episode: Mapping[str, Any]) -> str:
    title = _single_line(episode.get("title")) or "未命名单集"
    lines = [f"# {title}"]
    fields = (
        ("播客", _single_line(episode.get("podcast_title"))),
        ("发布于", _single_line(episode.get("published_at"))),
        ("时长", _duration(episode.get("duration")) if episode.get("duration") else ""),
        (
            "主播",
            _people(
                episode.get("hosts") or episode.get("host") or episode.get("author")
            ),
        ),
        ("嘉宾", _people(episode.get("guests") or episode.get("guest"))),
    )
    for label, value in fields:
        if value:
            lines.append(f"- {label}：{value}")

    source_url = _single_line(episode.get("url") or episode.get("episode_url"))
    if source_url:
        try:
            source_url, _ = normalize_episode_url(source_url)
        except ValueError:
            source_url = ""
    if source_url:
        lines.append(f"- 节目链接：[在小宇宙查看原节目]({source_url})")

    description = str(episode.get("description") or "").strip()
    if description:
        lines.extend(["", "## 节目简介", "", description])
    return "\n".join(lines).rstrip() + "\n"


def _atomic_write(path: Path, data: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_episode_markdown(path: Path, episode: Mapping[str, Any]) -> None:
    """Write human-readable episode metadata without exposing the audio URL."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, _render_episode_markdown(episode).encode("utf-8"))


def _regular_nonempty(
    path: Path, label: str, *, max_bytes: int | None = None
) -> os.stat_result:
    try:
        status = path.lstat()
    except FileNotFoundError as exc:
        raise AnalysisError(f"缺少{label}: {path.name}") from exc
    if not stat.S_ISREG(status.st_mode) or path.is_symlink():
        raise AnalysisError(f"{label}必须是普通文件且不能是符号链接: {path.name}")
    if status.st_size <= 0:
        raise AnalysisError(f"{label}为空: {path.name}")
    if max_bytes is not None and status.st_size > max_bytes:
        raise AnalysisError(f"{label}过大: {path.name}")
    return status


def _emit(callback: ProgressCallback | None, stage: str) -> None:
    if callback is not None:
        callback(stage, None, None)


def _copy_episode_input(
    result_dir: Path, staging_dir: Path, episode: Mapping[str, Any] | None
) -> bool:
    destination = staging_dir / "episode.md"
    if episode is not None:
        destination.write_text(_render_episode_markdown(episode), encoding="utf-8")
        return True

    source = result_dir / "episode.md"
    if source.exists() or source.is_symlink():
        _regular_nonempty(source, "节目元数据")
        shutil.copyfile(source, destination)
        return False

    destination.write_text("# 未命名单集\n", encoding="utf-8")
    return True


def _publish(result_dir: Path, staging_dir: Path, *, publish_episode: bool) -> None:
    names = list(ARTIFACT_NAMES)
    if publish_episode:
        names.append("episode.md")

    pending: list[tuple[Path, Path]] = []
    try:
        for name in names:
            source = staging_dir / name
            _regular_nonempty(source, "分析产物", max_bytes=MAX_ARTIFACT_BYTES)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{name}.", dir=result_dir
            )
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "wb") as output:
                output.write(source.read_bytes())
                output.flush()
                os.fsync(output.fileno())
            pending.append((temporary_path, result_dir / name))
        for temporary_path, destination in pending:
            os.replace(temporary_path, destination)
    finally:
        for temporary_path, _ in pending:
            temporary_path.unlink(missing_ok=True)


def _read_prompt(path: Path) -> str:
    try:
        prompt = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AnalysisError(f"无法读取分析提示词: {path.name}") from exc
    if not prompt:
        raise AnalysisError(f"分析提示词为空: {path.name}")
    return prompt


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_write(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def _directory(path: Path) -> Path:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise AnalysisError("分析检查点目录不安全")
    path.mkdir(exist_ok=True)
    return path


def _checked_bytes(path: Path) -> bytes:
    _regular_nonempty(path, "分析文件", max_bytes=MAX_ARTIFACT_BYTES)
    return path.read_bytes()


def _mechanical_checks(folder: Path, transcript: str, episode: str) -> dict:
    times = set(re.findall(r"^\[(\d{2}:\d{2}:\d{2})", transcript, re.M))
    # Only the generated metadata field is authoritative, not links in show notes.
    links = re.findall(r"^- 节目链接：.*?\]\((https://[^)]+)\)", episode, re.M)
    report = {}
    for name in ARTIFACT_NAMES:
        text = _checked_bytes(folder / name).decode("utf-8")
        report[name] = {
            "invalid_timestamps": sorted(set(re.findall(r"\b\d{2}:\d{2}:\d{2}\b", text)) - times),
            "missing_source_link": name != "mindmap.md" and any(url not in text for url in links),
            "missing_edit_notice": name == "article.md" and "非逐字原文" not in text,
            "invalid_headings": name in {"notes.md", "mindmap.md"} and bool(re.search(r"^#{3,}\s", text, re.M)),
            "timestamp_as_title": name == "notes.md" and bool(
                re.search(r"^(?:#{1,6}|[-*])\s*\[?\d{2}:\d{2}:\d{2}", text, re.M)
            ),
        }
    return report


def _validate_content(folder: Path, transcript: str, episode: str) -> None:
    report = _mechanical_checks(folder, transcript, episode)
    failures = [f"{name}: {key}" for name, checks in report.items() for key, value in checks.items() if value]
    if failures:
        raise AnalysisError("分析产物检查未通过；" + "；".join(failures))


def _checkpoint(run: Path, stage: str, names: tuple[str, ...]) -> Path | None:
    marker = run / f"{stage}.json"
    if not marker.exists():
        return None
    try:
        data = json.loads(_checked_bytes(marker))
        folder = run / stage
        if folder.is_symlink() or not folder.is_dir():
            raise ValueError("unsafe checkpoint")
        for name in names:
            if _digest(_checked_bytes(folder / name)) != data["hashes"][name]:
                raise ValueError("changed checkpoint")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise AnalysisError("分析检查点损坏，拒绝复用") from exc
    return folder


def _save_checkpoint(run: Path, stage: str, folder: Path, names: tuple[str, ...], metadata: dict) -> Path:
    destination = _directory(run / stage)
    hashes = {}
    for name in names:
        data = _checked_bytes(folder / name)
        _atomic_write(destination / name, data)
        hashes[name] = _digest(data)
    _json_write(run / f"{stage}.json", {"hashes": hashes, **metadata})
    return destination


def _style_report(work: Path, run: Path) -> None:
    # Run the reviewed upstream check ourselves; the model only needs file tools.
    try:
        result = subprocess.run(
            [sys.executable, str(work / ".skills/podcast-to-article/scripts/check_style.py"),
             str(work / "article.md"), "--quiet"], capture_output=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if result.returncode == 0:
        _atomic_write(run / "style-report.txt", result.stdout)


def _generate(run: Path, result_dir: Path, inputs: dict[str, bytes], prompt: str,
              config: AnalysisConfig, executable: str | Path | None) -> Path:
    transcript = inputs["transcript.txt"].decode("utf-8")
    episode = inputs["episode.md"].decode("utf-8")
    diagnostics = _directory(run / "diagnostics")
    for attempt in range(1, config.attempts + 1):
        diagnostic = {
            "version": 1, "stage": "generate", "attempt": attempt,
            "backend": config.backend, "model": config.model, "thinking": config.thinking,
            "timeout_seconds": config.timeout, "started_at": datetime.now(UTC).isoformat(),
            "outcome": "running", "exit_code": None, "timed_out": False,
            "error_category": None, "retryable": False, "validated": False,
        }
        record = diagnostics / f"{uuid.uuid4().hex}.json"
        _json_write(record, diagnostic)
        started = time.monotonic()
        failure = None
        try:
            # Never reuse partial edits from a failed attempt.
            with tempfile.TemporaryDirectory(prefix=".generate-", dir=run) as temp:
                work = Path(temp)
                for name, data in inputs.items():
                    target = work / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                try:
                    metadata = invoke(work, prompt, config, diagnostic, executable)
                finally:
                    if _checked_bytes(result_dir / "transcript.txt") != inputs["transcript.txt"]:
                        raise AnalysisError("原始 transcript.txt 被修改，拒绝发布", category="input_modified")
                    for name, data in inputs.items():
                        if _checked_bytes(work / name) != data:
                            raise AnalysisError(f"模型修改了输入 {name}，拒绝发布", category="input_modified")
                _validate_content(work, transcript, episode)
                diagnostic["validated"] = True
                _style_report(work, run)
                saved = _save_checkpoint(run, "generate", work, ARTIFACT_NAMES, metadata)
                diagnostic["outcome"] = "success"
                return saved
        except AnalysisError as exc:
            failure = exc
            diagnostic.update(outcome="error", error_category=exc.category, retryable=exc.retryable)
        except Exception:
            diagnostic.update(outcome="error", error_category="local_error")
            raise
        finally:
            diagnostic.update(finished_at=datetime.now(UTC).isoformat(),
                              elapsed_seconds=round(time.monotonic() - started, 3))
            _json_write(record, diagnostic)
        if not failure.retryable or attempt >= config.attempts:
            raise AnalysisError(
                f"{config.backend} 生成失败：{failure}", category=failure.category,
                retryable=failure.retryable,
            ) from failure
        time.sleep(RETRY_DELAY_SECONDS)
    raise AssertionError("unreachable")


def analyze(result_dir: Path, episode: dict[str, Any] | None = None, *,
            on_progress: ProgressCallback | None = None,
            executable: str | Path | None = None) -> None:
    config = AnalysisConfig.from_env()
    try:
        result_dir = Path(result_dir).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise AnalysisError("结果目录不存在") from exc
    if not result_dir.is_dir():
        raise AnalysisError("结果路径不是目录")
    cache = _directory(result_dir / ".analysis")
    with processing_lock(cache / ".lock"):
        _analyze(result_dir, cache, episode, config, on_progress, executable)


def _analyze(result_dir: Path, cache: Path, episode: dict | None, config: AnalysisConfig,
             on_progress: ProgressCallback | None, executable: str | Path | None) -> None:
    original = _checked_bytes(result_dir / "transcript.txt")
    prompt = _read_prompt(PROMPT_PATH)
    with tempfile.TemporaryDirectory(prefix=".episode-", dir=cache) as temp:
        publish_episode = _copy_episode_input(result_dir, Path(temp), episode)
        episode_bytes = _checked_bytes(Path(temp) / "episode.md")
    inputs = {"transcript.txt": original, "episode.md": episode_bytes}
    for name in SKILL_FILES:
        inputs[f".skills/podcast-to-article/{name}"] = _checked_bytes(SKILL_PATH / name)
    # v2 separates skill-based outputs from the old Gemini audit pipeline.
    key = _digest(json.dumps({
        "version": 2, "backend": config.backend, "model": config.model,
        "thinking": config.thinking, "prompt": prompt,
        "inputs": {name: _digest(data) for name, data in inputs.items()},
    }, sort_keys=True).encode())
    state_path = cache / "state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(_checked_bytes(state_path))
            if not isinstance(state, dict):
                raise ValueError()
        except (ValueError, OSError) as exc:
            raise AnalysisError("分析状态损坏，拒绝覆盖") from exc
    if state.get("key") != key or state.get("complete"):
        state = {"key": key, "run": uuid.uuid4().hex, "complete": False}
        _json_write(state_path, state)
    if not re.fullmatch(r"[a-f0-9]{32}", str(state.get("run", ""))):
        raise AnalysisError("分析检查点路径无效")
    run = _directory(cache / state["run"])
    _emit(on_progress, "analyzing")
    saved = _checkpoint(run, "generate", ARTIFACT_NAMES)
    if saved is None:
        saved = _generate(run, result_dir, inputs, prompt, config, executable)
    _validate_content(saved, original.decode("utf-8"), episode_bytes.decode("utf-8"))
    backup = _directory(run / "before-publication")
    for name in (*ARTIFACT_NAMES, "episode.md"):
        path = result_dir / name
        if (path.exists() or path.is_symlink()) and not (backup / name).exists():
            _atomic_write(backup / name, _checked_bytes(path))
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=run) as temp:
        work = Path(temp)
        for name in ARTIFACT_NAMES:
            (work / name).write_bytes(_checked_bytes(saved / name))
        (work / "episode.md").write_bytes(episode_bytes)
        if _checked_bytes(result_dir / "transcript.txt") != original:
            raise AnalysisError("原始 transcript.txt 被修改，拒绝发布", category="input_modified")
        _publish(result_dir, work, publish_episode=publish_episode)
    state["complete"] = True
    _json_write(state_path, state)
    _emit(on_progress, "done")
