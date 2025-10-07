# CLAUDE.md

本文件为 Claude Code (claude.ai/code) 在本代码仓库中工作时提供指导。

## ⚠️ 重要提示

**请使用简体中文与我沟通！** 所有回复、说明、错误信息等都应使用简体中文。

## 项目概述

CLP (CLI Proxy) 是一个本地AI代理工具，用于管理和转发 Claude 和 Codex 服务的API请求。它提供统一的CLI管理、Web UI监控、多配置支持、请求过滤、负载均衡和模型路由功能。

## 核心架构

### 服务结构
- **BaseProxyService** (`src/core/base_proxy.py`): 提供核心代理功能的抽象基类
  - 使用 httpx 处理异步 HTTP 代理
  - 实现流式响应支持
  - 管理请求过滤和日志记录
  - 提供模型路由和负载均衡
  - 跟踪使用统计
  - 通过 RealTimeRequestHub 支持 WebSocket 实时请求监控

- **ClaudeProxy** (`src/claude/proxy.py`): Claude 服务实现（端口 3210）
- **CodexProxy** (`src/codex/proxy.py`): Codex 服务实现（端口 3211）

### 配置管理
- **ConfigManager** (`src/config/config_manager.py`): 基础配置管理器
  - 从 `~/.clp/{service}.json` 加载配置
  - 支持每个服务的多个命名配置
  - 使用 `active` 标志跟踪激活配置
  - 支持基于权重的负载均衡

- **CachedConfigManager** (`src/config/cached_config_manager.py`): 添加基于文件签名的缓存以减少 I/O

配置文件格式：
```json
{
  "config_name": {
    "base_url": "https://api.example.com",
    "auth_token": "token_here",
    "api_key": "key_here",
    "weight": 10,
    "active": true
  }
}
```

### 模型路由
模型路由配置文件 `~/.clp/data/model_router_config.json` 支持：
- **model-mapping 模式**：将模型名称或配置映射到不同的目标模型
- **config-mapping 模式**：将特定模型路由到不同的配置
- 通过文件签名检查自动重新加载配置变更

### 负载均衡
负载均衡配置文件 `~/.clp/data/lb_config.json`：
- **active-first 模式**：始终使用激活配置
- **weight-based 模式**：按权重选择，跟踪失败，排除不健康配置
- 每个服务的失败阈值跟踪
- 自动排除重复失败的配置

### 请求过滤
- **RequestFilter** (`src/filter/request_filter.py`): 从 `~/.clp/filter.json` 应用文本替换规则
- **CachedRequestFilter** (`src/filter/cached_request_filter.py`): 添加文件签名缓存
- 过滤器支持对请求体的 `replace` 和 `remove` 操作

### 鉴权系统
- **AuthManager** (`src/auth/auth_manager.py`): Token 验证和配置管理核心
  - 从 `~/.clp/auth.json` 加载配置
  - 支持 token 过期时间和启用/禁用状态
  - 使用文件签名缓存机制提升性能
  - 提供完整的 token CRUD 接口

- **中间件实现** (`src/auth/fastapi_middleware.py`, `src/auth/flask_middleware.py`):
  - FastAPI 使用 BaseHTTPMiddleware 拦截所有请求
  - Flask 使用 before_request 钩子验证请求
  - 支持三种 token 提取方式：
    1. `Authorization: Bearer clp_xxx` - 标准 Bearer 认证
    2. `X-API-Key: clp_xxx` - 自定义 Header（推荐）
    3. `?token=clp_xxx` - Query 参数（WebSocket）
  - 白名单机制：`/health`, `/ping`, `/static/*` 等路径免鉴权

- **Token 生成器** (`src/auth/token_generator.py`):
  - 使用 `secrets` 模块生成密码学安全的随机字符串
  - Base62 编码（0-9, a-z, A-Z）
  - 默认 32 字符长度，`clp_` 前缀
  - 通过前缀区分代理层和上游层认证

**鉴权流程：**
```
客户端请求 → [鉴权中间件] → 现有代理逻辑 → 上游 API

1. 中间件提取 token（Authorization/X-API-Key/Query）
2. 验证 token 是否存在于 auth.json
3. 检查 token 状态（active、expires_at）
4. 验证通过 → 放行到代理逻辑
5. 验证失败 → 返回 401 Unauthorized

注意：代理逻辑中，客户端的 Authorization header 会被忽略，
使用配置文件中的真实 API key 访问上游，两层认证完全独立。
```

### 服务控制
- **BaseServiceController** (`src/core/base_proxy.py:820`): 用于启动/停止服务的基础控制器
- **Claude/Codex 控制器** (`src/claude/ctl.py`, `src/codex/ctl.py`): 服务特定控制器

