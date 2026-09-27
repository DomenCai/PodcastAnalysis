"""Persistent Xiaoyuzhou discovery, submitting to the shared durable job queue."""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from server.podcast_feed import (
    fetch_podcast,
    normalize_episode_url,
    normalize_podcast_url,
)
from server.job_options import ProcessingOptions

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = Path(os.getenv("PODCAST_DATA_DIR", ROOT / "data")).expanduser().resolve()
DEFAULT_DB_PATH = DATA_ROOT / "podcast.db"
LOG_ROOT = DATA_ROOT / "subscription-logs"
ENQUEUE_BATCH_SIZE = 16


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _future(minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=minutes)).isoformat()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class SubscriptionStore:
    def __init__(self, path: Path = DEFAULT_DB_PATH) -> None:
        self.path = path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        # Back up an existing pre-merge database once before additive migration.
        # sqlite backup includes committed WAL contents and is safe while the
        # public read-only application is reading. New/test databases need none.
        if self.path.is_file():
            with self.connect() as source:
                columns = {
                    row[1] for row in source.execute("PRAGMA table_info(subscriptions)")
                }
                backup = self.path.with_name(self.path.name + ".pre-merge.bak")
                if columns and "backend" not in columns and not backup.exists():
                    with sqlite3.connect(backup) as target:
                        source.backup(target)
        with self.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    podcast_id TEXT NOT NULL UNIQUE,
                    source_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    episode_count INTEGER,
                    latest_episode_at TEXT,
                    poll_interval_minutes INTEGER NOT NULL DEFAULT 30,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    last_checked_at TEXT,
                    next_check_at TEXT,
                    last_error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS subscription_episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
                    eid TEXT NOT NULL,
                    episode_url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    published_at TEXT,
                    duration INTEGER,
                    audio_url TEXT,
                    media_mode TEXT,
                    is_private INTEGER NOT NULL DEFAULT 0,
                    pay_type TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    result_dir TEXT,
                    error TEXT,
                    discovered_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    updated_at TEXT NOT NULL,
                    UNIQUE(subscription_id, eid)
                );

                CREATE INDEX IF NOT EXISTS idx_subscription_due
                    ON subscriptions(enabled, next_check_at);
                CREATE INDEX IF NOT EXISTS idx_episode_status
                    ON subscription_episodes(status, published_at);
                """
            )
            # Additive migration: preserve existing IDs, result paths and old links.
            for table in ("subscriptions", "subscription_episodes"):
                columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
                additions = {
                    "backend": "TEXT NOT NULL DEFAULT 'whisper'",
                    "skip_diarization": "INTEGER NOT NULL DEFAULT 1",
                    "num_speakers": "INTEGER",
                }
                if table == "subscription_episodes":
                    additions.update(
                        {
                            "job_id": "TEXT",
                            "operation": "TEXT NOT NULL DEFAULT 'transcribe'",
                        }
                    )
                for name, definition in additions.items():
                    if name not in columns:
                        db.execute(
                            f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
                        )
            # Recover subscription bookkeeping; the shared job manager recovers work.
            db.execute(
                """
                UPDATE subscription_episodes
                SET status = 'pending', error = '服务重启，任务等待重试', updated_at = ?
                WHERE status = 'processing'
                """,
                (_now(),),
            )

    def create_subscription(
        self,
        feed: dict[str, Any],
        *,
        poll_interval_minutes: int,
        initial_backfill: int,
        backend: str = "qwen",
        skip_diarization: bool = True,
        num_speakers: int | None = None,
    ) -> dict[str, Any]:
        options = ProcessingOptions(backend, skip_diarization, num_speakers)
        now = _now()
        with self.connect() as db:
            try:
                cursor = db.execute(
                    """
                    INSERT INTO subscriptions (
                        podcast_id, source_url, title, author, description,
                        episode_count, latest_episode_at, poll_interval_minutes,
                        enabled, last_checked_at, next_check_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                    """,
                    (
                        feed["podcast_id"],
                        feed["source_url"],
                        feed["title"],
                        feed.get("author", ""),
                        feed.get("description", ""),
                        feed.get("episode_count"),
                        feed.get("latest_episode_at"),
                        poll_interval_minutes,
                        now,
                        _future(poll_interval_minutes),
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("这个播客已经订阅") from exc
            subscription_id = int(cursor.lastrowid)
            db.execute(
                "UPDATE subscriptions SET backend = ?, skip_diarization = ?, num_speakers = ? WHERE id = ?",
                (
                    options.backend,
                    int(options.skip_diarization),
                    options.num_speakers,
                    subscription_id,
                ),
            )
            self._upsert_episodes(
                db,
                subscription_id,
                feed.get("episodes", []),
                initial=True,
                initial_backfill=initial_backfill,
            )
        result = self.get_subscription(subscription_id)
        if result is None:
            raise RuntimeError("订阅创建后无法读取")
        return result

    def update_discovery(
        self,
        subscription_id: int,
        feed: dict[str, Any],
    ) -> int:
        now = _now()
        with self.connect() as db:
            subscription = db.execute(
                "SELECT poll_interval_minutes FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            if subscription is None:
                raise KeyError("subscription not found")
            db.execute(
                """
                UPDATE subscriptions SET
                    title = ?, author = ?, description = ?, episode_count = ?,
                    latest_episode_at = ?, last_checked_at = ?, next_check_at = ?,
                    last_error = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    feed["title"],
                    feed.get("author", ""),
                    feed.get("description", ""),
                    feed.get("episode_count"),
                    feed.get("latest_episode_at"),
                    now,
                    _future(subscription["poll_interval_minutes"]),
                    now,
                    subscription_id,
                ),
            )
            return self._upsert_episodes(
                db,
                subscription_id,
                feed.get("episodes", []),
                initial=False,
                initial_backfill=0,
            )

    @staticmethod
    def _upsert_episodes(
        db: sqlite3.Connection,
        subscription_id: int,
        episodes: list[dict[str, Any]],
        *,
        initial: bool,
        initial_backfill: int,
    ) -> int:
        now = _now()
        inserted = 0
        processable_seen = 0
        for episode in episodes:
            processable = bool(episode.get("processable"))
            if initial and processable:
                status = "pending" if processable_seen < initial_backfill else "ignored"
                processable_seen += 1
            elif processable:
                status = "pending"
            else:
                status = "skipped"
            cursor = db.execute(
                """
                INSERT OR IGNORE INTO subscription_episodes (
                    subscription_id, eid, episode_url, title, description,
                    published_at, duration, audio_url, media_mode, is_private,
                    pay_type, status, discovered_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    subscription_id,
                    episode["eid"],
                    episode["episode_url"],
                    episode["title"],
                    episode.get("description", ""),
                    episode.get("published_at"),
                    episode.get("duration"),
                    episode.get("audio_url"),
                    episode.get("media_mode"),
                    int(bool(episode.get("is_private"))),
                    episode.get("pay_type"),
                    status,
                    now,
                    now,
                ),
            )
            if cursor.rowcount:
                # Snapshot defaults once. Changing subscription settings must not
                # mutate pending, running or historical episode configurations.
                db.execute(
                    """UPDATE subscription_episodes SET
                        backend = (SELECT backend FROM subscriptions WHERE id = ?),
                        skip_diarization = (SELECT skip_diarization FROM subscriptions WHERE id = ?),
                        num_speakers = (SELECT num_speakers FROM subscriptions WHERE id = ?)
                    WHERE id = ?""",
                    (
                        subscription_id,
                        subscription_id,
                        subscription_id,
                        cursor.lastrowid,
                    ),
                )
                inserted += 1
                continue
            # Refresh mutable metadata. A formerly unavailable episode becomes
            # pending if the public page later exposes its audio.
            existing = db.execute(
                """
                SELECT id, status FROM subscription_episodes
                WHERE subscription_id = ? AND eid = ?
                """,
                (subscription_id, episode["eid"]),
            ).fetchone()
            if existing is None:
                continue
            next_status = existing["status"]
            if next_status == "skipped" and processable:
                next_status = "pending"
            db.execute(
                """
                UPDATE subscription_episodes SET
                    episode_url = ?, title = ?, description = ?, published_at = ?,
                    duration = ?, audio_url = ?, media_mode = ?, is_private = ?,
                    pay_type = ?, status = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    episode["episode_url"],
                    episode["title"],
                    episode.get("description", ""),
                    episode.get("published_at"),
                    episode.get("duration"),
                    episode.get("audio_url"),
                    episode.get("media_mode"),
                    int(bool(episode.get("is_private"))),
                    episode.get("pay_type"),
                    next_status,
                    now,
                    existing["id"],
                ),
            )
        return inserted

    def list_subscriptions(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT s.*,
                    COUNT(e.id) AS discovered_count,
                    SUM(CASE WHEN e.status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                    SUM(CASE WHEN e.status = 'processing' THEN 1 ELSE 0 END) AS processing_count,
                    SUM(CASE WHEN e.status = 'done' THEN 1 ELSE 0 END) AS done_count,
                    SUM(CASE WHEN e.status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                FROM subscriptions s
                LEFT JOIN subscription_episodes e ON e.subscription_id = s.id
                GROUP BY s.id
                ORDER BY s.created_at DESC
                """
            ).fetchall()
        return [self._serialize_subscription(dict(value)) for value in rows]

    def get_subscription(self, subscription_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            value = db.execute(
                "SELECT * FROM subscriptions WHERE id = ?", (subscription_id,)
            ).fetchone()
        return self._serialize_subscription(dict(value)) if value else None

    @staticmethod
    def _serialize_subscription(value: dict[str, Any]) -> dict[str, Any]:
        value["enabled"] = bool(value.get("enabled"))
        value["skip_diarization"] = bool(value.get("skip_diarization", True))
        for name in (
            "discovered_count",
            "pending_count",
            "processing_count",
            "done_count",
            "failed_count",
        ):
            value[name] = int(value.get(name) or 0)
        return value

    def list_episodes(
        self, subscription_id: int, limit: int = 100
    ) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM subscription_episodes
                WHERE subscription_id = ?
                ORDER BY COALESCE(published_at, discovered_at) DESC
                LIMIT ?
                """,
                (subscription_id, limit),
            ).fetchall()
        values = [dict(row) for row in rows]
        for value in values:
            value["is_private"] = bool(value["is_private"])
            value["skip_diarization"] = bool(value.get("skip_diarization", True))
        return values

    def get_episode(self, episode_id: int) -> dict[str, Any] | None:
        with self.connect() as db:
            value = db.execute(
                "SELECT * FROM subscription_episodes WHERE id = ?", (episode_id,)
            ).fetchone()
        return _row(value)

    def find_episode(self, episode_url: str) -> dict[str, Any] | None:
        with self.connect() as db:
            value = db.execute(
                "SELECT * FROM subscription_episodes WHERE episode_url = ? ORDER BY id LIMIT 1",
                (episode_url,),
            ).fetchone()
        return _row(value)

    def due_subscriptions(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM subscriptions
                WHERE enabled = 1 AND (next_check_at IS NULL OR next_check_at <= ?)
                ORDER BY COALESCE(next_check_at, created_at)
                """,
                (_now(),),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_check_error(self, subscription_id: int, error: str) -> None:
        with self.connect() as db:
            row = db.execute(
                "SELECT poll_interval_minutes FROM subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone()
            if row:
                db.execute(
                    """
                    UPDATE subscriptions SET last_checked_at = ?, next_check_at = ?,
                        last_error = ?, updated_at = ? WHERE id = ?
                    """,
                    (
                        _now(),
                        _future(row["poll_interval_minutes"]),
                        error[:2000],
                        _now(),
                        subscription_id,
                    ),
                )

    def request_check(self, subscription_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE subscriptions SET next_check_at = NULL, updated_at = ? WHERE id = ?",
                (_now(), subscription_id),
            )
        return bool(cursor.rowcount)

    def set_enabled(self, subscription_id: int, enabled: bool) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE subscriptions SET enabled = ?, next_check_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (int(enabled), _now() if enabled else None, _now(), subscription_id),
            )
        return bool(cursor.rowcount)

    def delete_subscription(self, subscription_id: int) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                "DELETE FROM subscriptions WHERE id = ?", (subscription_id,)
            )
        return bool(cursor.rowcount)

    def claim_next_episode(self) -> dict[str, Any] | None:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            value = db.execute(
                """
                SELECT e.*, s.title AS podcast_title, s.author AS author
                FROM subscription_episodes e
                JOIN subscriptions s ON s.id = e.subscription_id
                WHERE e.status = 'pending' AND s.enabled = 1
                ORDER BY COALESCE(e.published_at, e.discovered_at)
                LIMIT 1
                """
            ).fetchone()
            if value is None:
                db.commit()
                return None
            now = _now()
            db.execute(
                """
                UPDATE subscription_episodes SET status = 'processing', attempts = attempts + 1,
                    started_at = ?, error = NULL, updated_at = ? WHERE id = ?
                """,
                (now, now, value["id"]),
            )
            db.commit()
            result = dict(value)
            result["attempts"] += 1
            result["status"] = "processing"
            return result
        finally:
            db.close()

    def list_processing_episodes(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute(
                """
                SELECT * FROM subscription_episodes
                WHERE status = 'processing'
                ORDER BY COALESCE(started_at, updated_at), id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def finish_episode(self, episode_id: int, result_dir: Path) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE subscription_episodes SET status = 'done', result_dir = ?, error = NULL,
                    finished_at = ?, updated_at = ? WHERE id = ?
                """,
                (str(result_dir.resolve()), _now(), _now(), episode_id),
            )

    def finish_claimed_episode(
        self,
        episode_id: int,
        *,
        expected_attempts: int,
        job_id: str,
        result_dir: Path,
    ) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE subscription_episodes SET status = 'done', result_dir = ?, error = NULL,
                    finished_at = ?, updated_at = ?
                WHERE id = ? AND status = 'processing' AND attempts = ? AND job_id = ?
                """,
                (
                    str(result_dir.resolve()),
                    _now(),
                    _now(),
                    episode_id,
                    expected_attempts,
                    job_id,
                ),
            )
        return bool(cursor.rowcount)

    def fail_episode(self, episode_id: int, error: str) -> None:
        with self.connect() as db:
            db.execute(
                """
                UPDATE subscription_episodes SET status = 'failed', error = ?,
                    finished_at = ?, updated_at = ? WHERE id = ?
                """,
                (error[:4000], _now(), _now(), episode_id),
            )

    def fail_claimed_episode(
        self,
        episode_id: int,
        error: str,
        *,
        expected_attempts: int,
        job_id: str | None = None,
    ) -> bool:
        query = """
            UPDATE subscription_episodes SET status = 'failed', error = ?,
                finished_at = ?, updated_at = ?
            WHERE id = ? AND status = 'processing' AND attempts = ?
        """
        values: list[Any] = [
            error[:4000],
            _now(),
            _now(),
            episode_id,
            expected_attempts,
        ]
        if job_id is not None:
            query += " AND job_id = ?"
            values.append(job_id)
        with self.connect() as db:
            cursor = db.execute(query, values)
        return bool(cursor.rowcount)

    def set_options(self, subscription_id: int, **changes) -> bool:
        existing = self.get_subscription(subscription_id)
        if not existing:
            return False
        options = ProcessingOptions(
            **{
                name: changes.get(name, existing.get(name))
                for name in ("backend", "skip_diarization", "num_speakers")
            }
        )
        with self.connect() as db:
            cursor = db.execute(
                "UPDATE subscriptions SET backend = ?, skip_diarization = ?, num_speakers = ?, updated_at = ? WHERE id = ?",
                (
                    options.backend,
                    int(options.skip_diarization),
                    options.num_speakers,
                    _now(),
                    subscription_id,
                ),
            )
        return bool(cursor.rowcount)

    def retry_episode(
        self, episode_id: int, *, analyze_only: bool = False, **changes
    ) -> bool:
        with self.connect() as db:
            existing = db.execute(
                "SELECT * FROM subscription_episodes WHERE id = ?", (episode_id,)
            ).fetchone()
            if not existing or existing["status"] in {"pending", "processing"}:
                return False
            options = ProcessingOptions(
                **{
                    name: changes.get(
                        name,
                        bool(existing[name])
                        if name == "skip_diarization"
                        else existing[name],
                    )
                    for name in ("backend", "skip_diarization", "num_speakers")
                }
            )
            if analyze_only:
                root = existing["result_dir"]
                if not root or not (Path(root) / "transcript.txt").is_file():
                    raise ValueError("没有可用逐字稿，请先完成转写")
            cursor = db.execute(
                """UPDATE subscription_episodes SET status = 'pending', error = NULL,
                    finished_at = NULL, backend = ?, skip_diarization = ?, num_speakers = ?,
                    operation = ?, updated_at = ?
                    WHERE id = ? AND status = ? AND attempts = ?""",
                (
                    options.backend,
                    int(options.skip_diarization),
                    options.num_speakers,
                    "analyze" if analyze_only else "retranscribe",
                    _now(),
                    episode_id,
                    existing["status"],
                    existing["attempts"],
                ),
            )
        return bool(cursor.rowcount)

    def requeue_linked_job(self, job_id: str, options: dict) -> None:
        """Manual reprocessing of a linked job must also invalidate public readiness."""
        with self.connect() as db:
            db.execute(
                """UPDATE subscription_episodes SET status = 'pending', error = NULL,
                    backend = ?, skip_diarization = ?, num_speakers = ?, operation = 'transcribe',
                    finished_at = NULL, updated_at = ? WHERE job_id = ?""",
                (
                    options["backend"],
                    int(options["skip_diarization"]),
                    options["num_speakers"],
                    _now(),
                    job_id,
                ),
            )

    def attach_job(self, episode_id: int, job_id: str, result_dir: Path) -> None:
        with self.connect() as db:
            db.execute(
                "UPDATE subscription_episodes SET job_id = ?, result_dir = ?, operation = 'transcribe', updated_at = ? WHERE id = ?",
                (job_id, str(result_dir.resolve()), _now(), episode_id),
            )

    def attach_claimed_job(
        self,
        episode_id: int,
        job_id: str,
        result_dir: Path,
        *,
        expected_attempts: int,
    ) -> bool:
        with self.connect() as db:
            cursor = db.execute(
                """
                UPDATE subscription_episodes SET job_id = ?, result_dir = ?,
                    operation = 'transcribe', updated_at = ?
                WHERE id = ? AND status = 'processing' AND attempts = ?
                """,
                (
                    job_id,
                    str(result_dir.resolve()),
                    _now(),
                    episode_id,
                    expected_attempts,
                ),
            )
        return bool(cursor.rowcount)


class PodcastSubscriptionService:
    """Poll subscriptions and track jobs executed by the shared JobManager."""

    def __init__(
        self,
        store: SubscriptionStore | None = None,
        *,
        fetcher=fetch_podcast,
        job_manager=None,
    ) -> None:
        self.store = store or SubscriptionStore()
        self.fetcher = fetcher
        self.job_manager = job_manager
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.store.initialize()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="podcast-subscriptions",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def add_subscription(
        self,
        url: str,
        *,
        poll_interval_minutes: int = 30,
        initial_backfill: int = 1,
        backend: str = "qwen",
        skip_diarization: bool = True,
        num_speakers: int | None = None,
    ) -> dict[str, Any]:
        if not 5 <= poll_interval_minutes <= 10080:
            raise ValueError("检查间隔必须在 5 分钟到 7 天之间")
        if not 0 <= initial_backfill <= 15:
            raise ValueError("首次处理数量必须在 0 到 15 之间")
        options = ProcessingOptions(backend, skip_diarization, num_speakers)
        normalized_url, _ = normalize_podcast_url(url)
        feed = self.fetcher(normalized_url)
        result = self.store.create_subscription(
            feed,
            poll_interval_minutes=poll_interval_minutes,
            initial_backfill=initial_backfill,
            **options.to_dict(),
        )
        self._wake.set()
        return result

    def check_subscription(self, subscription: dict[str, Any]) -> int:
        try:
            feed = self.fetcher(subscription["source_url"])
            return self.store.update_discovery(subscription["id"], feed)
        except Exception as exc:
            self.store.record_check_error(subscription["id"], str(exc))
            return 0

    def _loop(self) -> None:
        idle_seconds = float(os.getenv("WHISPER_SUBSCRIPTION_IDLE_SECONDS", "5"))
        while not self._stop.is_set():
            submitted = 0
            try:
                for subscription in self.store.due_subscriptions():
                    if self._stop.is_set():
                        return
                    self.check_subscription(subscription)
                self._reconcile_processing()
                for _ in range(ENQUEUE_BATCH_SIZE):
                    if self._stop.is_set():
                        return
                    episode = self.store.claim_next_episode()
                    if episode is None:
                        break
                    self._run_episode(episode)
                    submitted += 1
                self._reconcile_processing()
            except Exception:
                # Keep the scheduler alive; item-specific errors are persisted by
                # check_subscription/_run_episode whenever an item was claimed.
                pass
            timeout = 1.0 if submitted == ENQUEUE_BATCH_SIZE else max(1.0, idle_seconds)
            self._wake.wait(timeout=timeout)
            self._wake.clear()

    def _run_episode(self, episode: dict[str, Any]) -> None:
        from server.jobs import manager, result_directory

        jobs = self.job_manager or manager
        attempts = int(episode["attempts"])
        try:
            options = {
                "backend": episode.get("backend", "whisper"),
                "skip_diarization": bool(episode.get("skip_diarization", True)),
                "num_speakers": episode.get("num_speakers"),
            }
            job = jobs.get(episode["job_id"]) if episode.get("job_id") else None
            operation = episode.get("operation", "transcribe")
            if operation == "analyze":
                if job is None:
                    job = jobs.import_result(Path(episode["result_dir"]), episode)
                if job.status not in {"queued", "running"}:
                    job = jobs.reanalyze(job.id)
            else:
                if job is None:
                    normalized_url, _ = normalize_episode_url(episode["episode_url"])
                    episode_metadata = {
                        "id": episode["eid"],
                        "title": episode["title"],
                        "description": episode.get("description", ""),
                        "podcast_title": episode.get("podcast_title", ""),
                        "author": episode.get("author", ""),
                        "published_at": episode.get("published_at"),
                        "duration": episode.get("duration"),
                        "url": normalized_url,
                    }
                    job = jobs.create_from_url(
                        normalized_url,
                        episode_metadata=episode_metadata,
                        **options,
                    )
                if operation == "retranscribe" and job.status not in {
                    "queued",
                    "running",
                }:
                    job = jobs.retry(job.id, **options)
            self.store.attach_claimed_job(
                episode["id"],
                job.id,
                result_directory(job),
                expected_attempts=attempts,
            )
        except Exception as exc:
            self.store.fail_claimed_episode(
                episode["id"],
                str(exc),
                expected_attempts=attempts,
            )

    def _reconcile_processing(self) -> None:
        from server.jobs import manager, result_directory

        jobs = self.job_manager or manager
        for episode in self.store.list_processing_episodes():
            if self._stop.is_set():
                return
            attempts = int(episode["attempts"])
            job_id = episode.get("job_id")
            if not job_id:
                self.store.fail_claimed_episode(
                    episode["id"],
                    "任务未关联",
                    expected_attempts=attempts,
                )
                continue
            try:
                current = jobs.get(job_id)
                if current is None:
                    raise RuntimeError("任务不存在")
                if current.status == "error":
                    self.store.fail_claimed_episode(
                        episode["id"],
                        current.error or "处理失败",
                        expected_attempts=attempts,
                        job_id=job_id,
                    )
                    continue
                if current.status != "done":
                    continue
                root = result_directory(current)
                for name in ("transcript.txt", "article.md", "notes.md", "mindmap.md"):
                    path = root / name
                    if not path.is_file() or not path.stat().st_size:
                        raise RuntimeError(f"结果缺少 {name}")
                self.store.finish_claimed_episode(
                    episode["id"],
                    expected_attempts=attempts,
                    job_id=job_id,
                    result_dir=root,
                )
            except Exception as exc:
                self.store.fail_claimed_episode(
                    episode["id"],
                    str(exc),
                    expected_attempts=attempts,
                    job_id=job_id,
                )


subscription_service = PodcastSubscriptionService()
