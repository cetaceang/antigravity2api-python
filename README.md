# Antigravity to OpenAI API Gateway

将 Google Gemini API (Antigravity) 包装成 OpenAI 标准格式的 API 代理服务。

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
      "expires_at": null
    }
  ]
}
```

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
```

### 4. 启动服务

```bash
python main.py
```

或使用 uvicorn：

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

服务启动后会自动：
- 从 `data/tokens.json` 加载配置
- 使用 refresh_token 自动获取 access_token
- Token 过期时自动刷新
- 多项目 Round Robin 负载均衡

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

### GET /v1/models

获取可用模型列表。

### GET /health

健康检查端点。

## 项目结构

```
antifravity2api/
├── main.py              # FastAPI 主应用
├── config.py            # 配置管理
├── converter.py         # 协议转换逻辑
├── requirements.txt     # Python 依赖
├── .env.example         # 配置模板
├── .env                 # 实际配置（不提交）
├── CLAUDE.md            # 技术方案文档
└── README.md            # 本文档
```

## Token 管理

### 自动刷新机制

- 使用 OAuth2 refresh_token 自动获取和刷新 access_token
- Token 提前 5 分钟自动刷新，避免过期
- 遇到 401/403 错误时自动刷新并重试
- 更新后的 token 自动保存到 `data/tokens.json`

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
      "expires_at": null
    },
    {
      "project_id": "project-2",
      "refresh_token": "refresh_token_2",
      "access_token": null,
      "expires_at": null
    }
  ]
}
```

## 注意事项

1. **Token 安全**：`data/tokens.json` 包含敏感信息，不要提交到版本控制
2. **仅支持流式响应**：非流式响应暂未实现
3. **模型名称透传**：不做模型名称映射，客户端看到的就是 Google 提供的原始模型名

## 后续计划

- [ ] 支持非流式响应
- [ ] 完整的 usage 统计
- [ ] 请求日志记录
- [ ] 错误处理优化

## License

MIT
