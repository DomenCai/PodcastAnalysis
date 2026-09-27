"""Run ``agy`` against one episode transcript and publish Markdown artifacts."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import tempfile
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from server.podcast_feed import normalize_episode_url
from server.processing_lock import processing_lock

ROOT = Path(__file__).resolve().parents[1]
PROMPT_PATH = ROOT / "prompts" / "analysis.md"
AUDIT_PROMPT_PATH = ROOT / "prompts" / "audit.md"
STYLE_PROMPT_PATH = ROOT / "prompts" / "style.md"
DEFAULT_MODEL = "gemini-3.1-pro-high"
STYLE_MODEL = "claude-opus-4-6-thinking"
ARTIFACT_NAMES = ("article.md", "notes.md", "mindmap.md")
DEFAULT_TIMEOUT_SECONDS = 600.0
MAX_ARTIFACT_BYTES = 20 * 1024 * 1024

ProgressCallback = Callable[[str, int | None, int | None], None]


class AgyAnalysisError(RuntimeError):
    """The agy process failed or produced unsafe/incomplete artifacts."""


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
        raise AgyAnalysisError(f"缺少{label}: {path.name}") from exc
    if not stat.S_ISREG(status.st_mode) or path.is_symlink():
        raise AgyAnalysisError(f"{label}必须是普通文件且不能是符号链接: {path.name}")
    if status.st_size <= 0:
        raise AgyAnalysisError(f"{label}为空: {path.name}")
    if max_bytes is not None and status.st_size > max_bytes:
        raise AgyAnalysisError(f"{label}过大: {path.name}")
    return status


def _timeout_seconds() -> float:
    raw = os.environ.get("WHISPER_AGY_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
    try:
        value = float(raw)
    except ValueError as exc:
        raise AgyAnalysisError("WHISPER_AGY_TIMEOUT_SECONDS 必须是数字") from exc
    if not 0 < value <= 86_400:
        raise AgyAnalysisError("WHISPER_AGY_TIMEOUT_SECONDS 必须在 0 到 86400 秒之间")
    return value


def _terminate_process_group(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # The group can still contain grandchildren after its leader exits cleanly.
    # Always address the original process group once more with SIGKILL.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _invoke_agy(
    staging_dir: Path, prompt: str, executable: str | Path, model: str
) -> dict:
    timeout = _timeout_seconds()
    argv = [
        os.fspath(executable),
        "--model",
        model,
        "-p",
        prompt,
        "--add-dir",
        os.fspath(staging_dir),
        "--mode",
        "accept-edits",
        "--sandbox",
        "--output-format",
        "json",
        "--print-timeout",
        f"{timeout:g}s",
    ]
    with tempfile.TemporaryFile(mode="w+b") as log_file:
        try:
            process = subprocess.Popen(
                argv,
                cwd=staging_dir,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except (FileNotFoundError, OSError) as exc:
            raise AgyAnalysisError(f"无法启动 agy: {exc}") from exc
        try:
            return_code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _terminate_process_group(process)
            raise AgyAnalysisError(f"agy 分析超时（{timeout:g} 秒）") from exc
        log_file.seek(0)
        # Read the tail as well: agy can print diagnostics before its JSON result.
        size = log_file.seek(0, os.SEEK_END)
        log_file.seek(max(0, size - 1024 * 1024))
        diagnostic = log_file.read().decode("utf-8", errors="replace")
        if any(marker in diagnostic for marker in ('command" permission', "command permission", "auto-denied")):
            raise AgyAnalysisError(
                "agy 尝试使用无人值守模式不允许的命令工具；请仅重新分析，或检查分析提示词的文件工具约束"
            )
        if "jetski: no output produced" in diagnostic:
            raise AgyAnalysisError("agy 没有生成输出；请检查运行日志与工具权限后仅重新分析")
        if return_code != 0:
            if "not eligible for Antigravity" in diagnostic:
                raise AgyAnalysisError(
                    "agy 账号未通过 Antigravity 资格验证；请在 agy 中完成账号验证后仅重新分析"
                )
            # Tool output can contain transcript text or credentials echoed by a
            # child process. Keep the temporary log out of public/job errors.
            raise AgyAnalysisError(f"agy 分析失败（退出码 {return_code}）")
        result = None
        for line in reversed(diagnostic.splitlines()):
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if isinstance(item, dict) and "status" in item:
                result = item
                break
        if result and result.get("denied_actions"):
            raise AgyAnalysisError("agy 工具调用被拒绝，阶段未完成；请重试分析")
        if not result or result.get("status") != "SUCCESS":
            raise AgyAnalysisError("agy 未返回成功结果，阶段未完成；请重试分析")
        # Do not persist response/tool text, which can echo source text or secrets.
        usage = result.get("usage")
        return {
            "model": model,
            "usage": {
                key: value for key, value in (usage.items() if isinstance(usage, dict) else [])
                if key.endswith("tokens") and type(value) in (int, float)
            },
        }


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
            _regular_nonempty(source, "agy 产物", max_bytes=MAX_ARTIFACT_BYTES)
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
        raise AgyAnalysisError(f"无法读取分析提示词: {path.name}") from exc
    if not prompt:
        raise AgyAnalysisError(f"分析提示词为空: {path.name}")
    return prompt


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_write(path: Path, value: Any) -> None:
    _atomic_write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode())


def _directory(path: Path) -> Path:
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise AgyAnalysisError("分析检查点目录不安全")
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
        raise AgyAnalysisError("核稿产物检查未通过，已保留上一阶段；" + "；".join(failures))


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
        raise AgyAnalysisError("分析检查点损坏，拒绝复用") from exc
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


def _voice_sample(transcript: str) -> str:
    lines = [re.sub(r"^\[[^\]]+\]\s*", "", line) for line in transcript.splitlines() if line.strip()]
    if not lines:
        return "未提供可用口吻样本。"
    indexes = sorted({int((len(lines) - 1) * fraction) for fraction in (0, .25, .5, .75)})
    return "\n\n".join(lines[i][:300] for i in indexes)


def _apply_style_edits(article: str, raw: bytes) -> str:
    try:
        payload = json.loads(raw)
        edits = payload["edits"]
        if not isinstance(edits, list) or len(edits) > 8:
            raise ValueError()
        spans = []
        for edit in edits:
            before, after = edit["before"], edit["after"]
            if (
                not isinstance(before, str) or not isinstance(after, str)
                or not before or len(before) > 600 or len(after) > 900
            ):
                raise ValueError()
            if article.count(before) != 1:
                raise ValueError()
            start = article.index(before)
            end = start + len(before)
            if any(start < stop and end > begin for begin, stop, _ in spans):
                raise ValueError()
            # Conservative mechanical guard; semantic equivalence still needs review.
            protected = (
                r"https?://[^\s)]+|\d+(?:[.:/%～~-]\d+)*|[一二三四五六七八九十百千万两]+"
                r"|「[^」]*」|[不没未无]|可能|也许|大概|对我来说|据说|建议|假设"
                r"|已经|仍然|因为|所以|如果|但是"
            )
            if re.findall(protected, before) != re.findall(protected, after):
                raise ValueError()
            line_start = article.rfind("\n", 0, start) + 1
            notice = article.find("非逐字原文")
            if (
                article[line_start:].startswith("#")
                or (notice >= 0 and start < notice + len("非逐字原文"))
            ):
                raise ValueError()
            spans.append((start, end, after))
        if sum(end - start for start, end, _ in spans) > max(200, len(article) * .25):
            raise ValueError()
        for start, end, after in sorted(spans, reverse=True):
            article = article[:start] + after + article[end:]
        return article
    except (ValueError, KeyError, TypeError) as exc:
        raise AgyAnalysisError("Opus 局部修改未通过检查，Gemini 成稿已保留；请重试或关闭润色") from exc


def analyze(
    result_dir: Path,
    episode: dict[str, Any] | None = None,
    *,
    on_progress: ProgressCallback | None = None,
    executable: str | Path = "agy",
) -> None:
    """Generate and audit with Gemini; optionally apply small Opus style edits.

    Failed attempts never publish. Completed stages survive retry. Workspace and
    add-dir narrow context, but are not a filesystem security boundary.
    """
    try:
        result_dir = Path(result_dir).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise AgyAnalysisError("结果目录不存在") from exc
    if not result_dir.is_dir():
        raise AgyAnalysisError("结果路径不是目录")
    cache = _directory(result_dir / ".analysis")
    with processing_lock(cache / ".lock"):
        _analyze_stages(result_dir, cache, episode, on_progress, executable)


def _analyze_stages(
    result_dir: Path, cache: Path, episode: dict[str, Any] | None,
    on_progress: ProgressCallback | None, executable: str | Path,
) -> None:
    transcript_path = result_dir / "transcript.txt"
    original = _checked_bytes(transcript_path)
    transcript = original.decode("utf-8")
    model = os.getenv("PODCAST_AGY_MODEL", DEFAULT_MODEL).strip()
    if not model.startswith("gemini-"):
        raise AgyAnalysisError("PODCAST_AGY_MODEL 必须选择 Gemini 模型")
    style_option = os.getenv("PODCAST_AGY_STYLE_EDIT", "false").strip().lower()
    if style_option not in {"true", "false", "1", "0"}:
        raise AgyAnalysisError("PODCAST_AGY_STYLE_EDIT 必须是 true/false")
    style_enabled = style_option in {"true", "1"}
    prompts = {"generate": _read_prompt(PROMPT_PATH), "audit": _read_prompt(AUDIT_PROMPT_PATH)}
    if style_enabled:
        prompts["style"] = _read_prompt(STYLE_PROMPT_PATH)
    with tempfile.TemporaryDirectory(prefix=".episode-", dir=cache) as temp:
        publish_episode = _copy_episode_input(result_dir, Path(temp), episode)
        episode_bytes = _checked_bytes(Path(temp) / "episode.md")
    episode_text = episode_bytes.decode("utf-8")
    # Upstream cache identity deliberately excludes optional style configuration.
    key = _digest(json.dumps({
        "version": 1,
        "transcript": _digest(original),
        "episode": _digest(episode_bytes),
        "model": model,
        "generate": prompts["generate"],
        "audit": prompts["audit"],
    }, sort_keys=True).encode())
    state_path = cache / "state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(_checked_bytes(state_path))
            if not isinstance(state, dict):
                raise ValueError()
        except (ValueError, OSError) as exc:
            raise AgyAnalysisError("分析状态损坏，拒绝覆盖") from exc
    if state.get("key") != key or state.get("complete"):
        state = {"key": key, "run": uuid.uuid4().hex, "complete": False}
        _json_write(state_path, state)
    if not re.fullmatch(r"[a-f0-9]{32}", str(state.get("run", ""))):
        raise AgyAnalysisError("分析检查点路径无效")
    run = _directory(cache / state["run"])
    _emit(on_progress, "analyzing")
    previous = None
    names = ARTIFACT_NAMES
    for stage in ("generate", "audit", *(("style",) if style_enabled else ())):
        stage_id = stage if stage != "style" else "style-" + _digest(prompts[stage].encode())[:16]
        outputs = names
        if stage == "audit":
            outputs += ("audit.md",)
        elif stage == "style":
            outputs += ("style-edits.json",)
        saved = _checkpoint(run, stage_id, outputs)
        if saved is not None:
            previous = saved
            continue
        try:
            with tempfile.TemporaryDirectory(prefix=f".{stage}-", dir=run) as temp:
                work = Path(temp)
                if stage == "style":
                    inputs = {
                        "article-draft.md": _checked_bytes(previous / "article.md"),
                        "voice-sample.txt": _voice_sample(transcript).encode(),
                    }
                else:
                    inputs = {"transcript.txt": original, "episode.md": episode_bytes}
                for name, data in inputs.items():
                    (work / name).write_bytes(data)
                if stage == "audit":
                    for name in names:
                        (work / name).write_bytes(_checked_bytes(previous / name))
                    _json_write(
                        work / "mechanical-checks.json",
                        _mechanical_checks(work, transcript, episode_text),
                    )
                    inputs["mechanical-checks.json"] = _checked_bytes(work / "mechanical-checks.json")
                try:
                    metadata = _invoke_agy(
                        work, prompts[stage], executable,
                        STYLE_MODEL if stage == "style" else model,
                    )
                finally:
                    if _checked_bytes(transcript_path) != original:
                        raise AgyAnalysisError("原始 transcript.txt 被修改，拒绝发布")
                    for name, data in inputs.items():
                        if _checked_bytes(work / name) != data:
                            raise AgyAnalysisError(f"agy 修改了 staging 输入 {name}，拒绝发布")
                if stage == "style":
                    article = _apply_style_edits(
                        inputs["article-draft.md"].decode(),
                        _checked_bytes(work / "style-edits.json"),
                    )
                    (work / "article.md").write_text(article, encoding="utf-8")
                    for name in ("notes.md", "mindmap.md"):
                        _atomic_write(work / name, _checked_bytes(previous / name))
                if stage != "generate":
                    _validate_content(work, transcript, episode_text)
                previous = _save_checkpoint(run, stage_id, work, outputs, metadata)
        except AgyAnalysisError as exc:
            label = {"generate": "Gemini 生成", "audit": "Gemini 核稿", "style": "Opus 润色"}[stage]
            raise AgyAnalysisError(f"{label}失败：{exc}") from exc
    _validate_content(previous, transcript, episode_text)
    # Keep old published artifacts independently of the staging lifetime.
    backup = _directory(run / "before-publication")
    for name in (*names, "episode.md"):
        path = result_dir / name
        if (path.exists() or path.is_symlink()) and not (backup / name).exists():
            _atomic_write(backup / name, _checked_bytes(path))
    with tempfile.TemporaryDirectory(prefix=".publish-", dir=run) as temp:
        work = Path(temp)
        for name in names:
            (work / name).write_bytes(_checked_bytes(previous / name))
        (work / "episode.md").write_bytes(episode_bytes)
        if _checked_bytes(transcript_path) != original:
            raise AgyAnalysisError("原始 transcript.txt 被修改，拒绝发布")
        _publish(result_dir, work, publish_episode=publish_episode)
    state["complete"] = True
    _json_write(state_path, state)
    _emit(on_progress, "done")
