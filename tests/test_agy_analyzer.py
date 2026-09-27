from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
from unittest.mock import call, patch

import pytest

from server.agy_analyzer import AgyAnalysisError, analyze, _apply_style_edits

ARTIFACTS = ("article.md", "notes.md", "mindmap.md")
EPISODE_URL = "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe"


def _result_dir(tmp_path: Path, *, with_old: bool = False) -> Path:
    result = tmp_path / "result"
    result.mkdir()
    (result / "transcript.txt").write_text(
        "[00:00:01 发言人 1] 原始内容\n[00:00:03 发言人 2] 另一段内容\n",
        encoding="utf-8",
    )
    if with_old:
        for name in ARTIFACTS:
            (result / name).write_text(f"old {name}\n", encoding="utf-8")
    return result


def _popen_factory(action, captured: dict | None = None):
    class Process:
        pid = 43210

        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.cwd = Path(kwargs["cwd"])
            if captured is not None:
                captured.update(argv=argv, kwargs=kwargs, cwd=self.cwd)
            action(self.cwd)
            kwargs["stdout"].write(json.dumps({"status": "SUCCESS", "usage": {"input_tokens": 10}}).encode())

        def wait(self, timeout=None):
            return 0

    return Process


def _write_all(cwd: Path) -> None:
    for name in ARTIFACTS:
        (cwd / name).write_text(_expected(name), encoding="utf-8")
    if (cwd / "mechanical-checks.json").exists():
        (cwd / "audit.md").write_text("已对照原文核稿。\n", encoding="utf-8")


def _expected(name):
    return f"# generated {name}\n\n有删节和改写，非逐字原文\n[原节目]({EPISODE_URL})\n"


def test_analyze_publishes_all_markdown_and_episode_metadata(tmp_path: Path):
    result = _result_dir(tmp_path)
    original = (result / "transcript.txt").read_bytes()
    captured: dict = {}
    progress: list[tuple[str, None, None]] = []
    episode = {
        "title": "单集标题",
        "podcast_title": "播客标题",
        "published_at": "2026-09-01T00:00:00Z",
        "duration": 61,
        "episode_url": EPISODE_URL,
        "audio_url": "https://media.xyzcdn.net/secret.m4a?key=do-not-save",
        "description": "节目介绍",
    }

    with patch(
        "server.agy_analyzer.subprocess.Popen", _popen_factory(_write_all, captured)
    ):
        analyze(
            result,
            episode,
            on_progress=lambda stage, done, total: progress.append(
                (stage, done, total)
            ),
            executable="test-agy",
        )

    assert (result / "transcript.txt").read_bytes() == original
    for name in ARTIFACTS:
        assert (result / name).read_text(encoding="utf-8") == _expected(name)
    episode_markdown = (result / "episode.md").read_text(encoding="utf-8")
    assert "单集标题" in episode_markdown
    assert f"]({EPISODE_URL})" in episode_markdown
    assert "audio_url" not in episode_markdown
    assert "do-not-save" not in episode_markdown
    assert progress == [("analyzing", None, None), ("done", None, None)]

    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[0] == "test-agy"
    assert "--json-schema" not in argv
    assert argv[argv.index("--output-format") + 1] == "json"
    assert argv[argv.index("--model") + 1] == "gemini-3.1-pro-high"
    assert "--effort" not in argv
    assert "--dangerously-skip-permissions" not in argv
    assert "--sandbox" in argv
    assert captured["kwargs"]["start_new_session"] is True
    assert captured["cwd"] != result
    assert Path(argv[argv.index("--add-dir") + 1]) == captured["cwd"]
    prompt = argv[argv.index("-p") + 1]
    assert "完整" in prompt
    assert "禁止调用 command" in prompt


def test_missing_artifact_fails_and_preserves_all_old_files(tmp_path: Path):
    result = _result_dir(tmp_path, with_old=True)

    def omit_article(cwd: Path) -> None:
        (cwd / "notes.md").write_text("new notes\n", encoding="utf-8")
        (cwd / "mindmap.md").write_text("new map\n", encoding="utf-8")

    with (
        patch("server.agy_analyzer.subprocess.Popen", _popen_factory(omit_article)),
        pytest.raises(AgyAnalysisError, match="article.md"),
    ):
        analyze(result)

    for name in ARTIFACTS:
        assert (result / name).read_text(encoding="utf-8") == f"old {name}\n"


