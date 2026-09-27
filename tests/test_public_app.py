from fastapi.testclient import TestClient

import server.public_app as public_module
import server.public_catalog as catalog
from server.subscriptions import SubscriptionStore


def _seed_store(
    tmp_path, *, finish: bool, with_transcript: bool = True
) -> tuple[SubscriptionStore, int]:
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    feed = {
        "podcast_id": "pod",
        "source_url": "https://www.xiaoyuzhoufm.com/podcast/pod",
        "title": "测试播客",
        "author": "作者",
        "description": "简介",
        "episode_count": 1,
        "latest_episode_at": "2026-01-02T00:00:00+00:00",
        "episodes": [
            {
                "eid": "ep1",
                "episode_url": "https://www.xiaoyuzhoufm.com/episode/ep1",
                "title": "第一期",
                "description": "节目简介完整内容",
                "published_at": "2026-01-01T00:00:00+00:00",
                "duration": 1800,
                "audio_url": "https://media.example.com/ep1.m4a",
                "processable": True,
            }
        ],
    }
    store.create_subscription(feed, poll_interval_minutes=30, initial_backfill=1)
    episode_id = store.list_episodes(1)[0]["id"]
    if finish:
        result_dir = tmp_path / "result"
        result_dir.mkdir()
        if with_transcript:
            (result_dir / "transcript.txt").write_text(
                "[00:00:00] 你好\n", encoding="utf-8"
            )
        store.finish_episode(episode_id, result_dir)
    return store, episode_id


def _client(
    tmp_path, monkeypatch, *, finish: bool, with_transcript: bool = True
) -> tuple[TestClient, int]:
    store, episode_id = _seed_store(
        tmp_path, finish=finish, with_transcript=with_transcript
    )
    monkeypatch.setattr(public_module, "store", store)
    return TestClient(public_module.app), episode_id


def test_public_app_only_allows_get_and_head(tmp_path, monkeypatch):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    monkeypatch.setattr(public_module, "store", store)
    client = TestClient(public_module.app)

    assert client.get("/api/health").json() == {"ok": True, "read_only": True}
    assert client.get("/api/subscriptions").status_code == 200
    assert client.post("/api/subscriptions", json={}).status_code == 405
    assert (
        client.put("/api/subscriptions/1/enabled", json={"enabled": True}).status_code
        == 405
    )
    assert client.delete("/api/subscriptions/1").status_code == 405
    assert client.patch("/api/subscriptions/1").status_code == 405


def test_public_routes_register_no_write_methods():
    write_methods = {"POST", "PUT", "PATCH", "DELETE"}
    for route in public_module.app.routes:
        assert not (set(getattr(route, "methods", set())) & write_methods)


def test_episode_metadata_only_exposes_safe_fields(tmp_path, monkeypatch):
    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    response = client.get(f"/api/episodes/{episode_id}")
    assert response.status_code == 200
    assert response.json() == {
        "id": episode_id,
        "eid": "ep1",
        "episode_url": "https://www.xiaoyuzhoufm.com/episode/ep1",
        "title": "第一期",
        "description": "节目简介完整内容",
        "published_at": "2026-01-01T00:00:00+00:00",
        "duration": 1800,
        "status": "done",
        "has_result": True,
        "available_files": ["transcript.txt"],
    }
    for internal in ("result_dir", "audio_url", "error", "media_mode", "attempts"):
        assert internal not in response.text


def test_episode_metadata_marks_unfinished_episode(tmp_path, monkeypatch):
    client, episode_id = _client(tmp_path, monkeypatch, finish=False)
    response = client.get(f"/api/episodes/{episode_id}")
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
    assert response.json()["has_result"] is False


def test_episode_metadata_missing_returns_404(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, finish=True)
    assert client.get("/api/episodes/9999").status_code == 404


def test_transcript_page_served_when_done(tmp_path, monkeypatch):
    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    response = client.get(f"/episodes/{episode_id}/transcript")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert "<html" in response.text
    assert "result_dir" not in response.text
    assert str(tmp_path) not in response.text


def test_transcript_page_missing_episode_returns_404(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, finish=True)
    assert client.get("/episodes/9999/transcript").status_code == 404


def test_transcript_page_unfinished_episode_returns_409(tmp_path, monkeypatch):
    client, episode_id = _client(tmp_path, monkeypatch, finish=False)
    assert client.get(f"/episodes/{episode_id}/transcript").status_code == 409


def test_transcript_page_missing_file_returns_404(tmp_path, monkeypatch):
    client, episode_id = _client(
        tmp_path, monkeypatch, finish=True, with_transcript=False
    )
    assert client.get(f"/episodes/{episode_id}/transcript").status_code == 404


def test_transcript_page_rejects_write_methods(tmp_path, monkeypatch):
    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    for method in ("post", "put", "patch", "delete"):
        assert (
            getattr(client, method)(f"/episodes/{episode_id}/transcript").status_code
            == 405
        )
        assert getattr(client, method)("/podcasts/1").status_code == 405


def test_podcast_page_served(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, finish=True)
    response = client.get("/podcasts/1")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_podcast_page_missing_subscription_returns_404(tmp_path, monkeypatch):
    client, _ = _client(tmp_path, monkeypatch, finish=True)
    assert client.get("/podcasts/9999").status_code == 404


