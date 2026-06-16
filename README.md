# Podcast Analysis

小宇宙播客分析工具 —— 从链接到逐字稿和摘要的一站式 CLI。

## 流程

```
小宇宙链接 → 抓取元数据 → 下载音频 → 切片 + 语音转文字 → 可选摘要
```

## 依赖

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg / ffprobe](https://ffmpeg.org/)（音频处理）
- [MiMo](https://platform.xiaomimimo.com/) API Key（语音识别）
- 任意 OpenAI 兼容 LLM API Key（摘要，可选）

## 安装

```bash
uv sync
cp .env.example .env
# 编辑 .env 填入 API Key
```

## 使用

```bash
# 基本用法：抓取 + 下载 + 转录
uv run python main.py "https://www.xiaoyuzhoufm.com/episode/<id>"

# 跳过下载（已有音频时）
uv run python main.py "https://www.xiaoyuzhoufm.com/episode/<id>" --skip-download

# 生成摘要
uv run python main.py "https://www.xiaoyuzhoufm.com/episode/<id>" --summary

# 保存切片音频（调试用）
uv run python main.py "https://www.xiaoyuzhoufm.com/episode/<id>" --keep-splits

# 指定输出目录
uv run python main.py "https://www.xiaoyuzhoufm.com/episode/<id>" -o my_output
```

## Web 界面

Web 界面仍复用同一套 Python 处理流程，运行前需要完成上面的 Python / uv / ffmpeg / ffprobe / `.env` 配置。

首次使用或前端改动后，先构建前端：

```bash
cd web
npm install
npm run build
cd ..
```

之后在仓库根目录一条命令启动本机 Web 服务：

```bash
uv run python server.py
```

该命令默认监听 `127.0.0.1:8000`，并自动打开浏览器。也可以用 uvicorn 启动：

```bash
uv run uvicorn server:app
```

此方式同样默认服务 Web 界面和 `/api/*`，浏览器手动打开 `http://127.0.0.1:8000` 即可。

## 输出结构

```
output/<episode_id>/
├── meta.json         # 节目元数据
├── audio.m4a         # 原始音频
├── transcript.txt    # 逐字稿（带时间戳）
├── summary.md       # 摘要（--summary 时生成）
└── split/            # 切片音频（--keep-splits 时保留）
```

## 配置

通过 `.env` 文件配置，参考 `.env.example`：

| 变量 | 必填 | 说明 |
|------|------|------|
| `MIMO_API_KEY` | 是 | MiMo 语音识别 API Key |
| `MIMO_BASE_URL` | 否 | MiMo 服务地址，默认 `https://token-plan-cn.xiaomimimo.com/v1` |
| `LLM_BASE_URL` | 否 | LLM 服务地址，默认 OpenAI |
| `LLM_API_KEY` | 摘要时 | LLM API Key |
| `LLM_MODEL` | 否 | 模型名，默认 `gpt-4o-mini` |
| `STT_MAX_WORKERS` | 否 | 转录并发数，默认 `4` |

## 测试

```bash
uv run pytest
```
