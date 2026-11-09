import threading
import time
from pathlib import Path

from server.subscriptions import SubscriptionStore


PODCAST = {
    "podcast_id": "p1",
    "source_url": "https://www.xiaoyuzhoufm.com/podcast/" + "a" * 24,
    "title": "测试播客",
    "author": "主播",
    "description": "简介",
    "episode_count": 3,
    "latest_episode_at": "2026-01-03T00:00:00Z",
    "episodes": [
        {
            "eid": "c" * 24,
            "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "c" * 24,
            "title": "第三期",
            "description": "",
            "published_at": "2026-01-03T00:00:00Z",
            "duration": 60,
            "audio_url": "https://media.xyzcdn.net/c.m4a",
            "media_mode": "PUBLIC",
            "is_private": False,
            "pay_type": "FREE",
            "processable": True,
        },
        {
            "eid": "b" * 24,
            "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "b" * 24,
            "title": "第二期",
            "description": "",
            "published_at": "2026-01-02T00:00:00Z",
            "duration": 60,
            "audio_url": "https://media.xyzcdn.net/b.m4a",
            "media_mode": "PUBLIC",
            "is_private": False,
            "pay_type": "FREE",
            "processable": True,
        },
        {
            "eid": "a" * 24,
            "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "a" * 24,
            "title": "第一期（付费）",
            "description": "",
            "published_at": "2026-01-01T00:00:00Z",
            "duration": 60,
            "audio_url": None,
            "media_mode": "PRIVATE",
            "is_private": True,
            "pay_type": "PAID",
            "processable": False,
        },
    ],
}


def test_initial_backfill_and_deduplication(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    subscription = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=1
    )
    episodes = store.list_episodes(subscription["id"])
    assert [(e["eid"], e["status"]) for e in episodes] == [
        ("c" * 24, "pending"),
        ("b" * 24, "ignored"),
        ("a" * 24, "skipped"),
    ]

    assert store.update_discovery(subscription["id"], PODCAST) == 0
    assert len(store.list_episodes(subscription["id"])) == 3


def test_new_episode_is_pending_and_retry_is_supported(tmp_path: Path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    subscription = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=0
    )
    episode = store.list_episodes(subscription["id"])[0]
    store.fail_episode(episode["id"], "测试失败")
    assert store.get_episode(episode["id"])["status"] == "failed"
    assert store.retry_episode(episode["id"]) is True
    assert store.get_episode(episode["id"])["status"] == "pending"

    newer = {
        **PODCAST,
        "episodes": [
            {
                **PODCAST["episodes"][0],
                "eid": "d" * 24,
                "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "d" * 24,
                "title": "第四期",
                "published_at": "2026-01-04T00:00:00Z",
            }
        ],
    }
    assert store.update_discovery(subscription["id"], newer) == 1
    added = [e for e in store.list_episodes(subscription["id"]) if e["eid"] == "d" * 24]
    assert added[0]["status"] == "pending"


