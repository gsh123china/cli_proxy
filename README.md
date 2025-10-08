# CLP (CLI Proxy) - 本地AI代理工具

## 项目简介

CLP 是一个本地CLI代理工具，用于管理和代理AI服务（如Claude和Codex）的API请求。该工具提供统一的命令行界面来启动、停止和管理多个AI服务代理，支持多配置管理和Web UI监控。

## 亮点
- **动态切换配置**: 支持命令行/UI界面动态切换不同的服务配置，【无需重启claude/codex命令行终端，上下文保留】
- **三层敏感数据过滤**: Endpoint 阻断 → Header 过滤 → 请求体过滤，全方位保护隐私
- **智能负载均衡**: 支持"号池管理"，按权重智能选择，失败自动切换，支持两轮重试和自动重置
- **多服务支持**: 支持各种中转站配置，无需繁琐调整json配置后重启客户端
- **实时监控**: WebSocket 推送请求生命周期事件、负载均衡切换事件、响应块数据
- **token使用统计**: 自动解析请求中的token使用情况（支持 SSE/NDJSON 流式响应）
- **模型路由管理**: 支持自定义模型路由，灵活控制请求目标站点的模型名称

## 界面预览

![首页概览](assets/index.jpeg)
![配管理界面](assets/config.jpeg)
![请求过滤配置](assets/filter.jpeg)
![请求详情](assets/request_detail.jpeg)
![Token 使用统计](assets/token_use.jpeg)
![负载均衡](assets/lb.jpeg)
![模型路由配置](assets/model_router.jpeg)

## 主要功能

### 🚀 核心功能
- **多服务代理**: 支持Claude（端口3210）和Codex（端口3211）代理服务
- **配置管理**: 支持多配置切换和管理
- **Web UI界面**: 提供Web界面（端口3300）监控代理状态和使用统计
- **三层请求过滤**:
  - Endpoint 过滤：基于路径/方法/查询参数阻断请求
  - Header 过滤：移除敏感请求头
  - 请求体过滤：替换/移除敏感数据
- **智能负载均衡**:
  - active-first 模式：始终使用激活配置
  - weight-based 模式：按权重选择，自动健康检查，多候选重试
- **流式响应**:
  - 支持 SSE（Server-Sent Events）
  - 支持 NDJSON（Newline Delimited JSON）
  - 逐块转发，无缓冲延迟
- **使用统计**: 自动记录和分析API使用情况，实时解析流式响应中的 token 用量

### 📊 监控功能
- 实时服务状态监控（WebSocket 推送）
- 请求生命周期事件（started/streaming/completed）
- 负载均衡切换事件（lb_switch/lb_reset/lb_exhausted）
- 响应块实时推送
- API使用量统计（自动解析 SSE/NDJSON）
- 请求/响应日志记录（支持阻断信息审计）
- 配置状态跟踪

## 技术栈

- **Python 3.7+**
- **FastAPI**: 异步Web框架，用于代理服务
- **Flask**: Web UI界面
- **httpx**: 异步HTTP客户端
- **uvicorn**: ASGI服务器
- **psutil**: 进程管理

## 项目结构

```
src/
├── main.py                     # 主入口文件
├── core/
│   ├── base_proxy.py          # 基础代理服务类（核心请求处理逻辑）
│   └── realtime_hub.py        # WebSocket 实时事件广播
├── claude/
│   ├── configs.py             # Claude配置管理
│   ├── ctl.py                 # Claude服务控制器
│   └── proxy.py               # Claude代理服务
├── codex/
│   ├── configs.py             # Codex配置管理
│   ├── ctl.py                 # Codex服务控制器
│   └── proxy.py               # Codex代理服务
├── config/
│   ├── config_manager.py      # 配置管理器
│   └── cached_config_manager.py # 缓存配置管理器
├── filter/
│   ├── request_filter.py      # 请求体过滤器
│   ├── cached_request_filter.py # 缓存请求过滤器
│   ├── header_filter.py       # Header 过滤器
│   ├── cached_header_filter.py # 缓存 Header 过滤器
│   ├── endpoint_filter.py     # Endpoint 过滤器（最高优先级）
│   └── cached_endpoint_filter.py # 缓存 Endpoint 过滤器
├── auth/
│   ├── auth_manager.py        # 鉴权管理器
│   ├── token_generator.py     # Token 生成器
│   ├── fastapi_middleware.py  # FastAPI 鉴权中间件
│   └── flask_middleware.py    # Flask 鉴权中间件
├── ui/
│   ├── ctl.py                 # UI服务控制器
│   ├── ui_server.py           # Flask Web UI服务
│   └── static/                # 静态资源文件
└── utils/
    ├── platform_helper.py     # 平台工具
    └── usage_parser.py        # 使用统计解析器（支持 SSE/NDJSON）
```

