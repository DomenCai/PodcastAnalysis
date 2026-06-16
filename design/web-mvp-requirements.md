# PodcastAnalysis Web MVP 需求文档与实现规划

日期：2026-06-16

## 1. 背景与定位

PodcastAnalysis 当前是一个本地 Python CLI 工具：输入小宇宙节目链接，抓取元数据、下载音频、切片转录，并可选生成摘要。产物以文件写入 `output/<episode_id>/`，没有 HTTP 服务、数据库或账号系统。

本 MVP 给它加一个**本机运行的 Web 图形界面**（localhost），让使用者不必反复敲命令、翻文件，就能在浏览器里发起处理、浏览历史节目、阅读逐字稿与摘要。第一阶段聚焦「作者本机自用」；因为核心只依赖 Python，它天然也能被开源出去、让他人在自己机器上同样 localhost 运行（见 M3 的分发收尾）。

定位要点：

- 前端只负责**展示和触发**，所有重活（抓取、下载、切片、转录、摘要）复用现有 Python 函数，不重写。
- CLI（`main.py`）保留，前端是新增的图形入口，与 CLI **共用同一套底层编排**，避免两套流程分叉。
- 形态是「本机 localhost 工具」，默认只监听 `127.0.0.1`；开源 / 远程部署是可选的后续收尾，不是 MVP 的前置约束。

## 2. 目标

1. 在浏览器里粘贴小宇宙链接并启动现有处理流程。
2. 能看到任务当前阶段和数字进度（如切片 `12/71`），不必盯终端。
3. 能浏览本地 `output/` 下已处理过的节目。
4. 能在详情页播放音频、阅读逐字稿和摘要。
5. 一条命令在本机启动（`uv run`），浏览器访问 localhost 即可使用。

## 3. 非目标

MVP 不做：

- 不做账号、登录、多用户、权限隔离。所有访问者共享同一个本地节目库。
- 不在前端管理 API Key。Key 一律走现有 `.env`，前端不读取、不保存、不展示 Key 明文。
- 不做多人并发任务队列。同一时间只允许一个处理任务。
- 不做发言人识别（diarization）、说话人时间轴、逐字稿与说话人对齐。
- 不做逐字稿/摘要的在线编辑或校对。
- 不做节目删除、目录清理、回滚。
- 不做摘要的事后补生成入口（摘要只在新建处理时按勾选一次性生成）。
- 不做逐字稿与播放器的联动高亮（逐字稿为纯展示）。
- 不做 Redis / Celery / 数据库。任务状态保存在进程内存。
- 不打包 Python / `uv` / `ffmpeg`。沿用 README 的环境前置要求。
- MVP 不做远程访问加固：默认仅监听 `127.0.0.1`。需要远程访问时，由使用者自行配置反向代理与鉴权，自负安全。

## 4. 架构总览

```
浏览器 (React SPA, web/dist)
        │  HTTP (同源)
        ▼
FastAPI 单进程 (server.py)
   ├── 静态托管 web/dist  →  GET /
   ├── REST API          →  /api/*
   └── 后台线程跑 run_pipeline()
                  │  直接 import 调用
                  ▼
   现有 Python 模块 (scraper / downloader / stt / summarizer)
                  │
                  ▼
            output/<episode_id>/  (meta.json / audio.m4a / transcript.txt / summary.md)
```

要点：

- **单进程**：FastAPI 同时托管前端静态产物和 API，本机只起这一个服务。
- **后端与核心同语言**：FastAPI 直接 `import` 现有函数，进程内调用，无子进程、无额外 IPC。
- **进度**：后台线程执行编排，把阶段与 `done/total` 写进**进程内任务表**；前端**轮询** `GET /api/tasks/{id}`。
- **音频**：直接服务本地产物 `output/<id>/audio.m4a`（`FileResponse` 原生支持 Range，可直接 seek），不引入 CDN 代理。

## 5. 信息架构

三个页面：

1. **节目库（首页）**：扫描 `output/`，卡片列出已处理节目。
2. **新建处理**：输入链接、勾选选项、启动任务、看分步进度。
3. **节目详情**：元信息、音频播放器、逐字稿、摘要。

顶部或侧边提供一个轻量的**环境状态**提示（见 6.5），不单独成页。

## 6. 功能需求