def test_subscription_options_are_snapshotted_not_retroactive(tmp_path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(
        PODCAST,
        poll_interval_minutes=30,
        initial_backfill=1,
        backend="mimo",
        skip_diarization=False,
        num_speakers=2,
    )
    first = store.list_episodes(sub["id"])[0]
    assert (first["backend"], first["skip_diarization"], first["num_speakers"]) == (
        "mimo",
        False,
        2,
    )
    assert store.set_options(
        sub["id"], backend="whisper", skip_diarization=True, num_speakers=None
    )
    newer = {
        **PODCAST,
        "episodes": [
            {
                **PODCAST["episodes"][0],
                "eid": "d" * 24,
                "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "d" * 24,
            }
        ],
    }
    store.update_discovery(sub["id"], newer)
    rows = {row["eid"]: row for row in store.list_episodes(sub["id"])}
    assert rows["c" * 24]["backend"] == "mimo"
    assert rows["d" * 24]["backend"] == "whisper"
    assert rows["d" * 24]["skip_diarization"] is True


def test_retry_can_select_backend_without_changing_subscription(tmp_path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=0
    )
    episode = store.list_episodes(sub["id"])[0]
    assert store.retry_episode(
        episode["id"], backend="mimo", skip_diarization=False, num_speakers=2
    )
    saved = store.get_episode(episode["id"])
    assert saved["backend"] == "mimo" and saved["operation"] == "retranscribe"
    assert store.get_subscription(sub["id"])["backend"] == "qwen"
    assert not store.retry_episode(episode["id"])


def test_concurrent_retry_only_updates_the_selected_generation(tmp_path, monkeypatch):
    import server.subscriptions as subscriptions_module

    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=0
    )
    episode = store.list_episodes(sub["id"])[0]
    store.fail_episode(episode["id"], "可重试")

    original_options = subscriptions_module.ProcessingOptions
    selected = threading.Barrier(2)

    def synchronized_options(*args, **kwargs):
        selected.wait(timeout=1)
        return original_options(*args, **kwargs)

    monkeypatch.setattr(subscriptions_module, "ProcessingOptions", synchronized_options)
    results = []
    errors = []

    def retry():
        try:
            results.append(store.retry_episode(episode["id"]))
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    threads = [threading.Thread(target=retry) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not errors
    assert sorted(results) == [False, True]
    assert store.get_episode(episode["id"])["status"] == "pending"


def test_start_is_idempotent_before_processing_recovery(tmp_path):
    from server.subscriptions import PodcastSubscriptionService

    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    store.create_subscription(PODCAST, poll_interval_minutes=30, initial_backfill=1)
    episode = store.claim_next_episode()

    class LiveThread:
        @staticmethod
        def is_alive():
            return True

    service = PodcastSubscriptionService(store)
    service._thread = LiveThread()
    service.start()

    saved = store.get_episode(episode["id"])
    assert saved["status"] == "processing"
    assert saved["attempts"] == episode["attempts"]


def test_legacy_schema_migration_preserves_ids_paths_and_creates_backup(tmp_path):
    import sqlite3

    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=0
    )
    episode = store.list_episodes(sub["id"])[0]
    root = tmp_path / "old-output"
    root.mkdir()
    store.finish_episode(episode["id"], root)
    # Simulate schema from before this merge using SQLite's DROP COLUMN support.
    with store.connect() as db:
        for table in ("subscriptions", "subscription_episodes"):
            for column in ("backend", "skip_diarization", "num_speakers"):
                db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        db.execute("ALTER TABLE subscription_episodes DROP COLUMN job_id")
        db.execute("ALTER TABLE subscription_episodes DROP COLUMN operation")
    store.initialize()
    saved = store.get_episode(episode["id"])
    assert saved["result_dir"] == str(root.resolve())
    assert saved["status"] == "done" and saved["backend"] == "whisper"
    backup = store.path.with_name("podcast.db.pre-merge.bak")
    assert backup.is_file()
    with sqlite3.connect(backup) as db:
        assert "backend" not in {
            r[1] for r in db.execute("PRAGMA table_info(subscriptions)")
        }
    store.initialize()  # migration is idempotent
    assert store.get_episode(episode["id"])["result_dir"] == str(root.resolve())


def test_subscription_worker_uses_shared_job_manager_not_shell(tmp_path):
    from server.jobs import Job
    from server.subscriptions import PodcastSubscriptionService

    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    store.create_subscription(
        PODCAST,
        poll_interval_minutes=30,
        initial_backfill=1,
        backend="mimo",
        skip_diarization=False,
        num_speakers=2,
    )
    episode = store.claim_next_episode()
    root = tmp_path / "result"
    root.mkdir()
    for name in ("transcript.txt", "article.md", "notes.md", "mindmap.md"):
        (root / name).write_text("内容")

    class Jobs:
        options = None

        def create_from_url(self, url, **options):
            self.options = options
            return self.get("f" * 32)

        def get(self, job_id):
            return Job(
                id=job_id,
                filename="节目",
                status="done",
                stage="done",
                result_dir=str(root),
            )

    jobs = Jobs()
    service = PodcastSubscriptionService(store, job_manager=jobs)
    service._run_episode(episode)
    service._reconcile_processing()
    assert jobs.options == {
        "backend": "mimo",
        "skip_diarization": False,
        "num_speakers": 2,
        "episode_metadata": {
            "id": "c" * 24,
            "title": "第三期",
            "description": "",
            "podcast_title": "测试播客",
            "author": "主播",
            "published_at": "2026-01-03T00:00:00Z",
            "duration": 60,
            "url": "https://www.xiaoyuzhoufm.com/episode/" + "c" * 24,
        },
    }
    saved = store.get_episode(episode["id"])
    assert saved["status"] == "done" and saved["job_id"] == "f" * 32