def test_timeout_terminates_process_group_and_preserves_old_files(
    tmp_path: Path, monkeypatch
):
    result = _result_dir(tmp_path, with_old=True)
    monkeypatch.setenv("WHISPER_AGY_TIMEOUT_SECONDS", "1")

    class TimedOutProcess:
        pid = 24680

        def __init__(self, argv, **kwargs):
            self.wait_calls = 0

        def wait(self, timeout=None):
            self.wait_calls += 1
            if self.wait_calls == 1:
                raise subprocess.TimeoutExpired("agy", timeout)
            return -15

    with (
        patch("server.agy_analyzer.subprocess.Popen", TimedOutProcess),
        patch("server.agy_analyzer.os.killpg") as killpg,
        pytest.raises(AgyAnalysisError, match="超时"),
    ):
        analyze(result)

    assert killpg.call_args_list == [
        call(24680, __import__("signal").SIGTERM),
        call(24680, __import__("signal").SIGKILL),
    ]
    for name in ARTIFACTS:
        assert (result / name).read_text(encoding="utf-8") == f"old {name}\n"


def test_failed_process_does_not_expose_raw_log_output(tmp_path: Path):
    result = _result_dir(tmp_path)

    class FailedProcess:
        pid = 13579

        def __init__(self, argv, **kwargs):
            kwargs["stdout"].write(b"API_KEY=super-secret-value\n")

        def wait(self, timeout=None):
            return 7

    with (
        patch("server.agy_analyzer.subprocess.Popen", FailedProcess),
        pytest.raises(AgyAnalysisError) as captured,
    ):
        analyze(result)

    message = str(captured.value)
    assert "退出码 7" in message
    assert "super-secret-value" not in message


def test_transcript_modification_is_refused_and_old_files_survive(tmp_path: Path):
    result = _result_dir(tmp_path, with_old=True)

    def modify_transcript(cwd: Path) -> None:
        (cwd / "transcript.txt").write_text("changed\n", encoding="utf-8")
        _write_all(cwd)

    with (
        patch(
            "server.agy_analyzer.subprocess.Popen", _popen_factory(modify_transcript)
        ),
        pytest.raises(AgyAnalysisError, match="修改了 staging"),
    ):
        analyze(result)

    assert "原始内容" in (result / "transcript.txt").read_text(encoding="utf-8")
    for name in ARTIFACTS:
        assert (result / name).read_text(encoding="utf-8") == f"old {name}\n"


def test_symlink_artifact_is_rejected(tmp_path: Path):
    result = _result_dir(tmp_path, with_old=True)

    def create_symlink(cwd: Path) -> None:
        (cwd / "target.md").write_text("target\n", encoding="utf-8")
        os.symlink(cwd / "target.md", cwd / "article.md")
        (cwd / "notes.md").write_text("notes\n", encoding="utf-8")
        (cwd / "mindmap.md").write_text("map\n", encoding="utf-8")

    with (
        patch("server.agy_analyzer.subprocess.Popen", _popen_factory(create_symlink)),
        pytest.raises(AgyAnalysisError, match="符号链接"),
    ):
        analyze(result)

    for name in ARTIFACTS:
        assert (result / name).read_text(encoding="utf-8") == f"old {name}\n"


def test_empty_or_symlink_transcript_is_rejected_before_process(tmp_path: Path):
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / "transcript.txt").touch()
    with (
        patch("server.agy_analyzer.subprocess.Popen") as popen,
        pytest.raises(AgyAnalysisError, match="为空"),
    ):
        analyze(empty)
    popen.assert_not_called()

    target = tmp_path / "source.txt"
    target.write_text("content", encoding="utf-8")
    linked = tmp_path / "linked"
    linked.mkdir()
    os.symlink(target, linked / "transcript.txt")
    with pytest.raises(AgyAnalysisError, match="符号链接"):
        analyze(linked)


def test_account_eligibility_error_is_actionable_without_exposing_log(tmp_path):
    result = _result_dir(tmp_path)

    class IneligibleProcess:
        pid = 13579

        def __init__(self, argv, **kwargs):
            kwargs['stdout'].write(b'Your current account is not eligible for Antigravity. secret=value')

        def wait(self, timeout=None):
            return 1

    with patch('server.agy_analyzer.subprocess.Popen', IneligibleProcess):
        with pytest.raises(AgyAnalysisError, match='账号验证') as error:
            analyze(result)
    assert 'secret=value' not in str(error.value)
    assert (result / 'transcript.txt').is_file()


