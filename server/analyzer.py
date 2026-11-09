"""Generate skill-based podcast artifacts with Kimi, Codex or Gemini."""

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
from server import analysis_fallback
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
# Second pass: lieflat-less-ai-tone rewrites article.md only, always on agy/Gemini.
DEAI_PROMPT_PATH = ROOT / "prompts/de-ai-tone.md"
DEAI_SKILL_PATH = ROOT / "skills/lieflat-less-ai-tone"
DEAI_DOC_FILES = ("SKILL.md", "DETECT.md", "references/semantic-criteria.md")
DEAI_SCRIPT_FILES = ("scripts/detect.py", "scripts/report.py")
DEAI_DEFAULT_MODEL = "gemini-4-argon-medium"
DEAI_HAN_RANGE = (0.95, 1.01)
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
    primary = config.backend
    route = "primary"
    fallback_enabled = config.backend == "pi" and config.fallback_backend == "codex"
    if fallback_enabled and analysis_fallback.cooldown_status()["active"]:
        config = analysis_fallback.codex_config(config)
        route = "cooldown"
    attempt = 1
    while True:
        diagnostic = {
            "version": 3, "stage": "generate", "attempt": attempt,
            "backend": config.backend, "model": config.model, "thinking": config.thinking,
            "primary_backend": primary, "route": route,
            "idle_timeout_seconds": config.idle_timeout, "reminder_interval_seconds": config.reminder_interval,
            "started_at": datetime.now(UTC).isoformat(),
            "outcome": "running", "exit_code": None, "timed_out": False,
            "error_category": None, "retryable": False, "validated": False,
        }
        record = diagnostics / f"{uuid.uuid4().hex}.json"
        _json_write(record, diagnostic)
        started = time.monotonic()
        failure = None
        invocation_failure = None
        try:
            # Never reuse partial edits from a failed attempt.
            # Codex's writable workspace must not inherit the enclosing repository root.
            with tempfile.TemporaryDirectory(prefix="podcast-generate-",
                                             dir=None if config.backend == "codex" else run) as temp:
                work = Path(temp).resolve()
                for name, data in inputs.items():
                    target = work / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                try:
                    metadata = invoke(work, prompt, config, diagnostic,
                                      executable if config.backend == primary else None,
                                      on_update=lambda: _json_write(record, diagnostic))
                except AnalysisError as exc:
                    invocation_failure = exc
                    raise
                finally:
                    if _checked_bytes(result_dir / "transcript.txt") != inputs["transcript.txt"]:
                        raise AnalysisError("原始 transcript.txt 被修改，拒绝发布", category="input_modified")
                    for name, data in inputs.items():
                        if _checked_bytes(work / name) != data:
                            raise AnalysisError(f"模型修改了输入 {name}，拒绝发布", category="input_modified")
                _validate_content(work, transcript, episode)
                diagnostic["validated"] = True
                _style_report(work, run)
                metadata.update(primary_backend=primary, route=route)
                saved = _save_checkpoint(run, "generate", work, ARTIFACT_NAMES, metadata)
                diagnostic["outcome"] = "success"
                return saved
        except AnalysisError as exc:
            failure = exc
            diagnostic.update(outcome="error", error_category=exc.category, retryable=exc.retryable)
            if fallback_enabled and config.backend == "pi" and exc is invocation_failure:
                analysis_fallback.start_cooldown()
                diagnostic["fallback_to"] = "codex"
                diagnostic["cooldown_until"] = analysis_fallback.cooldown_status()["cooldown_until"]
        except Exception:
            diagnostic.update(outcome="error", error_category="local_error")
            raise
        finally:
            diagnostic.update(finished_at=datetime.now(UTC).isoformat(),
                              elapsed_seconds=round(time.monotonic() - started, 3))
            _json_write(record, diagnostic)
        if diagnostic.get("fallback_to") == "codex":
            config = analysis_fallback.codex_config(config)
            route = "request_failed"
            attempt = 1
            continue
        if not failure.retryable or attempt >= config.attempts:
            raise AnalysisError(
                f"{config.backend} 生成失败：{failure}", category=failure.category,
                retryable=failure.retryable,
            ) from failure
        time.sleep(RETRY_DELAY_SECONDS)
        attempt += 1


