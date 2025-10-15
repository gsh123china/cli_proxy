# Cursor Rules 索引

本目录包含 CLP 项目的 Cursor AI 规则文件，用于指导 AI 助手理解项目结构、编码规范和最佳实践。

## 规则文件列表

### 📋 项目总览
- **[project-overview.mdc](project-overview.mdc)** - 项目架构、核心组件、技术栈
  - ✅ 始终应用（alwaysApply: true）
  - 包含：核心架构、请求处理流程、默认端口、配置目录

### 🐍 Python 开发
- **[python-code-style.mdc](python-code-style.mdc)** - Python 代码风格规范
  - 适用于：`*.py` 文件
  - 包含：命名规范、类型注解、文档字符串、导入规范、异步编程

### 🔄 代理架构
- **[proxy-architecture.mdc](proxy-architecture.mdc)** - 代理服务架构规范
  - 适用于：`**/proxy.py`, `**/core/*.py`
  - 包含：BaseProxyService、负载均衡、三层过滤、流式响应、日志系统、WebSocket 事件

### 🧪 测试规范
- **[testing-guidelines.mdc](testing-guidelines.mdc)** - 测试规范与指南
  - 适用于：`tests/**/*.py`
  - 包含：测试框架、单元测试、集成测试、最佳实践、覆盖目标

### ⚙️ 配置管理
- **[config-management.mdc](config-management.mdc)** - 配置管理规范
  - 适用于：`**/configs.py`, `**/config_manager.py`
  - 包含：配置结构、逻辑删除、热重载、负载均衡状态、CLI 命令

### 🔍 过滤器系统
- **[filter-system.mdc](filter-system.mdc)** - 过滤器系统规范
  - 适用于：`**/filter/*.py`
  - 包含：Endpoint 过滤、Header 过滤、请求体过滤、缓存机制、JSONPath 支持

### 🎨 UI 开发
- **[ui-development.mdc](ui-development.mdc)** - UI 开发规范
  - 适用于：`**/ui/*.py`, `**/ui/static/**/*`
  - 包含：Flask 服务、WebSocket 实时通信、前端规范、响应式设计、性能优化

### 🔐 鉴权系统
- **[auth-system.mdc](auth-system.mdc)** - 鉴权系统规范
  - 适用于：`**/auth/*.py`
  - 包含：Token 生成、鉴权管理、FastAPI 中间件、Flask 中间件、安全最佳实践

### 💻 CLI 开发
- **[cli-development.mdc](cli-development.mdc)** - CLI 开发规范
  - 适用于：`src/main.py`, `**/ctl.py`
  - 包含：Typer 框架、命令定义、子命令、输出格式、服务控制器

### 📝 Git 提交规范
- **[git-commit-guide.mdc](git-commit-guide.mdc)** - Git 提交规范和 PR 流程
  - 描述性规则（需手动应用）
  - 包含：Conventional Commits、分支管理、PR 规范、提交前检查

## 规则类型说明

### alwaysApply（始终应用）
这些规则会自动应用于所有 AI 对话：
- `project-overview.mdc` - 确保 AI 始终了解项目整体结构

### globs（文件匹配）
这些规则根据文件路径自动应用：
- `*.py` → python-code-style.mdc
- `**/proxy.py` → proxy-architecture.mdc
- `tests/**/*.py` → testing-guidelines.mdc
- 等等...

### description（描述性规则）
这些规则需要手动引用或由 AI 根据上下文选择：
- `git-commit-guide.mdc` - 在讨论 Git 提交、PR 时应用

## 使用方法

### 对于开发者
1. 这些规则会自动被 Cursor AI 读取和应用
2. 编辑 `.py` 文件时，相关规则会自动激活
3. 可以在对话中引用特定规则文件

### 对于 AI 助手
1. 根据当前编辑的文件自动加载对应规则
2. `project-overview.mdc` 始终加载，提供项目全局视图
3. 在回答问题时参考相关规则文件中的规范

## 规则文件格式

每个 `.mdc` 文件包含：

```markdown
---
alwaysApply: true              # 可选：始终应用
globs: *.py,*.tsx              # 可选：文件匹配模式
description: 规则描述           # 可选：描述性规则
---

# 规则标题

规则内容（Markdown 格式）
```

## 引用其他文件

在规则中引用项目文件使用：
```markdown
[文件名](mdc:相对路径)
```

例如：
```markdown
[src/main.py](mdc:src/main.py)
[src/core/base_proxy.py](mdc:src/core/base_proxy.py)
```

## 维护指南

### 何时更新规则
- ✅ 新增核心模块或功能
- ✅ 修改项目架构或流程
- ✅ 更新编码规范或最佳实践
- ✅ 添加新的开发工具或框架

### 如何更新规则
1. 编辑对应的 `.mdc` 文件
2. 确保 frontmatter 格式正确
3. 使用清晰的 Markdown 格式
4. 添加代码示例和实际用例
5. 测试规则是否被 Cursor AI 正确识别

### 规则编写原则
- ✅ 简洁明了，重点突出
- ✅ 提供具体示例而非抽象描述
- ✅ 包含"应该做"和"不应该做"的对比
- ✅ 引用项目实际文件，保持一致性
- ✅ 定期审查和更新，避免过时信息

## 相关文档

项目文档：
- [README.md](../README.md) - 项目使用说明
- [CLAUDE.md](../CLAUDE.md) - Claude 客户端配置
- [GEMINI.md](../GEMINI.md) - Gemini 客户端配置
- [AGENTS.md](../AGENTS.md) - AI 代理配置

代码规范：
- `.gitignore` - Git 忽略规则
- `pyproject.toml` - Python 项目配置

## 贡献

如果您发现规则文件有错误或需要改进：
1. 直接编辑对应的 `.mdc` 文件
2. 遵循 [git-commit-guide.mdc](git-commit-guide.mdc) 提交规范
3. 在 PR 中说明修改原因

---

**最后更新**: 2025-10-15  
**Cursor Rules 版本**: 1.0.0

