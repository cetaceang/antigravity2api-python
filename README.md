# Antigravity to OpenAI API Gateway

将 Google Gemini API (Antigravity) 包装成 OpenAI 标准格式的 API 代理服务。

## 功能特性

- 🔄 **OpenAI 兼容 API**：完全兼容 OpenAI SDK，无缝切换
- 🎨 **图片生成**：支持 `-image` 后缀模型进行图像生成
- 🧠 **思考模式**：支持 `thinking` 模型的推理过程展示
- 🔧 **Function Calling**：完整支持多轮工具调用
- 🔑 **多项目管理**：Round Robin 负载均衡，自动 Token 轮换
- 🛡️ **自动刷新**：Token 过期自动刷新，失败自动禁用
- 📊 **管理面板**：Web UI 管理 Token，查看配额，OAuth 授权
- 🌐 **Gemini 原生 API**：同时支持 Gemini 原生格式透传

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 Token 文件

```bash
cp data/tokens.json.example data/tokens.json
```

编辑 `data/tokens.json`，填入你的 OAuth 配置和 refresh_token：

```json
{
  "oauth_config": {
    "client_id": "your_client_id",
    "client_secret": "your_client_secret",
    "token_url": "https://oauth2.googleapis.com/token"
  },
  "projects": [
    {
      "project_id": "your-project-id",
      "refresh_token": "your_refresh_token_here",
      "access_token": null,
      "expires_at": null,
      "enabled": true,
      "disabled_reason": null
    }
  ]
}
```