def deai_config(base: AnalysisConfig) -> AnalysisConfig | None:
    switch = os.getenv("PODCAST_DEAI", "on").strip().lower()
    if switch not in {"on", "off"}:
        raise AnalysisError("PODCAST_DEAI 必须是 on 或 off", category="config")
    if switch == "off":
        return None
    model = os.getenv("PODCAST_DEAI_MODEL", DEAI_DEFAULT_MODEL).strip()
    if not model.startswith("gemini-"):
        raise AnalysisError("PODCAST_DEAI_MODEL 必须选择 Gemini 模型", category="config")
    return AnalysisConfig("agy", model, None, base.idle_timeout, base.attempts, 0, None)


def _run_script(tools: Path, args: list[str]) -> bytes:
    try:
        result = subprocess.run([sys.executable, *args], cwd=tools, capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AnalysisError("去 AI 味检测脚本无法运行", category="deai_script") from exc
    if result.returncode != 0:
        raise AnalysisError("去 AI 味检测脚本失败", category="deai_script")
    return result.stdout


_HAN = re.compile(r"[一-鿿]")
_QUOTE = re.compile(r"「[^」]+」|“[^”]+”")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _deai_guard(before: str, after: str) -> None:
    """Reject rewrites that touch facts, structure or quotes; the pass may only polish wording."""
    problems = []
    headings = lambda text: [line for line in text.splitlines() if line.startswith("#")]
    if headings(before) != headings(after):
        problems.append("标题被修改")
    if re.findall(r"\]\([^)]+\)", before) != re.findall(r"\]\([^)]+\)", after):
        problems.append("链接被修改")
    if sorted(_NUMBER.findall(before)) != sorted(_NUMBER.findall(after)):
        problems.append("数字被修改")
    if any(quote not in after for quote in _QUOTE.findall(before)):
        problems.append("引语被修改")
    if after.count("——") > before.count("——"):
        problems.append("引入破折号")
    ratio = len(_HAN.findall(after)) / max(1, len(_HAN.findall(before)))
    if not DEAI_HAN_RANGE[0] <= ratio <= DEAI_HAN_RANGE[1]:
        problems.append(f"字数变化过大（{ratio:.3f}）")
    if problems:
        raise AnalysisError("去 AI 味改写未通过校验；" + "；".join(problems), category="deai_guard")


def _deai_attempt(run: Path, generated: Path, inputs: dict[str, bytes], deai_inputs: dict[str, bytes],
                  prompt: str, config: AnalysisConfig, diagnostic: dict, record: Path) -> Path:
    transcript = inputs["transcript.txt"].decode("utf-8")
    episode = inputs["episode.md"].decode("utf-8")
    before = _checked_bytes(generated / "article.md")
    with tempfile.TemporaryDirectory(prefix="podcast-deai-", dir=run) as temp:
        root = Path(temp).resolve()
        tools, work, out = root / "tools", root / "work", root / "out"
        files = {f".skills/lieflat-less-ai-tone/{name}": deai_inputs[name] for name in DEAI_DOC_FILES}
        files[".skills/style-rules.md"] = inputs[".skills/podcast-to-article/references/style-rules.md"]
        files["transcript.txt"] = inputs["transcript.txt"]
        for folder, mapping in ((tools, {name: deai_inputs[name] for name in DEAI_SCRIPT_FILES}),
                                (work, {**files, "article.md": before})):
            for name, data in mapping.items():
                target = folder / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        out.mkdir()
        detect = str(tools / "scripts/detect.py")
        article = str(work / "article.md")
        (out / "before.json").write_bytes(_run_script(tools, [detect, article, "--json"]))
        files["detect-report.txt"] = _run_script(tools, [detect, article, "--max-hits", "50"])
        (work / "detect-report.txt").write_bytes(files["detect-report.txt"])
        _run_script(tools, [detect, article, "--candidates", "--out", str(work / "candidates.json")])
        files["candidates.json"] = _checked_bytes(work / "candidates.json")
        metadata = invoke(work, prompt, config, diagnostic, on_update=lambda: _json_write(record, diagnostic))
        for name, data in files.items():
            if _checked_bytes(work / name) != data:
                raise AnalysisError(f"模型修改了输入 {name}，拒绝发布", category="input_modified")
        after = _checked_bytes(work / "article.md")
        _deai_guard(before.decode("utf-8"), after.decode("utf-8"))
        staged = out / "artifacts"
        staged.mkdir()
        for name in ARTIFACT_NAMES:
            (staged / name).write_bytes(after if name == "article.md" else _checked_bytes(generated / name))
        _validate_content(staged, transcript, episode)
        diagnostic["validated"] = True
        # Reports are best effort: a broken report never blocks the validated rewrite.
        reports = _directory(run / "deai-report")
        try:
            (out / "after.json").write_bytes(_run_script(tools, [detect, article, "--json"]))
            original = out / "original.md"
            original.write_bytes(before)
            args = [str(tools / "scripts/report.py"), str(original), article,
                    str(out / "before.json"), str(out / "after.json"), "--out", str(out / "report.md")]
            labels = work / "semantic-labels.json"
            if labels.is_file() and not labels.is_symlink():
                json.loads(labels.read_bytes())
                args += ["--semantic", str(labels)]
            _run_script(tools, args)
            _atomic_write(reports / "去AI味报告.md", _checked_bytes(out / "report.md"))
        except (AnalysisError, ValueError):
            pass
        for name in ("changes.md", "semantic-labels.json"):
            path = work / name
            if path.is_file() and not path.is_symlink() and path.stat().st_size <= MAX_ARTIFACT_BYTES:
                _atomic_write(reports / name, path.read_bytes())
        metadata["outcome"] = "rewritten" if after != before else "unchanged"
        return _save_checkpoint(run, "deai", staged, ARTIFACT_NAMES, metadata)


def _deai(run: Path, generated: Path, inputs: dict[str, bytes], deai_inputs: dict[str, bytes],
          prompt: str, config: AnalysisConfig) -> Path:
    """Run the de-AI pass; on any failure publish the generated artifacts unchanged."""
    diagnostics = _directory(run / "diagnostics")
    attempt = 1
    while True:
        diagnostic = {
            "version": 3, "stage": "deai", "attempt": attempt, "backend": config.backend,
            "model": config.model, "thinking": None, "idle_timeout_seconds": config.idle_timeout,
            "started_at": datetime.now(UTC).isoformat(), "outcome": "running", "exit_code": None,
            "timed_out": False, "error_category": None, "retryable": False, "validated": False,
        }
        record = diagnostics / f"{uuid.uuid4().hex}.json"
        _json_write(record, diagnostic)
        started = time.monotonic()
        failure: AnalysisError
        try:
            saved = _deai_attempt(run, generated, inputs, deai_inputs, prompt, config, diagnostic, record)
            diagnostic["outcome"] = "success"
            return saved
        except AnalysisError as exc:
            failure = exc
            diagnostic.update(outcome="error", error_category=exc.category, retryable=exc.retryable)
        except Exception as exc:  # optional polish must never block publication
            failure = AnalysisError(f"去 AI 味本地错误：{type(exc).__name__}", category="local_error")
            diagnostic.update(outcome="error", error_category="local_error", error_type=type(exc).__name__)
        finally:
            diagnostic.update(finished_at=datetime.now(UTC).isoformat(),
                              elapsed_seconds=round(time.monotonic() - started, 3))
            _json_write(record, diagnostic)
        if failure.retryable and attempt < config.attempts:
            time.sleep(RETRY_DELAY_SECONDS)
            attempt += 1
            continue
        return _save_checkpoint(run, "deai", generated, ARTIFACT_NAMES, {
            "backend": config.backend, "model": config.model,
            "outcome": "fallback", "error_category": failure.category})


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
    deai = deai_config(config)
    deai_prompt = ""
    deai_inputs: dict[str, bytes] = {}
    if deai is not None:
        deai_prompt = _read_prompt(DEAI_PROMPT_PATH)
        deai_inputs = {name: _checked_bytes(DEAI_SKILL_PATH / name)
                       for name in (*DEAI_DOC_FILES, *DEAI_SCRIPT_FILES)}
    # v3 binds checkpoints to the primary model and its fallback policy; v4 adds the de-AI pass.
    key = _digest(json.dumps({
        "version": 4, "backend": config.backend, "model": config.model,
        "fallback_backend": config.fallback_backend,
        "thinking": config.thinking, "prompt": prompt,
        "inputs": {name: _digest(data) for name, data in inputs.items()},
        "deai": None if deai is None else {
            "model": deai.model, "prompt": deai_prompt,
            "inputs": {name: _digest(data) for name, data in deai_inputs.items()}},
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
    if deai is not None:
        saved = _checkpoint(run, "deai", ARTIFACT_NAMES) or _deai(
            run, saved, inputs, deai_inputs, deai_prompt, deai)
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
