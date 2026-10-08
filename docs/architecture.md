# 架构与边界

`whisper/asr.app` 只处理音频转录，支持 Qwen、Whisper、MiMo；PodcastAnalysis `server.app` 拥有订阅、下载、任务队列和 pi/agy 分析。两者经 localhost HTTP 通信，不共享 Python 源码或运行时包。Qwen/MiMo 的原始转录直接进入分析器，Whisper 还保留原有的可选文字清洗和说话人分离。

PodcastAnalysis 的 `data/podcast.db` 保存订阅与发现的单集，`data/jobs/<id>` 保存手动或订阅任务及处理状态。历史结果复制到 `data/legacy-agy/`，数据库绝对路径在迁移时重写。原始音频和模型文件留在 whisper；可恢复的任务音频由各自服务管理。

`server.analyzer` 管理输入快照、检查点、重试工作副本与发布；`server.analysis_runner` 负责 pi/agy 调用、终态解析与安全错误分类。默认 pi 的 kimi/k3（thinking high），可通过 `PODCAST_ANALYSIS_BACKEND=agy` 选择 Gemini。两条路径用同一个固定版本 skill 和项目提示词，一次生成文章、笔记与导图并自检，不再叠加独立的 Gemini 核稿/Opus 润色。

每次尝试使用全新的临时目录，复制逐字稿、元数据和 skill 及其参考文件。pi 只启用 read/write/edit/grep/find/ls，不加载其他扩展或项目指令；agy 保留 sandbox 和 accept-edits。目录与提示词限制不等于操作系统文件沙箱。程序在调用结束后校验输入未变、产物为非空普通文件、时间戳/来源/声明/标题层级正确；安全保存检查点后才逐文件原子发布。

`.analysis/` 保存含后端、模型、thinking、skill/输入哈希的轮次指纹、产物哈希、每次调用的结构化诊断和旧版备份，不在公开文件白名单中。超时也归档诊断；只保存枚举、数值与时间等字段，原始 CLI 响应和日志只留在临时文件。pi 需有 agent_settled、最终助手 stopReason=stop、正确的 kimi/k3 和退出码 0；agy 需 SUCCESS 且无工具拒绝。已分类的瞬时错误最多按配置重试，工作目录不继承残稿；发布失败可复用已验证的 generate 检查点。旧版多阶段轮次保留，指纹 v2 不复用它们。

内容忠实度由 skill 的原文回查与模型自检负责，机械检查不能证明语义完全正确。程序另外运行上游文风检查脚本生成私有 style-report.txt，仅作参考，不作为发布门槛。主任务仍显示 analyzing，不增加队列状态。管理健康接口返回所选 analysis 后端、模型、thinking 及 CLI 是否安装，不代表远端模型已通过健康验证。

`server.public_app` 只注册 GET 并读取数据库、已完成任务的安全元数据与四类 Markdown/文本文件。公网根路径没有入口，`/podcasts` 是固定列表；手动任务详情是 `/jobs/<id>`，订阅历史详情是 `/episodes/<id>/transcript`。私有写 API 只在 `server.app`。React 复用阅读组件，公开详情无导航控件。

`bot/` 仅处理 owner 私聊。消息通过长连接进入，按钮回调立即返回，后续 HTTP 操作异步执行；任务终态轮询发送带稳定 UUID 的私聊卡片，成功确认记在 `bot/data/ledger.json`。它不承担聊天 Agent 能力，也不直接访问播客数据库。
