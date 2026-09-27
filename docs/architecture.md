# 架构与边界

`whisper/asr.app` 只处理音频转录，支持 Qwen、Whisper、MiMo；PodcastAnalysis `server.app` 拥有订阅、下载、任务队列和 agy 分析。两者经 localhost HTTP 通信，不共享 Python 源码或运行时包。Qwen/MiMo 的原始转录直接进入 agy，Whisper 还保留原有的可选文字清洗和说话人分离。

PodcastAnalysis 的 `data/podcast.db` 保存订阅与发现的单集，`data/jobs/<id>` 保存手动或订阅任务及处理状态。历史结果复制到 `data/legacy-agy/`，数据库绝对路径在迁移时重写。原始音频和模型文件留在 whisper；可恢复的任务音频由各自服务管理。

`server.agy_analyzer` 明确指定 Gemini 完成生成与核稿两个阶段；可选 Opus 只提出文章的局部语言修改，默认关闭。每阶段使用单独工作副本，只在 agy JSON 状态、输入完整性与产物检查通过后保存检查点。核稿与最终发布检查真实段首时间、原节目链接、口述整理说明及笔记/导图标题层级。`.analysis/` 保存输入指纹、阶段产物哈希、模型 token 统计和旧版备份，不在公开文件白名单中。主任务仍显示 `analyzing`，不增加新的队列状态。

内容正确性主要由 Gemini 对照逐字稿核对；机械检查只能发现格式、时间引用及部分局部修改问题。Opus 替换必须唯一定位、互不重叠，并保留数字、链接、引语和部分限定词；这些检查不能证明语义完全不变。

`server.public_app` 只注册 GET 并读取数据库、已完成任务的安全元数据与四类 Markdown/文本文件。公网根路径没有入口，`/podcasts` 是固定列表；手动任务详情是 `/jobs/<id>`，订阅历史详情是 `/episodes/<id>/transcript`。私有写 API 只在 `server.app`。React 复用阅读组件，公开详情无导航控件。

`bot/` 仅处理 owner 私聊。消息通过长连接进入，按钮回调立即返回，后续 HTTP 操作异步执行；任务终态轮询发送带稳定 UUID 的私聊卡片，成功确认记在 `bot/data/ledger.json`。它不承担聊天 Agent 能力，也不直接访问播客数据库。
