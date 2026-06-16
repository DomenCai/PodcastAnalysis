# PodcastAnalysis 项目简报（用于生成前端）

> 这份文档写给一个要为本项目生成前端页面的 AI。读完你应该清楚：项目做什么、有哪些功能、前端要渲染哪些数据、以及如何对接（重点：**当前没有任何 Web 后端，只有命令行**）。

## 一句话定位

把一个**小宇宙播客链接**变成**带时间戳的逐字稿**和**结构化摘要**的工具。输入一个 URL，自动完成：抓元数据 → 下载音频 → 切片并语音转文字 → （可选）生成摘要。

## 当前形态（重要约束）

- 这是一个 **Python 命令行工具**，通过 `uv run python main.py <url>` 运行。
- **没有 HTTP API、没有后端服务、没有数据库**。所有产物以文件形式落在本地磁盘 `output/<episode_id>/` 目录下。
- 因此前端无法"直接"调用现有逻辑。见文末「如何对接」——通常需要你顺手生成一个最小后端把现有函数包成 HTTP 接口。

---

## 功能清单

### 主流程（`main.py`，一条命令跑完）

| 步骤 | 模块 | 做什么 | 产物 |
|------|------|--------|------|
| 1. 解析链接 | `scraper.py` | 从 URL 提取 episode_id，抓取页面里的 `__NEXT_DATA__` JSON | — |
| 2. 元数据 | `scraper.py` | 拿到标题、简介、音频直链、时长、播客名 | `meta.json` |
| 3. 下载音频 | `downloader.py` | 流式下载音频直链 | `audio.m4a` |
| 4. 切片 | `audio_utils.py` | 用 ffmpeg 探测静音点，在 45~60 秒窗口内按最长静音切割（找不到就硬切） | （临时文件，默认不保留） |
| 5. 语音转文字 | `stt.py` | 多线程并发把每个切片发给 MiMo ASR 模型，按时间戳拼回完整文稿；内置重复文本去重 | `transcript.txt` |
| 6. 摘要（可选） | `summarizer.py` | 把整篇文稿 + 元数据发给 LLM，生成结构化笔记 | `summary.md` |

**命令行参数**（这些就是前端需要暴露的"处理选项"）：
- `url`（必填）：小宇宙播客链接
- `-o, --output`：输出根目录，默认 `output`
- `--skip-download`：已有音频时跳过下载
- `--summary`：生成摘要（默认**不**生成）
- `--keep-splits`：把切片音频保留到 `split/` 子目录（调试用）

**断点续传特性**：每一步都会先检查产物是否已存在——已有 `audio.m4a` 可跳过下载、已有 `transcript.txt` 直接跳过转录、已有 `summary.md` 则不重复生成。前端展示某集状态时可据此判断"已下载/已转录/已摘要"。

### 独立子工具（各自是单独的 CLI 脚本）

1. **`split_audio.py`** — 只做切片，把任意本地音频按静音点切成多段 mp3，打印每段的起止时间。
2. **`transcribe_file.py`** — 直接转录单个本地音频文件（**不切片**，整段发给 ASR），输出纯文本逐字稿。
3. **`diarize_audio.py`** — 发言人识别（speaker diarization）。用 pyannote 模型分析音频，输出"谁在什么时间段说话"的时间轴。属于可选功能（需 `uv sync --extra diarization` 和 Hugging Face Token）。
   - ⚠️ **注意**：diarization 的结果目前**没有**和 `transcript.txt` 合并。逐字稿里**没有说话人标签**。若前端想展示"带说话人的逐字稿"，需要自己按时间戳把两份数据对齐。

---

## 数据结构（前端要渲染的核心）

所有产物都在 `output/<episode_id>/` 下。以下是真实格式。

### `meta.json` — 节目元数据
```json
{
  "id": "6a2ea7064233e62bc549afed",
  "title": "电商女装退货率居高不下，为什么不能只怪「七天无理由退货」？",
  "description": "尽管电商平台上的服装选择越来越多……（可能很长，含换行）",
  "audio_url": "https://media.xyzcdn.net/.../xxx.m4a",
  "duration": 990,
  "podcast_title": "声动早咖啡"
}
```
- `duration` 单位是**秒**（990 = 16.5 分钟）。
- ⚠️ **没有封面图字段**。如果前端设计需要封面，目前抓不到（需扩展 scraper）。

### `transcript.txt` — 逐字稿
纯文本。每段以 `[HH:MM:SS]` 时间戳开头，段落之间用空行分隔：
```
[00:00:00] 生动早咖啡与你轻松同步日常生活与商业世界。今天是……

[00:01:00] ……尤其是女装，很多人下单之前也是反复比较……

[00:01:58] 这次 SpaceX 的上市也成为了有史以来规模最大的 IPO……
```
- 时间戳大致对应每个音频切片的起点（约每 45~60 秒一段），不是逐句时间轴。
- 前端典型用法：把时间戳做成可点击锚点，点击跳转音频播放器到对应秒数。

