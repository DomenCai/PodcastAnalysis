import copy
import hashlib
import json

import pytest

from server.obsidian_export import FILES, export_job


@pytest.fixture
def bundle(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    result = tmp_path / "result"
    result.mkdir()
    for name in FILES:
        (result / name).write_text("第一段\n第二段\n", encoding="utf-8")
    config = tmp_path / "obsidian-export.json"
    config.write_text(json.dumps({"vault": str(vault)}))
    job = {
        "id": "a" * 32, "status": "done", "updated_at": "unchanged",
        "episode_url": "https://example.com/episode/1",
        "episode": {"title": "第1期 / 理解世界？", "published_at": "2001-01-01", "podcast_title": "三点下班"},
    }
    return job, result, config, vault


def test_four_markdown_files_preserve_content_and_job_state(bundle):
    job, result, config, vault = bundle
    before = copy.deepcopy(job)
    target = export_job(job, result, config)
    assert target.parent.parent == vault / "_raw/podcast"
    assert target.parent.name == "三点下班"
    assert target.name == "010101-0000-第1期-理解世界"
    assert {p.name for p in target.iterdir()} == set(FILES.values())
    for name, destination in FILES.items():
        text = (target / destination).read_text()
        assert hashlib.sha256((result / name).read_bytes()).hexdigest() in text
        if name == "transcript.txt":
            assert text.endswith("第一段\n\n第二段\n")
        else:
            assert text.endswith((result / name).read_text())
    assert job == before
    assert "自动入库" in (vault / ".meta/log.md").read_text()


def test_restart_and_reanalysis_do_not_overwrite_user_notes(bundle):
    job, result, config, vault = bundle
    target = export_job(job, result, config)
    article = target / "文章.md"
    article.write_text(article.read_text() + "\n用户批注\n")
    original = {p.name: p.read_bytes() for p in target.iterdir()}
    (result / "article.md").write_text("重新分析内容")
    job["id"] = "b" * 32
    job["episode"]["title"] = "改过的节目标题"
    assert export_job(job, result, config) is None
    assert {p.name: p.read_bytes() for p in target.iterdir()} == original
    assert len(list((vault / "_raw/podcast").glob("*/*"))) == 1


def test_distinct_episodes_with_same_title_get_separate_folders(bundle):
    job, result, config, _ = bundle
    first = export_job(job, result, config)
    job["id"] = "b" * 32
    job["episode_url"] = "https://example.com/episode/2"
    second = export_job(job, result, config)
    assert second != first
    assert first.is_dir() and second.is_dir()
    assert export_job(job, result, config) is None


@pytest.mark.parametrize("published,created,prefix", [
    ("2026-09-30T17:15:00Z", "2026-10-02T00:00:00Z", "261001-0115"),
    (None, "2026-09-21T12:14:00+00:00", "260921-2014"),
    ("invalid", "2026-09-21T20:14:00", "260921-2014"),
])
def test_folder_sort_time_uses_shanghai_publication_or_creation(bundle, published, created, prefix):
    job, result, config, _ = bundle
    job["episode"]["published_at"] = published
    job["created_at"] = created
    assert export_job(job, result, config).name == prefix + "-第1期-理解世界"


@pytest.mark.parametrize("mode", ["missing", "empty", "symlink", "running", "disabled"])
def test_only_complete_enabled_terminal_bundles_are_published(bundle, mode):
    job, result, config, vault = bundle
    article = result / "article.md"
    if mode == "missing":
        article.unlink()
    elif mode == "empty":
        article.write_text(" ")
    elif mode == "symlink":
        article.unlink()
        article.symlink_to(result / "notes.md")
    elif mode == "running":
        job["status"] = "running"
    else:
        config.write_text(json.dumps({"enabled": False, "vault": str(vault)}))
    assert export_job(job, result, config) is None
    assert not (vault / "_raw/podcast").exists()


def test_failed_publication_can_retry_without_partial_bundle(bundle, monkeypatch, caplog):
    job, result, config, vault = bundle
    import server.obsidian_export as module

    original = module.os.fsync
    monkeypatch.setattr(module.os, "fsync", lambda _: (_ for _ in ()).throw(OSError("disk full")))
    assert export_job(job, result, config) is None
    assert not list((vault / "_raw/podcast").glob("*/*"))
    assert "入库失败" in caplog.text
    assert job["status"] == "done" and job["updated_at"] == "unchanged"
    monkeypatch.setattr(module.os, "fsync", original)
    assert export_job(job, result, config).is_dir()


def test_symlink_cannot_redirect_writes_outside_vault(bundle, tmp_path):
    job, result, config, vault = bundle
    outside = tmp_path / "outside"
    outside.mkdir()
    (vault / "_raw").symlink_to(outside, target_is_directory=True)
    assert export_job(job, result, config) is None
    assert list(outside.iterdir()) == []
