import requests

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"


def download_audio(url: str, output_path: str, chunk_size: int = 8192) -> str:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(url, headers=headers, stream=True, timeout=60)
    resp.raise_for_status()

    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=chunk_size):
            f.write(chunk)

    return output_path
