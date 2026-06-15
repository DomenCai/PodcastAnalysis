# 小宇宙播客分析工具 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use compose:subagent (recommended) or compose:execute to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 从小宇宙播客链接自动提取音频、转录文字、生成摘要

**Architecture:** CLI 工具，模块化设计：爬虫 → 下载器 → STT → 总结器，通过 main.py 串联

**Tech Stack:** Python 3.10+, requests, beautifulsoup4, python-dotenv

---

## 文件结构

```
PodcastAnalysis/
├── main.py                 # CLI 入口
├── scraper.py              # 小宇宙页面爬虫
├── downloader.py           # 音频下载器
├── stt.py                  # 小米云服务 STT 封装
├── summarizer.py           # LLM 总结封装
├── config.py               # 配置管理
├── .env.example            # 环境变量示例
├── requirements.txt        # 依赖列表
└── tests/
    ├── test_scraper.py
    ├── test_downloader.py
    ├── test_stt.py
    └── test_summarizer.py
```

---

### Task 1: 项目初始化与配置

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `config.py`

- [ ] **Step 1: 创建 requirements.txt**

```txt
requests>=2.31.0
beautifulsoup4>=4.12.0
python-dotenv>=1.0.0
```

- [ ] **Step 2: 创建 .env.example**

```env
# 小米云服务 STT
XIAOMI_APP_ID=your_app_id
XIAOMI_APP_KEY=your_app_key

# LLM 总结
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-xxx
LLM_MODEL=gpt-4o-mini
```

- [ ] **Step 3: 创建 config.py**

```python
import os
from dotenv import load_dotenv

load_dotenv()

XIAOMI_APP_ID = os.getenv("XIAOMI_APP_ID")
XIAOMI_APP_KEY = os.getenv("XIAOMI_APP_KEY")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
```

- [ ] **Step 4: 安装依赖并验证**

Run: `pip install -r requirements.txt`
Expected: Successfully installed

- [ ] **Step 5: Commit**

```bash
git add requirements.txt .env.example config.py
git commit -m "chore: initialize project with config and dependencies"
```

---

### Task 2: 小宇宙页面爬虫

**Covers:** [S1] 提取音频URL和元信息

**Files:**
- Create: `scraper.py`
- Create: `tests/test_scraper.py`

- [ ] **Step 1: 编写爬虫测试**

```python
# tests/test_scraper.py
from scraper import extract_episode_info

def test_extract_episode_id():
    url = "https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe"
    episode_id = extract_episode_id(url)
    assert episode_id == "6a2d134143a22a6955830bfe"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_scraper.py -v`
Expected: FAIL (模块不存在)

- [ ] **Step 3: 实现爬虫模块**

```python
# scraper.py
import re
import requests
from bs4 import BeautifulSoup

def extract_episode_id(url: str) -> str:
    """从 URL 提取 episode ID"""
    match = re.search(r'/episode/([a-f0-9]+)', url)
    if not match:
        raise ValueError(f"Invalid xiaoyuzhou URL: {url}")
    return match.group(1)

def fetch_episode_info(url: str) -> dict:
    """获取单集信息：标题、音频URL、描述"""
    episode_id = extract_episode_id(url)
    api_url = f"https://www.xiaoyuzhoufm.com/episode/{episode_id}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }
    
    resp = requests.get(api_url, headers=headers, timeout=30)
    resp.raise_for_status()
    
    soup = BeautifulSoup(resp.text, 'html.parser')
    
    # 从页面 script 标签提取 JSON 数据
    script_tag = soup.find('script', id='__NEXT_DATA__')
    if script_tag:
        import json
        data = json.loads(script_tag.string)
        props = data.get('props', {}).get('pageProps', {})
        episode = props.get('episode', {})
        
        return {
            'id': episode_id,
            'title': episode.get('title', ''),
            'description': episode.get('description', ''),
            'audio_url': episode.get('media', {}).get('source', ''),
            'duration': episode.get('duration', 0),
            'podcast_title': episode.get('podcast', {}).get('title', ''),
        }
    
    # fallback: 从 meta 标签提取
    audio_meta = soup.find('meta', property='og:audio')
    title_meta = soup.find('meta', property='og:title')
    
    return {
        'id': episode_id,
        'title': title_meta['content'] if title_meta else '',
        'audio_url': audio_meta['content'] if audio_meta else '',
        'description': '',
        'duration': 0,
        'podcast_title': '',
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_scraper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add scraper.py tests/test_scraper.py
git commit -m "feat: add xiaoyuzhou episode scraper"
```

---

### Task 3: 音频下载器

**Covers:** [S2] 下载音频文件

**Files:**
- Create: `downloader.py`
- Create: `tests/test_downloader.py`

