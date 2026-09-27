from email.parser import BytesParser
from email.policy import default

import pytest
from scripts import analyze_url as cli


def test_multipart_streams_audio_and_preserves_options(tmp_path):
    audio = tmp_path / "节目.m4a"
    audio.write_bytes(b"audio content")
    body, headers = cli.multipart(
        {"backend": "mimo", "skip_diarization": "false", "num_speakers": "2"}, audio
    )
    payload = b"".join(body)
    assert len(payload) == int(headers["Content-Length"])
    parsed = BytesParser(policy=default).parsebytes(
        f"Content-Type: {headers['Content-Type']}\r\nMIME-Version: 1.0\r\n\r\n".encode()
        + payload
    )
    fields = {
        part.get_param("name", header="content-disposition"): part
        for part in parsed.iter_parts()
    }
    assert fields["file"].get_payload(decode=True) == b"audio content"
    assert fields["backend"].get_payload(decode=True) == b"mimo"
    assert fields["skip_diarization"].get_payload(decode=True) == b"false"
    assert audio.read_bytes() == b"audio content"


def test_cli_analyze_only_uses_api_not_local_inference(monkeypatch):
    requests = []
    job_id = "a" * 32

    def request(base, path, **kwargs):
        requests.append((base, path, kwargs))
        if path.endswith("/analyze"):
            return {"job_id": job_id}
        return {"status": "done", "stage": "done", "available_files": ["article.md"]}

    monkeypatch.setattr(cli, "request_json", request)
    monkeypatch.setattr("sys.argv", ["analysis", "--analyze-only", job_id])
    assert cli.main() == 0
    assert requests[0][1] == f"/api/jobs/{job_id}/analyze"
    assert requests[0][2]["method"] == "POST"
    assert len(requests) == 2


def test_cli_rejects_invalid_job_id_before_http(monkeypatch):
    monkeypatch.setattr("sys.argv", ["analysis", "--analyze-only", "../../bad"])
    monkeypatch.setattr(
        cli, "request_json", lambda *a, **kw: pytest.fail("unexpected HTTP")
    )
    with pytest.raises(SystemExit) as result:
        cli.main()
    assert result.value.code == 2
