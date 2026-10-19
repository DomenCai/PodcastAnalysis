"""Exercise streaming, inactivity and steering using real local subprocesses."""
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from server.analysis_runner import AnalysisConfig, AnalysisError, invoke
from server import analysis_runner


@pytest.fixture(autouse=True)
def isolated_codex_home(tmp_path, monkeypatch):
    monkeypatch.setenv('CODEX_HOME', str(tmp_path / 'codex-home'))


PI_FINAL = '''
emit({'type': 'message_end', 'message': {'role': 'assistant', 'provider': 'kimi', 'model': 'k3',
      'stopReason': 'stop', 'usage': {'input': 1, 'output': 2}}})
emit({'type': 'agent_settled'})
for line in sys.stdin:
    pass
'''


def cli(tmp_path, body):
    path = tmp_path / 'fake-cli'
    path.write_text(f'#!{sys.executable}\n' + '''import sys, json, time, select, os
sys.stdin = os.fdopen(sys.stdin.fileno(), 'rb', buffering=0)

def emit(value):
    print(json.dumps(value), flush=True)

''' + body)
    path.chmod(0o700)
    return path


def config(backend='pi', idle=2.0, reminder=0.2):
    return AnalysisConfig(backend, 'kimi/k3' if backend == 'pi' else 'gemini-3.1-pro-high',
                          'high' if backend == 'pi' else None, idle, 1, reminder)


def test_live_thinking_outlasts_idle_limit_and_receives_repeated_reminders(tmp_path):
    exe = cli(tmp_path, '''
initial = json.loads(sys.stdin.readline())
assert initial['type'] == 'prompt' and initial['message'].startswith('/skill:podcast-to-article ')
# A large initial prompt also exercises nonblocking, partial stdin writes.
assert len(initial['message']) > 100000
# Leave room for cold interpreter startup; still run longer than the idle budget.
for i in range(26):
    emit({'type': 'message_update', 'assistantMessageEvent': {'type': 'thinking_delta', 'delta': 'work'}})
    ready, _, _ = select.select([sys.stdin], [], [], 0.1)
    if ready:
        command = json.loads(sys.stdin.readline())
        assert command['type'] == 'steer'
        emit({'type': 'response', 'id': command['id'], 'command': 'steer', 'success': True})
        emit({'type': 'message_start', 'message': {'role': 'user', 'content': command['message']}})
        time.sleep(0.1)
''' + PI_FINAL)
    diagnostic = {}
    started = time.monotonic()
    result = invoke(tmp_path, 'x' * 120000, config(), diagnostic, exe)
    assert time.monotonic() - started > 2.0
    assert result['model'] == 'kimi/k3'
    assert diagnostic['activity_events'] >= 26
    assert diagnostic['reminders_delivered'] >= 2
    assert diagnostic['reminders_accepted'] >= diagnostic['reminders_delivered']
    assert diagnostic['exit_code'] == 0 and not diagnostic['timed_out']


def test_logs_and_reminder_acknowledgements_do_not_reset_idle_timer(tmp_path):
    exe = cli(tmp_path, '''
json.loads(sys.stdin.readline())
while True:
    print('telemetry heartbeat', flush=True)
    print('background log', file=sys.stderr, flush=True)
    ready, _, _ = select.select([sys.stdin], [], [], 0.05)
    if ready:
        cmd = json.loads(sys.stdin.readline())
        emit({'type': 'response', 'id': cmd['id'], 'command': 'steer', 'success': True})
''')
    diagnostic = {}
    with pytest.raises(AnalysisError, match='无可见进展'):
        invoke(tmp_path, 'task', config(), diagnostic, exe)
    assert diagnostic['timeout_reason'] == 'idle' and diagnostic['timed_out']
    assert diagnostic['activity_events'] == 0 and diagnostic['idle_seconds'] >= 2.0
    # Do not pile up reminders while the first one is still waiting for the model.
    assert diagnostic['reminders_sent'] == 1 and diagnostic['reminders_accepted'] == 1
    assert diagnostic['reminders_delivered'] == 0
    assert 'heartbeat' not in json.dumps(diagnostic)