### 核心架构说明

**BaseProxyService** (`src/core/base_proxy.py`) 提供统一的代理服务实现：

1. **请求处理流程**（7个阶段）：
   - ① Endpoint 过滤 → ② 模型路由 → ③ 负载均衡选配置 → ④ 构建请求 → ⑤ 发送到上游 → ⑥ 处理响应（重试） → ⑦ 记录日志

2. **负载均衡**：
   - `active-first` 模式：始终使用激活配置，无重试
   - `weight-based` 模式：按权重选择健康配置，支持两轮重试，失败计数自动重置（可配置冷却期）

3. **流式响应**：
   - 支持 SSE/NDJSON，逐块转发，无缓冲延迟
   - 实时解析 usage 信息，广播 WebSocket 事件

4. **日志系统**：
   - 按服务拆分（`proxy_requests_{service}.jsonl`）
   - 内存缓存 + 文件锁，保留最近 1000 条记录
## 快速开始

### 虚拟环境安装（推荐）

使用虚拟环境可以更好地隔离依赖：

```bash
# 创建虚拟环境
python3 -m venv clp-env

# 激活虚拟环境
source clp-env/bin/activate

# 安装 CLP
pip install --force-reinstall ./dist/clp-1.11.0-py3-none-any.whl

# 使用 clp 命令
clp start

# 退出虚拟环境时使用
deactivate
```

### 直接安装
```bash
# 安装最新版本
pip install --force-reinstall ./dist/clp-1.11.0-py3-none-any.whl

# 更新后需要重启服务新功能才生效（先杀掉clp占用的三个端口保险一点）
# macOS / Linux
lsof -ti:3210,3211,3300 | xargs kill -9
clp restart
```

## 命令使用方法

### 基本命令

```bash
# 启动所有服务
clp start

# 停止所有服务
clp stop

# 重启所有服务
clp restart

# 查看服务状态
clp status

# 启动Web UI界面
clp ui
```

### 配置管理（可在UI界面快速添加和切换配置）

```bash
# 列出Claude的所有配置
clp list claude

# 列出Codex的所有配置
clp list codex

# 包含已禁用的配置
clp list claude --include-deleted

# 激活Claude的prod配置
clp active claude prod

# 激活Codex的dev配置
clp active codex dev

# 禁用配置（逻辑删除）
clp disable codex backup

# 恢复已禁用配置
clp enable claude backup

```

### claude 使用方法
1. 修改 `~/.claude/settings.json` Claude配置文件，连接本地CLI代理服务
```json
{
  "env": {
    "ANTHROPIC_AUTH_TOKEN": "-",
    "ANTHROPIC_BASE_URL": "http://127.0.0.1:3210",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "32000",
    "MAX_THINKING_TOKENS": "30000",
    "DISABLE_AUTOUPDATER": "1"
  },
  "permissions": {
    "allow": [],
    "deny": []
  }
}
```
2. 重启Claude命令行即可（确保本地代理已启动 clp start）

### codex 使用方法
1. 修改 `~/.codex/config.toml` Codex配置文件，连接本地CLI代理服务
```properties
model_provider = "local"
model = "gpt-5-codex"
model_reasoning_effort = "high"
model_reasoning_summary_format = "experimental"
network_access = "enabled"
disable_response_storage = true
show_raw_agent_reasoning = true

[model_providers.local]
name = "local"
base_url = "http://127.0.0.1:3211"
wire_api = "responses"
```
2. 修改 `~/.codex/auth.json` (没有就创建一个)
```json
{
  "OPENAI_API_KEY": "-"
}
```
3. 重启codex即可（确保本地代理已启动 clp start）

