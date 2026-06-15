import argparse
import os
import sys

from audio_utils import SEGMENT_MAX, SEGMENT_TARGET, convert_and_split, hms, mmss


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="按静音点切分本地音频")
    parser.add_argument("audio", help="输入音频文件路径")
    parser.add_argument(
        "-o",
        "--output",
        default="output/split",
        help="切片输出目录，默认 output/split",
    )
    parser.add_argument(
        "--target",
        type=float,
        default=SEGMENT_TARGET,
        help=f"开始寻找静音点的秒数，默认 {SEGMENT_TARGET}",
    )
    parser.add_argument(
        "--max-sec",
        type=float,
        default=SEGMENT_MAX,
        help=f"单段最长秒数，默认 {SEGMENT_MAX}",
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
    if args.target <= 0 or args.max_sec <= 0:
        print("--target 和 --max-sec 必须大于 0", file=sys.stderr)
        return 1
    if args.target >= args.max_sec:
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
        on_progress=on_progress,
    )
    print()

    print(f"已生成 {len(segments)} 个切片: {output_dir}")
    for path, start, end in segments:
        print(f"{mmss(start)}-{mmss(end)}  {hms(start)} -> {hms(end)}  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
