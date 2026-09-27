# 项目拆分验证（2026-09-26）

## 自动化验证

- whisper：37 项测试通过，覆盖原 ASR 适配器、队列恢复、取消/重试、Qwen checkpoint 与 token 截断拒绝、WebSocket partial/final。
- 独立 diarization worker：11 项测试通过。沿用的 worker 环境存在 TorchCodec 动态库加载告警，本轮没有实跑说话人分离；默认 Qwen 不依赖该环境。
- PodcastAnalysis：107 项测试通过，覆盖原订阅/管理/公开只读/agy 文件发布及新增 HTTP 边界、断线恢复和远端任务重用。
- React：7 项测试通过，TypeScript 和 Vite production build 通过。
- 两个项目 uv lock --check、git diff --check 通过。

## 真实推理与浏览器

- 使用本地《AI早知道-26-08-30》440.6775 秒音频，Qwen 写出 15 个切片，覆盖到音频末尾；原音频不变，ASR 上传副本在成功后清理。
- 首次模型加载期间出现一次 HTTP ReadError，转录实际继续完成。状态读取增加有限重试，任务 ID 持久化；恢复播客任务后直接取回原转录，没有重复模型推理。
- WebSocket 输入真实 8 秒 PCM，返回 final 的 start=0、end=8 和实际文本，随后 done。
- ego-browser 检查默认 Qwen、禁用其说话人选项、任务失败时仍可阅读逐字稿，以及“仅重新分析”入口。
- 另将已有《陶哲轩》历史产物登记到隔离验证库，验证文章、笔记和导图页面。它是历史结果，不是本轮 agy 新生成的文章。

## agy 实测（重试已通过）

首次调用因当前账号 `not eligible for Antigravity` 失败。2026-09-26 用户要求重试后，使用同一任务的已保存逐字稿，仅执行 agy 分析，任务成功完成。

已生成 article.md（4145 字符）、notes.md（1579 字符）、mindmap.md（1547 字符），三个文件均非空，原始逐字稿保留，未重新转录。已确认文章包含二级章节；本轮未进行独立人工事实校对。账号资格错误的脱敏提示保留，用于后续失败诊断。

## 保留的验证环境

- 播客管理：http://127.0.0.1:18000
- 转录 API：http://127.0.0.1:18010/docs
- 新样本任务：95683bd678554bc38ae6481d1f5e316a
- 历史阅读验证任务：18c89d24e8fb5cf086c369541fcf3436
- 播客验证数据：PodcastAnalysis/out/split-smoke/data
- ASR 验证数据：whisper/out/split-smoke/asr

旧 whisper 播客进程已正常停止。原历史数据、模型、音频和 benchmark 保留原处，未在验证环境自动启动历史订阅。正式接回历史数据的方法见 README；本轮未提交或推送 Git。