def test_zero_disables_idle_watchdog_and_reminders(tmp_path):
    exe = cli(tmp_path, '''
json.loads(sys.stdin.readline())
time.sleep(0.8)
''' + PI_FINAL)
    diagnostic = {}
    invoke(tmp_path, 'task', config(idle=0, reminder=0), diagnostic, exe)
    assert diagnostic['reminders_sent'] == 0 and not diagnostic['timed_out']


def test_rpc_prompt_rejection_is_classified_without_waiting_for_idle(tmp_path):
    exe = cli(tmp_path, '''
cmd = json.loads(sys.stdin.readline())
emit({'type': 'response', 'id': cmd['id'], 'command': 'prompt', 'success': False,
      'error': 'invalid API key secret-value'})
for line in sys.stdin:
    pass
''')
    diagnostic = {}
    with pytest.raises(AnalysisError) as failure:
        invoke(tmp_path, 'task', config(idle=10), diagnostic, exe)
    assert failure.value.category == 'auth'
    assert not diagnostic['timed_out']
    assert 'secret-value' not in json.dumps(diagnostic)


def test_agy_step_activity_and_stream_result(tmp_path):
    exe = cli(tmp_path, '''
for i in range(26):
    emit({'event': 'step_update', 'step_update': {'step_index': i, 'step_type': 'agent_response',
          'state': 'ACTIVE', 'text_delta': 'work'}})
    time.sleep(0.1)
emit({'event': 'result', 'result': {'status': 'SUCCESS', 'usage': {'input_tokens': 5}}})
''')
    diagnostic = {}
    result = invoke(tmp_path, 'task', config('agy'), diagnostic, exe)
    assert result['usage']['input_tokens'] == 5
    assert diagnostic['activity_events'] == 26 and not diagnostic['reminders_supported']
    assert not diagnostic['timed_out']


def test_agy_repeated_state_without_delta_does_not_count_as_progress(tmp_path):
    exe = cli(tmp_path, '''
while True:
    emit({'event': 'step_update', 'step_update': {'step_index': 1, 'step_type': 'agent_response',
          'state': 'ACTIVE'}})
    time.sleep(0.1)
''')
    diagnostic = {}
    with pytest.raises(AnalysisError, match='无可见进展'):
        invoke(tmp_path, 'task', config('agy'), diagnostic, exe)
    assert diagnostic['activity_events'] == 1
    assert diagnostic['timed_out']


def test_eof_without_settled_is_failure(tmp_path):
    exe = cli(tmp_path, '''
json.loads(sys.stdin.readline())
emit({'type': 'agent_end'})
''')
    with pytest.raises(AnalysisError) as failure:
        invoke(tmp_path, 'task', config(), {}, exe)
    assert failure.value.category == 'invalid_response'


def test_running_diagnostics_are_updated_before_completion(tmp_path, monkeypatch):
    clock = time.monotonic
    monkeypatch.setattr(analysis_runner, 'time', SimpleNamespace(
        monotonic=lambda: clock() * 100, sleep=time.sleep))
    exe = cli(tmp_path, '''
json.loads(sys.stdin.readline())
emit({'type': 'tool_execution_start', 'toolName': 'read'})
time.sleep(0.8)
''' + PI_FINAL)
    diagnostic, snapshots = {}, []
    invoke(tmp_path, 'task', config(idle=500, reminder=0), diagnostic, exe,
           on_update=lambda: snapshots.append(dict(diagnostic)))
    active = [s for s in snapshots if s['last_activity_kind'] == 'tool_execution_start']
    assert len(active) >= 2
    assert active[0]['last_activity_at']
    assert active[-1]['idle_seconds'] > active[0]['idle_seconds']


@pytest.mark.parametrize('name', ['PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', 'PODCAST_ANALYSIS_REMINDER_SECONDS'])
@pytest.mark.parametrize('value', ['NaN', 'inf', '-1', '86401', 'oops'])
def test_invalid_monitor_configuration(name, value, monkeypatch):
    monkeypatch.setenv(name, value)
    with pytest.raises(AnalysisError):
        AnalysisConfig.from_env()


