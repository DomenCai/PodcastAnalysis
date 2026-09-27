import json

import httpx
import pytest

from server import transcription_client as module


def test_client_streams_audio_and_reuses_remote_job(tmp_path, monkeypatch):
    source = tmp_path / "episode.wav"
    source.write_bytes(b"original audio")
    requests = []

    def handle(request):
        requests.append(request)
        if request.method == "POST":
            assert b"original audio" in request.read()
            assert b'"backend": "qwen"' in request.content
            return httpx.Response(202, json={"id": "remote-id"})
        if request.url.path.endswith("/result"):
            return httpx.Response(200, json={"text": "逐字稿", "segments": []})
        return httpx.Response(200, json={"status": "done", "stage": "done"})

    client_class = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kw: client_class(
        **kw, transport=httpx.MockTransport(handle)))
    for _ in range(2):
        assert module.transcribe(source, result_dir=tmp_path)["text"] == "逐字稿"
    assert sum(r.method == "POST" for r in requests) == 1
    assert source.read_bytes() == b"original audio"


def test_client_does_not_hide_remote_failure(tmp_path, monkeypatch):
    source = tmp_path / "episode.wav"
    source.write_bytes(b"audio")
    (tmp_path / "transcription-job.json").write_text(json.dumps({
        "id": "failed", "service": module.service_url(),
        "options": {"backend": "qwen", "skip_diarization": True, "num_speakers": None},
    }))
    client_class = httpx.Client
    monkeypatch.setattr(module.httpx, "Client", lambda **kw: client_class(
        **kw, transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
            "status": "error", "stage": "error", "error": "batch incomplete",
        }))))
    with pytest.raises(RuntimeError, match="batch incomplete"):
        module.transcribe(source, result_dir=tmp_path)


def test_status_connection_reset_is_retried_without_duplicate_upload(tmp_path, monkeypatch):
    source = tmp_path / 'audio.wav'
    source.write_bytes(b'audio')
    attempts = []

    def handle(request):
        attempts.append(request.method)
        if request.method == 'POST':
            return httpx.Response(202, json={'id': 'one-job'})
        if len(attempts) == 2:
            raise httpx.ReadError('connection reset', request=request)
        if request.url.path.endswith('/result'):
            return httpx.Response(200, json={'text': 'ready'})
        return httpx.Response(200, json={'status': 'done', 'stage': 'done'})

    cls = httpx.Client
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: cls(**kw, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(module.time, 'sleep', lambda _: None)
    assert module.transcribe(source, result_dir=tmp_path)['text'] == 'ready'
    assert attempts.count('POST') == 1


def test_explicit_resume_retries_failed_remote_job_without_source(tmp_path, monkeypatch):
    options = {'backend': 'qwen', 'skip_diarization': True, 'num_speakers': None}
    (tmp_path / 'transcription-job.json').write_text(json.dumps({
        'id': 'remote-id', 'service': module.service_url(), 'options': options,
    }))
    requests = []

    def handle(request):
        requests.append((request.method, request.url.path))
        if len(requests) == 1:
            return httpx.Response(200, json={'status': 'error'})
        if request.method == 'POST':
            assert request.url.path.endswith('/remote-id/retry')
            return httpx.Response(202, json={'status': 'queued'})
        if request.url.path.endswith('/result'):
            return httpx.Response(200, json={'text': 'resumed'})
        return httpx.Response(200, json={'status': 'done', 'stage': 'done'})

    cls = httpx.Client
    monkeypatch.setattr(module.httpx, 'Client', lambda **kw: cls(**kw, transport=httpx.MockTransport(handle)))
    assert module.transcribe(tmp_path / 'missing-audio', result_dir=tmp_path, retry_failed=True)['text'] == 'resumed'
    assert len([r for r in requests if r[0] == 'POST']) == 1
