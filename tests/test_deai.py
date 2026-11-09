from __future__ import annotations

import json
import subprocess

import pytest

from server import analyzer
from server.analysis_runner import AnalysisConfig, AnalysisError
from tests.test_analyzer import NAMES, URL, environment, install_process, result_dir, run_folder  # noqa: F401

REAL_POPEN = subprocess.Popen

BODY = "这家公司在二零一四年成立，业务覆盖亚太地区的景点门票和一日游。" * 20
ARTICLE = (f"# 标题\n\n有删节和改写，非逐字原文\n[原节目]({URL})\n\n## 它是怎么长出来的\n\n"
           f"真正的壁垒不是技术，而是认知。收入在 2024 年增长了 24%。\n\n{BODY}\n")
REWRITTEN = ARTICLE.replace("真正的壁垒不是技术，而是认知。", "真正的壁垒是认知。")


@pytest.fixture(autouse=True)
def deai_on(environment, monkeypatch):
    monkeypatch.setenv('PODCAST_DEAI', 'on')
    monkeypatch.delenv('PODCAST_DEAI_MODEL', raising=False)


def install(monkeypatch, actions):
    """Fake the model CLIs but run the vendored lieflat scripts for real."""
    calls = install_process(monkeypatch, 'pi', actions)
    fake, original = subprocess.Popen, analyzer._run_script

    def run_script(tools, args):
        subprocess.Popen = REAL_POPEN
        try:
            return original(tools, args)
        finally:
            subprocess.Popen = fake
    monkeypatch.setattr(analyzer, '_run_script', run_script)
    return calls


def generate(work, argv):
    for name in NAMES:
        (work / name).write_text(ARTICLE if name == 'article.md' else
                                 f'# {name}\n\n有删节和改写，非逐字原文\n[原节目]({URL})\n')


def rewrite(text=REWRITTEN, **response):
    def action(work, argv):
        assert (work / 'candidates.json').is_file() and (work / 'detect-report.txt').is_file()
        assert (work / '.skills/lieflat-less-ai-tone/SKILL.md').is_file()
        assert not (work / 'notes.md').exists()
        (work / 'article.md').write_text(text)
        (work / 'changes.md').write_text('1. 第 7 行｜规则 1｜…\n')
        return response
    return action


def deai_record(root):
    return json.loads((run_folder(root) / 'deai.json').read_text())


def test_rewrite_is_published_with_reports(tmp_path, monkeypatch):
    calls = install(monkeypatch, [generate, rewrite()])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    assert (root / 'article.md').read_text() == REWRITTEN
    assert calls[1].argv[0] == 'agy'
    assert calls[1].argv[calls[1].argv.index('--model') + 1] == 'gemini-4-argon-medium'
    assert deai_record(root)['outcome'] == 'rewritten'
    reports = run_folder(root) / 'deai-report'
    assert (reports / 'changes.md').is_file() and (reports / '去AI味报告.md').is_file()


@pytest.mark.parametrize('text,problem', [
    (REWRITTEN.replace('24%', '25%'), '数字'),
    (REWRITTEN.replace('## 它是怎么长出来的', '## 它怎么长出来'), '标题'),
    (REWRITTEN.replace('认知。', '认知——'), '破折号'),
    (REWRITTEN.replace(BODY, BODY[: len(BODY) // 2]), '字数'),
], ids=['number', 'heading', 'dash', 'length'])
def test_guard_failure_falls_back_to_generated_article(tmp_path, monkeypatch, text, problem):
    with pytest.raises(AnalysisError, match=problem):
        analyzer._deai_guard(ARTICLE, text)
    install(monkeypatch, [generate, rewrite(text)])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    assert (root / 'article.md').read_text() == ARTICLE
    record = deai_record(root)
    assert (record['outcome'], record['error_category']) == ('fallback', 'deai_guard')


def test_guard_rejects_changed_quote():
    with pytest.raises(AnalysisError, match='引语'):
        analyzer._deai_guard(ARTICLE + '「原话一句」\n', ARTICLE + '「原话改了」\n')


def test_model_failure_and_input_edits_fall_back(tmp_path, monkeypatch):
    def touch_transcript(work, argv):
        (work / 'transcript.txt').write_text('改了')
    install(monkeypatch, [generate, touch_transcript])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    assert (root / 'article.md').read_text() == ARTICLE
    assert deai_record(root)['error_category'] == 'input_modified'


def test_transient_failure_is_retried(tmp_path, monkeypatch):
    calls = install(monkeypatch, [generate, rewrite(status='ERROR', error='HTTP 503'), rewrite()])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    assert len(calls) == 3 and (root / 'article.md').read_text() == REWRITTEN


def test_short_article_skips_model(tmp_path, monkeypatch):
    def short(work, argv):
        for name in NAMES:
            (work / name).write_text(f'# {name}\n\n有删节和改写，非逐字原文\n[原节目]({URL})\n')
    calls = install(monkeypatch, [short])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    assert len(calls) == 1 and deai_record(root)['error_category'] == 'deai_script'


def test_deai_checkpoint_is_reused(tmp_path, monkeypatch):
    calls = install(monkeypatch, [generate, rewrite()])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    state = json.loads((root / '.analysis/state.json').read_text())
    state['complete'] = False
    (root / '.analysis/state.json').write_text(json.dumps(state))
    (root / 'article.md').write_text('stale')
    analyzer.analyze(root)
    assert len(calls) == 2 and (root / 'article.md').read_text() == REWRITTEN


def test_off_skips_pass(tmp_path, monkeypatch):
    monkeypatch.setenv('PODCAST_DEAI', 'off')
    calls = install(monkeypatch, [generate])
    root = result_dir(tmp_path)
    analyzer.analyze(root)
    assert len(calls) == 1 and (root / 'article.md').read_text() == ARTICLE


@pytest.mark.parametrize('name,value', [('PODCAST_DEAI', 'maybe'), ('PODCAST_DEAI_MODEL', 'claude-opus-5-5-high')])
def test_invalid_deai_config(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(AnalysisError):
        analyzer.deai_config(AnalysisConfig.from_env())


def test_low_model_override(monkeypatch):
    monkeypatch.setenv('PODCAST_DEAI_MODEL', 'gemini-4-argon-low')
    config = analyzer.deai_config(AnalysisConfig.from_env())
    assert (config.backend, config.model, config.fallback_backend) == ('agy', 'gemini-4-argon-low', None)


def test_health_reports_deai_model(monkeypatch):
    from server import app
    monkeypatch.setattr(app, 'capabilities', lambda: {})
    monkeypatch.setattr(app.shutil, 'which', lambda name: '/bin/' + name)
    assert app.health()['analysis']['deai'] == {'backend': 'agy', 'model': 'gemini-4-argon-medium', 'available': True}
