import json
import os
from collections.abc import Callable
from dataclasses import dataclass

from server.config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, MIMO_API_KEY
from server.downloader import download_audio
from server.scraper import extract_episode_id, fetch_episode_info
from server.stt import transcribe_audio
from server.summarizer import summarize_transcript

PipelineEvent = Callable[[str, int | None, int | None], None]


@dataclass(frozen=True)
class PipelineResult:
    episode_id: str
    output_dir: str
    meta: dict
    transcript_path: str
    summary_path: str | None


def _emit(
    on_event: PipelineEvent | None,
    stage: str,
    done: int | None = None,
    total: int | None = None,
) -> None:
    if on_event:
        on_event(stage, done, total)


def _write_text_atomic(path: str, content: str) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, path)


def run_pipeline(
    url: str,
    summary: bool = False,
    output_root: str = "output",
    on_event: PipelineEvent | None = None,
    keep_splits: bool = False,
    skip_download: bool = False,
) -> PipelineResult:
    episode_id = extract_episode_id(url)
    output_dir = os.path.join(output_root, episode_id)
    os.makedirs(output_dir, exist_ok=True)

    _emit(on_event, "fetching_info")
    info = fetch_episode_info(url)
    meta_path = os.path.join(output_dir, "meta.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    audio_path = os.path.join(output_dir, "audio.m4a")
    if os.path.exists(audio_path):
        pass
    else:
        if skip_download:
            raise FileNotFoundError(f"跳过下载但音频不存在: {audio_path}")
        if not info.get("audio_url"):
            raise ValueError("未找到音频链接")
        _emit(on_event, "downloading")
        download_audio(info["audio_url"], audio_path)

    transcript_path = os.path.join(output_dir, "transcript.txt")
    if os.path.exists(transcript_path):
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()
    else:
        if not MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY")
        split_dir = os.path.join(output_dir, "split") if keep_splits else None

        def _progress(stage: str, done: int, total: int) -> None:
            _emit(on_event, stage, done, total)

        transcript = transcribe_audio(
            audio_path,
            keep_splits_dir=split_dir,
            on_progress=_progress,
        )
        _write_text_atomic(transcript_path, transcript)

    summary_path = os.path.join(output_dir, "summary.json")
    result_summary_path: str | None = None
    if summary:
        result_summary_path = summary_path
        if not os.path.exists(summary_path):
            if not LLM_API_KEY:
                raise ValueError("未配置 LLM_API_KEY")
            _emit(on_event, "summarizing")
            summary_data = summarize_transcript(
                transcript,
                meta=info,
                api_key=LLM_API_KEY,
                base_url=LLM_BASE_URL,
                model=LLM_MODEL,
            )
            _write_text_atomic(
                summary_path, json.dumps(summary_data, ensure_ascii=False, indent=2)
            )

    _emit(on_event, "done")
    return PipelineResult(
        episode_id=episode_id,
        output_dir=output_dir,
        meta=info,
        transcript_path=transcript_path,
        summary_path=result_summary_path,
    )


def regenerate_episode(
    episode_id: str,
    transcript: bool = False,
    summary: bool = False,
    output_root: str = "output",
    on_event: PipelineEvent | None = None,
) -> PipelineResult:
    if not transcript and not summary:
        raise ValueError("请选择需要重新生成的内容")

    output_dir = os.path.join(output_root, episode_id)
    meta_path = os.path.join(output_dir, "meta.json")
    if not os.path.isdir(output_dir) or not os.path.exists(meta_path):
        raise FileNotFoundError(f"节目不存在: {episode_id}")

    with open(meta_path, "r", encoding="utf-8") as f:
        info = json.load(f)

    audio_path = os.path.join(output_dir, "audio.m4a")
    transcript_path = os.path.join(output_dir, "transcript.txt")
    transcript_text: str

    if transcript:
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"音频不存在，无法重新生成逐字稿: {audio_path}")
        if not MIMO_API_KEY:
            raise ValueError("未配置 MIMO_API_KEY")

        def _progress(stage: str, done: int, total: int) -> None:
            _emit(on_event, stage, done, total)

        transcript_text = transcribe_audio(audio_path, on_progress=_progress)
        _write_text_atomic(transcript_path, transcript_text)
    else:
        if not os.path.exists(transcript_path):
            raise FileNotFoundError(f"逐字稿不存在，无法生成摘要: {transcript_path}")
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript_text = f.read()

    summary_path = os.path.join(output_dir, "summary.json")
    result_summary_path: str | None = None
    if summary:
        if not LLM_API_KEY:
            raise ValueError("未配置 LLM_API_KEY")
        _emit(on_event, "summarizing")
        summary_data = summarize_transcript(
            transcript_text,
            meta=info,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            model=LLM_MODEL,
        )
        _write_text_atomic(
            summary_path, json.dumps(summary_data, ensure_ascii=False, indent=2)
        )
        result_summary_path = summary_path

    _emit(on_event, "done")
    return PipelineResult(
        episode_id=episode_id,
        output_dir=output_dir,
        meta=info,
        transcript_path=transcript_path,
        summary_path=result_summary_path,
    )