> 💡 **提示**：可以使用 `python scripts/oauth_server.py` 工具快速获取 refresh_token，详见 [Token 管理](#token-管理) 章节。

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env` 文件，填入 API Keys：

```env
# API Keys（用于验证OpenAI客户端）
API_KEYS=["sk-custom-key-1","sk-custom-key-2"]

# 服务配置（可选）
HOST=0.0.0.0
PORT=8000

# Token 轮换配置（可选）
TOKEN_ROTATION_COUNT=3  # 每个 token 使用多少次后切换，默认 3
```

### 4. 启动服务

```bash
python -m src.main
```

或使用 uvicorn：

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后会自动：
- 从 `data/tokens.json` 加载配置
- 使用 refresh_token 自动获取 access_token
- Token 过期时自动刷新
- 多项目 Round Robin 负载均衡

## Docker 部署

### 使用 docker-compose（推荐）

1. 准备配置文件：

```bash
# 创建 data 目录
mkdir -p data

# 配置 Token 文件
cp data/tokens.json.example data/tokens.json
# 编辑 data/tokens.json 填入配置

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Keys
```

2. 启动服务：

```bash
docker-compose up -d
```

3. 查看日志：

```bash
docker-compose logs -f
```

4. 停止服务：

```bash
docker-compose down
```

### 使用 Docker 命令

```bash
# 构建镜像
docker build -t antigravity2api .

# 运行容器
docker run -d \
  --name antigravity2api \
  -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  --env-file .env \
  antigravity2api
```

## 使用示例

### 使用 OpenAI SDK

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-custom-key-1",
    base_url="http://localhost:8000/v1"
)

# 流式聊天
response = client.chat.completions.create(
    model="gemini-2.5-flash",
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"}
    ],
    stream=True
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="")
```

### 图片生成（-image 模型）

当 `model` 以 `-image` 结尾时，请求会自动切换为上游 `image_gen`，返回内容为 Markdown 图片链接（图片保存到本地 `data/images/`，并通过 `/images/*` 访问）。

```python
response = client.chat.completions.create(
    model="gemini-3-pro-image",
    messages=[{"role": "user", "content": "Draw a cute cat"}],
    stream=False,
)

print(response.choices[0].message.content)
```

Docker 部署时默认 `WORKDIR=/app`，因此 `IMAGE_DIR=data/images` 会落到 `/app/data/images`；配合 `docker-compose.yml` 的 `./data:/app/data` 挂载即可在宿主机 `./data/images/` 持久化。

### 使用 curl

```bash
# 聊天补全
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-custom-key-1" \
  -d '{
    "model": "gemini-2.5-flash",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": true
  }'

# 获取模型列表
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer sk-custom-key-1"
```

## API 端点

### POST /v1/chat/completions

OpenAI 兼容的聊天补全端点。

**支持的参数：**
- `model` - 模型名称（透传给 Google API）
- `messages` - 消息列表
- `stream` - 是否流式响应（默认 true）
- `temperature` - 温度参数
- `max_tokens` - 最大 token 数
- `top_p` - Top-p 采样

#### 思考配置策略
- 服务端会在上游 `generationConfig.thinkingConfig` 中写入 `includeThoughts` 与 `thinkingBudget`。
- 启用条件：`model` 包含 `-thinking`，或为 `gemini-2.5-pro` / `gemini-3-pro-*` / `rev19-uic3-1p` / `gpt-oss-120b-medium`。
- `thinkingBudget` 优先使用请求参数 `thinking_budget`（整数）；其次使用 `reasoning_effort`（low=1024, medium=16000, high=32000）；否则默认 1024；未启用时为 0。
- 当上游模型返回 `{"thought": true, "text": "..."}` 片段时，会在 OpenAI 响应中填充 `reasoning_content` 字段（拼接后的纯文本），方便客户端分别展示思考与正文。

#### 多轮工具调用（Function calling）与 thoughtSignature
- 上游在思考/工具调用链路中会校验 `thoughtSignature`；缺失时，多轮 tool calling 可能无法继续。
- 服务端会在 OpenAI 响应中透传 `thoughtSignature` 与 `tool_calls[].thoughtSignature`（camelCase），并按 `sessionId + model` 做进程内缓存，供下一轮请求缺字段时兜底补齐。
- 兜底顺序：消息自带签名 → 缓存命中 → 内置常量（仅用于首轮/缺缓存场景）。
- `tool_call_id` 贯通链路：OpenAI `tool_calls[].id` → 上游 `functionCall.id` → OpenAI `role=tool.tool_call_id` → 上游 `functionResponse.id`。

#### 图片生成（-image 模型）
- 当 `model` 以 `-image` 结尾时：上游强制走非流式 `generateContent`，请求体写入 `requestType=image_gen`。
- 若客户端请求 `stream=true`：服务端会用 SSE 心跳维持连接，并在拿到上游结果后一次性返回包含图片 URL 的内容。

### GET /v1/models

获取可用模型列表。

### Gemini 原生 API 端点

支持 Gemini 原生格式透传，兼容 Gemini SDK：

```bash
# 非流式
POST /v1/models/{model}:generateContent
POST /v1beta/models/{model}:generateContent

# 流式
POST /v1/models/{model}:streamGenerateContent
POST /v1beta/models/{model}:streamGenerateContent
```

**认证方式**（三选一）：
- `Authorization: Bearer <key>`
- `X-Goog-Api-Key: <key>`
- 查询参数 `?key=<key>`

### GET /health

健康检查端点。

## 管理面板

提供 Web UI 管理界面，支持：

- 📋 查看所有项目状态（启用/禁用、Token 过期时间）
- 🔄 切换项目启用状态
- ✏️ 编辑项目 ID
- 🗑️ 删除项目
- 📊 查看模型配额（Claude / Gemini）
- 🔑 在线 OAuth 授权添加新项目

### 访问管理面板

```
http://localhost:8000/admin/
```

**登录密码**：使用 `.env` 中配置的任意 `API_KEYS` 值登录。

### 添加新项目

1. 登录管理面板
2. 点击「添加新项目」
3. 点击「点击这里进行 Google 授权」
4. 完成 Google 账号授权
5. 自动返回并添加项目

## 项目结构

```
antigravity2api-python/
├── src/                      # 源代码目录
│   ├── __init__.py          # 包初始化
│   ├── main.py              # FastAPI 主应用
│   ├── config.py            # 配置管理
│   ├── converter.py         # OpenAI ↔ Google 协议转换
│   ├── gemini_converter.py  # Gemini 原生 API 转换
│   ├── token_manager.py     # Token 管理与自动刷新
│   ├── image_storage.py     # 图片存储管理
│   ├── signature_cache.py   # thoughtSignature 缓存
│   ├── tool_name_cache.py   # 工具名称缓存
│   └── admin/               # 管理面板
│       ├── __init__.py
│       ├── routes.py        # 管理面板路由
│       └── templates/       # HTML 模板
├── scripts/                  # 工具脚本
│   └── oauth_server.py      # OAuth 服务器工具
├── tests/                    # 测试文件
│   ├── test_function_calling.py
│   ├── test_image_support.py
│   └── test_tool_calling_conversion.py
├── docs/                     # 文档
│   └── CLAUDE.md            # 技术方案文档
├── data/                     # 数据目录（运行时创建）
│   ├── tokens.json          # Token 配置文件
│   └── images/              # 生成的图片
├── requirements.txt          # Python 依赖
├── .env.example              # 配置模板
├── .env                      # 实际配置（不提交）
├── Dockerfile                # Docker 镜像定义
├── docker-compose.yml        # Docker Compose 配置
└── README.md                 # 本文档
```

## Token 管理

### 使用 OAuth 工具获取 Token

项目提供了 OAuth 授权工具，可以快速获取 refresh_token：

**使用步骤：**

1. **在项目根目录运行**（重要！）：
```bash
cd d:\桌面\antigravity2api-python
python scripts/oauth_server.py
```

2. 脚本会自动：
   - 启动本地 OAuth 回调服务器
   - 打开浏览器进行 Google 授权
   - 显示授权链接（如果浏览器未自动打开，手动复制链接）

3. 在浏览器中完成授权后：
   - Token 自动保存到 `data/tokens.json`
   - 生成随机的 `project_id`
   - 新增的项目默认为启用状态

**注意事项：**
- ⚠️ **必须在项目根目录运行**，否则文件会保存到错误位置
- 如果已有 `data/tokens.json`，新 token 会追加到 `projects` 数组
- 每次运行会添加一个新项目，支持多项目配置

### 自动刷新机制

- 使用 OAuth2 refresh_token 自动获取和刷新 access_token
- Token 提前 5 分钟自动刷新，避免过期
- 遇到 401/403 错误时自动刷新并重试
- 更新后的 token 自动保存到 `data/tokens.json`

### Token 禁用机制

- 当 token 刷新后仍然失败（401/403）时，自动永久禁用该项目
- 禁用状态保存到 `data/tokens.json`，重启后依然生效
- Round Robin 轮询会自动跳过已禁用的项目
- 记录禁用原因（`disabled_reason`），便于排查问题

### Token 轮换策略

- 每个 token 使用指定次数后自动切换到下一个 token
- 默认使用 3 次后切换，可通过环境变量 `TOKEN_ROTATION_COUNT` 配置
- 避免单个 token 被过度使用，分散请求负载
- 日志显示当前使用次数（例如：`使用次数: 2/3`）

**配置示例：**
```env
# 每个 token 使用 5 次后切换
TOKEN_ROTATION_COUNT=5
```

### 多项目支持

- 支持配置多个项目的 refresh_token
- Round Robin 负载均衡，自动轮询使用
- 每个项目独立管理 token 生命周期
- 并发请求时避免重复刷新（使用 asyncio.Lock）

### 配置示例

```json
{
  "oauth_config": {
    "client_id": "your_client_id",
    "client_secret": "your_client_secret",
    "token_url": "https://oauth2.googleapis.com/token"
  },
  "projects": [
    {
      "project_id": "project-1",
      "refresh_token": "refresh_token_1",
      "access_token": null,
      "expires_at": null,
      "enabled": true,
      "disabled_reason": null
    },
    {
      "project_id": "project-2",
      "refresh_token": "refresh_token_2",
      "access_token": null,
      "expires_at": null,
      "enabled": true,
      "disabled_reason": null
    }
  ]
}
```

**字段说明：**
- `enabled`: 项目是否启用（默认 `true`）
- `disabled_reason`: 禁用原因（禁用时自动记录）

## 注意事项

1. **Token 安全**：`data/tokens.json` 包含敏感信息，不要提交到版本控制
2. **模型名称透传**：不做模型名称映射，客户端看到的就是 Google 提供的原始模型名
3. **管理面板安全**：生产环境建议通过反向代理限制 `/admin` 路径的访问

## 环境变量参考

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `API_KEYS` | `["sk-test-key"]` | API 密钥列表（JSON 数组） |
| `HOST` | `0.0.0.0` | 服务监听地址 |
| `PORT` | `8000` | 服务监听端口 |
| `TOKEN_ROTATION_COUNT` | `3` | Token 轮换次数 |
| `IMAGE_DIR` | `data/images` | 图片存储目录 |
| `IMAGE_BASE_URL` | ` ` | 图片 URL 前缀（空则使用请求域名） |
| `MAX_IMAGES` | `10` | 最大图片保留数量 |
| `SSE_HEARTBEAT_INTERVAL` | `15` | SSE 心跳间隔（秒） |

## 后续计划

- [ ] 完整的 usage 统计
- [ ] 请求日志记录与分析
- [ ] 管理面板认证增强（OAuth / 2FA）

## License

MIT