## 鉴权配置

### 功能说明

CLP 提供 API Token 鉴权功能，用于保护部署在公网环境的代理服务。该功能采用 Bearer Token 认证方式，通过 `clp_` 前缀的 token 区分代理层和上游 API 认证。

**特性：**
- ✅ 支持 `Authorization: Bearer clp_xxx` 和 `X-API-Key: clp_xxx` 两种认证方式
- ✅ 支持 WebSocket 连接鉴权（通过 query 参数）
- ✅ Token 支持过期时间和启用/禁用状态
- ✅ 默认关闭，不影响现有部署（向后兼容）
- ✅ 服务级别控制（可单独控制 UI、Claude、Codex 服务的鉴权）

### 快速开始

#### 1. 生成鉴权 Token

```bash
# 为代理服务生成 token（只允许访问 Claude/Codex）
clp auth generate --name codex-prod --services claude codex --description "生产环境token"

# 为 Web UI 生成独立 token（具备管理权限）
clp auth generate --name ui-admin --services ui --description "UI 管理员"

# 输出示例：
# ✓ Token 生成成功！
# 名称: codex-prod
# Token: clp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
# 服务: claude, codex
#
# 请妥善保管此token，它将用于访问代理服务。
```

#### 2. 启用鉴权

```bash
# 启用鉴权功能
clp auth on

# 重启服务使配置生效
clp restart
```

#### 3. 客户端使用

**Python (Anthropic SDK):**
```python
import anthropic

# 使用 X-API-Key 方式（推荐，避免与上游认证冲突）
client = anthropic.Anthropic(
    base_url="http://your-server:3210",
    api_key="your-upstream-claude-key",
    default_headers={
        "X-API-Key": "clp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
    }
)
```

**cURL:**
```bash
# 方式 1: 使用 X-API-Key（推荐）
curl http://your-server:3210/v1/messages \
  -H "X-API-Key: clp_your_token_here" \
  -H "Content-Type: application/json" \
  -d '{...}'

# 方式 2: 使用 Authorization Bearer
curl http://your-server:3210/v1/messages \
  -H "Authorization: Bearer clp_your_token_here" \
  -H "Content-Type: application/json" \
  -d '{...}'
```

**Web UI 访问:**
```bash
# 访问 UI 时，在浏览器中添加 header 或使用 query 参数
http://your-server:3300?token=clp_your_token_here
```

### Token 管理命令

```bash
# 列出所有 token
clp auth list

# 输出示例：
# === 鉴权Token列表 ===
# 全局状态: 已启用
#
# 名称             状态     服务               创建时间              描述
# ----------------------------------------------------------------------------------
# codex-prod      启用     claude,codex      2025-01-15T10:30:00   生产环境token
# ui-admin        启用     ui                2025-01-15T11:00:00   UI 管理员
#
# 共 2 个token

# 禁用指定 token（不删除）
clp auth disable development

# 启用已禁用的 token
clp auth enable development

# 删除 token（永久删除）
clp auth remove development

# 关闭鉴权（需要重启服务）
clp auth off
```

### 配置文件

鉴权配置保存在 `~/.clp/auth.json`：

```json
{
  "enabled": true,
  "tokens": [
    {
      "token": "clp_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
      "name": "production",
      "description": "生产环境token",
      "created_at": "2025-01-15T10:30:00",
      "expires_at": null,
      "active": true,
      "services": ["claude", "codex"]
    }
  ],
  "services": {
    "ui": true,
    "claude": true,
    "codex": true
  }
}
```

**配置说明：**
- `enabled`: 全局鉴权开关
- `tokens`: Token 列表
  - `token`: 完整的 token 字符串
  - `name`: 唯一标识符
  - `description`: 描述信息
  - `created_at`: 创建时间
  - `expires_at`: 过期时间（null 表示永不过期）
  - `active`: 是否启用
- `services`: 各服务的鉴权开关

### 安全建议

