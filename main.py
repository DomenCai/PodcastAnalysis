import argparse
import sys

from pipeline import run_pipeline


def _print_event(stage: str, done: int | None, total: int | None) -> None:
    labels = {
        "fetching_info": "🔍 获取节目信息...",
        "downloading": "⬇️  下载音频...",
        "summarizing": "📝 生成摘要...",
        "done": "✅ 处理完成！",
    }
    if stage in {"splitting", "transcribing"} and done is not None and total is not None:
        label = "切片进度" if stage == "splitting" else "转录进度"
        print(f"\r   {label}: {done}/{total}", end="", flush=True)
        if done == total:
            print()
        return
    if message := labels.get(stage):
        print(message)


def main():
    parser = argparse.ArgumentParser(description="小宇宙播客分析工具")
    parser.add_argument("url", help="小宇宙播客链接")
    parser.add_argument("-o", "--output", default="output", help="输出目录")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载（使用已有音频）")
    parser.add_argument("--summary", action="store_true", help="生成摘要（默认跳过）")
    parser.add_argument("--keep-splits", action="store_true", help="保存切片音频到 split/ 目录")
    args = parser.parse_args()

    print(f"📻 开始处理: {args.url}")

    try:
        result = run_pipeline(
            args.url,
            summary=args.summary,
            output_root=args.output,
            on_event=_print_event,
            keep_splits=args.keep_splits,
            skip_download=args.skip_download,
        )
    except Exception as exc:
        print(f"❌ {exc}")
        sys.exit(1)

    print(f"📂 输出目录: {result.output_dir}")


if __name__ == "__main__":
    main()