- [ ] **Step 1: 编写下载器测试**

```python
# tests/test_downloader.py
import os
from downloader import download_audio

def test_download_creates_file(tmp_path):
    # 使用一个小的测试 URL
    url = "https://httpbin.org/bytes/100"
    output = tmp_path / "test.bin"
    download_audio(url, str(output))
    assert output.exists()
    assert output.stat().st_size > 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_downloader.py -v`
Expected: FAIL (模块不存在)

- [ ] **Step 3: 实现下载器**

```python
# downloader.py
import requests

def download_audio(url: str, output_path: str) -> str:
    """下载音频文件到指定路径"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    }
    
    resp = requests.get(url, headers=headers, stream=True, timeout=60)
    resp.raise_for_status()
    
    with open(output_path, 'wb') as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    
    return output_path
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_downloader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add downloader.py tests/test_downloader.py
git commit -m "feat: add audio downloader"
```

---

### Task 4: 小米云服务 STT 封装

**Covers:** [S3] 音频转文字

**Files:**
- Create: `stt.py`
- Create: `tests/test_stt.py`

- [ ] **Step 1: 编写 STT 测试**

```python
# tests/test_stt.py
from unittest.mock import patch, MagicMock
from stt import transcribe_audio

def test_transcribe_audio():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'result': '这是一段测试文字'
    }
    mock_response.raise_for_status.return_value = None
    
    with patch('stt.requests.post', return_value=mock_response):
        result = transcribe_audio('test.m4a', 'app_id', 'app_key')
        assert '测试' in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_stt.py -v`
Expected: FAIL (模块不存在)

- [ ] **Step 3: 实现 STT 模块**

```python
# stt.py
import requests
import time

def transcribe_audio(audio_path: str, app_id: str, app_key: str) -> str:
    """调用小米云服务 STT API 将音频转为文字"""
    
    # 上传音频文件
    upload_url = "https://speech.ai.xiaomi.com/api/v1/upload"
    headers = {
        "Authorization": f"Bearer {app_key}",
    }
    
    with open(audio_path, 'rb') as f:
        files = {'audio': (audio_path, f, 'audio/m4a')}
        data = {'app_id': app_id}
        resp = requests.post(upload_url, headers=headers, files=files, data=data, timeout=120)
        resp.raise_for_status()
    
    task_id = resp.json().get('task_id')
    
    # 轮询结果
    result_url = f"https://speech.ai.xiaomi.com/api/v1/result/{task_id}"
    for _ in range(60):  # 最多等待 5 分钟
        time.sleep(5)
        resp = requests.get(result_url, headers=headers, timeout=30)
        resp.raise_for_status()
        result = resp.json()
        
        if result.get('status') == 'completed':
            return result.get('text', '')
        elif result.get('status') == 'failed':
            raise Exception(f"STT failed: {result.get('error')}")
    
    raise Exception("STT timeout")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_stt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add stt.py tests/test_stt.py
git commit -m "feat: add xiaomi cloud STT integration"
```

---

### Task 5: LLM 总结模块

**Covers:** [S4] 内容总结

**Files:**
- Create: `summarizer.py`
- Create: `tests/test_summarizer.py`

- [ ] **Step 1: 编写总结器测试**

```python
# tests/test_summarizer.py
from unittest.mock import patch, MagicMock
from summarizer import summarize_transcript

def test_summarize_transcript():
    mock_response = MagicMock()
    mock_response.json.return_value = {
        'choices': [{
            'message': {
                'content': '这是一段摘要'
            }
        }]
    }
    mock_response.raise_for_status.return_value = None
    
    with patch('summarizer.requests.post', return_value=mock_response):
        result = summarize_transcript(
            '这是一段很长的逐字稿...',
            'https://api.openai.com/v1',
            'sk-xxx',
            'gpt-4o-mini'
        )
        assert '摘要' in result
```

- [ ] **Step 2: 运行测试确认失败**

Run: `pytest tests/test_summarizer.py -v`
Expected: FAIL (模块不存在)

- [ ] **Step 3: 实现总结器**