#### Token 安全
- ✅ 妥善保管 token，不要提交到代码仓库
- ✅ 定期轮换 token（生成新 token，删除旧 token）
- ✅ 为不同服务（UI / Claude / Codex）和环境分别配置 token
- ✅ 使用 `--services` 时至少选择一个合法服务，命令会在输入无效时终止
- ✅ 设置 token 过期时间：`clp auth generate --name temp --expires 2025-12-31T23:59:59`
- ✅ 不需要的 token 及时删除

#### 鉴权与反向代理
如果使用 Nginx/Caddy 等反向代理，建议：
- 在反向代理层使用 Basic Auth 或 OAuth
- CLP 层使用 Token 认证作为第二层防护
- 两层认证提供更好的安全性

#### 白名单路径
以下路径无需鉴权（便于监控和健康检查）：
- `/health` - 健康检查
- `/ping` - 心跳检测
- `/favicon.ico` - 图标
- `/static/*` - 静态资源（仅 UI 服务）

## 部署与配置

### 监听地址配置

CLP 支持通过环境变量灵活控制服务的监听地址，适应不同的部署场景：

| 环境变量 | 说明 | 默认值 | 适用服务 |
|---------|------|--------|---------|
| `CLP_UI_HOST` | Web UI 监听地址 | `127.0.0.1` | UI 服务（端口 3300） |
| `CLP_PROXY_HOST` | 代理服务监听地址 | `127.0.0.1` | Claude（3210）和 Codex（3211） |

#### 监听地址说明

- **`0.0.0.0`** - 监听所有网络接口，允许外部访问（适合本地开发）
- **`127.0.0.1`** - 仅监听本地回环接口，只允许本机访问（适合公网部署，更安全）

### 部署场景

#### 场景 1：本地开发环境

需要从局域网内其他设备访问：

```bash
# 允许所有网络接口访问
export CLP_UI_HOST=0.0.0.0
export CLP_PROXY_HOST=0.0.0.0
clp start

# 从同一局域网的其他设备访问
# 访问 http://<your-local-ip>:3300
```

#### 场景 2：公网服务器部署（推荐配置）

服务部署在公网服务器，使用默认配置（仅本地访问）：

```bash
# 使用默认配置，仅允许本地访问（安全）
clp start

# 通过 SSH 隧道或 Nginx 反向代理访问
```

**配合 Nginx 反向代理使用**（推荐）：

```nginx
# Nginx 完整透传配置示例
server {
    listen 80;
    server_name your-domain.com;

    # UI 服务代理
    location / {
        proxy_pass http://127.0.0.1:3300;

        # 保留原始请求信息
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # 透传所有原始请求头（重要！）
        proxy_pass_request_headers on;

        # 支持 WebSocket（实时监控功能需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置（适应流式响应）
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 300s;

        # 关闭缓冲，实现真正的流式传输
        proxy_buffering off;
        proxy_request_buffering off;
    }

    # 如果需要直接暴露代理服务（不推荐，建议保持 127.0.0.1）
    # location /claude/ {
    #     proxy_pass http://127.0.0.1:3210/;
    #     proxy_pass_request_headers on;
    #     proxy_http_version 1.1;
    #     proxy_buffering off;
    # }
}

# HTTPS 配置（生产环境强烈推荐）
server {
    listen 443 ssl http2;
    server_name your-domain.com;

    ssl_certificate /path/to/your/cert.pem;
    ssl_certificate_key /path/to/your/key.pem;

    # SSL 安全配置
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    location / {
        proxy_pass http://127.0.0.1:3300;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;  # 注意这里是 https

        proxy_pass_request_headers on;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 300s;

        proxy_buffering off;
        proxy_request_buffering off;
    }
}

# HTTP 自动跳转到 HTTPS
server {
    listen 80;
    server_name your-domain.com;
    return 301 https://$server_name$request_uri;
}
```

**关键配置说明**：