## 开发命令

### 环境变量配置

项目支持通过环境变量控制服务监听地址：

- `CLP_UI_HOST` - UI 服务监听地址（默认 `127.0.0.1`）
- `CLP_PROXY_HOST` - Claude/Codex 代理服务监听地址（默认 `127.0.0.1`）

**使用示例**：

```bash
# 默认配置（仅本地访问，适合公网部署）
clp start

# 本地开发环境 - 允许局域网访问
export CLP_UI_HOST=0.0.0.0
export CLP_PROXY_HOST=0.0.0.0
clp restart

# 或者一次性设置
CLP_UI_HOST=0.0.0.0 CLP_PROXY_HOST=0.0.0.0 clp start

# 持久化配置（添加到 ~/.bashrc 或 ~/.zshrc）
echo 'export CLP_UI_HOST=0.0.0.0' >> ~/.bashrc
echo 'export CLP_PROXY_HOST=0.0.0.0' >> ~/.bashrc
source ~/.bashrc
```

### 虚拟环境管理

推荐使用虚拟环境隔离依赖：

```bash
# 创建虚拟环境
python3 -m venv clp-env

# 激活虚拟环境
source clp-env/bin/activate

# 在虚拟环境中安装
pip install --force-reinstall ./dist/clp-1.11.0-py3-none-any.whl

# 使用 clp 命令
clp restart

# 退出虚拟环境
deactivate
```

- 在运行 `pytest -q` 或其他测试命令前，务必先执行 `source clp-env/bin/activate` 激活虚拟环境。

### 安装
```bash
# 方式 1：从源代码安装（开发模式）
pip install -e .

# 方式 2：从 wheel 包安装（推荐）
pip install --force-reinstall ./dist/clp-1.11.0-py3-none-any.whl

# 方式 3：在虚拟环境中安装（推荐用于生产环境）
python3 -m venv clp-env
source clp-env/bin/activate
pip install --force-reinstall ./dist/clp-1.11.0-py3-none-any.whl
```

### 构建与打包

```bash
# 方式 1：直接构建（需要先安装 build 模块）
pip install build
python -m build

# 方式 2：在虚拟环境中构建（推荐）
python3 -m venv clp-env
source clp-env/bin/activate
pip install build
python -m build
```

### 服务管理
```bash
# 启动所有服务 (claude:3210, codex:3211, ui:3300)
clp start

# 停止所有服务
clp stop

# 重启所有服务
clp restart

# 查看服务状态
clp status

# 打开 Web UI
clp ui
```

### 配置管理
```bash
# 列出配置
clp list claude
clp list codex

# 切换激活配置（无需重启 - 动态重载）
clp active claude prod
clp active codex dev
```

### 强制停止端口（如需要）
```bash
# macOS/Linux
lsof -ti:3210,3211,3300 | xargs kill -9
```

## 重要文件

- `~/.clp/claude.json` - Claude 配置文件
- `~/.clp/codex.json` - Codex 配置文件
- `~/.clp/filter.json` - 请求过滤规则
- `~/.clp/auth.json` - 鉴权配置和 token 管理
- `~/.clp/data/model_router_config.json` - 模型路由配置
- `~/.clp/data/lb_config.json` - 负载均衡配置
- `~/.clp/data/proxy_requests.jsonl` - 请求日志（最近 100 条记录）
- `~/.clp/run/*.pid` - 服务 PID 文件
- `~/.clp/run/*.log` - 服务日志文件

## 核心特性

1. **动态配置切换**：无需重启 CLI 终端即可切换配置（保留上下文）
2. **请求过滤**：从请求中过滤敏感数据
3. **模型路由**：根据规则将请求路由到不同的模型或配置
4. **负载均衡**：使用基于权重或优先激活的策略在多个配置间分配请求
5. **实时监控**：WebSocket 端点 `/ws/realtime` 用于实时请求跟踪
6. **使用统计**：自动解析和记录 token 使用情况
7. **鉴权保护**：Bearer Token 认证，保护公网部署的代理服务

## API 端点测试

ClaudeProxy 和 CodexProxy 都实现了 `test_endpoint()` 方法用于连接性测试。该测试发送一个最小请求来验证 API 是否可访问。

## 技术说明

- 服务通过 `platform_helper.create_detached_process()` 作为独立进程运行
- 所有服务使用 FastAPI + uvicorn，采用 h11 HTTP 实现
- 异步操作使用 httpx.AsyncClient 并启用 keep-alive
- 日志轮转：保留最近 100 条请求记录
- 配置变更通过文件签名（mtime + size）检测