```python
# summarizer.py
import requests

SUMMARY_PROMPT = """请根据以下播客逐字稿，生成一份结构化摘要，包括：

1. **核心主题**：一句话概括本期播客讨论的核心内容
2. **关键观点**：列出 3-5 个最重要的观点或结论
3. **精彩金句**：摘录 2-3 句最有价值的原话
4. **行动建议**：如果有的话，列出可执行的建议

逐字稿内容：
{transcript}
"""

def summarize_transcript(
    transcript: str,
    base_url: str,
    api_key: str,
    model: str
) -> str:
    """调用 LLM API 生成摘要"""
    
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个专业的播客内容分析师，擅长提取关键信息并生成结构化摘要。"},
            {"role": "user", "content": SUMMARY_PROMPT.format(transcript=transcript)}
        ],
        "temperature": 0.3
    }
    
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    
    return resp.json()['choices'][0]['message']['content']
```

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/test_summarizer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add summarizer.py tests/test_summarizer.py
git commit -m "feat: add LLM summarizer with structured output"
```

---

### Task 6: CLI 主入口

**Covers:** [S5] 整体流程串联

**Files:**
- Create: `main.py`

- [ ] **Step 1: 实现 CLI 入口**

```python
# main.py
import argparse
import os
import sys

from config import XIAOMI_APP_ID, XIAOMI_APP_KEY, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
from scraper import fetch_episode_info
from downloader import download_audio
from stt import transcribe_audio
from summarizer import summarize_transcript

def main():
    parser = argparse.ArgumentParser(description='小宇宙播客分析工具')
    parser.add_argument('url', help='小宇宙播客链接')
    parser.add_argument('-o', '--output', default='output', help='输出目录')
    parser.add_argument('--skip-download', action='store_true', help='跳过下载（使用已有音频）')
    args = parser.parse_args()
    
    # 创建输出目录
    episode_id = args.url.split('/episode/')[-1].split('?')[0]
    output_dir = os.path.join(args.output, episode_id)
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"📻 开始处理: {args.url}")
    
    # Step 1: 获取节目信息
    print("🔍 获取节目信息...")
    info = fetch_episode_info(args.url)
    print(f"   标题: {info['title']}")
    print(f"   播客: {info['podcast_title']}")
    
    # 保存元信息
    import json
    with open(os.path.join(output_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(info, f, ensure_ascii=False, indent=2)
    
    # Step 2: 下载音频
    audio_path = os.path.join(output_dir, 'audio.m4a')
    if args.skip_download and os.path.exists(audio_path):
        print("⏭️  跳过下载（使用已有音频）")
    else:
        if not info.get('audio_url'):
            print("❌ 未找到音频链接")
            sys.exit(1)
        print("⬇️  下载音频...")
        download_audio(info['audio_url'], audio_path)
        print(f"   已保存到: {audio_path}")
    
    # Step 3: 语音转文字
    transcript_path = os.path.join(output_dir, 'transcript.txt')
    if os.path.exists(transcript_path):
        print("⏭️  跳过转录（使用已有逐字稿）")
        with open(transcript_path, 'r', encoding='utf-8') as f:
            transcript = f.read()
    else:
        if not XIAOMI_APP_ID or not XIAOMI_APP_KEY:
            print("❌ 未配置小米云服务 STT 凭证")
            sys.exit(1)
        print("🎙️  语音转文字...")
        transcript = transcribe_audio(audio_path, XIAOMI_APP_ID, XIAOMI_APP_KEY)
        with open(transcript_path, 'w', encoding='utf-8') as f:
            f.write(transcript)
        print(f"   逐字稿已保存到: {transcript_path}")
    
    # Step 4: 生成摘要
    summary_path = os.path.join(output_dir, 'summary.txt')
    if not LLM_API_KEY:
        print("❌ 未配置 LLM API Key")
        sys.exit(1)
    print("📝 生成摘要...")
    summary = summarize_transcript(transcript, LLM_BASE_URL, LLM_API_KEY, LLM_MODEL)
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write(summary)
    print(f"   摘要已保存到: {summary_path}")
    
    print("\n✅ 处理完成！")
    print(f"📂 输出目录: {output_dir}")

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: 验证 CLI 帮助信息**

Run: `python main.py --help`
Expected: 显示帮助信息

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: add CLI entry point with full pipeline"
```

---

### Task 7: 端到端测试

**Covers:** [S6] 完整流程验证

- [ ] **Step 1: 创建 .env 文件（使用真实凭证）**

```bash
cp .env.example .env
# 编辑 .env 填入真实凭证
```

- [ ] **Step 2: 运行完整流程**

Run: `python main.py https://www.xiaoyuzhoufm.com/episode/6a2d134143a22a6955830bfe`
Expected: 所有步骤成功完成

- [ ] **Step 3: 验证输出文件**

Run: `ls -la output/6a2d134143a22a6955830bfe/`
Expected: 存在 meta.json, audio.m4a, transcript.txt, summary.txt

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "docs: add .env.example and update README"
```

---

## 验证清单

- [ ] 所有单元测试通过: `pytest tests/ -v`
- [ ] CLI 帮助信息正常: `python main.py --help`
- [ ] 端到端流程成功: 使用真实链接测试
- [ ] 输出文件完整: meta.json, transcript.txt, summary.txt
