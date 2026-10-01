# 运维

生产服务均监听 localhost：ASR `18010`、管理 `18000`、只读 `8001`。Cloudflare Tunnel 仅转发只读端口。开发启动、CLI 和常驻服务使用同一组默认端口。`scripts/services.py` 生成独立 launchd plist，Python 服务统一使用各项目 `.venv/bin/python`，机器人使用解析后的 Node 路径；使用 `zsh -lc` 读取用户 shell 环境，日志在 `data/logs/`。机器人另外读取 `bot/data/lark.json`。不要将管理端、ASR 端或机器人配置文件置于公网。

检查健康：`curl http://127.0.0.1:18010/health`、`curl http://127.0.0.1:18000/api/health`、`curl http://127.0.0.1:8001/api/health`。公开列表为 `/podcasts`，根路径应为 404，写请求应为 405。修改前端后先 `cd web && npm run build`，再重启只读和管理服务以读取新资源。

迁移历史时先停旧播客服务，运行 `scripts.migrate_history` dry-run，核对订阅/单集/目录计数与缺失路径，再 `--apply`。脚本通过 SQLite backup 读取含 WAL 的旧库，复制 jobs 与 agy 产物到新 `data/`，验证目录仅存档重复项；原目录不删除。旧订阅未来处理默认改 Qwen，59 条历史单集仍保留 Whisper 后端记录，不自动重跑历史失败任务。迁移后的 `data/podcast.db.pre-merge.bak` 是旧 schema 快照。

任务队列由单个管理进程持有文件锁，避免多 worker 重复执行。停服务使用 `uv run --no-sync python -m scripts.services stop`，检查当前任务是否完成后再重启；任务失败可在本地管理页或飞书卡片重试。机器人推送的本地持久记录可防止重启后重复通知，首次启动将迁移来的历史终态标为已见。

## 分阶段文章分析

默认 `PODCAST_AGY_MODEL=gemini-3.1-pro-high`、`PODCAST_AGY_STYLE_EDIT=false`。提示词分别为 `prompts/analysis.md`（生成）、`prompts/audit.md`（Gemini 核稿）、`prompts/style.md`（可选 Opus 语言编辑）。不再传入 `--effort high`，因为 Opus 不支持该参数。模型调用仍受沙箱约束，不通过放开命令权限来处理失败。

检查点位于 `<result_dir>/.analysis/<run>/`。`generate/` 保存初稿，`audit/` 保存 Gemini 成稿和核稿记录，`style-*/` 保存可选润色版本与局部修改 JSON。同级阶段 JSON 保存产物哈希与 token 统计，不持久化 agy 原始响应或工具日志。`state.json` 指向当前轮次；只复用未完成轮次中哈希一致的已完成阶段。逐字稿、元数据、Gemini 模型或生成/核稿提示词变化会开始新轮次。Opus 提示词变化仅重做润色。

断线、额度不足、命令权限拒绝、缺文件或机械检查失败均停止本轮，不无限重连。点击“仅重新分析”可从失败阶段重试；它不同于重新转写。若 Opus 失败，可在管理服务环境中设 `PODCAST_AGY_STYLE_EDIT=false`，重启空闲的管理服务，再仅重新分析，直接发布缓存的 Gemini 成稿。普通重试不会自动清理检查点；确认不再需要历史版本后再统一整理。

发布前会将旧文件保存在该轮的 `before-publication/`，生成或核稿失败不会用半成品覆盖旧文章。文件发布逐个原子替换；异常断电并非跨文件事务，可从检查点重试完成发布或从备份恢复。可选润色不是事实核验，程序的数字与限定词检查也不能保证语义等价；长节目、健康建议及复杂多人归属仍可能需要人工复核。

### 2026-09-28 接入验证

后端 126 项测试通过，其中分析器 25 项覆盖阶段恢复、检查点损坏、输入保护、无效时间戳、Opus 局部修改限制和权限拒绝。用费曼单集的输入副本在 `out/writing-tests/20260928-integrated-gemini/` 实测：生成完成后，首次核稿因 agy 命令权限拒绝而失败；随后仅重试核稿成功，生成检查点的 SHA-256 与修改时间未变。全程只调用 Gemini，Opus 路径只做模拟测试，未消耗真实额度。核稿改善了部分不确定性表达，但模型的审查报告不等于所有内容都已验证。

确认队列空闲后重启管理服务，ASR、管理、公开只读三个健康接口均返回 200，四个 launchd 服务运行中。未重跑历史任务，EP88 五份线上产物与原 SHA-256 清单一致。新流程应用于后续任务及用户主动发起的重新分析。

## 2026-09-26 迁移验收

旧 `whisper/data/jobs` 与 `whisper/out/agy` 的 250 个原文件和目标副本逐一 SHA-256 一致，迁移后的 SQLite `integrity_check` 为 `ok`。本机 ASR、管理、只读三个健康接口均返回 200，MiMo 能力为可用，真实 8 秒音频转录成功。公网 `https://podcast.fullai.top/` 返回 404，`/podcasts` 返回 200；浏览器确认历史订阅文章默认打开文章标签、详情无返回列表入口，390px 手机宽度没有横向溢出。飞书 `/help` 卡片真实发送成功。正式任务 `453a70...` 的 Qwen 转录经 agy 重新分析后生成 article/notes/mindmap/transcript，机器人对完成版本的私聊通知已发送并持久确认。用户端按钮回调仍待人工点按验证。上述检查仅证明部署与页面路径工作，不代替逐篇文章的内容校对。

