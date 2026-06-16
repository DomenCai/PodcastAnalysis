import argparse
import os
import sys

from server.stt import transcribe_file as transcribe_audio_file


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m cli.transcribe_file",
        description="直接转录本地音频文件（不切片）",
    )
    parser.add_argument("audio", help="输入音频文件路径")
    parser.add_argument(
        "-o",
        "--output",
        default="output/transcribe",
        help="逐字稿输出文件，默认 output/transcribe",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已存在的输出文件",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audio_path = os.path.abspath(args.audio)

    if not os.path.isfile(audio_path):
        print(f"输入音频不存在: {audio_path}", file=sys.stderr)
        return 1

    output_path = os.path.abspath(args.output)
    if output_path and os.path.exists(output_path) and not args.force:
        print(
            f"输出文件已存在: {output_path}\n"
            "为避免覆盖已有逐字稿，请换一个路径，或显式加 --force。",
            file=sys.stderr,
        )
        return 1

    try:
        result = transcribe_audio_file(audio_path)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"逐字稿已保存到: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