| 配置项 | 作用 | 是否透传原始信息 |
|-------|------|-----------------|
| `proxy_pass_request_headers on` | 透传所有原始请求头 | ✅ 是 |
| `proxy_set_header Host $host` | 保留原始 Host 头 | ✅ 是 |
| `proxy_set_header X-Real-IP $remote_addr` | 传递真实客户端 IP | ✅ 是 |
| `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for` | 传递完整 IP 链 | ✅ 是 |
| `proxy_set_header X-Forwarded-Proto $scheme` | 传递协议（http/https） | ✅ 是 |
| `proxy_http_version 1.1` | 使用 HTTP/1.1（支持长连接） | ✅ 是 |
| `proxy_buffering off` | 关闭缓冲，实时流式传输 | ✅ 是 |
| `proxy_request_buffering off` | 关闭请求缓冲 | ✅ 是 |

**注意事项**：
- ✅ 请求方法、路径、查询参数、请求体会自动透传
- ✅ `proxy_pass` 使用 `http://127.0.0.1:3300` 不带尾部斜杠，会保留原始路径
- ✅ WebSocket 支持确保实时监控功能正常工作
- ⚠️ 如果 CLP 服务需要特定的自定义请求头，Nginx 会自动透传

---

**使用 Nginx Proxy Manager（NPM）配置**（推荐新手使用）：

Nginx Proxy Manager 是一个可视化的 Nginx 反向代理管理工具，通过 Web UI 界面配置，无需手动编辑配置文件。

##### 1. 安装 Nginx Proxy Manager

使用 Docker Compose 安装：

```yaml
# docker-compose.yml
version: '3.8'
services:
  nginx-proxy-manager:
    image: 'jc21/nginx-proxy-manager:latest'
    restart: unless-stopped
    ports:
      - '80:80'      # HTTP
      - '443:443'    # HTTPS
      - '81:81'      # NPM 管理界面
    volumes:
      - ./data:/data
      - ./letsencrypt:/etc/letsencrypt
```

启动服务：

```bash
docker-compose up -d
```

访问管理界面：`http://your-server-ip:81`
- 默认账号：`admin@example.com`
- 默认密码：`changeme`
- **首次登录后请立即修改密码！**

##### 2. 创建代理主机（Proxy Host）

在 NPM 管理界面中：

**步骤 1：添加代理主机**
1. 进入 `Hosts` -> `Proxy Hosts`
2. 点击 `Add Proxy Host` 按钮

**步骤 2：填写基本信息（Details 选项卡）**

| 字段 | 填写内容 |
|------|---------|
| Domain Names | `your-domain.com` 或 `clp.yourdomain.com` |
| Scheme | `http` |
| Forward Hostname / IP | `host.docker.internal` (Docker) 或 `服务器内网IP` |
| Forward Port | `3300` |
| Cache Assets | ❌ 不勾选 |
| Block Common Exploits | ✅ 勾选（推荐）|
| Websockets Support | ✅ **必须勾选**（支持实时监控）|

**重要**：如果 NPM 在 Docker 中运行，而 CLP 在宿主机运行：
- Linux: 使用 `host.docker.internal` 或宿主机 IP（如 `192.168.1.100`）
- macOS/Windows Docker Desktop: 使用 `host.docker.internal`
- 或者在 `docker-compose.yml` 中添加 `network_mode: host`

**步骤 3：配置 SSL 证书（SSL 选项卡）**

| 字段 | 填写内容 |
|------|---------|
| SSL Certificate | 选择 `Request a new SSL Certificate` |
| Force SSL | ✅ 勾选（强制 HTTPS）|
| HTTP/2 Support | ✅ 勾选 |
| Use a DNS Challenge | 根据需要选择 |
| Email Address | 你的邮箱（用于 Let's Encrypt）|
| I Agree to the Let's Encrypt Terms of Service | ✅ 勾选 |

**步骤 4：添加自定义 Nginx 配置（Advanced 选项卡）**

为了支持流式传输和完整透传，在 `Custom Nginx Configuration` 框中添加以下配置：

