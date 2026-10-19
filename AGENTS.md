# PodcastAnalysis 项目约定

- 本项目负责播客下载、订阅、任务编排、文章生成与阅读。音频推理调用独立 Whisper ASR HTTP 服务，不导入其源码。
- Python 使用本项目 `.venv` 和 `uv sync --frozen --dev`；前端、机器人分别使用 `web/`、`bot/` 的 npm 锁文件。
- 默认 ASR `127.0.0.1:18010`、管理 `127.0.0.1:18000`、公开只读 `127.0.0.1:8001`。公网隧道只指向只读服务。管理和 ASR 不对公网开放。
- CLI 只提交到管理 API。管理服务只有一个任务 worker；重启前检查队列。服务入口为 `scripts/services.py`。
- 分析后端可选 pi/codex/agy，默认 pi 的 kimi/k3、thinking high；pi 调用失败自动切 Codex gpt-6.1-sol/high，并持久冷却 1 小时。直接使用项目内固定版本 podcast-to-article skill 生成三份产物并自检。真实模型测试优先放 `out/writing-tests/`，不自动重跑历史文章或触发飞书通知。
- 后端检查 `uv run --no-sync pytest -q`；前端检查 `cd web && npm test && npm run build`；机器人检查 `cd bot && npm test`。
- 保留用户已有未提交改动、`data/`、`out/`、分析检查点和历史备份。数据库及任务包含绝对路径，不擅自搬项目。凭据留在 shell、CLI 用户配置或 `bot/data/`，不打印、不入库。
- 项目事实以 README、docs/architecture.md、docs/operations.md 为准；当前拆分改动范围见 docs/change-inventory.md。
