# 两项目改动清单

当前项目位于 `Documents/PodcastWorkspace/PodcastAnalysis`，独立 ASR 项目为相邻 `whisper`。本清单记录改动与验证情况，提交状态以 Git 记录为准。

## 2026-10-19：Codex 自动备用与一小时冷却

- 默认 pi 一次 CLI 调用失败后立即切换 Codex `gpt-6.1-sol` / `high`，不依赖额度识别；输入保护、产物校验和本地文件错误仍直接报错。
- 新增 `server/analysis_fallback.py`，冷却状态原子保存到数据目录，跨任务、跨管理服务重启有效。固定冷却 3600 秒，到期后下次任务尝试 pi；Codex 失败不续期、不循环切换。
- Codex 使用 exec JSONL 与独立临时工作副本，保留现有 provider/认证，禁用本次外部工具与 hooks；复用写作 skill、输入检查和三份产物发布。沿用空闲监测，无 120 秒总时限。
- 健康接口暴露备用配置和冷却状态；诊断记录实际模型、路由、切换和冷却截止时间。README、运维说明及前端健康类型同步。
- 真实合成短素材生成三份产物用时 122.71 秒，校验通过；样稿、检查点与诊断在 `out/writing-tests/20261019-122934-codex-smoke/`。工具错误计数为 1，最终 CLI 成功并通过输入/产物检查；这不是长播客质量验收。
- 验证：后端 270 项、前端 9 项测试通过，前端构建通过；覆盖任意调用失败切换、干净副本、跨任务/重启冷却、到期恢复、备用失败不续期、输入保护及 Codex 流式终态。已有子进程测试的 0.7 秒启动余量偶发不足，调至 2 秒并延长活动序列，仍验证活动持续超过空闲阈值。
- 原未提交改动已保留，修改前 patch 与原测试副本在 `out/maintenance-20261019-122554-before-codex/`。本轮未重启生产服务、未重跑历史任务、未触发通知。

## 2026-10-09：空闲监测与 pi 收尾提醒

- 取消 CLI 总时长限制，改为可关闭的连续无活动时限，默认 20 分钟。
- pi 改用 RPC，每 15 分钟排队收尾提醒；模型增量与工具活动续期，日志、回执和重试通知不续期，未消费提醒不堆积。
- agy 通过流式步骤监测空闲，暂不提供运行中催稿。
- 结构化诊断增加最后活动、空闲时长、提醒发送/接受/送达和超时原因，运行中每 30 秒更新。
- 验证：后端 221 项测试通过；pi 合成素材完成三份产物且 4 条提醒均送达，agy 流式短响应通过。空闲时重启管理服务，健康检查通过，历史任务和通知账本未变。

## 2026-10-08：可选分析后端与 skill 生成

- `server/analyzer.py`、`server/analysis_runner.py` 替代 agy 专用模块；默认 pi / kimi/k3 / high，agy 可选。
- `skills/podcast-to-article/` 原样保存固定版本 skill、参考文件、脚本和 MIT 许可。`prompts/analysis.md` 补充三份产物约定；移除旧独立核稿/Opus 提示词。
- 文章覆盖主要议题、关键论据、案例和限制条件，取消上游固定字数与章节数量限制；笔记收紧为 5–7 条核心观点，以 800–1,200 汉字为目标，避免重复展开文章论述。
- 每次调用默认 1200 秒；已分类瞬时错误有有限重试，每次从干净副本开始；所有调用保存私有结构化诊断。
- 健康接口和管理页面显示所选分析后端；CLI 文案、环境示例、README、架构与运维说明同步。
- 旧输入、产物和分析轮次保留；改动前未提交文件副本与 patch 在 `out/maintenance-20261008-before-pi/`。
- 验证：后端 202 项、前端 9 项和构建通过。pi 在 #752 输入副本上生成三份产物，706.51 秒完成；agy 合成短素材调用 59.55 秒完成，记录在 `out/writing-tests/20261008-*/`。
- 上述真实模型样稿生成于文章篇幅和笔记精简规则调整之前；新写作规则尚未重新生成样稿验证。

## 2026-09-28：历史拆分与环境整理

以下为当时的改动分组与验收记录，旧模块名、模型流程、数据数量与路径仅描述该历史版本。

## Whisper：独立转录服务

| 改动组 | 主要文件/目录 | 结果 |
|---|---|---|
| ASR 服务与任务恢复 | `asr/app.py`、`asr/jobs.py`、`asr/cli.py`、`asr/qwen.py` | 音频 HTTP API、窗口流式接口、单模型队列、Qwen 批次检查点 |
| 转录适配器 | `server/local_transcriber.py`、`server/mimo_transcriber.py`、`server/audio_utils.py` | Qwen/Whisper/MiMo 后端，懒加载和音频转换 |
| 说话人分离 | `server/diarization.py`、`workers/diarization/worker.py`、相关测试 | 独立 worker、说话区间、单说话人快速路径 |
| 项目拆分 | 原 `server/app.py`、播客 jobs/subscriptions/public/note 文件，旧 analysis/fetch/scripts/web 删除 | 播客职责转移到 PodcastAnalysis；不恢复这些旧入口 |
| 环境与说明 | `pyproject.toml`、`uv.lock`、`.env.example`、README、AGENTS、`docs/operations.md` | `.venv` + local extra；默认端口 18010，密钥通过私有环境传入 |

