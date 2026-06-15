import base64
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from openai import OpenAI

from audio_utils import convert_and_split, hms, mmss
from config import MIMO_API_KEY, MIMO_BASE_URL, MIMO_ASR_MODEL, STT_MAX_WORKERS


def _dedup_text(text: str, min_len: int = 15) -> str:
    """检测并移除 ASR 模型重复循环生成的文本。

    当模型陷入 repetition loop 时，会产生同一段话连续重复几十次的输出。
    策略：按句号/问号/感叹号分句，如果连续出现相同句子就截断。
    """
    sentences = re.split(r'(?<=[。？！])', text)
    sentences = [s for s in sentences if len(s.strip()) >= min_len]
    if len(sentences) < 4:
        return text

    result_sents: list[str] = []
    repeat_count = 0
    for s in sentences:
        if result_sents and s == result_sents[-1]:
            repeat_count += 1
            if repeat_count >= 2:
                continue
        else:
            repeat_count = 0
        result_sents.append(s)

    deduped = "".join(result_sents)
    return deduped if deduped else text


def _audio_to_data_url(path: str, mime: str = "audio/mpeg") -> str:
    data = Path(path).read_bytes()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def transcribe_segment(
    client: OpenAI,
    segment_path: str,
    model: str = MIMO_ASR_MODEL,
    language: str = "zh",
) -> str:
    data_url = _audio_to_data_url(segment_path)
    completion = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_audio",
                        "input_audio": {"data": data_url},
                    }
                ],
            }
        ],
        extra_body={"asr_options": {"language": language}},
    )
    return _dedup_text(completion.choices[0].message.content)


def transcribe_file(
    audio_path: str,
    api_key: str | None = None,
    base_url: str = MIMO_BASE_URL,
    model: str = MIMO_ASR_MODEL,
    language: str = "zh",
) -> str:
    """直接转录单个音频文件（不切片）。"""
    api_key = api_key or MIMO_API_KEY
    if not api_key:
        raise ValueError("缺少 MIMO_API_KEY")
    client = OpenAI(api_key=api_key, base_url=base_url)
    return transcribe_segment(client, audio_path, model, language)


def transcribe_audio(
    audio_path: str,
    api_key: str | None = None,
    base_url: str = MIMO_BASE_URL,
    model: str = MIMO_ASR_MODEL,
    language: str = "zh",
    max_workers: int = STT_MAX_WORKERS,
    keep_splits_dir: str | None = None,
) -> str:
    api_key = api_key or MIMO_API_KEY
    if not api_key:
        raise ValueError("缺少 MIMO_API_KEY")

    client = OpenAI(api_key=api_key, base_url=base_url)

    with tempfile.TemporaryDirectory() as tmp:
        def _split_progress(done: int, total: int) -> None:
            print(f"\r   切片进度: {done}/{total}", end="", flush=True)

        segments = convert_and_split(audio_path, tmp, on_progress=_split_progress)
        print()

        if keep_splits_dir:
            os.makedirs(keep_splits_dir, exist_ok=True)
            for seg_path, start, end in segments:
                dst = os.path.join(keep_splits_dir, f"{mmss(start)}-{mmss(end)}.mp3")
                shutil.copy2(seg_path, dst)

        total = len(segments)
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {}
            for i, (seg_path, start, end) in enumerate(segments):
                fut = pool.submit(transcribe_segment, client, seg_path, model, language)
                futures[fut] = (i, start)

            results: list[tuple[float, str] | None] = [None] * total
            for done, fut in enumerate(as_completed(futures), 1):
                i, start = futures[fut]
                results[i] = (start, fut.result())
                print(f"\r   转录进度: {done}/{total}", end="", flush=True)
            print()

        parts = [f"[{hms(start)}] {text}" for start, text in results]
        return "\n\n".join(parts)
