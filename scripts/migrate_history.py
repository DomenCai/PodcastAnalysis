"""Copy legacy podcast state into PodcastAnalysis/data without touching sources.

Default is a dry run. Stop all podcast services before --apply.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from server.subscriptions import SubscriptionStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = ROOT.parent / "whisper"
DEFAULT_TARGET = ROOT / "data"


def inspect(source: Path, target: Path) -> dict:
    source_db = source / "data/podcast.db"
    if not source_db.is_file():
        raise RuntimeError(f"源数据库不存在：{source_db}")
    with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as db:
        columns = {row[1] for row in db.execute("PRAGMA table_info(subscriptions)")}
        rows = db.execute("SELECT id, status, result_dir FROM subscription_episodes").fetchall()
        subscriptions = db.execute("SELECT count(*) FROM subscriptions").fetchone()[0]
    missing = [path for _, _, value in rows if value for path in [Path(value)] if not path.is_dir()]
    source_jobs = [p for p in (source / "data/jobs").iterdir() if p.is_dir()]
    agy = [p for p in (source / "out/agy").iterdir() if p.is_dir()]
    split = ROOT / "out/split-smoke/data"
    split_jobs = list((split / "jobs").iterdir()) if (split / "jobs").is_dir() else []
    importable_old_jobs = sum((p / "transcript.txt").is_file() for p in source_jobs)
    split_unique = sum(
        (p / "job.json").is_file()
        and not json.loads((p / "job.json").read_text()).get("result_dir")
        for p in split_jobs
    )
    return {
        "subscriptions": subscriptions, "episodes": len(rows),
        "finished_episodes": sum(status == "done" for _, status, _ in rows),
        "source_jobs": len(source_jobs), "agy_results": len(agy),
        "importable_old_jobs": importable_old_jobs,
        "validation_jobs": len(split_jobs),
        "unique_validation_jobs_to_import": split_unique,
        "legacy_schema": "backend" not in columns,
        "missing_result_dirs": [str(path) for path in missing],
        "target_exists": target.exists(),
    }


def _snapshot(source: Path, destination: Path) -> None:
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as old:
        with sqlite3.connect(destination) as new:
            old.backup(new)


def migrate(source: Path, target: Path) -> dict:
    report = inspect(source, target)
    if report["missing_result_dirs"]:
        raise RuntimeError("存在缺失的历史结果目录；拒绝迁移")
    if target.exists():
        raise RuntimeError("目标 data 已存在；拒绝覆盖或合并，请先检查目标数据")
    stage = target.with_name(target.name + ".migration-stage")
    if stage.exists():
        raise RuntimeError(f"暂存目录已存在：{stage}")
    stage.mkdir(mode=0o700)
    try:
        _snapshot(source / "data/podcast.db", stage / "podcast.db")
        shutil.copytree(source / "data/jobs", stage / "jobs")
        for name in ("uploads", "subscription-logs"):
            if (source / "data" / name).is_dir():
                shutil.copytree(source / "data" / name, stage / name)
        shutil.copytree(source / "out/agy", stage / "legacy-agy")
        split = ROOT / "out/split-smoke/data"
        if split.is_dir():
            shutil.copytree(split, stage / "validation-backup", ignore=shutil.ignore_patterns("*.db-wal", "*.db-shm", ".service.lock", ".pipeline.lock"))
            if (split / "podcast.db").is_file():
                _snapshot(split / "podcast.db", stage / "validation-backup/podcast.db")
            for folder in (split / "jobs").iterdir():
                state = folder / "job.json"
                if not state.is_file():
                    continue
                job = json.loads(state.read_text())
                # A split-smoke import pointing to old agy is the same result;
                # preserve that validation job in backup without double counting.
                if job.get("status") != "done" or job.get("result_dir"):
                    continue
                if (stage / "jobs" / folder.name).exists():
                    raise RuntimeError(f"验证 job ID 冲突：{folder.name}")
                shutil.copytree(folder, stage / "jobs" / folder.name)
        with sqlite3.connect(stage / "podcast.db") as db:
            for row_id, old_dir in db.execute("SELECT id, result_dir FROM subscription_episodes WHERE result_dir IS NOT NULL"):
                old = Path(old_dir)
                if old.parent != source / "out/agy":
                    raise RuntimeError(f"未知结果目录：{old}")
                new = target / "legacy-agy" / old.name
                db.execute("UPDATE subscription_episodes SET result_dir = ? WHERE id = ?", (str(new), row_id))
            db.commit()
        SubscriptionStore(stage / "podcast.db").initialize()
        if report["legacy_schema"]:
            with sqlite3.connect(stage / "podcast.db") as db:
                # Historical episodes keep their whisper snapshot; only future
                # subscription work uses the new qwen default.
                db.execute("UPDATE subscriptions SET backend = 'qwen'")
                db.commit()
        agy_by_episode = {}
        for folder in (stage / "legacy-agy").iterdir():
            info_path = folder / "episode.json"
            if not info_path.is_file():
                continue
            info = json.loads(info_path.read_text())
            for identity in (info.get("id"), info.get("url")):
                if identity:
                    agy_by_episode[identity] = folder
        for folder in (stage / "jobs").iterdir():
            state = folder / "job.json"
            if state.is_file() or not (folder / "transcript.txt").is_file():
                continue
            info_path = folder / "episode.json"
            info = json.loads(info_path.read_text()) if info_path.is_file() else {}
            meta_path = folder / "meta.json"
            meta = json.loads(meta_path.read_text()) if meta_path.is_file() else {}
            agy = agy_by_episode.get(info.get("id")) or agy_by_episode.get(info.get("url"))
            state.write_text(json.dumps({
                "id": folder.name, "filename": info.get("title") or meta.get("filename") or folder.name,
                "status": "done", "stage": "done", "backend": "whisper", "episode": info,
                "episode_url": info.get("url"),
                "result_dir": str(target / "legacy-agy" / agy.name) if agy else str(target / "jobs" / folder.name),
                "created_at": datetime.fromtimestamp((folder / "transcript.txt").stat().st_mtime, UTC).isoformat(),
                "updated_at": datetime.fromtimestamp((folder / "transcript.txt").stat().st_mtime, UTC).isoformat(),
            }, ensure_ascii=False))
        # One article directory was not linked in the old subscription DB.
        # Give unlinked articles a stable job manifest so the public index can read them.
        with sqlite3.connect(stage / "podcast.db") as db:
            linked = {Path(row[0]).name for row in db.execute("SELECT result_dir FROM subscription_episodes WHERE result_dir IS NOT NULL")}
        linked.update(
            Path(json.loads(path.read_text())["result_dir"]).name
            for path in (stage / "jobs").glob("*/job.json")
            if json.loads(path.read_text()).get("result_dir")
        )
        for folder in (stage / "legacy-agy").iterdir():
            if folder.name in linked or not (folder / "article.md").is_file():
                continue
            info = json.loads((folder / "episode.json").read_text()) if (folder / "episode.json").is_file() else {}
            job_id = uuid.uuid5(uuid.NAMESPACE_URL, f"legacy-agy:{folder.name}").hex
            job_folder = stage / "jobs" / job_id
            if job_folder.exists():
                raise RuntimeError(f"历史 job ID 冲突：{job_id}")
            job_folder.mkdir()
            (job_folder / "job.json").write_text(json.dumps({
                "id": job_id, "filename": info.get("title") or folder.name,
                "status": "done", "stage": "done", "backend": "whisper",
                "episode": info, "episode_url": info.get("url"),
                "result_dir": str(target / "legacy-agy" / folder.name),
            }, ensure_ascii=False))
        (stage / "migration_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
        stage.rename(target)
        with sqlite3.connect(target / "podcast.db") as db:
            paths = [Path(row[0]) for row in db.execute("SELECT result_dir FROM subscription_episodes WHERE result_dir IS NOT NULL")]
            if any(not path.is_dir() for path in paths):
                raise RuntimeError("迁移后结果路径校验失败")
        return report
    except Exception:
        # Keep stage for inspection; source remains untouched.
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--target", type=Path, default=DEFAULT_TARGET)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    result = migrate(args.source.resolve(), args.target.resolve()) if args.apply else inspect(args.source.resolve(), args.target.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))