本轮仅进一步统一端口、补齐正式 `.venv` 依赖和运行文档，没有改写 ASR 推理算法。旧 `.venv-asr`、模型缓存、音频和迁移前数据均保留。

## PodcastAnalysis：播客编排与阅读

| 改动组 | 主要文件/目录 | 结果 |
|---|---|---|
| 任务与订阅 | `server/jobs.py`、`subscriptions.py`、`job_options.py`、`podcast_feed.py`、`transcription_client.py` | 默认 Qwen，通过 HTTP 调用 ASR；持久任务、订阅、重试与恢复 |
| 分阶段文章生成 | `server/agy_analyzer.py`、`prompts/`、`tests/test_agy_analyzer.py` | Gemini 生成/核稿，Opus 可选局部润色且默认关闭；检查点及旧版本备份 |
| 管理/公开边界 | `server/app.py`、`public_app.py`、`public_catalog.py`、`public_store.py`、`web_ui.py` | 管理写 API 与只读阅读分开；公开文件白名单 |
| 阅读前端 | `web/src/`、Vite、npm 锁文件 | 文章/笔记/导图/逐字稿阅读；管理端与公开端共用渲染组件 |
| 飞书机器人 | `bot/` | owner 私聊、交互卡片、API 编排、持久通知去重 |
| 命令行、服务及迁移 | `analysis`、`fetch.py`、`scripts/` | 命令行提交到管理 API；四个 launchd 服务；历史数据复制迁移 |
| 旧实现移除 | 原 CLI、本地转录/摘要模块、旧页面、Docker 配置 | 不保留已被新边界替代的运行链路 |
| 环境与说明 | README、AGENTS、`.env.example`、`docs/`、`tests/test_services.py` | 默认端口 18000/8001；启动前检查目标解释器；部署/恢复说明 |

这些分组可作为后续逐组检查或提交的边界。本轮没有替用户执行 Git 分组暂存，也没有将原先的大量改动误算成本轮新功能。

## 本轮环境统一

- ASR 手动入口、CLI 和客户端默认 18010；管理手动入口、CLI、机器人和 Vite 开发代理默认 18000；公开阅读仍为 8001。
- Python 服务统一使用各项目 `.venv`；说话人分离继续隔离在其子项目 `.venv`，不强行合并 Torch 与 MLX 环境。
- ASR `.env.example` 的 MiMo 密钥改为注释示例，避免空值掩盖 shell 已导出的密钥。
- 服务重启前先检查所有目标解释器，Python 服务不再依赖 Node 路径解析。仍保留用户 shell 环境的加载方式。
- 项目级 AGENTS 只记录稳定边界、运行入口与检查命令，详细操作放在 README/运维文档。

## 验证

| 检查 | 结果 |
|---|---|
| Whisper 主环境测试 | 30 通过 |
| 独立分离 worker 测试 | 11 通过；有 TorchCodec 动态库警告 |
| PodcastAnalysis 后端测试 | 130 通过（包含 4 项新增部署脚本测试） |
| React 测试 | 9 通过 |
| 飞书机器人测试 | 6 通过；本轮未发送测试消息 |
| 前端构建 | 通过 |
| 两项目 uv lock 检查 / 安装 dry-run | 通过；无需再变更包 |
| 新主环境真实 ASR | 8 秒音频 Qwen 成功，1 个片段，46 字符；CLI 使用默认端口 |
| 服务健康 | ASR / 管理 / 只读均为 HTTP 200，四个 launchd 服务已重启 |
| 浏览器 | 管理页、公开文章/笔记读取正常；390px 无横向溢出；Vite 默认代理 /api/health 返回 200 |
| 数据库 | SQLite integrity_check=ok；21 条结果路径全部存在 |
| 既有文章 | EP88 五份文件哈希与原清单一致 |

测试记录和快照位于 `out/maintenance-20260928/`；ASR 短音频及结果位于 Whisper 的同名 `out/maintenance-20260928/`。

## 保留与限制

- 不搬目录：数据库有 21 条绝对结果路径，任务元数据有 20 条绝对结果路径，启动脚本也默认按相邻项目定位。搬迁需要单独重写并验证这些引用，目前没有对应收益。
- 不删除历史源副本：原数据库、`whisper/data/jobs`、`whisper/out/agy` 与迁移快照继续保留。模型文件和已有未提交源码没有清理删除。
- TorchCodec 警告属于既有依赖问题。worker 已用 ffmpeg 预解码 waveform；本轮没有真实加载分离模型，不声称端到端分离已验证。
- Gemini 核稿仍可能漏掉语义错误；Opus 默认关闭，机械检查不等于所有事实正确。环境整理不改变此前确定的模型职责。
- 常驻服务切换到新配置前确认队列空闲；未重新处理历史任务，也未触发文章生成。
