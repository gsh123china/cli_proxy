# Repository Guidelines

## 项目结构与模块组织
- 代码位于 `src/`：`claude/`、`codex/`、`ui/`、`core/`、`config/`、`filter/`、`utils/`、`auth/`。
- **核心文件**：
  - `src/core/base_proxy.py`：BaseProxyService（代理核心逻辑）和 BaseServiceController（服务生命周期管理）
  - `src/core/realtime_hub.py`：RealTimeRequestHub（WebSocket 实时事件广播）
- CLI 入口：`src/main.py`（安装后命令为 `clp`）。静态资源：`src/ui/static/`；文档图片：`assets/`；构建产物：`dist/`。
- 默认端口：Claude `3210`、Codex `3211`、UI `3300`。运行/日志与数据目录：`~/.clp/run`、`~/.clp/data`。

## BaseProxyService 架构概览
- **请求处理流程**（7个阶段）：Endpoint 过滤 → 模型路由 → 负载均衡选配置 → 构建请求 → 发送到上游 → 处理响应（重试） → 记录日志。
- **三层过滤机制**：
  1. Endpoint 过滤（最高优先级，命中即阻断）
  2. Header 过滤（移除敏感请求头）
  3. 请求体过滤（替换/移除敏感数据）
- **负载均衡模式**：
  - `active-first`：始终使用激活配置，无重试
  - `weight-based`：按权重选择健康配置，支持多候选重试（两轮），失败计数自动重置（可配置冷却期）
- **流式响应**：支持 SSE/NDJSON，逐块转发，实时解析 usage，广播 WebSocket 事件。
- **日志系统**：按服务拆分（`proxy_requests_{service}.jsonl`），内存缓存 + 文件锁，保留最近 1000 条。

## 构建、测试与开发命令
- 开发安装：`python3 -m venv clp-env && source clp-env/bin/activate && pip install -e .`
- 启动/停止/状态/UI：`clp start | clp stop | clp status | clp ui`。
- 构建发布：`pip install build && python -m build`（产物在 `dist/`）。
- 配置管理：`clp list claude`、`clp list codex`；切换：`clp active claude prod`、`clp active codex dev`（热切换）。
- 端口被占用：`lsof -ti:3210,3211,3300 | xargs kill -9`。可用环境变量 `CLP_PROXY_HOST`、`CLP_UI_HOST` 覆盖监听地址。

## 代码风格与命名规范
- Python 3.7+；4 空格缩进；UTF‑8；尽量使用类型注解与简洁中文 docstring。
- 包/模块小写；函数与变量 `snake_case`；类 `PascalCase`。
- 每个服务遵循 `ctl.py`、`configs.py`、`proxy.py` 命名；使用自顶向下绝对导入：`from src.* import ...`。

## 测试指南
- 推荐 `pytest`：`tests/unit/`（工具与过滤器）、`tests/integration/`（FastAPI 代理路径，`httpx.AsyncClient`）。
- 文件命名 `test_*.py`，运行 `pytest -q`；避免固定端口，优先 ASGI 测试客户端与临时事件循环。
- 运行 `pytest -q`、`pytest tests/...` 等命令前，请先执行 `source clp-env/bin/activate` 激活虚拟环境。
- 建议覆盖率 ≥70%（可用 `pytest-cov`）。测试写入请隔离 `~/.clp` 到临时目录。

## 提交与 PR 规范
- 采用 Conventional Commits（历史示例：`feat:`、`fix:`、`build:`）。示例：`feat(codex): 支持 Header 过滤热重载`。
- PR 必须包含：变更目的/影响面、测试步骤（命令）、受影响端口；UI 变更请附截图（`src/ui/static/`）。
- 关联 Issue（如 `Fixes #123`）；涉及 CLI、配置或安全行为，需同步更新 `README.md`/本文件/`CLAUDE.md`。
- 禁止提交密钥与私有数据；切勿提交 `~/.clp/*`。

## 安全与配置提示
- 默认仅监听 `127.0.0.1`；外网访问请使用反向代理 + TLS，并启用鉴权：`clp auth on`、生成并轮换 token（推荐 `X-API-Key` 头）。
- 关键配置文件：`~/.clp/claude.json`、`~/.clp/codex.json`、`~/.clp/filter.json`、`~/.clp/auth.json`、`~/.clp/data/model_router_config.json`、`~/.clp/data/lb_config.json`。
- 文档与沟通请统一使用简体中文。
