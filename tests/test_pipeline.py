import json

from server.pipeline import regenerate_episode, run_pipeline


def test_run_pipeline_reuses_existing_steps(tmp_path, monkeypatch):
    episode_id = "6a2d134143a22a6955830bfe"
    output_dir = tmp_path / episode_id
    output_dir.mkdir()
    (output_dir / "audio.m4a").write_bytes(b"existing")

    events = []
    monkeypatch.setattr("server.pipeline.MIMO_API_KEY", "mimo-key")
    monkeypatch.setattr(
        "server.pipeline.fetch_episode_info",
        lambda url: {
            "id": episode_id,
            "title": "标题",
            "podcast_title": "播客",
            "audio_url": "https://audio.example.com/a.m4a",
            "duration": 12,
        },
    )
    monkeypatch.setattr(
        "server.pipeline.download_audio",
        lambda url, path: (_ for _ in ()).throw(AssertionError("should not download")),
    )

    def fake_transcribe(audio_path, keep_splits_dir=None, on_progress=None):
        on_progress("splitting", 1, 2)
        on_progress("transcribing", 2, 2)
        return "逐字稿"

    monkeypatch.setattr("server.pipeline.transcribe_audio", fake_transcribe)

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
        "server.pipeline.fetch_episode_info",
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


def test_regenerate_episode_reuses_audio_without_download(tmp_path, monkeypatch):
    episode_id = "6a2d134143a22a6955830bfe"
    output_dir = tmp_path / episode_id
    output_dir.mkdir()
    (output_dir / "meta.json").write_text(
        json.dumps({"id": episode_id, "title": "标题"}),
        encoding="utf-8",
    )
    (output_dir / "audio.m4a").write_bytes(b"audio")
    (output_dir / "transcript.txt").write_text("旧逐字稿", encoding="utf-8")
    (output_dir / "summary.json").write_text("旧摘要", encoding="utf-8")

    events = []
    monkeypatch.setattr("server.pipeline.MIMO_API_KEY", "mimo-key")
    monkeypatch.setattr("server.pipeline.LLM_API_KEY", "llm-key")
    monkeypatch.setattr(
        "server.pipeline.download_audio",
        lambda url, path: (_ for _ in ()).throw(AssertionError("should not download")),
    )
    monkeypatch.setattr(
        "server.pipeline.fetch_episode_info",
        lambda url: (_ for _ in ()).throw(AssertionError("should not fetch")),
    )

    def fake_transcribe(audio_path, keep_splits_dir=None, on_progress=None):
        assert audio_path == str(output_dir / "audio.m4a")
        on_progress("splitting", 1, 1)
        on_progress("transcribing", 1, 1)
        return "新逐字稿"

    def fake_summarize(transcript, meta=None, api_key=None, base_url=None, model=None):
        assert transcript == "新逐字稿"
        assert meta["title"] == "标题"
        return {"overview": [], "mindmap": {"note": "新摘要", "nodes": []}, "worth_following": []}

    monkeypatch.setattr("server.pipeline.transcribe_audio", fake_transcribe)
    monkeypatch.setattr("server.pipeline.summarize_transcript", fake_summarize)

    regenerate_episode(
        episode_id,
        transcript=True,
        summary=True,
        output_root=str(tmp_path),
        on_event=lambda stage, done, total: events.append((stage, done, total)),
    )

    assert (output_dir / "transcript.txt").read_text(encoding="utf-8") == "新逐字稿"
    saved = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert saved["mindmap"]["note"] == "新摘要"
    assert ("splitting", 1, 1) in events
    assert ("transcribing", 1, 1) in events
    assert ("summarizing", None, None) in events
    assert events[-1] == ("done", None, None)


def test_regenerate_episode_summary_requires_transcript(tmp_path):
    episode_id = "6a2d134143a22a6955830bfe"
    output_dir = tmp_path / episode_id
    output_dir.mkdir()
    (output_dir / "meta.json").write_text("{}", encoding="utf-8")

    try:
        regenerate_episode(episode_id, summary=True, output_root=str(tmp_path))
    except FileNotFoundError as exc:
        assert "逐字稿不存在" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
