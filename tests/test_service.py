import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server.app as app_module
import server.jobs as jobs_module
from server.jobs import Job, JobManager
from server.subscriptions import SubscriptionStore

URL = "https://www.xiaoyuzhoufm.com/episode/" + "a" * 24


class NoopSubscriptions:
    def __init__(self, store):
        self.store = store
        self._wake = threading.Event()

    def start(self):
        pass

    def stop(self):
        pass


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    uploads = tmp_path / "uploads"
    jobs.mkdir()
    uploads.mkdir()
    monkeypatch.setattr(jobs_module, "JOBS_ROOT", jobs)
    monkeypatch.setattr(jobs_module, "UPLOAD_ROOT", uploads)
    monkeypatch.setattr(app_module, "JOBS_ROOT", jobs)
    manager = JobManager()
    monkeypatch.setattr(app_module, "manager", manager)
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    monkeypatch.setattr(app_module, "subscription_service", NoopSubscriptions(store))
    yield manager, jobs, uploads, store
    manager.shutdown()


@pytest.fixture
def pipeline(isolated, monkeypatch):
    manager, jobs, uploads, store = isolated
    seen = {"transcribe": 0, "clean": 0, "analyze": 0, "mimo": 0}

    def remote(source, *, backend, **options):
        assert source.is_file()
        seen["remote_options"] = options
        if backend == "mimo":
            return mimo(source, **options)
        seen["transcribe"] += 1
        return {"language": "zh", "text": "Cloud 测试",
                "segments": [{"start": 0, "end": 1, "text": "Cloud 测试"}],
                "turns": [{"id": "turn_000001", "start": 0, "end": 1, "text": "Cloud 测试"}]}

    def clean(turns):
        seen["clean"] += 1
        return [{**turns[0], "text": "Claude 测试。"}], {
            "corrections": [{"to": "Claude"}],
            "meta": {},
        }

    def mimo(source, **options):
        seen["mimo"] += 1
        seen["mimo_options"] = options
        return {
            "text": "MiMo 原文。",
            "segments": [],
            "turns": [
                {"id": "turn_000001", "start": 0, "end": 2, "text": "MiMo 原文。"}
            ],
        }

    def analyze(directory, episode=None, on_progress=None):
        seen["analyze"] += 1
        # Audio is deleted before agy; other queued uploads are allowed.
        assert not list(uploads.glob("**/source.m4a"))
        assert (directory / "transcript.txt").is_file()
        for name in ("article.md", "notes.md", "mindmap.md"):
            (directory / name).write_text("# 测试\n\n正文", encoding="utf-8")

    monkeypatch.setattr(jobs_module, "transcribe_remote", remote)
    monkeypatch.setattr(jobs_module, "process_turns", clean)
    monkeypatch.setattr(jobs_module, "analyze_markdown", analyze)
    return seen