def test_headless_command_denial_is_reported_even_with_zero_exit(tmp_path):
    result = _result_dir(tmp_path)

    class DeniedProcess:
        pid = 13580

        def __init__(self, argv, **kwargs):
            kwargs["stdout"].write(
                b'jetski: no output produced -- a tool required the "command" permission '
                b'that headless mode cannot prompt for, so it was auto-denied.'
            )

        def wait(self, timeout=None):
            return 0

    with patch("server.agy_analyzer.subprocess.Popen", DeniedProcess):
        with pytest.raises(AgyAnalysisError, match="命令工具"):
            analyze(result)


@pytest.fixture(autouse=True)
def default_analysis_settings(monkeypatch):
    monkeypatch.delenv("PODCAST_AGY_MODEL", raising=False)
    monkeypatch.delenv("PODCAST_AGY_STYLE_EDIT", raising=False)


def test_audit_failure_resumes_without_regenerating(tmp_path):
    result = _result_dir(tmp_path, with_old=True)
    stages = []

    def first(cwd):
        stages.append("audit" if (cwd / "mechanical-checks.json").exists() else "generate")
        if stages[-1] == "audit":
            raise AgyAnalysisError("connection lost")
        _write_all(cwd)

    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(first)):
        with pytest.raises(AgyAnalysisError, match="核稿失败"):
            analyze(result)
    assert stages == ["generate", "audit"]
    assert (result / "article.md").read_text() == "old article.md\n"

    def resume(cwd):
        assert (cwd / "mechanical-checks.json").exists()
        _write_all(cwd)

    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(resume)) as process:
        analyze(result)
    assert (result / "article.md").read_text() == _expected("article.md")
    backups = list((result / ".analysis").glob("*/before-publication/article.md"))
    assert backups[0].read_text() == "old article.md\n"


def test_changed_transcript_invalidates_incomplete_checkpoint(tmp_path):
    result = _result_dir(tmp_path)
    def interrupted(cwd):
        if (cwd / "mechanical-checks.json").exists():
            raise AgyAnalysisError("interrupted")
        _write_all(cwd)
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(interrupted)):
        with pytest.raises(AgyAnalysisError): analyze(result)
    (result / "transcript.txt").write_text("[00:00:01] different source\n")
    calls = []
    def complete(cwd):
        calls.append(cwd)
        _write_all(cwd)
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(complete)):
        analyze(result)
    assert len(calls) == 2


def test_invalid_timestamp_blocks_publication_after_audit(tmp_path):
    result = _result_dir(tmp_path, with_old=True)
    def invalid(cwd):
        _write_all(cwd)
        (cwd / "notes.md").write_text(_expected("notes.md") + "回听 00:04:00\n")
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(invalid)):
        with pytest.raises(AgyAnalysisError, match="invalid_timestamps"):
            analyze(result)
    assert (result / "notes.md").read_text() == "old notes.md\n"
    state = json.loads((result / ".analysis/state.json").read_text())
    assert (result / ".analysis" / state["run"] / "generate.json").exists()
    assert not (result / ".analysis" / state["run"] / "audit.json").exists()


def test_style_only_sees_article_and_voice_and_retries_alone(tmp_path, monkeypatch):
    result = _result_dir(tmp_path, with_old=True)
    monkeypatch.setenv("PODCAST_AGY_STYLE_EDIT", "true")
    stages = []
    def action(cwd):
        if (cwd / "article-draft.md").exists():
            stages.append("style")
            assert {p.name for p in cwd.iterdir()} == {"article-draft.md", "voice-sample.txt"}
            raise AgyAnalysisError("quota exhausted")
        stages.append("audit" if (cwd / "mechanical-checks.json").exists() else "generate")
        _write_all(cwd)
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(action)):
        with pytest.raises(AgyAnalysisError, match="Opus 润色失败"):
            analyze(result)
    assert stages == ["generate", "audit", "style"]
    assert (result / "article.md").read_text() == "old article.md\n"
    captured = {}
    def finish(cwd):
        assert (cwd / "article-draft.md").is_file()
        (cwd / "style-edits.json").write_text('{"edits": []}')
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(finish, captured)):
        analyze(result)
    assert "claude-opus-4-6-thinking" in captured["argv"]
    assert "--effort" not in captured["argv"]
    assert (result / "notes.md").read_text() == _expected("notes.md")


def test_disable_style_after_failure_publishes_cached_gemini(tmp_path, monkeypatch):
    result = _result_dir(tmp_path)
    monkeypatch.setenv("PODCAST_AGY_STYLE_EDIT", "true")
    def action(cwd):
        if (cwd / "article-draft.md").exists(): raise AgyAnalysisError("quota")
        _write_all(cwd)
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(action)):
        with pytest.raises(AgyAnalysisError): analyze(result)
    monkeypatch.setenv("PODCAST_AGY_STYLE_EDIT", "false")
    with patch("server.agy_analyzer.subprocess.Popen") as process:
        analyze(result)
        process.assert_not_called()