def test_reanalysis_requires_transcript_not_audio(tmp_path):
    import pytest

    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=0
    )
    episode = store.list_episodes(sub["id"])[0]
    with pytest.raises(ValueError, match="逐字稿"):
        store.retry_episode(episode["id"], analyze_only=True)
    root = tmp_path / "result"
    root.mkdir()
    (root / "transcript.txt").write_text("原文")
    store.finish_episode(episode["id"], root)
    assert store.retry_episode(episode["id"], analyze_only=True)
    assert store.get_episode(episode["id"])["operation"] == "analyze"


def _claimed_episode_with_job(tmp_path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    store.create_subscription(PODCAST, poll_interval_minutes=30, initial_backfill=1)
    episode = store.claim_next_episode()
    root = tmp_path / "result"
    root.mkdir()
    for name in ("transcript.txt", "article.md", "notes.md", "mindmap.md"):
        (root / name).write_text("内容")
    job_id = "f" * 32
    assert store.attach_claimed_job(
        episode["id"], job_id, root, expected_attempts=episode["attempts"]
    )
    return store, episode, root, job_id


def test_stale_done_cannot_finish_after_linked_job_requeued(tmp_path):
    from server.jobs import Job
    from server.subscriptions import PodcastSubscriptionService

    store, episode, root, job_id = _claimed_episode_with_job(tmp_path)

    class Jobs:
        def get(self, requested_id):
            assert requested_id == job_id
            store.requeue_linked_job(
                job_id,
                {
                    "backend": "whisper",
                    "skip_diarization": True,
                    "num_speakers": None,
                },
            )
            return Job(
                id=job_id,
                filename="节目",
                status="done",
                stage="done",
                result_dir=str(root),
            )

    PodcastSubscriptionService(store, job_manager=Jobs())._reconcile_processing()
    saved = store.get_episode(episode["id"])
    assert saved["status"] == "pending"
    assert saved["attempts"] == episode["attempts"]


def test_stale_error_cannot_fail_after_linked_job_requeued(tmp_path):
    from server.jobs import Job
    from server.subscriptions import PodcastSubscriptionService

    store, episode, root, job_id = _claimed_episode_with_job(tmp_path)

    class Jobs:
        def get(self, requested_id):
            assert requested_id == job_id
            store.requeue_linked_job(
                job_id,
                {
                    "backend": "mimo",
                    "skip_diarization": False,
                    "num_speakers": 2,
                },
            )
            return Job(
                id=job_id,
                filename="节目",
                status="error",
                stage="error",
                error="旧任务失败",
                result_dir=str(root),
            )

    PodcastSubscriptionService(store, job_manager=Jobs())._reconcile_processing()
    saved = store.get_episode(episode["id"])
    assert saved["status"] == "pending"
    assert saved["error"] is None
    assert saved["backend"] == "mimo"


def test_new_claim_generation_rejects_old_finalize(tmp_path):
    store, first, root, first_job_id = _claimed_episode_with_job(tmp_path)
    store.requeue_linked_job(
        first_job_id,
        {
            "backend": "whisper",
            "skip_diarization": True,
            "num_speakers": None,
        },
    )
    second = store.claim_next_episode()
    second_job_id = "e" * 32
    assert second["attempts"] == first["attempts"] + 1
    assert store.attach_claimed_job(
        second["id"], second_job_id, root, expected_attempts=second["attempts"]
    )

    assert not store.finish_claimed_episode(
        first["id"],
        expected_attempts=first["attempts"],
        job_id=first_job_id,
        result_dir=root,
    )
    assert not store.fail_claimed_episode(
        first["id"],
        "旧错误",
        expected_attempts=first["attempts"],
        job_id=first_job_id,
    )
    assert store.finish_claimed_episode(
        second["id"],
        expected_attempts=second["attempts"],
        job_id=second_job_id,
        result_dir=root,
    )
    assert store.get_episode(second["id"])["status"] == "done"


def test_queued_job_does_not_block_later_subscription_discovery(tmp_path, monkeypatch):
    from server.jobs import Job
    from server.subscriptions import PodcastSubscriptionService

    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    subscription = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=1
    )
    result = tmp_path / "queued-result"
    checked = threading.Event()

    class Jobs:
        def create_from_url(self, url, **options):
            return Job(
                id="f" * 32,
                filename="节目",
                status="queued",
                stage="queued",
                result_dir=str(result),
            )

        def get(self, job_id):
            return Job(
                id=job_id,
                filename="节目",
                status="queued",
                stage="queued",
                result_dir=str(result),
            )

    def fetcher(_url):
        checked.set()
        return PODCAST

    monkeypatch.setenv("WHISPER_SUBSCRIPTION_IDLE_SECONDS", "30")
    service = PodcastSubscriptionService(store, fetcher=fetcher, job_manager=Jobs())
    service.start()
    try:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            saved = store.list_episodes(subscription["id"])[0]
            if saved["status"] == "processing" and saved["job_id"]:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("subscription episode was not attached")

        assert store.request_check(subscription["id"])
        service._wake.set()
        assert checked.wait(1), "queued job blocked the subscription discovery loop"
    finally:
        service.stop()