```nginx
# 关闭缓冲，支持流式传输（必须！）
proxy_buffering off;
proxy_request_buffering off;

# 超时设置
proxy_connect_timeout 60s;
proxy_send_timeout 60s;
proxy_read_timeout 300s;

# 保留原始请求信息
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header Host $host;

# WebSocket 支持（NPM 已自动添加，这里是确保）
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

**步骤 5：保存配置**

点击 `Save` 按钮，NPM 会自动：
- 生成 Nginx 配置文件
- 申请 SSL 证书（如果选择了）
- 重载 Nginx 服务

##### 3. NPM 与传统 Nginx 配置对比

| 配置项 | 传统 Nginx | Nginx Proxy Manager |
|-------|-----------|---------------------|
| 配置方式 | 编辑 `.conf` 文件 | Web UI 界面 |
| SSL 证书 | 手动申请和配置 | 自动申请和续期 |
| WebSocket | 手动添加配置 | 勾选选项 + 自定义配置 |
| 流式传输 | 手动添加 `proxy_buffering off` | 在 Advanced 中添加 |
| 基本反向代理 | 完整配置块 | 填写表单 |
| 适用场景 | 高级用户、复杂配置 | 新手、快速部署 |

##### 4. NPM 注意事项

**Docker 网络配置**

如果 NPM 无法访问宿主机的 `127.0.0.1:3300`，尝试以下方法：

方法 1：使用宿主机网络模式
```yaml
services:
  nginx-proxy-manager:
    network_mode: host
    # 注意：使用 host 模式后，ports 映射会被忽略
```

方法 2：使用宿主机内网 IP
```
Forward Hostname / IP: 192.168.1.100  # 你的服务器内网 IP
Forward Port: 3300
```

方法 3：Docker 特殊域名（推荐）
```
# Linux (需要在 docker run 时添加 --add-host=host.docker.internal:host-gateway)
Forward Hostname / IP: host.docker.internal

# macOS/Windows Docker Desktop（自动支持）
Forward Hostname / IP: host.docker.internal
```

**验证配置**

在 NPM 中配置完成后，检查是否工作：

```bash
# 测试 HTTP 访问
curl -I http://your-domain.com

# 测试 HTTPS 访问
curl -I https://your-domain.com

# 测试 WebSocket（实时监控）
# 在浏览器控制台查看 WebSocket 连接状态
```

**常见问题**

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 502 Bad Gateway | NPM 无法连接到 CLP 服务 | 检查 Forward Hostname/IP 和端口 |
| 实时监控不工作 | WebSocket 未启用 | 勾选 "Websockets Support" |
| 流式响应卡顿 | 缓冲未关闭 | 在 Advanced 中添加 `proxy_buffering off` |
| 无法申请 SSL 证书 | 域名未正确解析 | 确保域名 A 记录指向服务器 IP |

##### 5. 完整 Docker Compose 示例

将 CLP 和 NPM 一起部署：

```yaml
version: '3.8'

services:
  clp:
    build: .
    environment:
      - CLP_UI_HOST=127.0.0.1
      - CLP_PROXY_HOST=127.0.0.1
    volumes:
      - ~/.clp:/root/.clp
    network_mode: host
    restart: unless-stopped

  nginx-proxy-manager:
    image: 'jc21/nginx-proxy-manager:latest'
    restart: unless-stopped
    network_mode: host
    volumes:
      - ./npm-data:/data
      - ./letsencrypt:/etc/letsencrypt
```

使用 `network_mode: host` 后，两个服务可以直接通过 `127.0.0.1` 互相访问。

---

#### 场景 3：混合配置

UI 通过反向代理公开，代理服务仅本地访问：

```bash
# UI 允许外部访问
export CLP_UI_HOST=0.0.0.0

# 代理服务仅本地访问（更安全）
export CLP_PROXY_HOST=127.0.0.1

clp start
```

### 持久化配置

#### 方法 1：Shell 配置文件（推荐）

将环境变量添加到 shell 配置文件：

```bash
# Bash
echo 'export CLP_UI_HOST=127.0.0.1' >> ~/.bashrc
echo 'export CLP_PROXY_HOST=127.0.0.1' >> ~/.bashrc
source ~/.bashrc

# Zsh
echo 'export CLP_UI_HOST=127.0.0.1' >> ~/.zshrc
echo 'export CLP_PROXY_HOST=127.0.0.1' >> ~/.zshrc
source ~/.zshrc
```

#### 方法 2：Systemd 服务（Linux）

创建 systemd 服务文件 `/etc/systemd/system/clp.service`：

```ini
[Unit]
Description=CLP AI Proxy Service
After=network.target

