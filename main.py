import argparse
import json
import os
import sys

from config import MIMO_API_KEY, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from scraper import extract_episode_id, fetch_episode_info
from downloader import download_audio
from stt import transcribe_audio
from summarizer import summarize_transcript


def main():
    parser = argparse.ArgumentParser(description="小宇宙播客分析工具")
    parser.add_argument("url", help="小宇宙播客链接")
    parser.add_argument("-o", "--output", default="output", help="输出目录")
    parser.add_argument("--skip-download", action="store_true", help="跳过下载（使用已有音频）")
    args = parser.parse_args()

    episode_id = extract_episode_id(args.url)
    output_dir = os.path.join(args.output, episode_id)
    os.makedirs(output_dir, exist_ok=True)

    print(f"📻 开始处理: {args.url}")

    print("🔍 获取节目信息...")
    info = fetch_episode_info(args.url)
    print(f"   标题: {info['title']}")
    print(f"   播客: {info['podcast_title']}")

    with open(os.path.join(output_dir, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    audio_path = os.path.join(output_dir, "audio.m4a")
    if args.skip_download and os.path.exists(audio_path):
        print("⏭️  跳过下载（使用已有音频）")
    else:
        if not info.get("audio_url"):
            print("❌ 未找到音频链接")
            sys.exit(1)
        print("⬇️  下载音频...")
        download_audio(info["audio_url"], audio_path)
        print(f"   已保存到: {audio_path}")

    transcript_path = os.path.join(output_dir, "transcript.txt")
    if os.path.exists(transcript_path):
        print("⏭️  跳过转录（使用已有逐字稿）")
        with open(transcript_path, "r", encoding="utf-8") as f:
            transcript = f.read()
    else:
        if not MIMO_API_KEY:
            print("❌ 未配置 MIMO_API_KEY")
            sys.exit(1)
        print("🎙️  语音转文字...")
        transcript = transcribe_audio(audio_path)
        with open(transcript_path, "w", encoding="utf-8") as f:
            f.write(transcript)
        print(f"   逐字稿已保存到: {transcript_path}")

    summary_path = os.path.join(output_dir, "summary.txt")
    if not LLM_API_KEY:
        print("❌ 未配置 LLM API Key")
        sys.exit(1)
    print("📝 生成摘要...")
    summary = summarize_transcript(transcript, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(f"   摘要已保存到: {summary_path}")

    print("\n✅ 处理完成！")
    print(f"📂 输出目录: {output_dir}")


if __name__ == "__main__":
    main()