def test_article_is_public_but_internal_files_audio_and_writes_are_not(
    tmp_path, monkeypatch
):
    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    root = tmp_path / "result"
    (root / "article.md").write_text("# 文章")
    (root / "episode.json").write_text('{"audio_url":"private"}')
    (root / "audio.m4a").write_bytes(b"audio")
    prefix = f"/api/episodes/{episode_id}/files/"
    assert client.get(prefix + "article.md").text == "# 文章"
    for name in ("episode.json", "audio.m4a", "job.json", "corrections.json"):
        assert client.get(prefix + name).status_code == 404
    assert client.get("/api/jobs").status_code == 404
    assert client.get("/jobs").status_code == 404
    for method in ("POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        assert client.request(method, prefix + "article.md").status_code == 405


def test_public_artifacts_reject_symlinks(tmp_path, monkeypatch):
    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    secret = tmp_path / "secret"
    secret.write_text("private")
    (tmp_path / "result" / "article.md").symlink_to(secret)
    assert client.get(f"/api/episodes/{episode_id}/files/article.md").status_code == 404


def test_react_asset_path_is_confined(tmp_path, monkeypatch):
    from server import web_ui

    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "main.js").write_text("console.log('ok')")
    outside = tmp_path / "secret.js"
    outside.write_text("private")
    (dist / "assets" / "escape.js").symlink_to(outside)
    monkeypatch.setattr(web_ui, "WEB_DIST", dist)
    client, _ = _client(tmp_path, monkeypatch, finish=True)
    assert client.get("/assets/main.js").status_code == 200
    assert client.get("/assets/escape.js").status_code == 404
    assert client.get("/assets/..%2F..%2Fsecret.js").status_code == 404


def test_public_store_is_sql_read_only_and_missing_db_is_503(tmp_path, monkeypatch):
    import sqlite3
    import pytest
    from server.public_store import ReadOnlySubscriptionStore

    missing = tmp_path / "missing" / "podcast.db"
    monkeypatch.setattr(public_module, "store", ReadOnlySubscriptionStore(missing))
    client = TestClient(public_module.app)
    assert client.get("/api/subscriptions").status_code == 503
    assert not missing.parent.exists()
    writable = SubscriptionStore(tmp_path / "podcast.db")
    writable.initialize()
    readonly = ReadOnlySubscriptionStore(writable.path)
    with readonly.connect() as db:
        assert db.execute("PRAGMA query_only").fetchone()[0] == 1
        with pytest.raises(sqlite3.OperationalError):
            db.execute("CREATE TABLE forbidden (id INTEGER)")
    monkeypatch.setattr(public_module, "store", readonly)
    assert client.get("/api/subscriptions").json() == []


def test_public_library_and_job_routes_are_read_only_and_confined(tmp_path, monkeypatch):
    import json

    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(catalog, "JOBS_ROOT", jobs)
    monkeypatch.setattr(catalog, "DATA_ROOT", tmp_path)
    (tmp_path / "result" / "article.md").write_text("# 订阅文章")
    job_id = "a" * 32
    folder = jobs / job_id
    folder.mkdir()
    (folder / "article.md").write_text("# 手动文章")
    (folder / "audio.m4a").write_bytes(b"private audio")
    (folder / "job.json").write_text(json.dumps({
        "id": job_id, "status": "done", "filename": "本地音频",
        "result_dir": str(folder), "episode_url": None,
    }))
    assert client.get("/").status_code == 404
    assert client.get("/podcasts").status_code == 200
    assert client.get(f"/jobs/{job_id}").status_code == 200
    assert client.get(f"/api/jobs/{job_id}").json()["title"] == "本地音频"
    assert client.get(f"/api/jobs/{job_id}/files/article.md").text == "# 手动文章"
    for name in ("audio.m4a", "job.json", "episode.json", "../audio.m4a"):
        assert client.get(f"/api/jobs/{job_id}/files/{name}").status_code == 404
    assert client.post(f"/api/jobs/{job_id}/files/article.md").status_code == 405
    assert client.get("/api/library").status_code == 200

    (folder / "job.json").write_text(json.dumps({"id": job_id, "status": "running"}))
    assert client.get(f"/jobs/{job_id}").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/files/article.md").status_code == 404
    (folder / "job.json").write_text(json.dumps({
        "id": job_id, "status": "done", "result_dir": str(tmp_path.parent),
    }))
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_library_deduplicates_episode_url_but_keeps_distinct_local_files(tmp_path, monkeypatch):
    import json

    client, episode_id = _client(tmp_path, monkeypatch, finish=True)
    (tmp_path / "result" / "article.md").write_text("# 订阅文章")
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(catalog, "JOBS_ROOT", jobs)
    monkeypatch.setattr(catalog, "DATA_ROOT", tmp_path)
    episode_url = client.get(f"/api/episodes/{episode_id}").json()["episode_url"]
    for index in range(3):
        job_id = f"{index + 1:032x}"
        folder = jobs / job_id
        folder.mkdir()
        (folder / "article.md").write_text("# 文章")
        (folder / "job.json").write_text(json.dumps({
            "id": job_id, "status": "done", "filename": "audio.m4a",
            "result_dir": str(folder),
            "episode_url": episode_url if index == 0 else None,
        }))
    articles = [article for group in client.get("/api/library").json() for article in group["articles"]]
    assert len(articles) == 3  # subscription + matching URL collapse; local jobs remain separate
    assert sum(article["title"] == "audio.m4a" for article in articles) == 3