[Service]
Type=forking
User=your-username
Environment="CLP_UI_HOST=127.0.0.1"
Environment="CLP_PROXY_HOST=127.0.0.1"
ExecStart=/usr/local/bin/clp start
ExecStop=/usr/local/bin/clp stop
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

启用服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable clp
sudo systemctl start clp
```

#### 方法 3：Docker 容器

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY . .
RUN pip install -e .

ENV CLP_UI_HOST=0.0.0.0
ENV CLP_PROXY_HOST=0.0.0.0

EXPOSE 3300 3210 3211

CMD ["clp", "start"]
```

### 安全建议

#### 公网部署安全清单

- ✅ **启用 CLP 鉴权**：运行 `clp auth on` 并生成 token
- ✅ 设置 `CLP_UI_HOST=127.0.0.1` 和 `CLP_PROXY_HOST=127.0.0.1`
- ✅ 使用 Nginx/Caddy 等反向代理并配置 HTTPS
- ✅ 启用反向代理的访问认证（Basic Auth 或 OAuth）
- ✅ 配置防火墙规则，仅允许必要的端口
- ✅ 定期更新依赖和系统补丁
- ✅ 使用非 root 用户运行服务
- ✅ 监控日志文件 `~/.clp/run/*.log`
- ✅ 定期轮换 API Token

#### SSH 隧道访问（临时方案）

如果需要临时访问远程服务器的 UI：

```bash
# 在本地机器执行
ssh -L 3300:localhost:3300 user@remote-server

# 在浏览器访问
http://localhost:3300
```

### 验证配置

启动服务后，检查监听地址：

```bash
# 查看服务状态
clp status

# 检查端口监听情况
sudo lsof -i :3300
sudo lsof -i :3210
sudo lsof -i :3211

# 或者使用 netstat
sudo netstat -tlnp | grep -E '3300|3210|3211'
```

预期输出：
- `127.0.0.1:3300` - 仅本地访问
- `0.0.0.0:3300` - 允许外部访问

### 故障排查

#### 问题 1：无法从外部访问服务

**原因**：使用默认配置（`127.0.0.1`），仅允许本地访问

**解决**：
```bash
export CLP_UI_HOST=0.0.0.0
export CLP_PROXY_HOST=0.0.0.0
clp restart
```

#### 问题 2：环境变量不生效

**原因**：环境变量未正确设置或服务未重启

**解决**：
```bash
# 验证环境变量
echo $CLP_UI_HOST
echo $CLP_PROXY_HOST

# 重启服务
clp restart
```

#### 问题 3：服务无法启动

**检查日志**：
```bash
cat ~/.clp/run/ui.log
cat ~/.clp/run/claude_proxy.log
cat ~/.clp/run/codex_proxy.log
```

## 开发指南

### 1. 虚拟环境设置（推荐）

```bash
# 创建虚拟环境
python3 -m venv clp-env

# 激活虚拟环境
source clp-env/bin/activate

# 安装依赖
pip install -e .

# 退出虚拟环境
deactivate
```

### 2. 直接安装依赖

```bash
pip install -e .
```

### 3. 构建打包

```bash
# 方式 1：直接构建
pip install build
python -m build

# 方式 2：在虚拟环境中构建（推荐）
python3 -m venv clp-env
source clp-env/bin/activate
pip install build
python -m build
```

### 4. 配置文件

工具会在用户主目录下创建 `~/.clp/` 目录存储配置：

- `~/.clp/claude.json` - Claude服务配置
- `~/.clp/codex.json` - Codex服务配置
- `~/.clp/run/` - 运行时文件（PID、日志）
- `~/.clp/data/` - 数据文件（请求日志、统计数据）

> 说明：逻辑删除（deleted=true）的配置不会参与路由与负载均衡；禁用时系统会从负载均衡状态中清理该配置的失败计数与排除列表。

#### 配置字段示例