## 2026-09-28 环境整理

ASR 主 `.venv` 已按锁文件补齐 local/dev 依赖，launchd 改用该环境；旧 `.venv-asr` 保留作回退。手动启动、两个 CLI、服务互调、机器人默认 API、Vite 开发代理及环境示例统一使用 ASR 18010 / 管理 18000 / 只读 8001。Vite 可通过 `PODCAST_API_URL` 覆盖开发代理目标，生产构建仍使用同源 `/api`。

启动脚本先解析全部目标运行环境，再停现有服务，避免运行文件缺失时先中断服务；Python 服务不再要求 Node 存在。`restart` 仍需在队列空闲时手动执行，并在重启后检查健康接口；脚本不等于部署事务或自动回滚器。

整理前快照保存在 `out/maintenance-20260928/before/`，分别包含两仓库的 Git 状态、工作树 patch 和未提交文件副本。项目目录、模型、数据库、历史产物及原环境均未删除或搬迁。改动分组见 [change-inventory.md](change-inventory.md)。


## 2026-10-01 目录搬迁

当前项目为 `/Users/domenxxt/Documents/PodcastWorkspace/PodcastAnalysis`，ASR 为相邻 `../whisper`。两者保持独立 Git 仓库，通过 HTTP 通信；父目录不建仓库。默认关闭说话人分离，现有 10 个订阅均为 Qwen / `skip_diarization=true`。

停服状态下先核对 `/Users/domenxxt/Documents/PodcastMigrationBackup/` 原备份，并在其 `repair-20261001/` 下使用 SQLite backup API 生成一致性快照，备份活跃任务、历史产物、bot/data 和四份 plist。数据库事务仅更新 36 个 `subscription_episodes.result_dir`，原子写入仅更新 20 个任务 JSON 的 `result_dir`。191 条单集、10 个订阅及 43 个持久任务的数量、状态、ID、updated_at 均保留；通知账本未修改。活跃路径字段无旧项目路径残留，历史错误文本和源备份不改写。

主 `.venv` 按原 Python 3.12.14 和 `uv sync --frozen --dev` 重建；原环境保存在上述备份的 `environments/`。Node 24.16.0、锁文件依赖和软链接检查正常，无需 npm 重装。后端 130 项、前端 9 项、机器人 6 项测试通过，前端构建成功；测试使用临时数据与模拟通知。

使用新位置 `scripts/services.py start asr`、`start manager public`，依赖健康且通知账本校验通过后 `start bot`。四份 plist 的启动目录、Python 入口和日志路径均已更新；服务单进程且未启用 reload。三个健康接口正常，只读服务保持只读，共享 Cloudflare Tunnel 未重启。

迁移核查发现既有缺失：19 个旧任务缺少共 49 个 article/notes/mindmap 文件，另 2 个旧订阅结果无 article.md；原备份也同样缺失。已有逐字稿和文章文件保留且哈希不变，不补跑历史任务。完整验收清单、异常明细及回退步骤见 `/Users/domenxxt/Documents/PodcastMigrationBackup/repair-20261001/report.md`。

浏览器验收：管理页、本地公开列表和旧订阅文章均正常；公网 `/podcasts`、EP88 文章及四类文件读取通过。本地只读写请求返回405，公网链路返回403，根路径均404。未发送测试通知。

恢复服务后的正常订阅轮询会更新数据库的检查时间、源站元数据和单集updated_at，并可能推进sqlite_sequence；这些运行时变化另记于上述备份的runtime-diff.json。停服路径修复本身仅改result_dir，任务JSON时间戳与通知账本保持不变。


## 2026-10-01 Obsidian 入库

已配置 `data/obsidian-export.json` 指向 `/Users/domenxxt/Obsidian/forge/forge`。任务完成后写入 `_raw/podcast/播客名/YYMMDD-HHmm-单集中文标题/`，四文件为文章、笔记、思维导图、逐字稿（均 .md）。按用户最新要求，以播客名称分组，不再按月份分层；前缀取上海时区节目发布时间，无发布时间时使用任务创建时间，再回退入库时间。原始发布日期保存在 frontmatter。

首批导入34条完整内容、136个文件，随后已按用户要求改为10个播客分组；21条旧内容缺少部分产物，未生成占位或重跑。导入清单和哈希在 `out/obsidian-export-20261001/manifest.json`，缺失清单在知识库 `.meta/podcast-import-2026-10-01.md`。

`server/obsidian_export.py` 通过来源URL或job id去重，保护已有_raw及用户批注；重新分析不会覆盖已入库稿件。同名不同来源加短标识。四文件先写临时目录再整体发布，失败不改变job状态和updated_at，错误记录在管理服务日志；下次启动管理服务会补试未入库的已完成任务。`enabled: false`或移走配置可停用，不删除已导入文件。无需新增定时服务或依赖。

后端143项测试通过，覆盖完整导出、同源去重、同名冲突、缺失/空文件/符号链接、写入失败恢复、任务成功路径与重启补试。测试全部使用临时知识库和模拟分析，未创建生产任务。队列空闲时仅重启manager，三健康接口200、四服务运行；已有136个导出文件、job JSON及bot通知账本哈希均未变。未提交或推送。

目录调整后相关40项测试通过，包括时区跨日、发布时间缺失回退及自动入库。34个目录重排映射在 `out/obsidian-export-20261001/podcast-group-renames.json`，136个文件内容哈希未变。空闲时重启manager后未重复导入，任务JSON、通知账本哈希不变，三个健康接口200。