def test_manual_subscription_parks_new_episodes_until_approved(tmp_path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(
        PODCAST, poll_interval_minutes=30, initial_backfill=1, auto_process=False
    )
    assert sub["auto_process"] is False
    statuses = {e["eid"]: e["status"] for e in store.list_episodes(sub["id"])}
    assert statuses == {"c" * 24: "awaiting", "b" * 24: "ignored", "a" * 24: "skipped"}
    assert store.claim_next_episode() is None

    newer = {
        **PODCAST,
        "episodes": [
            {
                **PODCAST["episodes"][0],
                "eid": "d" * 24,
                "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "d" * 24,
            }
        ],
    }
    assert store.update_discovery(sub["id"], newer) == 1
    rows = {e["eid"]: e for e in store.list_episodes(sub["id"])}
    assert rows["d" * 24]["status"] == "awaiting"
    assert store.list_subscriptions()[0]["awaiting_count"] == 2
    awaiting = store.list_awaiting_episodes()
    assert {e["eid"] for e in awaiting} == {"d" * 24, "c" * 24}
    assert awaiting[0]["podcast_title"] == "测试播客"
    assert store.list_awaiting_episodes(sub["id"] + 1) == []

    assert store.dismiss_episode(rows["c" * 24]["id"]) is True
    assert store.get_episode(rows["c" * 24]["id"])["status"] == "ignored"
    assert store.approve_episode(rows["d" * 24]["id"], backend="mimo") is True
    approved = store.get_episode(rows["d" * 24]["id"])
    assert (approved["status"], approved["operation"], approved["backend"]) == (
        "pending",
        "transcribe",
        "mimo",
    )
    assert store.approve_episode(rows["d" * 24]["id"]) is False
    assert store.claim_next_episode()["eid"] == "d" * 24


def test_switching_auto_process_only_affects_future_discovery(tmp_path):
    store = SubscriptionStore(tmp_path / "podcast.db")
    store.initialize()
    sub = store.create_subscription(PODCAST, poll_interval_minutes=30, initial_backfill=1)
    assert sub["auto_process"] is True
    assert store.set_auto_process(sub["id"], False) is True
    newer = {
        **PODCAST,
        "episodes": [
            {
                **PODCAST["episodes"][0],
                "eid": "d" * 24,
                "episode_url": "https://www.xiaoyuzhoufm.com/episode/" + "d" * 24,
            }
        ],
    }
    store.update_discovery(sub["id"], newer)
    rows = {e["eid"]: e["status"] for e in store.list_episodes(sub["id"])}
    assert rows["c" * 24] == "pending"
    assert rows["d" * 24] == "awaiting"
    assert store.set_auto_process(sub["id"], True) is True
    assert store.get_episode(
        next(e["id"] for e in store.list_episodes(sub["id"]) if e["eid"] == "d" * 24)
    )["status"] == "awaiting"
