from __future__ import annotations

import json
import io
import signal
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest

from server import analyzer, analysis_runner, analysis_fallback
from server.analysis_runner import AnalysisConfig, AnalysisError

URL = 'https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe'
NAMES = ('article.md', 'notes.md', 'mindmap.md')


@pytest.fixture(autouse=True)
def environment(monkeypatch, tmp_path):
    for name in ('PODCAST_ANALYSIS_BACKEND', 'PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS',
                 'PODCAST_ANALYSIS_REMINDER_SECONDS',
                 'PODCAST_ANALYSIS_ATTEMPTS', 'PODCAST_AGY_MODEL'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('PODCAST_ANALYSIS_FALLBACK', 'none')
    monkeypatch.setenv('PODCAST_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex-home'))
    monkeypatch.setattr(analyzer, '_style_report', lambda *args: None)
    monkeypatch.setattr(analyzer.time, 'sleep', Mock())


@pytest.fixture(params=['pi', 'agy', 'codex'])
def backend(request, monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', request.param)
    return request.param


def result_dir(tmp_path, old=False):
    root = tmp_path / 'result'
    root.mkdir()
    (root / 'transcript.txt').write_text('[00:00:01 发言人 1] 原始内容\n[00:00:03 发言人 2] 另一段\n')
    if old:
        for name in NAMES:
            (root / name).write_text('old ' + name)
    return root


def write_all(work):
    for name in NAMES:
        (work / name).write_text(f'# {name}\n\n有删节和改写，非逐字原文\n[原节目]({URL})\n')


def pi_events(stop='stop', error=None, settled=True, model='k3'):
    message = {'role': 'assistant', 'provider': 'kimi', 'model': model, 'stopReason': stop,
               'content': [], 'usage': {'input': 10, 'output': 20, 'totalTokens': 30}}
    if error:
        message['errorMessage'] = error
    events = [{'type': 'message_end', 'message': message}, {'type': 'agent_end', 'messages': [message]}]
    if settled:
        events.append({'type': 'agent_settled'})
    return '\n'.join(json.dumps(e) for e in events).encode()


def install_process(monkeypatch, backend, actions):
    calls = []

    class Process:
        pid = 45678
        returncode = None

        def __init__(self, argv, **kwargs):
            self.index = len(calls)
            self.wait_count = 0
            self.argv = argv
            active_backend = argv[0] if argv[0] in {'pi', 'agy', 'codex'} else backend
            self.stdin = io.BytesIO() if active_backend == 'pi' else None
            self.kwargs = kwargs
            calls.append(self)
            self.response = actions[self.index](Path(kwargs['cwd']), argv) or {}
            response = self.response
            if active_backend == 'pi':
                raw = response.get('raw', pi_events(response.get('stop', 'stop'), response.get('error'),
                                                   response.get('settled', True), response.get('model', 'k3')))
            elif active_backend == 'codex':
                raw = response.get('raw', json.dumps({
                    'type': 'turn.failed' if response.get('error') or response.get('timeout') else 'turn.completed',
                    'error': {'message': response.get('error')},
                    'usage': {'input_tokens': 10}}).encode())
            else:
                raw = response.get('raw', json.dumps({'status': response.get('status', 'SUCCESS'),
                        'error': response.get('error'), 'denied_actions': response.get('denied', []),
                        'usage': {'input_tokens': 10}}).encode())
            kwargs['stdout'].write(raw)
            kwargs['stdout'].flush()
            if response.get('cli_log'):
                Path(argv[argv.index('--log-file') + 1]).write_text(response['cli_log'])

        def poll(self):
            return self.returncode

        def wait(self, timeout=None):
            self.wait_count += 1
            self.wait_timeout = timeout
            self.returncode = self.response.get('code', -15 if self.response.get('timeout') else 0)
            return self.returncode

    def monitor(process, output, prompt, config, diagnostic, on_update=None):
        if process.response.get('timeout'):
            diagnostic['timeout_reason'] = 'idle'
            return True
        return False

    monkeypatch.setattr(analysis_runner, '_monitor', monitor)
    monkeypatch.setattr(analysis_runner.subprocess, 'Popen', Process)
    monkeypatch.setattr(analysis_runner.os, 'killpg', Mock())
    return calls


def diagnostics(root):
    return sorted([json.loads(p.read_text()) for p in root.glob('.analysis/*/diagnostics/*.json')],
                  key=lambda d: (d['started_at'], d['attempt']))


def run_folder(root):
    return root / '.analysis' / json.loads((root / '.analysis/state.json').read_text())['run']


def test_default_config_is_pi_k3_high_20_idle_minutes():
    config = AnalysisConfig.from_env()
    assert (config.backend, config.model, config.thinking, config.idle_timeout, config.attempts) == (
        'pi', 'kimi/k3', 'high', 1200, 2)


@pytest.mark.parametrize('name,value', [('PODCAST_ANALYSIS_BACKEND', 'unknown'),
    ('PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', 'NaN'), ('PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', 'inf'),
    ('PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', '-1'), ('PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', 'x'),
    ('PODCAST_ANALYSIS_ATTEMPTS', '0'), ('PODCAST_ANALYSIS_ATTEMPTS', '6'),
    ('PODCAST_ANALYSIS_ATTEMPTS', '1.5')])
def test_invalid_config_is_rejected(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(AnalysisError):
        AnalysisConfig.from_env()


def test_unsupported_agy_model_is_rejected(monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy')
    monkeypatch.setenv('PODCAST_AGY_MODEL', 'claude-opus')
    with pytest.raises(AnalysisError, match='Gemini'):
        AnalysisConfig.from_env()


def test_generates_validates_and_publishes(backend, tmp_path, monkeypatch):
    root = result_dir(tmp_path, old=True)
    original = (root / 'transcript.txt').read_bytes()
    calls = install_process(monkeypatch, backend, [lambda work, argv: write_all(work)])
    progress = []
    analyzer.analyze(root, {'url': URL, 'title': '节目', 'audio_url': 'secret'},
                     on_progress=lambda *args: progress.append(args))
    assert (root / 'transcript.txt').read_bytes() == original
    assert 'secret' not in (root / 'episode.md').read_text()
    assert progress == [('analyzing', None, None), ('done', None, None)]
    assert all((root / name).read_text().startswith('#') for name in NAMES)
    assert (run_folder(root) / 'before-publication/article.md').read_text() == 'old article.md'
    record, = diagnostics(root)
    assert record['outcome'] == 'success' and record['validated']
    assert record['exit_code'] == 0
    assert record['backend'] == backend and record['elapsed_seconds'] >= 0
    argv = calls[0].argv
    assert argv[0] == backend
    assert '--dangerously-skip-permissions' not in argv
    if backend == 'pi':
        assert argv[argv.index('--model') + 1] == 'kimi/k3'
        assert argv[argv.index('--thinking') + 1] == 'high'
        assert '--no-session' in argv and '--no-extensions' in argv
        assert argv[argv.index('--skill') + 1].endswith('/.skills/podcast-to-article/SKILL.md')
        assert 'bash' not in argv[argv.index('--tools') + 1]
        assert argv[argv.index('--mode') + 1] == 'rpc'
        assert '--print' not in argv
    elif backend == 'codex':
        assert argv[argv.index('--model') + 1] == 'gpt-6.1-sol'
        assert 'model_reasoning_effort="high"' in argv
        assert '--json' in argv and '--ephemeral' in argv
        assert argv[argv.index('--sandbox') + 1] == 'workspace-write'
        assert not calls[0].kwargs['cwd'].is_relative_to(root)
    else:
        assert argv[argv.index('--print-timeout') + 1] == '0'
        assert '--sandbox' in argv and '--log-file' in argv
        assert argv[argv.index('--output-format') + 1] == 'stream-json'


def test_slow_network_failure_retries_with_clean_workspace(backend, tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    ticks = iter([0, 181, 200, 205])
    monkeypatch.setattr(analyzer.time, 'monotonic', lambda: next(ticks))

    def fail(work, argv):
        write_all(work)
        (work / 'article.md').write_text('partial article')
        (work / 'editorial-plan.md').write_text('partial plan')
        (work / 'residue').mkdir()
        return {'stop': 'error', 'status': 'FAILED', 'error': 'request failed: EOF', 'code': 1}

    def succeed(work, argv):
        assert not (work / 'article.md').exists()
        assert not (work / 'editorial-plan.md').exists()
        assert not (work / 'residue').exists()
        assert '原始内容' in (work / 'transcript.txt').read_text()
        assert (work / '.skills/podcast-to-article/references/example.md').is_file()
        write_all(work)

    calls = install_process(monkeypatch, backend, [fail, succeed])
    analyzer.analyze(root, {'url': URL})
    assert len(calls) == 2 and calls[0].kwargs['cwd'] != calls[1].kwargs['cwd']
    first, second = diagnostics(root)
    assert first['elapsed_seconds'] == 181
    assert first['error_category'] == 'network' and first['retryable']
    assert second['outcome'] == 'success'
    analyzer.time.sleep.assert_called_once_with(10)


def test_timeout_saves_diagnostic_and_kills_group(backend, tmp_path, monkeypatch):
    root = result_dir(tmp_path, old=True)
    monkeypatch.setenv('PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', '1')
    calls = install_process(monkeypatch, backend, [lambda *args: {'timeout': True, 'settled': False, 'status': 'TIMEOUT'}])
    with pytest.raises(AnalysisError, match='无可见进展'):
        analyzer.analyze(root)
    assert len(calls) == 1
    assert analysis_runner.os.killpg.call_args_list[0].args == (45678, signal.SIGTERM)
    assert analysis_runner.os.killpg.call_args_list[1].args == (45678, signal.SIGKILL)
    record, = diagnostics(root)
    assert record['timed_out'] and record['error_category'] == 'timeout'
    assert not record['retryable'] and record['exit_code'] == -15
    assert (root / 'article.md').read_text() == 'old article.md'


def test_timeout_with_network_evidence_can_retry(backend, tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    calls = install_process(monkeypatch, backend, [
        lambda *args: {'timeout': True, 'settled': False, 'status': 'ERROR', 'stop': 'error',
                       'error': 'TLS handshake timeout'},
        lambda work, argv: write_all(work)])
    analyzer.analyze(root, {'url': URL})
    assert len(calls) == 2
    first, _ = diagnostics(root)
    assert first['timed_out'] and first['error_category'] == 'network'


@pytest.mark.parametrize('error,category', [('permission denied', 'permission'),
    ('not eligible for Antigravity', 'auth'), ('invalid API key', 'auth'),
    ('HTTP 401 unauthorized; previous request failed: EOF', 'auth'),
    ('quota exceeded', 'quota'), ('unrecognized failure API_KEY=super-secret', 'process_exit')])
def test_permanent_or_unknown_error_is_not_retried_and_is_private(backend, tmp_path, monkeypatch, error, category):
    root = result_dir(tmp_path, old=True)
    calls = install_process(monkeypatch, backend, [lambda *args: {
        'stop': 'error', 'status': 'FAILED', 'error': error, 'code': 1}])
    with pytest.raises(AnalysisError) as failure:
        analyzer.analyze(root)
    assert len(calls) == 1 and failure.value.category == category
    assert 'super-secret' not in str(failure.value)
    assert error not in json.dumps(diagnostics(root))
    assert diagnostics(root)[0]['error_category'] == category


@pytest.mark.parametrize('error,category', [('eligibility check failed: EOF', 'network'),
    ('local error: tls: bad record MAC', 'network'), ('HTTP 429', 'rate_limit'),
    ('HTTP 503', 'upstream')])
def test_transient_errors_have_bounded_attempts(backend, tmp_path, monkeypatch, error, category):
    root = result_dir(tmp_path)
    action = lambda *args: {'stop': 'error', 'status': 'FAILED', 'error': error, 'code': 1}
    calls = install_process(monkeypatch, backend, [action, action])
    with pytest.raises(AnalysisError) as failure:
        analyzer.analyze(root)
    assert len(calls) == 2 and failure.value.category == category
    assert len(diagnostics(root)) == 2


def test_agy_reads_only_this_invocations_cli_errors(tmp_path, monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy')
    root = result_dir(tmp_path)
    calls = install_process(monkeypatch, 'agy', [lambda *args: {
        'status': 'FAILED', 'code': 1,
        'cli_log': 'Run: attempt 1 failed (request failed: local error: tls: bad record MAC)\n'},
        lambda work, argv: write_all(work)])
    analyzer.analyze(root, {'url': URL})
    assert len(calls) == 2
    assert diagnostics(root)[0]['error_category'] == 'network'


def test_telemetry_error_is_not_model_network_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy')
    root = result_dir(tmp_path)
    install_process(monkeypatch, 'agy', [lambda *args: {
        'status': 'FAILED', 'code': 1, 'cli_log': 'client.go:70] TLS handshake timeout\n'}])
    with pytest.raises(AnalysisError) as failure:
        analyzer.analyze(root)
    assert failure.value.category == 'process_exit'


def test_agy_tool_denial_even_with_success_artifacts(tmp_path, monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy')
    root = result_dir(tmp_path, old=True)
    def denied(work, argv):
        write_all(work)
        return {'denied': [{'action': 'command'}]}
    install_process(monkeypatch, 'agy', [denied])
    with pytest.raises(AnalysisError, match='权限'):
        analyzer.analyze(root, {'url': URL})
    assert (root / 'article.md').read_text() == 'old article.md'


@pytest.mark.parametrize('response,category', [({'settled': False}, 'invalid_response'),
    ({'stop': 'length'}, 'output_limit'), ({'model': 'another'}, 'model_mismatch'),
    ({'raw': b'{"status":"SUCCESS"}'}, 'invalid_response')])
def test_pi_needs_settled_final_success_from_k3(tmp_path, monkeypatch, response, category):
    root = result_dir(tmp_path, old=True)
    def action(work, argv):
        write_all(work)
        return response
    install_process(monkeypatch, 'pi', [action])
    with pytest.raises(AnalysisError) as failure:
        analyzer.analyze(root, {'url': URL})
    assert failure.value.category == category
    assert (root / 'article.md').read_text() == 'old article.md'


def test_pi_recovered_internal_failure_uses_last_message(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    def action(work, argv):
        write_all(work)
        return {'raw': pi_events('error', 'HTTP 503') + b'\n' +
                b'{"type":"auto_retry_start"}\n{"type":"agent_start"}\n' + pi_events()}
    install_process(monkeypatch, 'pi', [action])
    analyzer.analyze(root, {'url': URL})
    assert diagnostics(root)[0]['internal_retries'] == 1
    assert diagnostics(root)[0]['outcome'] == 'success'
    assert diagnostics(root)[0]['usage']['input'] == 20


def test_agy_cli_timeout_status_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy')
    root = result_dir(tmp_path)
    install_process(monkeypatch, 'agy', [lambda *args: {'status': 'TIMEOUT', 'code': 1}])
    with pytest.raises(AnalysisError, match='超时'):
        analyzer.analyze(root)
    record, = diagnostics(root)
    assert record['timed_out'] and record['error_category'] == 'timeout'


def test_pi_does_not_classify_tool_text_as_network_failure(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    raw = b'{"type":"tool_execution_end","isError":false,"result":{"text":"HTTP 503 EOF API_KEY=secret"}}\n'
    install_process(monkeypatch, 'pi', [lambda *args: {'raw': raw, 'code': 1}])
    with pytest.raises(AnalysisError) as failure:
        analyzer.analyze(root)
    assert failure.value.category == 'process_exit'
    assert 'secret' not in json.dumps(diagnostics(root))


def test_malformed_pi_terminal_status_fails_without_leaking(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    install_process(monkeypatch, 'pi', [lambda *args: {'raw': pi_events({'secret': 'value'})}])
    with pytest.raises(AnalysisError):
        analyzer.analyze(root)
    record, = diagnostics(root)
    assert record['stop_reason'] == 'UNKNOWN'
    assert 'secret' not in json.dumps(record)


def test_pi_reported_timeout_is_recorded(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    install_process(monkeypatch, 'pi', [lambda *args: {'stop': 'error', 'error': 'request timed out'}])
    with pytest.raises(AnalysisError, match='超时'):
        analyzer.analyze(root)
    record, = diagnostics(root)
    assert record['timed_out'] and record['error_category'] == 'timeout'


@pytest.mark.parametrize('mutation', ['missing', 'timestamp', 'headings', 'source', 'notice', 'symlink', 'empty'])
def test_bad_artifacts_do_not_publish_or_retry(backend, tmp_path, monkeypatch, mutation):
    root = result_dir(tmp_path, old=True)
    def action(work, argv):
        write_all(work)
        article = work / 'article.md'
        if mutation == 'missing': article.unlink()
        elif mutation == 'timestamp': article.write_text(article.read_text() + '\n[00:00:02]')
        elif mutation == 'headings': (work / 'notes.md').write_text('### deep\n' + URL)
        elif mutation == 'source': article.write_text('# no link\n非逐字原文')
        elif mutation == 'notice': article.write_text('# no notice\n' + URL)
        elif mutation == 'empty': article.write_text('')
        elif mutation == 'symlink':
            article.unlink(); article.symlink_to(root / 'article.md')
    calls = install_process(monkeypatch, backend, [action])
    with pytest.raises(AnalysisError): analyzer.analyze(root, {'url': URL})
    assert len(calls) == 1
    assert all((root / name).read_text() == 'old ' + name for name in NAMES)
    assert not diagnostics(root)[0]['validated']


@pytest.mark.parametrize('name', ['transcript.txt', 'episode.md', '.skills/podcast-to-article/SKILL.md',
                                 '.skills/podcast-to-article/scripts/check_style.py'])
def test_input_modification_blocks_retry(backend, tmp_path, monkeypatch, name):
    root = result_dir(tmp_path, old=True)
    def action(work, argv):
        (work / name).write_text('changed')
        return {'stop': 'error', 'status': 'ERROR', 'error': 'request failed: EOF', 'code': 1}
    calls = install_process(monkeypatch, backend, [action])
    with pytest.raises(AnalysisError, match='修改了输入'):
        analyzer.analyze(root)
    assert len(calls) == 1
    assert diagnostics(root)[0]['error_category'] == 'input_modified'
    assert '原始内容' in (root / 'transcript.txt').read_text()


def test_missing_executable_is_diagnosed(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    monkeypatch.setattr(analysis_runner.subprocess, 'Popen', Mock(side_effect=FileNotFoundError('secret')))
    with pytest.raises(AnalysisError, match='无法启动'):
        analyzer.analyze(root)
    assert diagnostics(root)[0]['error_category'] == 'startup'
    assert 'secret' not in json.dumps(diagnostics(root))


def test_publish_failure_resumes_valid_checkpoint(backend, tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    calls = install_process(monkeypatch, backend, [lambda work, argv: write_all(work)])
    publish = analyzer._publish
    monkeypatch.setattr(analyzer, '_publish', Mock(side_effect=OSError('disk failure')))
    with pytest.raises(OSError): analyzer.analyze(root, {'url': URL})
    run = run_folder(root)
    before = (run / 'generate/article.md').stat().st_mtime_ns
    monkeypatch.setattr(analyzer, '_publish', publish)
    analyzer.analyze(root, {'url': URL})
    assert len(calls) == 1 and (run / 'generate/article.md').stat().st_mtime_ns == before
    assert json.loads((root / '.analysis/state.json').read_text())['complete']


@pytest.mark.parametrize('change', ['backend', 'skill', 'prompt'])
def test_configuration_change_invalidates_incomplete_checkpoint(tmp_path, monkeypatch, change):
    root = result_dir(tmp_path)
    install_process(monkeypatch, 'pi', [lambda work, argv: write_all(work)])
    publish = analyzer._publish
    monkeypatch.setattr(analyzer, '_publish', Mock(side_effect=OSError('disk failure')))
    with pytest.raises(OSError): analyzer.analyze(root, {'url': URL})
    old_run = run_folder(root)
    monkeypatch.setattr(analyzer, '_publish', publish)
    next_backend = 'pi'
    if change == 'backend':
        monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy'); next_backend = 'agy'
    elif change == 'prompt':
        prompt = tmp_path / 'prompt.md'; prompt.write_text('new prompt')
        monkeypatch.setattr(analyzer, 'PROMPT_PATH', prompt)
    else:
        import shutil
        skill = tmp_path / 'skill'; shutil.copytree(analyzer.SKILL_PATH, skill)
        with (skill / 'references/example.md').open('a') as file: file.write('\nnew reference')
        monkeypatch.setattr(analyzer, 'SKILL_PATH', skill)
    calls = install_process(monkeypatch, next_backend, [lambda work, argv: write_all(work)])
    analyzer.analyze(root, {'url': URL})
    assert len(calls) == 1 and run_folder(root) != old_run
    assert (old_run / 'generate/article.md').is_file()


def test_corrupt_checkpoint_is_not_reused(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    calls = install_process(monkeypatch, 'pi', [lambda work, argv: write_all(work)])
    monkeypatch.setattr(analyzer, '_publish', Mock(side_effect=OSError()))
    with pytest.raises(OSError): analyzer.analyze(root, {'url': URL})
    (run_folder(root) / 'generate/article.md').write_text('tampered')
    with pytest.raises(AnalysisError, match='检查点损坏'):
        analyzer.analyze(root, {'url': URL})
    assert len(calls) == 1


def test_successful_reanalysis_starts_new_run(tmp_path, monkeypatch):
    root = result_dir(tmp_path)
    action = lambda work, argv: write_all(work)
    calls = install_process(monkeypatch, 'pi', [action, action])
    analyzer.analyze(root, {'url': URL})
    first = run_folder(root)
    analyzer.analyze(root, {'url': URL})
    assert len(calls) == 2 and run_folder(root) != first


def test_health_reports_selected_backend(monkeypatch):
    from server import app
    monkeypatch.setattr(app, 'capabilities', lambda: {})
    monkeypatch.setattr(app.shutil, 'which', lambda name: '/bin/' + name)
    assert app.health()['analysis'] == {'backend': 'pi', 'model': 'kimi/k3', 'thinking': 'high', 'available': True, 'fallback': None}
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'agy')
    assert app.health()['analysis']['backend'] == 'agy'
    assert app.health()['analysis']['thinking'] is None


@pytest.mark.parametrize('response', [
    {'stop': 'error', 'error': 'quota exceeded'},
    {'stop': 'error', 'error': 'HTTP 429'},
    {'stop': 'error', 'error': 'request failed: EOF'},
    {'stop': 'error', 'error': 'invalid API key'},
    {'stop': 'error', 'code': 1},
    {'settled': False},
    {'timeout': True},
])
def test_pi_request_failure_switches_immediately_to_clean_codex(tmp_path, monkeypatch, response):
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    root = result_dir(tmp_path, old=True)
    original = (root / 'transcript.txt').read_bytes()

    def fail(work, argv):
        (work / 'article.md').write_text('partial')
        return response

    def succeed(work, argv):
        assert argv[0] == 'codex'
        assert not (work / 'article.md').exists()
        write_all(work)

    calls = install_process(monkeypatch, 'pi', [fail, succeed])
    analyzer.analyze(root, {'url': URL})
    assert [c.argv[0] for c in calls] == ['pi', 'codex']
    analyzer.time.sleep.assert_not_called()
    first, second = diagnostics(root)
    assert first['fallback_to'] == 'codex' and first['cooldown_until']
    assert second['route'] == 'request_failed' and second['validated']
    assert second['model'] == 'gpt-6.1-sol' and second['thinking'] == 'high'
    assert (root / 'transcript.txt').read_bytes() == original
    saved = json.loads((run_folder(root) / 'generate.json').read_text())
    assert saved['backend'] == 'codex' and saved['primary_backend'] == 'pi'
    assert 3590 <= analysis_fallback.cooldown_status()['remaining_seconds'] <= 3600


def test_cooldown_survives_reload_and_expiry_retries_pi(tmp_path, monkeypatch):
    import importlib
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    now = [10000.0]
    monkeypatch.setattr(analysis_fallback.time, 'time', lambda: now[0])
    root = result_dir(tmp_path)
    calls = install_process(monkeypatch, 'pi', [
        lambda *args: {'stop': 'error'},
        lambda work, argv: write_all(work),
        lambda work, argv: write_all(work),
        lambda work, argv: write_all(work),
    ])
    analyzer.analyze(root, {'url': URL})
    importlib.reload(analysis_fallback)
    now[0] += 3599
    other = tmp_path / 'another-task'
    other.mkdir()
    second_root = result_dir(other)
    analyzer.analyze(second_root, {'url': URL})
    assert diagnostics(second_root)[-1]['route'] == 'cooldown'
    assert analysis_fallback.cooldown_status()['remaining_seconds'] == 1
    now[0] += 1
    analyzer.analyze(root, {'url': URL})
    assert [c.argv[0] for c in calls] == ['pi', 'codex', 'codex', 'pi']
    assert diagnostics(root)[-1]['route'] == 'primary'


def test_failing_codex_does_not_loop_or_extend_cooldown(tmp_path, monkeypatch):
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    now = [10000.0]
    monkeypatch.setattr(analysis_fallback.time, 'time', lambda: now[0])
    root = result_dir(tmp_path, old=True)

    def fail_codex(work, argv):
        now[0] += 200
        return {'error': 'HTTP 503', 'code': 1}

    calls = install_process(monkeypatch, 'pi', [lambda *args: {'stop': 'error'}, fail_codex, fail_codex])
    with pytest.raises(AnalysisError, match='codex 生成失败'):
        analyzer.analyze(root)
    assert [c.argv[0] for c in calls] == ['pi', 'codex', 'codex']
    assert analysis_fallback.cooldown_status()['remaining_seconds'] == 3200
    assert (root / 'article.md').read_text() == 'old article.md'


@pytest.mark.parametrize('mutation', ['missing_output', 'input_changed', 'input_deleted'])
def test_local_validation_failure_does_not_switch_or_start_cooldown(tmp_path, monkeypatch, mutation):
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    root = result_dir(tmp_path, old=True)

    def fail(work, argv):
        if mutation == 'input_changed':
            (work / 'transcript.txt').write_text('changed')
        elif mutation == 'input_deleted':
            (work / 'transcript.txt').unlink()
        return {'stop': 'error'} if mutation != 'missing_output' else {}

    calls = install_process(monkeypatch, 'pi', [fail])
    with pytest.raises(AnalysisError):
        analyzer.analyze(root)
    assert len(calls) == 1
    assert not analysis_fallback.cooldown_status()['active']
    assert (root / 'article.md').read_text() == 'old article.md'


def test_health_reports_active_cooldown_without_secrets(tmp_path, monkeypatch):
    from server import app
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    monkeypatch.setattr(app, 'capabilities', lambda: {})
    monkeypatch.setattr(app.shutil, 'which', lambda name: '/bin/' + name)
    analysis_fallback.start_cooldown()
    fallback = app.health()['analysis']['fallback']
    assert fallback['backend'] == 'codex' and fallback['active']
    assert fallback['cooldown_seconds'] == 3600
    assert fallback['model'] == 'gpt-6.1-sol' and fallback['thinking'] == 'high'


def test_corrupt_cooldown_is_not_overwritten(tmp_path, monkeypatch):
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    path = analysis_fallback._state_path()
    path.parent.mkdir(parents=True)
    path.write_text('{bad json')
    root = result_dir(tmp_path)
    with pytest.raises(AnalysisError, match='备用状态损坏'):
        analyzer.analyze(root)
    assert path.read_text() == '{bad json'


def test_missing_pi_executable_still_falls_back(tmp_path, monkeypatch):
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    root = result_dir(tmp_path)

    def missing(work, argv):
        raise FileNotFoundError('pi missing')

    calls = install_process(monkeypatch, 'pi', [missing, lambda work, argv: write_all(work)])
    analyzer.analyze(root, {'url': URL}, executable='custom-pi')
    assert [c.argv[0] for c in calls] == ['custom-pi', 'codex']
    assert diagnostics(root)[0]['error_category'] == 'startup'


def test_default_fallback_and_invalid_selection(monkeypatch):
    monkeypatch.delenv('PODCAST_ANALYSIS_FALLBACK')
    assert AnalysisConfig.from_env().fallback_backend == 'codex'
    monkeypatch.setenv('PODCAST_ANALYSIS_BACKEND', 'codex')
    assert AnalysisConfig.from_env().fallback_backend is None
    monkeypatch.setenv('PODCAST_ANALYSIS_FALLBACK', 'unknown')
    with pytest.raises(AnalysisError, match='FALLBACK'):
        AnalysisConfig.from_env()