```json
{
  "prod": {
    "base_url": "https://api.example.com",
    "auth_token": "token-prod",
    "weight": 100,
    "active": true
  },
  "backup": {
    "base_url": "https://backup.example.com",
    "auth_token": "token-backup",
    "weight": 50,
    "deleted": true,
    "deleted_at": "2025-10-07T03:25:00Z"
  }
}
```

- `deleted`: 设置为 `true` 表示逻辑删除，配置不会用于请求转发，可通过 UI 或 `clp enable` 恢复。
- `deleted_at`: 记录禁用时间（ISO8601），禁用时自动写入，恢复启用后可留空。
- 未显式声明 `deleted` 字段的旧配置默认视为启用，无需手动迁移。

### 添加新的AI服务

1. 在 `src/` 下创建新的服务目录
2. 继承 `BaseProxyService` 和 `BaseServiceController`
3. 实现服务特定的配置和代理逻辑
4. 在 `main.py` 中注册新服务

### 自定义请求过滤器

在 `src/filter/` 目录下实现自定义过滤器：

```python
def custom_filter(data: bytes) -> bytes:
    # 实现自定义过滤逻辑
    return filtered_data
```

### 请求接口过滤（endpoint_filter.json）

- 位置：`~/.clp/endpoint_filter.json`
- 作用：按"方法 + 路径(精确/前缀/正则) + 查询参数"匹配并阻断请求，不向上游转发；原始请求会被记录到本地日志用于审计；UI 提供可视化管理。
- **优先级最高**：在模型路由和负载均衡之前判定，命中后立即返回错误，不消耗上游配额。

最小示例（拦截 /api/v1/messages/count_tokens?beta=true）：

```json
{
  "enabled": true,
  "rules": [
    {
      "id": "block-count-tokens",
      "services": ["claude", "codex"],
      "methods": ["GET", "POST"],
      "path": "/api/v1/messages/count_tokens",
      "pathMatchType": "exact",
      "query": { "beta": "true" },
      "action": { "type": "block", "status": 403, "message": "count_tokens disabled" }
    }
  ]
}
```

**配置说明**：
- `services`：适用服务（缺省表示两者皆适用）
- `methods`：HTTP 方法列表（缺省为 `["*"]` 任意方法）
- `path`：匹配路径（始终带前导 `/`）
- `pathMatchType`：匹配模式（`exact`/`prefix`/`regex`）
- `query`：查询参数 AND 关系，值为 `"*"` 表示"仅需存在"
- `action.status`：返回的 HTTP 状态码（推荐 403/451）
- `action.message`：错误消息

**命中后的行为**：
- 日志包含 `blocked: true`、`blocked_by`（规则ID）、`blocked_reason`（消息）
- 实时面板 `channel` 显示为 `blocked`
- WebSocket 广播 `request_started` 和 `request_completed` 事件（`success: false`）

## 特性说明

### 异步处理
- 使用FastAPI和httpx实现高性能异步代理
- 支持并发请求处理
- 优化的连接池管理（max_connections=200, max_keepalive_connections=100）
- 使用 `asyncio.to_thread` 避免阻塞（日志记录、过滤器应用）

### 安全特性
- 请求头过滤和标准化（移除 `authorization`、`host`、`content-length` 后重新设置）
- 三层敏感信息过滤（Endpoint 阻断 → Header 过滤 → 请求体过滤）
- 配置文件安全存储（`~/.clp/`）
- 鉴权系统（Bearer Token，`clp_` 前缀区分代理层和上游层）

### 监控和日志
- 详细的请求/响应日志（支持 Base64 编码的原始和过滤后内容）
- 使用量统计和分析（自动解析 SSE/NDJSON 流式响应中的 usage 信息）
- Web UI可视化监控（WebSocket 实时推送）
- 日志轮转（保留最近 1000 条，按服务拆分）
- 阻断请求审计（记录 `blocked_by`、`blocked_reason`）

### 配置热重载
- 基于文件签名检测（`st_mtime_ns + st_size`）
- 无需重启服务即可生效
- 适用范围：路由配置、负载均衡配置、所有过滤器、鉴权配置

## 许可证

MIT License

## 作者

gjp
---

**注意**: 首次运行时，工具会以占位模式启动，请编辑相应的配置文件后重启服务。