def wait(manager, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job.status in {"done", "error"}:
            return job
        time.sleep(0.01)
    raise AssertionError("job did not complete")


def upload(client, **options):
    response = client.post(
        "/api/jobs", files={"file": ("sample.m4a", b"audio", "audio/mp4")}, data={"backend": "whisper", **options}
    )
    assert response.status_code == 202, response.text
    return response.json()["job_id"]


def test_health_reports_available_backends_without_secrets(isolated):
    response = TestClient(app_module.app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["worker"] == "single"
    assert response.json()["read_only"] is False
    assert set(response.json()["backends"]) == {"qwen", "whisper", "mimo"}


def test_whisper_cleans_then_generates_markdown_only(isolated, pipeline):
    manager, jobs, uploads, _ = isolated
    with TestClient(app_module.app) as client:
        job_id = upload(client)
        state = wait(manager, job_id)
        assert state.status == "done", state.error
        assert client.get(f"/api/jobs/{job_id}/files/article.md").status_code == 200
        assert client.get(f"/api/jobs/{job_id}/notes").status_code == 404
        assert client.get(f"/api/jobs/{job_id}/files/audio.m4a").status_code == 404
    assert pipeline["clean"] == 1 and pipeline["analyze"] == 1
    assert pipeline["remote_options"]["skip_diarization"] is True  # default is no separation
    assert not list(uploads.glob("**/*"))
    root = jobs / job_id
    assert (root / "transcript.txt").read_text() == "[00:00:00] Claude 测试。"
    assert (
        json.loads((root / "transcript.raw.json").read_text())["text"] == "Cloud 测试"
    )
    assert (
        json.loads((root / "corrections.json").read_text())["corrections"][0]["to"]
        == "Claude"
    )
    assert not (root / "notes.json").exists()


@pytest.mark.parametrize("skip", [True, False])
def test_mimo_backend_with_optional_diarization_no_cleaning(isolated, pipeline, skip):
    manager = isolated[0]
    client = TestClient(app_module.app)
    job_id = upload(
        client, backend="mimo", skip_diarization=str(skip).lower(), num_speakers="2"
    )
    state = wait(manager, job_id)
    assert state.status == "done", state.error
    assert pipeline["mimo"] == 1 and pipeline["transcribe"] == pipeline["clean"] == 0
    assert pipeline["mimo_options"]["skip_diarization"] is skip
    assert pipeline["mimo_options"]["num_speakers"] == 2


def test_whisper_optional_speaker_count(isolated, pipeline):
    job_id = upload(
        TestClient(app_module.app), skip_diarization="false", num_speakers="2"
    )
    assert wait(isolated[0], job_id).status == "done"
    assert pipeline["remote_options"]["num_speakers"] == 2


def test_reanalysis_reuses_transcript_without_asr_or_audio(isolated, pipeline):
    manager = isolated[0]
    client = TestClient(app_module.app)
    job_id = upload(client)
    assert wait(manager, job_id).status == "done"
    assert client.post(f"/api/jobs/{job_id}/analyze").status_code == 202
    assert wait(manager, job_id).status == "done"
    assert pipeline["transcribe"] == pipeline["clean"] == 1
    assert pipeline["analyze"] == 2
    response = client.post(f"/api/jobs/{job_id}/retry", json={"backend": "mimo"})
    assert response.status_code == 409
    assert "重新上传" in response.json()["detail"]


def test_analysis_failure_keeps_transcript_and_cleans_audio(
    isolated, pipeline, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("agy unavailable")

    monkeypatch.setattr(jobs_module, "analyze_markdown", fail)
    job_id = upload(TestClient(app_module.app))
    state = wait(isolated[0], job_id)
    assert state.status == "error"
    assert (isolated[1] / job_id / "transcript.txt").is_file()
    assert not list(isolated[2].glob("**/*"))


def test_asr_failure_cleans_audio(isolated, pipeline, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("asr failed")

    monkeypatch.setattr(jobs_module, "transcribe_remote", fail)
    job_id = upload(TestClient(app_module.app))
    assert wait(isolated[0], job_id).status == "error"
    assert not list(isolated[2].glob("**/*"))
    assert pipeline["analyze"] == 0


def test_ensure_roots_never_deletes_other_uploads(isolated):
    _, _, uploads, _ = isolated
    directory = uploads / "job-other"
    directory.mkdir()
    (directory / "source.m4a").write_bytes(b"queued")
    jobs_module.ensure_roots()
    assert (directory / "source.m4a").read_bytes() == b"queued"


def test_jobs_survive_manager_restart(isolated, pipeline):
    job_id = upload(TestClient(app_module.app))
    assert wait(isolated[0], job_id).status == "done"
    recovered = JobManager()
    try:
        recovered.start()
        assert recovered.get(job_id).status == "done"
        assert recovered.list()[0].id == job_id
    finally:
        recovered.shutdown()


def test_recover_interrupted_upload_requires_reupload(isolated):
    manager, _, _, _ = isolated
    job = Job(
        id="f" * 32, filename="upload.m4a", status="running", stage="transcribing"
    )
    manager._persist(job)
    recovered = JobManager()
    try:
        recovered.start()
        assert recovered.get(job.id).status == "error"
        assert "重新上传" in recovered.get(job.id).error
    finally:
        recovered.shutdown()


def test_recover_analysis_needs_no_audio(isolated, pipeline):
    manager, root, _, _ = isolated
    job = Job(
        id="f" * 32,
        filename="upload.m4a",
        status="running",
        stage="analyzing",
        operation="analyze",
    )
    manager._persist(job)
    (root / job.id / "transcript.txt").write_text("[00:00:00] 原文")
    recovered = JobManager()
    try:
        recovered.start()
        assert wait(recovered, job.id).status == "done"
        assert pipeline["transcribe"] == 0
    finally:
        recovered.shutdown()


def test_url_dedup_and_backend_retry(isolated, pipeline, monkeypatch):
    import fetch

    seen = []

    def fetch_episode(url, *, download_dir):
        seen.append(url)
        path = download_dir / "source.m4a"
        path.write_bytes(b"audio")
        return {"url": url, "title": "节目", "audio_path": path}

    monkeypatch.setattr(fetch, "fetch_episode", fetch_episode)
    manager = isolated[0]
    first = manager.create_from_url(URL)
    assert manager.create_from_url(URL).id == first.id
    assert wait(manager, first.id).status == "done"
    manager.retry(first.id, backend="mimo", skip_diarization=False, num_speakers=2)
    assert wait(manager, first.id).status == "done"
    assert len(seen) == 2 and pipeline["mimo"] == 1
    assert list((isolated[1] / first.id / "history").iterdir())


def test_invalid_options_and_sources_rejected(isolated):
    client = TestClient(app_module.app)
    for data in ({"backend": "bad"}, {"num_speakers": "0"}, {"num_speakers": "33"}):
        assert (
            client.post(
                "/api/jobs", data=data, files={"file": ("x.m4a", b"x")}
            ).status_code
            == 400
        )
    assert (
        client.post(
            "/api/jobs", data={"url": "https://example.com/episode/" + "a" * 24}
        ).status_code
        == 400
    )
    assert (
        client.post("/api/jobs", files={"file": ("empty.mp3", b"")}).status_code == 400
    )
    assert client.get("/api/jobs/not-an-id").status_code == 400
    assert client.get("/api/jobs/" + "f" * 32).status_code == 404
    assert not list(isolated[2].glob("**/*"))


def test_manager_executes_jobs_serially(isolated, pipeline, monkeypatch):
    manager, _, uploads, _ = isolated
    active = maximum = 0
    mutex = threading.Lock()
    release = threading.Event()
    original = jobs_module.transcribe_remote

    def transcribe(*args, **kwargs):
        nonlocal active, maximum
        with mutex:
            active += 1
            maximum = max(maximum, active)
        release.wait(timeout=2)
        result = original(*args, **kwargs)
        with mutex:
            active -= 1
        return result

    monkeypatch.setattr(jobs_module, "transcribe_remote", transcribe)
    # No global empty-upload assertion: a second queued upload legitimately exists.
    monkeypatch.setattr(jobs_module, "analyze_markdown", lambda root, *a, **kw: None)
    ids = []
    for index in range(2):
        _, source = jobs_module.save_upload(
            __import__("io").BytesIO(b"audio"), f"{index}.m4a"
        )
        ids.append(manager.create(f"{index}.m4a", source).id)
    time.sleep(0.05)
    assert maximum == 1
    release.set()
    for job_id in ids:
        assert wait(manager, job_id).status == "done"
    assert maximum == 1 and not list(uploads.glob("**/*"))


def test_episode_reading_routes_keep_legacy_links(isolated):
    _, root, _, store = isolated
    feed = {
        "podcast_id": "pod",
        "source_url": URL,
        "title": "测试",
        "episodes": [
            {"eid": "a" * 24, "episode_url": URL, "title": "节目", "processable": True}
        ],
    }
    store.create_subscription(feed, poll_interval_minutes=30, initial_backfill=1)
    episode_id = store.list_episodes(1)[0]["id"]
    client = TestClient(app_module.app)
    assert client.get(f"/episodes/{episode_id}/transcript").status_code == 409
    metadata = client.get(f"/api/episodes/{episode_id}").json()
    for field in ("result_dir", "audio_url", "error"):
        assert field not in metadata
    directory = root / "legacy"
    directory.mkdir()
    (directory / "transcript.txt").write_text("[00:00:00] 原文")
    (directory / "article.md").write_text("# 报道")
    store.finish_episode(episode_id, directory)
    assert client.get(f"/episodes/{episode_id}/transcript").status_code == 200
    assert client.get(f"/api/episodes/{episode_id}/files/article.md").text == "# 报道"
    assert client.get(f"/api/episodes/{episode_id}/files/audio.m4a").status_code == 404
    assert client.get("/episodes/9999/transcript").status_code == 404


def test_internal_state_is_not_in_job_dto(isolated, pipeline):
    client = TestClient(app_module.app)
    job_id = upload(client)
    wait(isolated[0], job_id)
    state = client.get(f"/api/jobs/{job_id}").json()
    assert "result_dir" not in state
    assert client.get("/api/jobs").json()[0]["id"] == job_id
    assert client.get(f"/api/jobs/{job_id}/files/job.json").status_code == 404


def test_shutdown_cancels_queued_upload_and_preserves_queued_url(
    isolated, pipeline, monkeypatch
):
    import fetch

    manager, _, uploads, _ = isolated
    started, release = threading.Event(), threading.Event()
    original = jobs_module.transcribe_remote

    def blocked(source, **kwargs):
        started.set()
        assert release.wait(2)
        return original(source, **kwargs)

    monkeypatch.setattr(jobs_module, "transcribe_remote", blocked)
    monkeypatch.setattr(jobs_module, "analyze_markdown", lambda *a, **kw: None)
    monkeypatch.setattr(
        fetch,
        "fetch_episode",
        lambda *a, **kw: pytest.fail("cancelled URL must not download"),
    )
    first = upload(TestClient(app_module.app))
    assert started.wait(1)
    second = upload(TestClient(app_module.app))
    queued_url = manager.create_from_url(URL)
    stopping = threading.Thread(target=manager.shutdown)
    stopping.start()
    time.sleep(0.05)
    release.set()
    stopping.join(timeout=3)
    assert not stopping.is_alive()
    assert manager.get(first).status == "done"
    assert manager.get(second).status == "error"
    assert manager.get(queued_url.id).status == "queued"
    assert pipeline["transcribe"] == 1
    assert not list(uploads.glob("**/*"))


def test_retry_archive_intent_is_persisted_and_resumable(
    isolated, pipeline, monkeypatch
):
    import fetch

    manager, roots, _, _ = isolated

    def fetch_episode(url, *, download_dir):
        source = download_dir / "source.m4a"
        source.write_bytes(b"audio")
        return {"url": url, "title": "节目", "audio_path": source}

    monkeypatch.setattr(fetch, "fetch_episode", fetch_episode)
    job = manager.create_from_url(URL)
    assert wait(manager, job.id).status == "done"
    original = Path.replace

    def fail_notes_once(source, destination):
        if source.name == "notes.md" and "history" in Path(destination).parts:
            assert (
                json.loads((roots / job.id / "job.json").read_text())["status"]
                != "done"
            )
            raise OSError("simulated disk error")
        return original(source, destination)

    monkeypatch.setattr(Path, "replace", fail_notes_once)
    manager.retry(job.id)
    failed = wait(manager, job.id)
    assert failed.status == "error" and failed.archive_pending
    with pytest.raises(ValueError, match="归档"):
        manager.reanalyze(job.id)
    monkeypatch.setattr(Path, "replace", original)
    manager.retry(job.id)
    assert wait(manager, job.id).status == "done"
    assert len(list((roots / job.id / "history").iterdir())) == 1


def test_metadata_merge_keeps_subscription_details(isolated, pipeline, monkeypatch):
    import fetch

    def fetch_episode(url, *, download_dir):
        source = download_dir / "source.m4a"
        source.write_bytes(b"audio")
        return {
            "url": url,
            "title": "新标题",
            "description": "",
            "podcast_title": "",
            "duration": 0,
            "audio_path": source,
        }

    monkeypatch.setattr(fetch, "fetch_episode", fetch_episode)
    manager = isolated[0]
    job = manager.create_from_url(
        URL,
        episode_metadata={
            "title": "旧标题",
            "description": "原简介",
            "podcast_title": "播客名",
            "duration": 123,
        },
    )
    done = wait(manager, job.id)
    assert done.status == "done"
    assert done.episode["title"] == "新标题"
    assert done.episode["description"] == "原简介" and done.episode["duration"] == 123
    assert done.episode["podcast_title"] == "播客名"


def test_before_requeue_invalidates_public_state_before_artifact_changes(
    isolated, pipeline
):
    manager = isolated[0]
    job_id = upload(TestClient(app_module.app))
    assert wait(manager, job_id).status == "done"
    called = []

    def before(job):
        called.append(job.id)
        assert manager.get(job_id).status == "done"
        assert (jobs_module.result_directory(job) / "article.md").is_file()

    manager.reanalyze(job_id, before_requeue=before)
    assert wait(manager, job_id).status == "done"
    assert called == [job_id]


def test_provider_error_does_not_persist_configured_key(
    isolated, pipeline, monkeypatch
):
    key = "fixture-secret-provider-key"
    monkeypatch.setenv("MIMO_API_KEY", key)

    def fail(*args, **kwargs):
        raise RuntimeError(f"request rejected: {key}")

    monkeypatch.setattr(jobs_module, "transcribe_remote", fail)
    job_id = upload(TestClient(app_module.app), backend="mimo")
    job = wait(isolated[0], job_id)
    assert job.status == "error" and key not in job.error
    assert "[REDACTED]" in job.error
    assert key not in (isolated[1] / job_id / "job.json").read_text()


def test_missing_react_build_returns_actionable_503(isolated, monkeypatch):
    from server import web_ui

    monkeypatch.setattr(web_ui, "WEB_DIST", isolated[1] / "missing-dist")
    response = TestClient(app_module.app).get("/")
    assert response.status_code == 503
    assert "npm" in response.json()["detail"]


def test_configured_speaker_count(monkeypatch):
    monkeypatch.delenv("WHISPER_NUM_SPEAKERS", raising=False)
    assert jobs_module._configured_speaker_count() is None
    monkeypatch.setenv("WHISPER_NUM_SPEAKERS", "2")
    assert jobs_module._configured_speaker_count() == 2
    monkeypatch.setenv("WHISPER_NUM_SPEAKERS", "bad")
    with pytest.raises(ValueError, match="正整数"):
        jobs_module._configured_speaker_count()