### 6.1 节目库（首页）

扫描默认输出目录 `output/` 下的一级子目录，含 `meta.json` 的视为一个节目。

卡片展示字段（全部来自 `meta.json` 与目录内文件存在性）：标题、播客名、时长、是否已有逐字稿、是否已有摘要。

验收标准：

- 启动后能看到 `output/` 里已有的节目。
- 点击卡片进入详情页。
- 某目录缺失或损坏 `meta.json` 时，跳过该项，不报错、不修复、不删除。
- 顶部提供「新建处理」入口。

### 6.2 新建处理

表单字段：

- 小宇宙节目链接（必填）。
- 「同时生成摘要」勾选，默认关闭。

提交后调用后端 `POST /api/episodes` 启动任务，页面切换到进度视图（见 6.3）。

验收标准：

- URL 为空不能提交。
- URL 不是合法小宇宙 episode 链接（正则 `/episode/([a-f0-9]+)` 不匹配）时，前端直接提示，不发请求。
- 已有任务在跑时，提交被拒绝并提示「已有任务进行中」（后端返回 409）。
- 缺少 `ffmpeg` / `ffprobe`、输出目录不可写、或 `MIMO_API_KEY` 时，提交按钮不可用并说明原因（见 6.5）。
- 缺少 `LLM_API_KEY` 时，「同时生成摘要」勾选不可用并提示。

**实现补充**：后端编排沿用现有幂等逻辑——同一 episode 若已有 `audio`/`transcript`/`summary`，对应步骤跳过，不重复下载或转录。

### 6.3 任务进度

进度阶段（前端按顺序展示，当前阶段高亮）：

1. 获取节目信息
2. 下载音频
3. 切片
4. 转录
5. 摘要（仅当勾选）
6. 完成

切片与转录阶段显示数字进度 `done/total`。其余阶段显示阶段状态文本。前端每 1–2 秒轮询 `GET /api/tasks/{id}`。

验收标准：

- 用户能判断任务在运行、已完成还是失败。
- 失败时显示可指导下一步的错误信息（见 第 11 节）。
- 失败后保留已生成的本地产物，不自动清理。
- 任务完成后自动跳转到对应节目详情页。
- MVP **不提供取消按钮**（列入后续版本）。

### 6.4 节目详情

展示：标题、播客名、时长、节目简介（均来自 `meta.json`）、音频播放器、逐字稿、摘要。

**音频播放器**：使用 wavesurfer.js，音频源为 `GET /api/episodes/{id}/audio`（后端以 `FileResponse` 服务本地 `output/<id>/audio.m4a`，同源、自带 Range）。`audio.m4a` 不存在时，显示「音频不可用」，不影响逐字稿与摘要阅读。

**逐字稿**：读取 `transcript.txt`，前端按空行拆段展示。每段以 `[HH:MM:SS]` 时间戳开头时，时间戳作为文本前缀显示（**不可点击、不与播放器联动**）。纯只读。

**摘要**：读取 `summary.md`，按 Markdown 渲染。摘要不存在时显示「未生成摘要」，不报错。

**下载入口**：提供「下载逐字稿（.txt）」「下载摘要（.md）」按钮（摘要按钮仅在存在时显示）。**不提供「打开本地目录」**（Web 沙箱无此能力，且与开源/远程部署语义不符）。

验收标准：

- 已有节目无需重新处理即可浏览。
- 音频可播放并可拖动 seek；波形正常渲染。
- 逐字稿可阅读。
- 摘要存在时渲染正常，不存在时不报错。

### 6.5 环境状态（轻量）

**实现补充**（grill 未覆盖，但能避免最常见的「跑一半才失败」）：前端启动时请求 `GET /api/health`，得到 `ffmpeg`、`ffprobe`、输出目录可写、`MIMO_API_KEY`、`LLM_API_KEY` 是否就绪，用于：

- 缺 `ffmpeg` / `ffprobe`、输出目录不可写、或缺 `MIMO_API_KEY` → 禁用「新建处理」提交并提示具体缺项。
- 缺 `LLM_API_KEY` → 禁用「同时生成摘要」勾选并提示。

`ffprobe` 须单独检查：切片前 `audio_utils.probe_duration` 会调用它，只查 `ffmpeg` 会出现“健康检查通过、任务却在切片前失败”。只返回布尔就绪状态，**不返回 Key 明文**。这是唯一的环境检查，刻意保持最小。

