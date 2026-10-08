#!/usr/bin/env python3
"""Submit URL/local audio to the shared service; never spawn a second model worker."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

STAGES = {
    "queued": "排队中",
    "fetching": "获取节目和临时音频",
    "starting": "开始处理",
    "converting": "转换音频",
    "splitting": "切片",
    "transcribing": "转写",
    "diarizing": "发言人分离",
    "postprocessing": "错别字清洗与标点恢复",
    "analyzing": "生成文章、笔记与导图",
    "archiving": "归档上一版产物",
    "done": "完成",
    "error": "失败",
}


def request_json(base: str, path: str, *, data=None, headers=None, method=None):
    request = urllib.request.Request(
        base.rstrip("/") + path, data=data, headers=headers or {}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("detail", str(exc))
        except (ValueError, AttributeError):
            detail = str(exc)
        raise RuntimeError(detail) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            "无法连接管理服务。请先启动 python -m server.app，或指定 --api。"
        ) from exc


def multipart(fields: dict[str, str], source: Path | None):
    boundary = "podcast-" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
        )
    if source is not None:
        # Use a safe ASCII filename; the server still gets the extension for decoding.
        name = "source" + source.suffix[:12]
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
        )
    head = b"".join(parts)
    tail = (
        "\r\n" if source is not None else ""
    ).encode() + f"--{boundary}--\r\n".encode()
    length = len(head) + len(tail) + (source.stat().st_size if source else 0)

    def body():
        yield head
        if source:
            with source.open("rb") as stream:
                while block := stream.read(1024 * 1024):
                    yield block
        yield tail

    return body(), {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(length),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", nargs="?", help="小宇宙单集 URL 或本地音频")
    parser.add_argument("--backend", choices=("qwen", "whisper", "mimo"), default="qwen")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--diarize", action="store_true", help="启用发言人分离")
    group.add_argument(
        "--skip-diarization", "--skip-speaker-identification", action="store_true"
    )
    parser.add_argument(
        "--num-speakers", type=int, help="指定 1～32 人，同时启用分离（1 人跳过模型）"
    )
    parser.add_argument(
        "--analyze-only", metavar="JOB_ID", help="复用已保存逐字稿，仅重新生成文章、笔记与导图"
    )
    parser.add_argument(
        "--api", default=os.getenv("PODCAST_API_URL", "http://127.0.0.1:18000")
    )
    parser.add_argument("--interval", type=float, default=3)
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error("--interval 必须大于 0")
    if args.num_speakers is not None and not 1 <= args.num_speakers <= 32:
        parser.error("--num-speakers 必须为 1～32")
    if args.analyze_only:
        if args.source:
            parser.error("--analyze-only 不需要 source")
        if len(args.analyze_only) != 32 or any(
            c not in "0123456789abcdef" for c in args.analyze_only
        ):
            parser.error("JOB_ID 格式错误")
        created = request_json(
            args.api, f"/api/jobs/{args.analyze_only}/analyze", data=b"", method="POST"
        )
    else:
        if not args.source:
            parser.error("请提供 source，或使用 --analyze-only JOB_ID")
        enabled = (
            args.diarize or args.num_speakers is not None
        ) and not args.skip_diarization
        fields = {"backend": args.backend, "skip_diarization": str(not enabled).lower()}
        if args.num_speakers is not None:
            fields["num_speakers"] = str(args.num_speakers)
        source = None
        if args.source.startswith(("http://", "https://")):
            fields["url"] = args.source
        else:
            source = Path(args.source).expanduser().resolve()
            if not source.is_file():
                parser.error(f"音频不存在：{source}")
        body, headers = multipart(fields, source)
        created = request_json(
            args.api, "/api/jobs", data=body, headers=headers, method="POST"
        )
    job_id = created["job_id"]
    print(f"任务: {job_id}\n阅读: {args.api.rstrip('/')}/jobs/{job_id}", flush=True)
    previous = None
    while True:
        state = request_json(args.api, f"/api/jobs/{job_id}")
        progress = (
            state["status"],
            state["stage"],
            state.get("done"),
            state.get("total"),
        )
        if progress != previous:
            print(
                f"[{state['status']}] {STAGES.get(state['stage'], state['stage'])}",
                flush=True,
            )
            previous = progress
        if state["status"] == "error":
            print(state.get("error") or "任务失败", file=sys.stderr)
            return 1
        if state["status"] == "done":
            print("完成：" + "、".join(state.get("available_files", [])))
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n停止等待；服务端任务继续执行。", file=sys.stderr)
        raise SystemExit(130)
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        raise SystemExit(1)
