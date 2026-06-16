import json

from pipeline import run_pipeline


def test_run_pipeline_reuses_existing_steps(tmp_path, monkeypatch):
    episode_id = "6a2d134143a22a6955830bfe"
    output_dir = tmp_path / episode_id
    output_dir.mkdir()
    (output_dir / "audio.m4a").write_bytes(b"existing")

    events = []
    monkeypatch.setattr("pipeline.MIMO_API_KEY", "mimo-key")
    monkeypatch.setattr(
        "pipeline.fetch_episode_info",
        lambda url: {
            "id": episode_id,
            "title": "标题",
            "podcast_title": "播客",
            "audio_url": "https://audio.example.com/a.m4a",
            "duration": 12,
        },
    )
    monkeypatch.setattr(
        "pipeline.download_audio",
        lambda url, path: (_ for _ in ()).throw(AssertionError("should not download")),
    )

    def fake_transcribe(audio_path, keep_splits_dir=None, on_progress=None):
        on_progress("splitting", 1, 2)
        on_progress("transcribing", 2, 2)
        return "逐字稿"

    monkeypatch.setattr("pipeline.transcribe_audio", fake_transcribe)

    result = run_pipeline(
        f"https://www.xiaoyuzhoufm.com/episode/{episode_id}",
        output_root=str(tmp_path),
        on_event=lambda stage, done, total: events.append((stage, done, total)),
    )

    assert result.episode_id == episode_id
    assert (output_dir / "transcript.txt").read_text(encoding="utf-8") == "逐字稿"
    meta = json.loads((output_dir / "meta.json").read_text(encoding="utf-8"))
    assert meta["title"] == "标题"
    assert ("splitting", 1, 2) in events
    assert ("transcribing", 2, 2) in events
    assert events[-1] == ("done", None, None)


def test_run_pipeline_skip_download_requires_existing_audio(tmp_path, monkeypatch):
    episode_id = "6a2d134143a22a6955830bfe"
    monkeypatch.setattr(
        "pipeline.fetch_episode_info",
        lambda url: {"id": episode_id, "audio_url": "https://audio.example.com/a.m4a"},
    )

    try:
        run_pipeline(
            f"https://www.xiaoyuzhoufm.com/episode/{episode_id}",
            output_root=str(tmp_path),
            skip_download=True,
        )
    except FileNotFoundError as exc:
        assert "音频不存在" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
