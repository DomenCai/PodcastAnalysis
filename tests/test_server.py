import importlib
import threading
import time

from fastapi.testclient import TestClient

server_module = importlib.import_module("server.app")


def _reset_tasks():
    with server_module._tasks_lock:
        server_module._tasks.clear()
        server_module._running_task_id = None


def test_server_package_exports_asgi_app():
    package = importlib.import_module("server")
    assert package.app is server_module.app


def test_list_episodes_skips_corrupt_meta(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    good = tmp_path / "6a2d134143a22a6955830bfe"
    good.mkdir()
    (good / "meta.json").write_text(
        '{"title":"标题","podcast_title":"播客","duration":60}',
        encoding="utf-8",
    )
    (good / "transcript.txt").write_text("逐字稿", encoding="utf-8")

    corrupt = tmp_path / "6a2ea7064233e62bc549afed"
    corrupt.mkdir()
    (corrupt / "meta.json").write_text("{bad json", encoding="utf-8")

    invalid_name = tmp_path / "not-an-id"
    invalid_name.mkdir()
    (invalid_name / "meta.json").write_text('{"title":"bad"}', encoding="utf-8")

    response = TestClient(server_module.app).get("/api/episodes")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "6a2d134143a22a6955830bfe",
            "title": "标题",
            "podcast_title": "播客",
            "duration": 60,
            "has_transcript": True,
            "has_summary": False,
        }
    ]


def test_episode_id_validation_and_missing_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()
    client = TestClient(server_module.app)

    invalid = client.get("/api/episodes/not-valid")
    assert invalid.status_code == 400

    missing_summary = client.get("/api/episodes/6a2d134143a22a6955830bfe/summary")
    assert missing_summary.status_code == 404


def test_post_episode_invalid_url_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    response = TestClient(server_module.app).post("/api/episodes", json={"url": "https://example.com"})

    assert response.status_code == 400


def test_post_episode_running_task_returns_409(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    task_id = "a" * 32
    with server_module._tasks_lock:
        server_module._running_task_id = task_id
        server_module._tasks[task_id] = server_module.TaskState(
            task_id=task_id,
            episode_id="6a2d134143a22a6955830bfe",
            stage="transcribing",
            done=1,
            total=2,
            status="running",
            error=None,
        )

    response = TestClient(server_module.app).post(
        "/api/episodes",
        json={"url": "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe"},
    )

    assert response.status_code == 409


def test_get_task_invalid_id_returns_400(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    response = TestClient(server_module.app).get("/api/tasks/not-a-task")

    assert response.status_code == 400


def test_delete_episode_removes_episode_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    episode = tmp_path / "6a2d134143a22a6955830bfe"
    episode.mkdir()
    (episode / "meta.json").write_text('{"title":"标题"}', encoding="utf-8")
    (episode / "transcript.txt").write_text("逐字稿", encoding="utf-8")

    response = TestClient(server_module.app).delete("/api/episodes/6a2d134143a22a6955830bfe")

    assert response.status_code == 204
    assert not episode.exists()


def test_delete_episode_running_task_returns_409(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    episode = tmp_path / "6a2d134143a22a6955830bfe"
    episode.mkdir()

    task_id = "a" * 32
    with server_module._tasks_lock:
        server_module._running_task_id = task_id
        server_module._tasks[task_id] = server_module.TaskState(
            task_id=task_id,
            episode_id="6a2d134143a22a6955830bfe",
            stage="transcribing",
            done=1,
            total=2,
            status="running",
            error=None,
        )

    response = TestClient(server_module.app).delete("/api/episodes/6a2d134143a22a6955830bfe")

    assert response.status_code == 409
    assert episode.exists()


def test_regenerate_episode_requires_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    episode = tmp_path / "6a2d134143a22a6955830bfe"
    episode.mkdir()
    (episode / "meta.json").write_text('{"title":"标题"}', encoding="utf-8")

    response = TestClient(server_module.app).post(
        "/api/episodes/6a2d134143a22a6955830bfe/regenerate",
        json={"transcript": False, "summary": False},
    )

    assert response.status_code == 400


def test_regenerate_episode_endpoint_reports_transcript_progress(tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "OUTPUT_ROOT", tmp_path)
    _reset_tasks()

    episode_id = "6a2d134143a22a6955830bfe"
    episode = tmp_path / episode_id
    episode.mkdir()
    (episode / "meta.json").write_text('{"title":"标题"}', encoding="utf-8")

    progress_seen = threading.Event()
    finish = threading.Event()

    def fake_regenerate_episode(
        called_episode_id,
        transcript=False,
        summary=False,
        output_root="output",
        on_event=None,
    ):
        assert called_episode_id == episode_id
        assert transcript is True
        assert summary is False
        assert output_root == str(tmp_path)
        on_event("transcribing", 2, 5)
        progress_seen.set()
        finish.wait(timeout=1)

    monkeypatch.setattr(server_module, "regenerate_episode", fake_regenerate_episode)

    client = TestClient(server_module.app)
    response = client.post(
        f"/api/episodes/{episode_id}/regenerate",
        json={"transcript": True, "summary": False},
    )

    assert response.status_code == 200
    task_id = response.json()["task_id"]
    assert progress_seen.wait(timeout=1)

    task = client.get(f"/api/tasks/{task_id}")

    assert task.status_code == 200
    assert task.json() == {
        "task_id": task_id,
        "episode_id": episode_id,
        "stage": "transcribing",
        "done": 2,
        "total": 5,
        "status": "running",
        "error": None,
    }

    finish.set()
    deadline = time.monotonic() + 1
    while time.monotonic() < deadline:
        if client.get(f"/api/tasks/{task_id}").json()["status"] == "done":
            break
        time.sleep(0.01)


def test_static_dist_serves_index_assets_and_spa_fallback(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text(
        '<div id="root"></div><script src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets / "app.js").write_text('console.log("ok");', encoding="utf-8")
    monkeypatch.setattr(server_module, "WEB_DIST", dist)

    client = TestClient(server_module.app)

    index = client.get("/")
    asset = client.get("/assets/app.js")
    fallback = client.get("/episodes/6a2d134143a22a6955830bfe")

    assert index.status_code == 200
    assert '<div id="root"></div>' in index.text
    assert asset.status_code == 200
    assert 'console.log("ok");' in asset.text
    assert fallback.status_code == 200
    assert '<div id="root"></div>' in fallback.text