### `summary.md` — 摘要（Markdown）
LLM 生成，固定三段结构（后两段视内容可能省略）：
```markdown
### 这期讲了什么
（约 1000 字的时间线叙事，每段以 [MM:SS] 时间戳开头）

### 思维导图
（Markdown 大纲，按逻辑组织的干货，要点带【概念】【方法】【反直觉】【书】等标签；纯闲聊则只写一句话）

### 值得追的
（值得读/尝试的书、工具、论文、人物列表；没有则省略）
```
- 前端按标准 Markdown 渲染即可。
- 历史遗留：旧产物里可能有 `summary.txt`，当前代码统一写 `summary.md`。

### `diarization.json` — 发言人时间轴（仅当跑了 diarize_audio.py）
```json
[
  { "start": 0.0, "end": 12.34, "speaker": "SPEAKER_00" },
  { "start": 12.34, "end": 20.10, "speaker": "SPEAKER_01" }
]
```
- `start`/`end` 单位是秒。`speaker` 是匿名标签（SPEAKER_00、SPEAKER_01…），不是真实姓名。

### 目录总览
```
output/<episode_id>/
├── meta.json          # 元数据（一定有）
├── audio.m4a          # 原始音频（一定有，可作播放器音源）
├── transcript.txt     # 逐字稿（一定有）
├── summary.md         # 摘要（仅 --summary 时）
├── diarization.json   # 发言人时间轴（仅单独跑 diarize 时）
└── split/             # 切片音频（仅 --keep-splits 时）
```

---

## 配置（`.env`）

| 变量 | 何时需要 | 说明 |
|------|----------|------|
| `MIMO_API_KEY` | 转录必填 | MiMo 语音识别 API Key |
| `MIMO_BASE_URL` | 否 | 默认 `https://token-plan-cn.xiaomimimo.com/v1` |
| `LLM_API_KEY` | 摘要必填 | 任意 OpenAI 兼容服务的 Key |
| `LLM_BASE_URL` | 否 | 默认 OpenAI |
| `LLM_MODEL` | 否 | 默认 `gpt-4o-mini` |
| `HF_TOKEN` | 发言人识别必填 | Hugging Face Token |
| `STT_MAX_WORKERS` | 否 | 转录并发线程数，默认 4 |

---

## 如何对接（给生成前端的你）

现状是纯 CLI，前端要能用，二选一：

**方案 A（推荐）：顺手生成一个最小后端**
把现有函数包成 HTTP 接口（用 FastAPI 即可），前端调它。现有函数已经是现成的积木：
- `scraper.fetch_episode_info(url) -> dict`
- `downloader.download_audio(url, path)`
- `stt.transcribe_audio(audio_path, keep_splits_dir=None) -> str`
- `summarizer.summarize_transcript(transcript, meta, ...) -> str`

建议的接口（按现有能力设计）：
- `POST /episodes` body `{url, summary?}` → 触发处理，返回 `episode_id`。**注意这是耗时任务**（下载 + 转录可能几分钟），需要异步任务 + 进度上报（SSE/WebSocket/轮询 `GET /episodes/{id}/status`）。进度阶段就是上面主流程的 4 步：下载 / 切片 / 转录 / 摘要。
- `GET /episodes` → 扫描 `output/` 列出所有已处理节目（读各自的 meta.json）。
- `GET /episodes/{id}` → 该集的 meta + 拥有哪些产物（是否有 transcript/summary/diarization）。
- `GET /episodes/{id}/transcript` → 逐字稿文本。
- `GET /episodes/{id}/summary` → 摘要 Markdown。
- `GET /episodes/{id}/audio` → 返回 audio.m4a 供播放器使用。

**方案 B：纯静态前端**
只读 `output/<id>/` 下已生成的文件做展示（不支持"输入链接触发处理"，因为那必须有后端跑 Python）。适合只做"阅读器"。

## 建议的前端页面（基于现有功能，供参考）

- **首页 / 节目列表**：卡片展示已处理的各集（标题、播客名、时长、有无摘要），点进详情。
- **新建处理**：输入框贴小宇宙链接，勾选「是否生成摘要」，提交后展示分步进度（下载→切片→转录→摘要）。
- **节目详情页**：
  - 顶部：标题、播客名、时长、简介（meta.json）。
  - 音频播放器：播放 audio.m4a。
  - 摘要 Tab：渲染 summary.md。
  - 逐字稿 Tab：渲染 transcript.txt，时间戳可点击跳转播放器。
  - （进阶）若有 diarization.json，可叠加说话人色块到逐字稿/时间轴。

整个产品是中文播客场景，UI 文案用中文。
