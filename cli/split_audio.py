import argparse
import os
import sys

from server.audio_utils import (
    LONG_SILENCE_MIN_DURATION,
    LONG_SILENCE_SEARCH_END,
    LONG_SILENCE_SEARCH_START,
    SEGMENT_MAX,
    SEGMENT_TARGET,
    convert_and_split,
    hms,
    mmss,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m cli.split_audio",
        description="按静音点切分本地音频",
    )
    parser.add_argument("audio", help="输入音频文件路径")
    parser.add_argument(
        "-o",
        "--output",
        default="output/split",
        help="切片输出目录，默认 output/split",
    )
    parser.add_argument(
        "--long-search-start",
        type=float,
        default=LONG_SILENCE_SEARCH_START,
        help=f"长静音扫描窗口起点秒数，默认 {LONG_SILENCE_SEARCH_START}",
    )
    parser.add_argument(
        "--long-search-end",
        type=float,
        default=LONG_SILENCE_SEARCH_END,
        help=f"长静音扫描窗口终点秒数，默认 {LONG_SILENCE_SEARCH_END}",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=SEGMENT_TARGET,
        help=f"普通静音兜底窗口起点秒数，默认 {SEGMENT_TARGET}",
    )
    parser.add_argument(
        "--max-sec",
        type=float,
        default=SEGMENT_MAX,
        help=f"普通静音兜底窗口终点和硬切秒数，默认 {SEGMENT_MAX}",
    )
    parser.add_argument(
        "--long-silence-sec",
        type=float,
        default=LONG_SILENCE_MIN_DURATION,
        help=f"优先切开的长静音秒数，默认 {LONG_SILENCE_MIN_DURATION}",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖输出目录内同名切片文件",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audio_path = os.path.abspath(args.audio)
    output_dir = os.path.abspath(args.output)

    if not os.path.isfile(audio_path):
        print(f"输入音频不存在: {audio_path}", file=sys.stderr)
        return 1
    if (
        args.long_search_start <= 0
        or args.long_search_end <= 0
        or args.target <= 0
        or args.max_sec <= 0
        or args.long_silence_sec <= 0
    ):
        print("所有时长参数都必须大于 0", file=sys.stderr)
        return 1
    if not args.long_search_start < args.long_search_end:
        print(
            "--long-search-start 必须小于 --long-search-end",
            file=sys.stderr,
        )
        return 1
    if not args.target < args.max_sec:
        print("--target 必须小于 --max-sec", file=sys.stderr)
        return 1

    os.makedirs(output_dir, exist_ok=True)
    existing_files = [
        name
        for name in os.listdir(output_dir)
        if os.path.isfile(os.path.join(output_dir, name))
    ]
    if existing_files and not args.force:
        print(
            f"输出目录已有文件: {output_dir}\n"
            "为避免覆盖已有切片，请换一个目录，或显式加 --force。",
            file=sys.stderr,
        )
        return 1

    def on_progress(done: int, total: int) -> None:
        print(f"\r切片进度: {done}/{total}", end="", flush=True)

    segments = convert_and_split(
        audio_path,
        output_dir,
        target=args.target,
        max_sec=args.max_sec,
        long_search_start=args.long_search_start,
        long_search_end=args.long_search_end,
        long_silence_sec=args.long_silence_sec,
        on_progress=on_progress,
    )
    print()

    print(f"已生成 {len(segments)} 个切片: {output_dir}")
    for path, start, end in segments:
        print(f"{mmss(start)}-{mmss(end)}  {hms(start)} -> {hms(end)}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
