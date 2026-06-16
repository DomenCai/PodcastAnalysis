import importlib

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
