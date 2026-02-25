# GitHub Copilot OpenAI API

一个轻量级且高效的桥接服务，将 GitHub Copilot 转换为与 OpenAI 兼容的 API 端点。本项目支持流式响应、多模型切换、工具调用以及思维链（Reasoning）展示，完美适配各种 OpenAI API 客户端。

> ⚠️ **风险提示**：本项目通过非官方方式调用 GitHub Copilot API，可能违反 GitHub 服务条款，存在账号被封禁的风险。**强烈建议使用 GitHub 小号订阅 GitHub Copilot 套餐后再使用本项目**，避免影响您的主账号。

本项目基于 [liuzhuogood/github-copilot-openai-api](https://github.com/liuzhuogood/github-copilot-openai-api) 进行二次开发，感谢原作者的开源贡献！🙏

**新增功能：**

- **图片识别支持**：支持多模态视觉模型，可发送图片进行分析
- **工具调用 (Function Calling)**：完整支持 OpenAI 风格的工具调用
- **Claude API 兼容**：新增 `/v1/messages` 端点，兼容 Claude Code 等客户端
- **Responses API 支持**：新增 `/v1/responses` 端点，支持 GPT-5 Codex 等新模型

---

## 📐 架构概览

```mermaid
flowchart TB
    subgraph 客户端
        A1[OpenAI 客户端<br/>Cherry Studio / Cursor]
        A2[Claude 客户端<br/>Claude Code]
        A3[其他客户端]
    end

    subgraph 本服务
        subgraph 路由层
            R1["/v1/chat/completions"]
            R2["/v1/messages"]
            R3["/v1/responses"]
            R4["/v1/models"]
            R5["/auth/device"]
        end

        subgraph 中间件
            M1[API 认证中间件]
        end

        subgraph 服务层
            S1[消息格式转换服务]
            S2[ChatAPI 客户端]
        end

        subgraph 认证模块
            AUTH1[EnvsAuth<br/>环境变量]
            AUTH2[HostsAuth<br/>hosts.json]
            AUTH3[DeviceAuth<br/>设备授权]
        end
    end

    subgraph GitHub Copilot API
        GH1["/chat/completions"]
        GH2["/responses"]
        GH3["Token API"]
    end

    A1 --> R1
    A2 --> R2
    A3 --> R3

    R1 --> M1
    R2 --> M1
    R3 --> M1

    M1 --> S1
    S1 --> S2

    S2 --> AUTH1
    S2 --> AUTH2
    S2 --> AUTH3

    AUTH1 -.-> GH3
    AUTH2 -.-> GH3
    AUTH3 --> R5
    R5 -.-> GH3

    S2 --> GH1
    S2 --> GH2
```

### 请求处理流程

```mermaid
sequenceDiagram
    participant Client as 客户端
    participant Server as FastAPI 服务
    participant Auth as 认证模块
    participant Converter as 消息转换器
    participant ChatAPI as ChatAPI
    participant Copilot as GitHub Copilot API

    Client->>Server: POST /v1/chat/completions
    Server->>Auth: 验证 API Key

    alt API Key 无效
        Auth-->>Server: 401 Unauthorized
        Server-->>Client: 认证失败
    end

    Server->>Auth: 获取 Copilot Token

    alt Token 不存在
        Auth->>Auth: 尝试多种认证方式
        Note over Auth: EnvsAuth → HostsAuth → DeviceAuth
    end

    Auth-->>Server: 返回 Token
    Server->>Converter: 规范化消息格式
    Converter-->>Server: 处理后的消息

    Server->>ChatAPI: 调用 Copilot API
    ChatAPI->>Copilot: 请求 /chat/completions

    alt 流式响应
        loop SSE 流
            Copilot-->>ChatAPI: data: {...}
            ChatAPI-->>Server: 转换格式
            Server-->>Client: data: {...}
        end
        Copilot-->>ChatAPI: data: [DONE]
        Server-->>Client: data: [DONE]
    else 非流式响应
        Copilot-->>ChatAPI: JSON 响应
        ChatAPI-->>Server: 转换格式
        Server-->>Client: JSON 响应
    end
```

---

## 📁 项目结构

```
github-copilot-openai-api/
├── server.py              # 应用入口
├── config.py              # 统一配置管理
├── exceptions.py          # 自定义异常类
├── api/
│   ├── chat_api.py        # Copilot API 客户端
│   └── chat_stream.py     # 流式/非流式处理入口
├── auth/
│   ├── __init__.py        # Auth 基类
│   ├── envs_auth.py       # 环境变量认证
│   ├── hosts_auth.py      # hosts.json 文件认证
│   └── device_auth.py     # 设备授权认证
├── middleware/
│   └── auth.py            # API 认证中间件
├── routes/
│   ├── admin.py           # /admin/* 管理路由（热重载）
│   ├── auth.py            # /auth/* 路由
│   ├── chat.py            # /v1/chat/completions 路由
│   ├── claude.py          # /v1/messages 路由
│   ├── responses.py       # /v1/responses 路由
│   ├── models.py          # /v1/models 路由
│   └── usage.py           # /usage 用量查询路由
├── services/
│   └── message_converter.py  # OpenAI/Claude 消息格式转换
├── utils/
│   └── retry.py           # 重试工具
├── templates/
│   └── auth.html          # 设备认证页面
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

---

## 🚀 快速开始 (Docker Compose)

1. **克隆并准备代码**：
   建议在 `/opt` 目录下进行部署：

   ```bash
   cd /opt
   git clone https://github.com/jett2025/github-copilot-openai-api.git
   cd github-copilot-openai-api
   ```

   _注意：如果目录已存在且需要强制覆盖本地更改，请执行：_

   ```bash
   git fetch --all && git reset --hard origin/main && git pull
   ```

2. **构建并启动服务**：

   ```bash
   docker compose up -d --build
   ```

3. **设置 API 密钥 (可选)**：
   在 `docker-compose.yml` 的 `environment` 下设置 `API_KEY`。

### 🔐 首次使用认证流程：

1. 访问：`http://你的服务器IP:43953/auth/device`
2. 页面会显示一个 8 位字符的激活码，点击按钮跳转到 GitHub 授权页面输入。
3. 授权成功后，服务将自动获取并保存 Copilot 令牌，即可开始使用。

> ⚠️ **注意**：每次使用 `docker compose up -d --build` 重新构建镜像后，需要重新进行认证流程。

---

## 🌟 特性

- **OpenAI API 兼容**：无缝对接 Cherry Studio, Cursor, Claude Code 等客户端
- **Claude API 兼容**：支持 `/v1/messages` 端点，兼容 Claude 原生客户端
- **Responses API 支持**：支持 `/v1/responses` 端点，适配 GPT-5 Codex 等新模型
- **图片识别支持**：支持多模态视觉模型，可发送图片进行分析
- **支持流式响应**：实时的流式文本输出体验
- **支持工具调用 (Function Calling)**：完整支持 OpenAI 风格的工具调用
- **支持思维链 (Reasoning)**：支持显式展示 o1/o3-mini/Claude 3.7 的思考过程
- **多模型支持**：支持 GPT-5.2, Claude 4.5, Gemini 3 等前沿模型
- **设备认证**：简单的网页输码授权流程
- **安全保障**：可选的 `API_KEY` 认证机制

---

## 🛠 技术栈

- **FastAPI**: 高性能异步 Web 框架
- **Python 3.12+**: 现代 Python 特性
- **Docker Compose**: 容器编排与部署
- **aiohttp**: 异步 HTTP 客户端
- **Jinja2**: 页面模板引擎

---

## 🔧 配置项

可以通过 `docker-compose.yml` 进行配置：

| 环境变量        | 说明                        | 默认值                          |
| --------------- | --------------------------- | ------------------------------- |
| `HOST`          | 服务器监听地址              | `0.0.0.0`                       |
| `PORT`          | 服务器内部端口              | `8000`                          |
| `API_KEY`       | API 访问身份验证密钥        | `github-copilot-openai-api-key` |
| `MODEL_MAPPING` | 自定义模型映射（JSON 格式） | 见下方默认映射                  |

### 模型映射配置

通过 `MODEL_MAPPING` 环境变量可以自定义模型映射，格式为 JSON 字符串：

```yaml
environment:
  - MODEL_MAPPING={"gpt-4o-mini":"gemini-3-pro-preview","claude-haiku-4-5-20251001":"gpt-5.3-codex","claude-sonnet-4-6":"gpt-5.3-codex"}
```

**默认映射：**

| 请求模型                   | 实际调用          |
| -------------------------- | ----------------- |
| gpt-o4-mini               | claude-opus-4.6   |
| gpt-4o-mini  | claude-opus-4.6  |

_注：设置 `MODEL_MAPPING` 后将完全覆盖默认映射，未映射的模型名将直接透传。_

---

## 🔌 Claude Code 接入配置

使用本服务接入 Claude Code，需要设置以下环境变量：

### Windows (PowerShell)

```powershell
$env:ANTHROPIC_BASE_URL = "http://你的服务器IP:43953"
$env:ANTHROPIC_AUTH_TOKEN = "docker-compose.yml environment 下设置的 API_KEY"
$env:ANTHROPIC_MODEL = "claude-opus-4.6"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL = "claude-opus-4.6"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL = "claude-sonnet-4.6"
$env:ANTHROPIC_SMALL_FAST_MODEL = "claude-haiku-4-5-20251001"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL = "claude-haiku-4-5-20251001"
$env:DISABLE_NON_ESSENTIAL_MODEL_CALLS = "1"
$env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = "1"
```

### macOS / Linux (Bash/Zsh)

```bash
export ANTHROPIC_BASE_URL="http://你的服务器IP:43953"
export ANTHROPIC_AUTH_TOKEN="docker-compose.yml environment 下设置的 API_KEY"
export ANTHROPIC_MODEL="claude-opus-4.6"
export ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-4.6"
export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-4.6"
export ANTHROPIC_SMALL_FAST_MODEL="claude-haiku-4-5-20251001"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="claude-haiku-4-5-20251001"
export DISABLE_NON_ESSENTIAL_MODEL_CALLS="1"
export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1"
```

> **提示**：可将上述配置添加到 `~/.bashrc`、`~/.zshrc` 或 PowerShell 配置文件中以实现持久化。

---

## 📚 API 端点

| 端点                        | 说明                                        |
| --------------------------- | ------------------------------------------- |
| `POST /v1/chat/completions` | OpenAI Chat Completions API 兼容            |
| `POST /v1/messages`         | Claude API 兼容                             |
| `POST /v1/responses`        | OpenAI Responses API 兼容（GPT-5 Codex 等） |
| `GET /v1/models`            | 获取支持的模型列表                          |
| `GET /auth/device`          | 设备认证页面                                |
| `GET /usage`                | 查询用量                                    |
| `GET /admin/mapping`        | 查看/管理模型映射（热重载）                 |

---

## 🔥 模型映射热重载

支持在不重启服务的情况下动态修改模型映射，通过浏览器直接访问 URL 即可操作。

### API 端点

| 操作     | URL                                                            | 说明                                       |
| -------- | -------------------------------------------------------------- | ------------------------------------------ |
| 查看映射 | `/admin/mapping?api_key=<API_KEY>`                             | 返回当前生效的映射                         |
| 添加映射 | `/admin/mapping/set?api_key=<API_KEY>&from=<源模型>&to=<目标>` | 添加或更新单个映射                         |
| 删除映射 | `/admin/mapping/del?api_key=<API_KEY>&from=<源模型>`           | 删除单个映射                               |
| 重置映射 | `/admin/mapping/reset?api_key=<API_KEY>`                       | 恢复为初始配置（优先环境变量，否则代码默认值） |

### 示例

假设服务地址为 `http://localhost:43953`，API Key 为 `github-copilot-openai-api-key`：

```bash
# 查看当前映射
curl "http://localhost:43953/admin/mapping?api_key=github-copilot-openai-api-key"

# 添加映射：gpt-4 -> claude-sonnet-4.5
curl "http://localhost:43953/admin/mapping/set?api_key=github-copilot-openai-api-key&from=gpt-4&to=claude-sonnet-4.5"

# 删除映射
curl "http://localhost:43953/admin/mapping/del?api_key=github-copilot-openai-api-key&from=gpt-4"

# 重置为初始配置（环境变量或代码默认值）
curl "http://localhost:43953/admin/mapping/reset?api_key=github-copilot-openai-api-key"
```


### 使用示例

```bash
curl http://localhost:43953/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer github-copilot-openai-api-key" \
  -d '{"model": "claude-haiku-4.5", "messages": [{"role": "user", "content": "你好"}], "stream": true}'
```

---

## 🎯 支持的模型

**直接支持：**

- gpt-5.2 / gpt-5.2-codex / gpt-5.3-codex / gpt-5.1-codex-max
- claude-sonnet-4.5 / claude-sonnet-4.6 / claude-opus-4.5 / claude-opus-4.6 / claude-haiku-4.5
- gemini-3-pro-preview / gemini-3-flash-preview / gemini-3.1-pro-preview

_注：模型映射配置请参考上方「配置项」章节。_

---

## 📄 开源协议

本项目采用 MIT 协议开源。
