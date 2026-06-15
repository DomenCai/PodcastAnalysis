import base64
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile

from openai import OpenAI

from audio_utils import convert_and_split
from config import MIMO_API_KEY, MIMO_BASE_URL, MIMO_ASR_MODEL


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
    return completion.choices[0].message.content


def transcribe_audio(
    audio_path: str,
    api_key: str | None = None,
    base_url: str = MIMO_BASE_URL,
    model: str = MIMO_ASR_MODEL,
    language: str = "zh",
    max_workers: int = 4,
) -> str:
    api_key = api_key or MIMO_API_KEY
    if not api_key:
        raise ValueError("缺少 MIMO_API_KEY")

    client = OpenAI(api_key=api_key, base_url=base_url)

    with tempfile.TemporaryDirectory() as tmp:
        segments = convert_and_split(audio_path, tmp)
        if len(segments) == 1:
            return transcribe_segment(client, segments[0], model, language)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(transcribe_segment, client, seg, model, language)
                for seg in segments
            ]
            texts = [f.result() for f in futures]
        return "\n".join(texts)