@pytest.mark.parametrize("before,after", [
    ("可能要十个小时", "要十个小时"),
    ("需要10小时", "需要1小时"),
    ("没有完成", "已经完成"),
    ("同一句", "重复定位"),
])
def test_style_rejects_changed_qualifiers_numbers_or_ambiguous_match(before, after):
    text = "# 标题\n\n" + before + ("，同一句" if before == "同一句" else "")
    raw = json.dumps({"edits": [{"before": before, "after": after}]}).encode()
    with pytest.raises(AgyAnalysisError, match="局部修改"):
        _apply_style_edits(text, raw)


def test_style_applies_nonoverlapping_edits_against_original():
    article = "# 标题\n\n这个事非常非常重要。保留原话。"
    raw = json.dumps({"edits": [{"before": "非常非常重要", "after": "很重要"}]}).encode()
    assert _apply_style_edits(article, raw) == "# 标题\n\n这个事很重要。保留原话。"


def test_json_tool_denial_is_failure_even_when_artifacts_exist(tmp_path):
    result = _result_dir(tmp_path, with_old=True)
    class Denied:
        pid = 1234
        def __init__(self, argv, **kwargs):
            _write_all(Path(kwargs["cwd"]))
            kwargs["stdout"].write(b'{"status":"SUCCESS","denied_actions":[{"action":"command"}]}')
        def wait(self, timeout=None): return 0
    with patch("server.agy_analyzer.subprocess.Popen", Denied):
        with pytest.raises(AgyAnalysisError, match="工具调用被拒绝"):
            analyze(result)
    assert (result / "article.md").read_text() == "old article.md\n"


def test_successful_reanalysis_starts_a_new_run(tmp_path):
    result = _result_dir(tmp_path)
    calls = []
    def action(cwd):
        calls.append(cwd)
        _write_all(cwd)
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(action)):
        analyze(result)
        first = json.loads((result / ".analysis/state.json").read_text())["run"]
        analyze(result)
        second = json.loads((result / ".analysis/state.json").read_text())["run"]
    assert len(calls) == 4
    assert first != second


def test_tampered_checkpoint_is_not_reused(tmp_path):
    result = _result_dir(tmp_path)
    def interrupted(cwd):
        if (cwd / "mechanical-checks.json").exists():
            raise AgyAnalysisError("interrupted")
        _write_all(cwd)
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(interrupted)):
        with pytest.raises(AgyAnalysisError): analyze(result)
    state = json.loads((result / ".analysis/state.json").read_text())
    checkpoint = result / ".analysis" / state["run"] / "generate/article.md"
    checkpoint.write_text("tampered")
    with patch("server.agy_analyzer.subprocess.Popen") as process:
        with pytest.raises(AgyAnalysisError, match="检查点损坏"):
            analyze(result)
        process.assert_not_called()


def test_audit_cannot_modify_episode_or_mechanical_checks(tmp_path):
    result = _result_dir(tmp_path, with_old=True)
    def action(cwd):
        _write_all(cwd)
        if (cwd / "mechanical-checks.json").exists():
            (cwd / "mechanical-checks.json").write_text('{}')
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(action)):
        with pytest.raises(AgyAnalysisError, match="staging 输入"):
            analyze(result)
    assert (result / "article.md").read_text() == "old article.md\n"


def test_overlapping_style_edits_are_rejected():
    article = "# 标题\n\n这句话非常生硬。"
    raw = json.dumps({"edits": [
        {"before": "这句话非常", "after": "这句话很"},
        {"before": "非常生硬", "after": "很生硬"},
    ]}).encode()
    with pytest.raises(AgyAnalysisError):
        _apply_style_edits(article, raw)


def test_missing_source_link_is_rejected_after_audit(tmp_path):
    result = _result_dir(tmp_path, with_old=True)
    def action(cwd):
        _write_all(cwd)
        (cwd / "notes.md").write_text("# 没有来源\n\n笔记内容。")
    with patch("server.agy_analyzer.subprocess.Popen", _popen_factory(action)):
        with pytest.raises(AgyAnalysisError, match="missing_source_link"):
            analyze(result, {"url": EPISODE_URL})
    assert (result / "article.md").read_text() == "old article.md\n"
