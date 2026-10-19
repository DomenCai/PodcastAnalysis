# PodcastAnalysis — 播客转文章

本项目负责小宇宙订阅、下载、持久任务、pi/Codex/agy 文章生成和 React 阅读；相邻 `whisper` 项目只提供 HTTP 转录 API。默认 Qwen，MiMo 可选。Whisper 和说话人分离保留在本地管理页。

## 安装与本地运行

需要 Python 3.12～3.13、uv、Node 22+、ffmpeg，以及已安装并配置 `kimi/k3` 的 `pi`，以及可调用 `gpt-6.1-sol` 的 Codex CLI（切换 agy 时需安装并登录 agy）。先按 `../whisper/README.md` 启动 ASR，再执行：

```bash
uv sync --frozen --dev
cd web && npm ci && npm run build && cd ..
uv run --no-sync python -m server.app
# http://127.0.0.1:18000 本地管理页
```

只读阅读服务单独启动，公网隧道只能指向它：

```bash
uv run --no-sync python -m server.public_app
# http://127.0.0.1:8001/podcasts
```

公网根路径 `/` 返回 404。固定入口 `/podcasts` 按播客分组列出已完成内容，点击直接阅读文章、笔记、导图与逐字稿。手动任务和订阅任务都可公开阅读；详情页没有返回列表的导航。管理/上传/ASR API 仅在 localhost 开放。

`./analysis <小宇宙单集链接或本地音频>` 通过管理 API 提交任务，`--backend mimo` 选择 MiMo，`--analyze-only <JOB_ID>` 仅重新生成文章。管理端只有一个任务 worker，订阅每 30 分钟检查一次。失败任务可重试，逐字稿完成后可只重新分析；处理成功会清理临时上传音频。

分析后端由管理服务环境变量 `PODCAST_ANALYSIS_BACKEND=pi|codex|agy` 选择，默认 **pi / kimi/k3 / thinking high**；agy 使用 `PODCAST_AGY_MODEL=gemini-3.1-pro-high`。三种后端都直接使用固定版本的 [podcast-to-article skill](skills/podcast-to-article/UPSTREAM.md)，一次调用生成文章、笔记和思维导图并自检。文章按话题重组，保留主要议题、关键论据、代表性案例及限制条件，篇幅随有效信息量决定，覆盖上游固定字数和章节数量限制；笔记提炼 5–7 条核心观点，以 800–1,200 汉字为目标，避免重复展开文章论述；导图呈现关系，不只复刻文章目录。项目约定在 `prompts/analysis.md`，不再单独调用 Gemini 核稿或 Opus 润色。

分析没有总时长上限。`PODCAST_ANALYSIS_IDLE_TIMEOUT_SECONDS` 默认 1200 秒：连续没有模型输出、思考增量或工具活动才停止，设为 0 可关闭。pi 通过 RPC 接收 `PODCAST_ANALYSIS_REMINDER_SECONDS`（默认 900 秒，0 关闭）控制的收尾提醒，在当前工具轮次结束后送达；未消费的提醒最多排队一条。agy 和 Codex 使用流式事件监测空闲，目前不支持运行中催稿。日志、提醒回执和内部重试通知不会重置空闲计时。

**自动备用**：默认 `PODCAST_ANALYSIS_FALLBACK=codex`。pi 一次 CLI 调用失败就切换到 **Codex / gpt-6.1-sol / high**，不要求识别额度原因，也不再做 pi 外层重试。自失败时起冷却 1 小时，期间其他任务直接使用 Codex，到期后下一次任务重新尝试 pi。冷却状态保存在 `PODCAST_DATA_DIR/analysis-fallback.json`（默认 `data/`），管理服务重启仍有效；Codex 失败不会延长冷却或回切 pi。输入保护、产物校验和本地发布错误直接报错。设为 `none` 可关闭备用，或设 `PODCAST_ANALYSIS_BACKEND=codex` 直接使用 Codex。

`PODCAST_ANALYSIS_ATTEMPTS` 为每个后端的总尝试次数（1～5，默认 2），已分类的网络异常、限流和暂时上游故障不论发生多晚，都可在等待 10 秒后重试；纯空闲超时、权限、账号、额度、未知错误和产物检查失败不自动重试。每次重试重新创建工作副本。pi 内置有限重试仍受空闲监测约束，内部重试次数另行记录。旧 `PODCAST_ANALYSIS_TIMEOUT_SECONDS`、`WHISPER_AGY_*` 和 `PODCAST_AGY_STYLE_EDIT` 不再使用。

每次调用的结构化诊断保存在 `.analysis/<run>/diagnostics/`，包括后端、模型、空闲阈值、耗时、最后活动时间与类型、空闲时长、提醒发送/接受/送达次数、退出码、终态、错误类别和 token 用量；运行中每 30 秒更新安全诊断，超时也记录，不保存原始响应、逐字稿或凭据。检查通过后保存 `generate/`；发布失败时“仅重新分析”可复用它，已成功任务再次分析则开启新一轮。模型、skill 或提示词变化会启用新轮次，旧检查点和发布前的 `before-publication/` 备份保留；旧版 Gemini 多阶段检查点不混用。详见 [运维说明](docs/operations.md)。