## 7. 后端 API 规格

所有接口同源，前缀 `/api`。

| 方法与路径 | 作用 | 返回 |
|---|---|---|
| `GET /api/health` | 环境就绪状态 | `{ffmpeg, ffprobe, output_writable, mimo_key, llm_key}`（均为 bool） |
| `GET /api/episodes` | 节目库列表（扫 `output/`） | `[{id, title, podcast_title, duration, has_transcript, has_summary}]` |
| `GET /api/episodes/{id}` | 节目详情元数据 | `meta.json` 内容 + `{has_audio, has_transcript, has_summary}` |
| `GET /api/episodes/{id}/transcript` | 逐字稿原文 | `text/plain` |
| `GET /api/episodes/{id}/summary` | 摘要原文 | `text/markdown`，不存在返回 404 |
| `GET /api/episodes/{id}/audio` | 服务本地 `audio.m4a` | `FileResponse`（自带 Range/206）；文件不存在返回 404 |
| `POST /api/episodes` | 启动处理任务 | `{task_id}`；已有任务运行中返回 409；URL 非法返回 400 |
| `GET /api/tasks/{id}` | 查询任务进度 | 见第 8 节任务状态 |
| `GET /` 及静态资源 | 托管 `web/dist` | SPA |

**音频说明**：直接用 Starlette `FileResponse` 返回本地 `output/<id>/audio.m4a` 即可，它原生处理 `Range` 与 `206`，wavesurfer 同源加载无跨域问题。不用 CDN 代理——音频本就是现有 CLI 的产物，沿用即可，也不依赖 CDN 存活。

**路径参数校验**：所有 `{id}` 必须匹配 `^[a-f0-9]+$`，不匹配返回 400。拼接 `output/<id>/` 之前先校验，避免路径穿越——即便默认只绑本机，文件服务端点也不留隐含假设。

## 8. 数据与任务状态模型

不引入数据库。状态来源：

- 节目列表 / 详情 / 逐字稿 / 摘要：直接读 `output/<id>/` 下文件。
- 任务状态：**进程内内存**（一个 `dict[task_id] -> TaskState`）。

任务状态结构：

```json
{
  "task_id": "uuid",
  "episode_id": "6a2e...",        // 解析到链接后填入
  "stage": "transcribing",        // fetching_info|downloading|splitting|transcribing|summarizing|done|error
  "done": 12,                      // 当前阶段已完成数（切片/转录阶段有效）
  "total": 71,                     // 当前阶段总数
  "status": "running",            // running|done|error
  "error": null                    // status=error 时为可读错误信息
}
```

并发约束：进程内维护「当前运行任务」标记，同时仅允许一个 `running` 任务；运行中收到新的 `POST /api/episodes` 返回 409。进程重启后内存任务状态丢失（可接受：产物已落盘，刷新节目库即可看到结果）。

## 9. 技术约束与依赖

- 前端：React + TypeScript + Vite + Tailwind CSS；播放器用 wavesurfer.js；摘要渲染用 react-markdown。
- 后端：FastAPI + uvicorn，加入 `pyproject.toml` 依赖。
- 前端构建产物 `web/dist`：本机自用可先不提交；开源分发时再提交进仓库，使他人无需安装 Node 即可运行。
- 启动方式：`uv run uvicorn server:app`（或 `uv run python server.py`）。`server.py` 默认绑定 `127.0.0.1`，并可在启动后自动打开浏览器，方便本机使用。远程访问需使用者自行加反向代理与鉴权（非 MVP 范围）。
- 现有抓取、下载、切片、转录、摘要逻辑不重写，仅做第 10 节所列的最小改造。

## 10. 对现有代码的改动

最小化改动，集中在两处：

1. **抽出共用编排 `pipeline.py`**：把「解析链接 → 抓元数据 → 下载 → 转录 →（可选）摘要」抽成一个函数，例如 `run_pipeline(url, summary, output_root, on_event)`，其中 `on_event(stage, done, total)` 用于上报进度。
   - `main.py`（CLI）改为调用 `run_pipeline`，进度回调里 `print`；
   - FastAPI 后台线程也调用 `run_pipeline`，进度回调里更新任务表。
   - 这样 CLI 与 GUI **共用一条流程**，不分叉。沿用现有「产物已存在则跳过」的幂等判断。

