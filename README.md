# PodcastAnalysis — 播客转文章

本项目负责小宇宙订阅、下载、持久任务、agy 文章生成和 React 阅读；相邻 `whisper` 项目只提供 HTTP 转录 API。默认 Qwen，MiMo 可选。Whisper 和说话人分离保留在本地管理页。

## 安装与本地运行

需要 Python 3.12～3.13、uv、Node 22+、ffmpeg，以及已安装并登录的 `agy`。先按 `../whisper/README.md` 启动 ASR，再执行：

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

文章分析默认由 `gemini-3.1-pro-high` 分两阶段完成：先生成文章、笔记和导图，再对照完整逐字稿核稿。文章保留说话人的口吻，笔记按内容关系组织，时间戳仅辅助回听。核稿检查的是转述是否忠实，不是对节目观点做外部事实验证。

管理服务环境变量 `PODCAST_AGY_MODEL` 可选择其他 Gemini 模型。`PODCAST_AGY_STYLE_EDIT=true` 才启用可选 Opus 语言编辑（默认关闭）：只读文章和少量口吻样本，最多返回八处局部修改，不负责事实鉴定、重选内容或改写笔记。`WHISPER_AGY_TIMEOUT_SECONDS` 是每次模型调用的超时，不是整个分析任务的总时长。配置需导出到管理进程环境；项目不会自动加载 `.env`。

失败后使用“仅重新分析”会复用已完成阶段；已成功的任务再次分析则开启新一轮。检查点保存在结果目录的 `.analysis/`，发布前旧文件保存在该轮的 `before-publication/`。Opus 失败时保留 Gemini 成稿，可稍后重试润色，或关闭润色并重试以发布 Gemini 版本。详见 [运维说明](docs/operations.md)。

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