配置需导出到管理进程环境；项目不会自动加载 `.env`。手动切换示例：

```bash
PODCAST_ANALYSIS_BACKEND=agy uv run --no-sync python -m server.app
# 默认使用 pi，无需设置 PODCAST_ANALYSIS_BACKEND
```

常驻服务需在 `~/.zshenv` 导出所选配置，并在队列空闲时通过 `scripts.services restart manager` 生效。`pi` 使用当前用户的 `~/.pi/agent` 模型与凭据配置；Codex 继承当前用户的 provider/认证配置（含现有自定义 provider），命令行不传递明文密钥。Codex 在仓库外的临时副本中使用 `workspace-write`，关闭本次调用的 MCP、插件、hooks、自动技能目录和网络搜索，仅读写任务文件；提示词仅适配文件工具，不改变写作要求。健康接口的 `analysis.fallback` 显示备用配置与冷却状态，`available` 仅表示 CLI 可执行文件存在。

## 飞书私聊机器人

机器人是 `bot/` 下的独立 Node 程序，使用 `@larksuite/channel` 长连接与 schema 2.0 卡片，只调用本地管理 API。首次运行：

```bash
cd bot
npm ci
npm run setup  # 扫码创建独立飞书应用并绑定 owner
npm start
```

凭据保存在 `bot/data/lark.json`，不会复用其他机器人。给机器人私聊发送 `/help`，再通过卡片选择“处理单集”或“订阅播客”；裸链接不会直接执行。订阅初始可选仅未来更新、最新 1 集、最新 3 集，默认最新 1 集。卡片还可查看任务、暂停/恢复订阅、立即检查更新、重试失败、只重新生成文章，并打开阅读页。处理完成或失败会私聊通知。非 owner 与群聊请求均被拒绝。

## 数据与常驻运行

历史播客数据已复制到本项目 `data/`：原 `whisper/data/jobs`、数据库、`whisper/out/agy` 均保留原位作源备份；验证目录保存于 `data/validation-backup/`。迁移脚本默认为 dry-run：

```bash
.venv/bin/python -m scripts.migrate_history
# 仅在目标 data 不存在、旧服务已停止时：
.venv/bin/python -m scripts.migrate_history --apply
```

macOS 常驻四服务（ASR、管理、只读、机器人）的 launchd 工具。两边 Python 都使用各自 `.venv`，首次使用前完成两项目安装、前端构建及机器人 `npm ci`：

```bash
.venv/bin/python -m scripts.services status
.venv/bin/python -m scripts.services start
.venv/bin/python -m scripts.services stop bot
```

启动命令由 `zsh -lc` 执行，继承用户 `.zshenv` 中的 `MIMO_API_KEY`；不自动加载 `.env.example`，也不会用空值覆盖已有密钥。手动运行、命令行、前端开发代理与常驻服务统一默认端口：ASR `18010`、管理 `18000`、只读 `8001`，只读服务对应 `podcast.fullai.top`。若手动运行时使用不同端口，设置 `TRANSCRIPTION_API_URL`、`PODCAST_API_URL`、`PUBLIC_PORT` 等变量；完整配置见 `.env.example`。

## Obsidian 自动入库

在本项目 `data/obsidian-export.json` 配置知识库根目录即可启用（该文件不入 Git）：

```json
{"enabled": true, "vault": "/absolute/path/to/vault"}
```

任务完成后自动写入 `_raw/podcast/播客名/YYMMDD-HHmm-单集中文标题/`，例如 `纵横四海/260921-2014-EP88-史上最强播客-读书笔记/`。日期时间取节目发布时间，统一为上海时区；无发布时间时使用任务创建时间，两者均不可用时使用入库时间。无播客名称的本地音频归入“其他音频”。按名称排序即可看到先后。目录内固定为 `文章.md`、`笔记.md`、`思维导图.md`、`逐字稿.md`。保留节目来源、发布日期和原文件哈希；逐字稿只增加段落空行。

只有四类产物齐全才入库。同一任务或节目来源已入库时跳过，保留用户批注及既有 `_raw` 素材；重新分析不覆盖旧稿。同名的不同节目使用短标识区分。写入失败只记录日志，不改变任务结果和通知时间戳；管理服务下次启动会补试未入库的已完成任务。配置 `enabled: false` 或移走配置文件可停用。首次加入代码后需在队列空闲时重启管理服务。

## 验证

```bash
uv run --no-sync pytest -q
cd web && npm test && npm run build
cd ../bot && npm test
```

架构和运维细节见 [架构说明](docs/architecture.md)、[运维说明](docs/operations.md)；当前未提交改动按项目职责整理于 [改动清单](docs/change-inventory.md)。