def test_legacy_total_timeout_is_ignored(monkeypatch):
    monkeypatch.setenv('PODCAST_ANALYSIS_TIMEOUT_SECONDS', '1')
    monkeypatch.delenv('PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS', raising=False)
    monkeypatch.delenv('PODCAST_ANALYSIS_REMINDER_SECONDS', raising=False)
    value = AnalysisConfig.from_env()
    assert value.idle_timeout == 1200 and value.reminder_interval == 900


def test_codex_stream_stdin_activity_and_success(tmp_path):
    exe = cli(tmp_path, '''
prompt = sys.stdin.read().decode()
assert 'Codex 文件工具适配' in prompt and 'task' in prompt
assert sys.argv[sys.argv.index('--model') + 1] == 'gpt-6.1-sol'
assert 'model_reasoning_effort="high"' in sys.argv
emit({'type': 'turn.started'})
for i in range(26):
    emit({'type': 'item.completed', 'item': {'id': str(i), 'type': 'reasoning', 'text': 'work'}})
    time.sleep(0.1)
emit({'type': 'turn.completed', 'usage': {'input_tokens': 5, 'output_tokens': 3}})
''')
    cfg = AnalysisConfig('codex', 'gpt-6.1-sol', 'high', 2.0, 1)
    diagnostic = {}
    result = invoke(tmp_path, 'task', cfg, diagnostic, exe)
    assert result['model'] == 'gpt-6.1-sol'
    assert diagnostic['activity_events'] == 26 and not diagnostic['reminders_supported']
    assert diagnostic['status'] == 'COMPLETED' and not diagnostic['timed_out']


@pytest.mark.parametrize('event', [
    {'type': 'error', 'message': 'Reconnecting...'},
    {'type': 'item.updated', 'item': {'id': 'same', 'type': 'command_execution', 'status': 'in_progress'}},
])
def test_codex_retry_logs_and_duplicate_snapshots_do_not_extend_idle(tmp_path, event):
    exe = cli(tmp_path, f'''
sys.stdin.read()
while True:
    emit({event!r})
    time.sleep(0.1)
''')
    diagnostic = {}
    with pytest.raises(AnalysisError, match='无可见进展'):
        invoke(tmp_path, 'task', AnalysisConfig('codex', 'gpt-6.1-sol', 'high', 2.0, 1), diagnostic, exe)
    assert diagnostic['activity_events'] <= 1 and diagnostic['timed_out']


@pytest.mark.parametrize('events,category', [
    ([{'type': 'turn.started'}], 'invalid_response'),
    ([{'type': 'turn.failed', 'error': {'message': 'invalid API key secret'}}], 'auth'),
    ([{'type': 'turn.completed'}, {'type': 'turn.started'}], 'invalid_response'),
])
def test_codex_requires_completed_final_turn(tmp_path, events, category):
    exe = cli(tmp_path, f'''
sys.stdin.read()
for event in {events!r}: emit(event)
''')
    diagnostic = {}
    with pytest.raises(AnalysisError) as exc:
        invoke(tmp_path, 'task', AnalysisConfig('codex', 'gpt-6.1-sol', 'high', 5, 1), diagnostic, exe)
    assert exc.value.category == category
    assert 'secret' not in json.dumps(diagnostic)


def test_codex_preserves_provider_config_but_disables_unrelated_tools(tmp_path, monkeypatch):
    home = tmp_path / 'codex-home'
    home.mkdir()
    settings = '''model_provider = "private"
[model_providers.private]
experimental_bearer_token = "secret-token"
[mcp_servers.node_repl]
command = "some-command"
[plugins."documents@local"]
enabled = true
'''
    (home / 'config.toml').write_text(settings)
    argv = analysis_runner._codex_argv('codex', AnalysisConfig('codex', 'gpt-6.1-sol', 'high', 1200, 2))
    assert '--ignore-user-config' not in argv
    assert 'secret-token' not in str(argv)
    assert 'mcp_servers.node_repl.enabled=false' in argv
    assert 'plugins.documents@local.enabled=false' in argv
    assert 'hooks.SessionStart=[]' in argv
    assert (home / 'config.toml').read_text() == settings
