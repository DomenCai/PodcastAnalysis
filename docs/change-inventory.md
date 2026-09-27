# 两项目未提交改动清单

本清单整理当前工作树的职责和验证状态，不代表 Git 提交已经完成。现有改动保留，未暂存、未提交、未推送。两项目目录继续位于 `Documents/Personal/whisper` 与 `Documents/Personal/PodcastAnalysis`。

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
