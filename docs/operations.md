# 运维

生产服务均监听 localhost：ASR `18010`、管理 `18000`、只读 `8001`。Cloudflare Tunnel 仅转发只读端口。开发启动、CLI 和常驻服务使用同一组默认端口。`scripts/services.py` 生成独立 launchd plist，Python 服务统一使用各项目 `.venv/bin/python`，机器人使用解析后的 Node 路径；使用 `zsh -lc` 读取用户 shell 环境，日志在 `data/logs/`。机器人另外读取 `bot/data/lark.json`。不要将管理端、ASR 端或机器人配置文件置于公网。

检查健康：`curl http://127.0.0.1:18010/health`、`curl http://127.0.0.1:18000/api/health`、`curl http://127.0.0.1:8001/api/health`。公开列表为 `/podcasts`，根路径应为 404，写请求应为 405。修改前端后先 `cd web && npm run build`，再重启只读和管理服务以读取新资源。

迁移历史时先停旧播客服务，运行 `scripts.migrate_history` dry-run，核对订阅/单集/目录计数与缺失路径，再 `--apply`。脚本通过 SQLite backup 读取含 WAL 的旧库，复制 jobs 与 agy 产物到新 `data/`，验证目录仅存档重复项；原目录不删除。旧订阅未来处理默认改 Qwen，59 条历史单集仍保留 Whisper 后端记录，不自动重跑历史失败任务。迁移后的 `data/podcast.db.pre-merge.bak` 是旧 schema 快照。

任务队列由单个管理进程持有文件锁，避免多 worker 重复执行。停服务使用 `uv run --no-sync python -m scripts.services stop`，检查当前任务是否完成后再重启；任务失败可在本地管理页或飞书卡片重试。机器人推送的本地持久记录可防止重启后重复通知，首次启动将迁移来的历史终态标为已见。

## 文章分析配置（2026-10-08）

| 配置 | 默认值 | 用途 |
|---|---|---|
| `PODCAST_ANALYSIS_BACKEND` | `pi` | 选择 `pi` 或 `agy`，服务级配置 |
| `PODCAST_ANALYSIS_TIMEOUT_SECONDS` | `1200` | 每次 CLI 调用上限，大于 0 且不超过 86400 秒；agy 另有 15 秒退出宽限 |
| `PODCAST_ANALYSIS_ATTEMPTS` | `2` | 包括首次在内的总尝试次数，1～5 |
| `PODCAST_AGY_MODEL` | `gemini-3.1-pro-high` | 仅 agy 使用的 Gemini 模型 |

pi 固定指定 `kimi/k3` 和 `--thinking high`，继承当前用户 `~/.pi/agent` 中的配置；使用 `--no-session`、关闭扩展/其他 skill/上下文文件发现，仅显式加载本项目 skill 和文件工具。已用本机 pi 0.84.4 验证事件格式。agy 保留沙箱和文件工具权限约束；无头模式仍需要在用户设置中允许任务目录的文件读写，不能通过放开命令权限解决失败。

项目不自动加载 `.env`。手动运行可用 `PODCAST_ANALYSIS_BACKEND=agy uv run --no-sync python -m server.app`。launchd 通过 `zsh -lc` 启动，需在 `~/.zshenv` 导出配置后，确认队列空闲，再执行 `.venv/bin/python -m scripts.services restart manager`。随后检查 `/api/health` 的 `analysis` 对象，默认应为 pi / kimi/k3 / high。不要同时启动第二个管理 worker。旧 `WHISPER_AGY_TIMEOUT_SECONDS`、`WHISPER_AGY_ATTEMPTS`、`PODCAST_AGY_STYLE_EDIT` 已退役。

两种后端统一使用 `skills/podcast-to-article/` 中原样保存的上游 skill，版本和许可见 UPSTREAM.md / LICENSE；生成规则由 `prompts/analysis.md` 补充无人值守、来源、文章覆盖、笔记和导图约定。项目提示词覆盖上游文章 2,500–3,000 汉字、5–8 节及按比例删字的要求，以主要议题、关键论据、代表性案例和限制条件的保留为先，篇幅随有效信息量决定。笔记定位为快速复习，提炼 5–7 条核心观点，以 800–1,200 汉字为目标，避免重复展开文章论述。一次模型调用完成三份产物并回查原文；程序随后运行文风报告与机械校验，不再额外调用 Gemini 核稿或 Opus。

网络 EOF、TLS/连接错误、限流及暂时的上游故障可在等待 10 秒后重试，不再限制必须在 120 秒内失败。权限拒绝、明确账号拒绝、额度不足、未知进程错误、输入/产物损坏直接停止。没有明确网络证据的超时不自动重试；超时伴随已分类的瞬时故障可以重试。pi 自带的有限 agent 重试发生在一次 CLI 内，受外层时限限制；诊断的 internal_retries 单独记录，避免把它与外层 attempt 混淆。

每次外层尝试重新复制不可变输入和 skill，工作目录互相独立。诊断原子保存到 `<result_dir>/.analysis/<run>/diagnostics/<uuid>.json`：含后端、模型、thinking、stage、attempt、时间、耗时、退出码、超时标记、终态、错误类别、是否可重试、token 统计及校验结果。调用前先写 running，正常结束/错误/超时后更新；意外断电留下 running，表示该次未正常收尾。只保存白名单字段，不持久化原始响应、工具文本或凭据。

`generate/` 及 generate.json 保存已验证产物与哈希；发布前旧文件在 `before-publication/`。发布失败可在“仅重新分析”时复用同轮检查点，生成未通过检查则重新调用。模型、skill 内容、提示词或输入变化开启新轮次；成功任务再分析也开启新轮次。旧 Gemini 多阶段轮次原样保留，v2 指纹不混用，恢复旧失败任务会按当前所选后端重新生成，但无需重转录。

发布为逐文件原子替换，不是跨文件事务。意外中断后可从检查点续发。文风报告只作提示，机械校验与模型自检不代表外部事实核查或全部语义正确。

### 2026-10-08 接入验收

后端 202 项测试、前端 9 项测试与构建通过。pi / kimi/k3 / high 用 #752 的完整逐字稿副本生成三份产物，706.51 秒完成；agy 用合成短素材完成相同文件流程，59.55 秒。生成结果、检查点、文风报告和调用诊断分别在 `out/writing-tests/20261008-k3-skill-8six8fan/` 与 `out/writing-tests/20261008-agy-smoke-s43vd10p/`。K3 样稿 7 处直接引语中，6 处去除空白后可逐字找到，另 1 处将句号改成逗号，原意未变；这不代表全面人工核稿。上游脚本不识别「」引号，直接引语比例的零值不能当作实际没有引语。

该次长文验证在开发中 token 聚合修正前已启动，其 usage 只包含最后一条助手消息；当前实现汇总该次调用全部已完成助手消息的用量，已有多轮事件测试覆盖。不要用该早期测试记录的 usage 推断整次调用成本。

队列空闲时重启管理/只读服务，管理健康接口确认 pi / kimi/k3 / high；ASR、管理、只读健康均返回 200，四服务运行。浏览器确认管理文案及既有文章/导图阅读正常，390px 无横向溢出。53 个持久任务 JSON、机器人通知账本及 #752 原文章/笔记/导图哈希均未变，未重跑生产历史任务或发送通知。验收清单与改动前快照在 `out/maintenance-20261008-before-pi/`。

## 历史运行记录

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