2. **`stt.transcribe_audio` 增加进度回调参数**：现有实现内部已分别打印「切片进度」和「转录进度」，将其改为可选回调 `on_progress(stage, done, total)`（`stage ∈ {splitting, transcribing}`），默认行为不变（无回调时仍可 `print` 或静默）。

其余文件（`scraper.py` / `downloader.py` / `summarizer.py` / `audio_utils.py` / `config.py`）不改。新增 `server.py`（FastAPI 应用，含任务表与后台线程）。

## 11. 错误处理原则

需要明确展示的错误：URL 解析失败、网络请求失败、未解析到音频链接、`MIMO_API_KEY` 未配置、选了摘要但 `LLM_API_KEY` 未配置、`ffmpeg`/`ffprobe` 不可用或执行失败、转录接口失败、摘要接口失败、输出目录不可写。

原则（沿用 codex 文档中的好实践）：

- 错误信息要能指导下一步操作。
- 不吞异常、不静默失败。
- 失败不自动删除半成品文件。
- 不用默认值伪装成功。

## 12. 实现规划

按依赖顺序分里程碑，每个里程碑可独立验证。M0 即可让「浏览已有节目」可用，价值早现；前端（M2）可与后端（M0/M1）并行。

**M0 — 只读后端骨架**
FastAPI 应用 + 托管静态目录占位；实现 `GET /api/health`、`GET /api/episodes`、`GET /api/episodes/{id}`、`.../transcript`、`.../summary`、`.../audio`（以 `FileResponse` 服务本地 `audio.m4a`，自带 Range）。
验证：用 curl/浏览器能列出、读取现有 `output/` 节目，并能播放、seek 本地音频。

**M1 — 处理任务**
抽 `pipeline.py:run_pipeline`；`main.py` 切到复用它；给 `stt.transcribe_audio` 加进度回调；实现进程内任务表 + 后台线程；`POST /api/episodes`、`GET /api/tasks/{id}`；单任务互斥（409）。
验证：POST 一个链接，轮询能看到阶段与 `done/total` 推进，完成后 `output/` 出现产物。

**M2 — 前端三页面**
Vite + React + Tailwind 脚手架；节目库、新建处理（含进度视图）、节目详情；wavesurfer 播放器接 M0 的本地音频端点；react-markdown 渲染摘要；轮询进度；`health` 驱动按钮禁用与提示。
验证：走完第 6 节各页的验收标准。

**M3 — 集成与本机分发**
`npm run build` 产出 `web/dist`；FastAPI 托管 `dist`；`server.py` 默认绑 `127.0.0.1` 并在启动后自动开浏览器；更新 README（新增「Web 界面」启动说明）。
（开源收尾，可选）将 `web/dist` 提交进仓，使他人 `clone` 后免装 Node 即可 `uv run` 启动。
验证：本机 `uv run` 一条命令启动 → 浏览器走通全流程。

## 13. 仓库结构

```
podcast-analysis/
├── main.py              # CLI 入口（改为复用 pipeline）
├── pipeline.py          # 新增：run_pipeline 共用编排
├── server.py            # 新增：FastAPI（API + 静态托管 + 任务表 + 后台线程）
├── scraper.py           # 现有，不改
├── downloader.py        # 现有，不改
├── stt.py               # 微改：transcribe_audio 增加进度回调
├── summarizer.py        # 现有，不改
├── audio_utils.py       # 现有，不改
├── config.py            # 现有，不改
├── web/                 # 新增：前端源码
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   └── dist/            # 构建产物（开源分发时提交进仓）
├── output/              # 产物目录（运行时生成）
├── pyproject.toml       # 加 fastapi、uvicorn 依赖
└── README.md            # 更新启动说明
```

## 14. 后续版本候选

MVP 之后再考虑：取消运行中任务、摘要事后补生成、逐字稿与播放器联动高亮、逐字稿搜索、节目删除/管理、发言人识别与时间轴、封面图抓取、多任务队列、用 Tauri 加载 localhost + FastAPI sidecar 套一层原生壳、把 Python 与 ffmpeg 一并打包给非开发环境用户。
