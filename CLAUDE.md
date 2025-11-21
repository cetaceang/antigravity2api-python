# Antigravity to OpenAI API 转换项目

## 项目概述

将 Google Gemini API (Antigravity) 包装成 OpenAI 标准格式的 API 代理服务，使得任何支持 OpenAI API 的客户端都能无缝调用 Google 的 AI 模型。

## 核心判断

**值得做** - 这是一个标准的API网关/协议转换问题，技术上清晰可行。

## 架构设计

```
┌─────────────┐      ┌──────────────────┐      ┌─────────────┐
│ OpenAI SDK  │─────▶│  Python FastAPI  │─────▶│  Google API │
│             │      │  (协议转换层)      │      │             │
└─────────────┘      └──────────────────┘      └─────────────┘
                            │
                            ▼
                     ┌──────────────┐
                     │ 配置文件      │
                     │ - projects   │
                     │ - auth_keys  │
                     └──────────────┘
```

## 数据结构映射

### 请求格式转换

```
OpenAI格式                    Google Gemini格式
─────────────────────────────────────────────────
messages[{role,content}]  →  contents[{role,parts[{text}]}]
model: "gpt-4"            →  model: "gemini-2.5-flash" (透传)
stream: true              →  alt=sse (URL参数)
temperature: 0.7          →  generationConfig.temperature
max_tokens: 1000          →  generationConfig.maxOutputTokens
system消息                 →  systemInstruction
```

### 响应格式转换

#### 流式响应 (SSE)

**Google格式:**
```json
data: {"response":{"candidates":[{"content":{"role":"model","parts":[{"text":"根"}]}}],"modelVersion":"claude-sonnet-4-5"},"traceId":"xxx"}
```

**OpenAI格式:**
```json
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"claude-sonnet-4-5","choices":[{"index":0,"delta":{"content":"根"},"finish_reason":null}]}
```

#### 结束标记

**Google格式:**
```json
data: {"response":{"candidates":[{"content":{"role":"model","parts":[{"text":""}]},"finishReason":"STOP"}]}}
data: {"response":{"usageMetadata":{"promptTokenCount":18907,"candidatesTokenCount":171,"totalTokenCount":19078}}}
```

**OpenAI格式:**
```json
data: {"id":"chatcmpl-xxx","object":"chat.completion.chunk","created":1234567890,"model":"xxx","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

### 模型列表转换

**Google API端点:**
```
POST /v1internal:fetchAvailableModels
Body: {"project":"clear-parser-nsl36"}
```

**OpenAI API端点:**
```
GET /v1/models
```

## 认证流程

```
1. 启动时用 refresh_token 获取 access_token
2. OpenAI 请求��� Authorization: Bearer <自定义key>
3. 验证自定义key后，用 access_token 请求 Google API
4. access_token 过期时自动刷新
```

## 核心模块

### 1. Token管理模块 (`token_manager.py`)

**职责:**
- 管理 refresh_token → access_token 转换
- 自动刷新过期 token
- 支持多项目配置

**关键功能:**
```python
class TokenManager:
    async def get_access_token(project_id: str) -> str
    async def refresh_token(project_id: str) -> str
```

### 2. 认证模块 (`auth.py`)

**职责:**
- 验证 OpenAI 客户端的 API key
- 提供认证中间件

**关键功能:**
```python
async def validate_api_key(api_key: str) -> bool
async def get_api_key_from_header(authorization: str) -> str
```

### 3. 协议转换模块 (`converter.py`)

**职责:**
- OpenAI → Google 请求格式转换
- Google → OpenAI 响应格式转换
- SSE 流式数据转换

**关键功能:**
```python
class RequestConverter:
    def openai_to_google(openai_request: dict) -> dict
    def extract_system_instruction(messages: list) -> tuple

class ResponseConverter:
    async def google_sse_to_openai(google_stream) -> AsyncGenerator
    def format_openai_chunk(text: str, model: str) -> dict
```

### 4. API路由 (`main.py`)

**端点:**
- `POST /v1/chat/completions` - 聊天补全
- `GET /v1/models` - 模型列表
- `GET /health` - 健康检查

### 5. 配置管理 (`config.py`)

**配置项:**
```python
class ProjectConfig:
    project_id: str
    refresh_token: str

class Settings:
    projects: List[ProjectConfig]
    api_keys: List[str]
    google_api_base: str = "https://daily-cloudcode-pa.sandbox.googleapis.com"
```

## 文件结构

```
antifravity2api/
├── main.py              # FastAPI入口，路由定义
├── auth.py              # 认证管理，token刷新
├── converter.py         # 协议转换逻辑
├── config.py            # 配置管理
├── requirements.txt     # Python依赖
├── .env.example         # 配置模板
├── .env                 # 实际配置（不提交）
├── CLAUDE.md            # 本文档
└── README.md            # 使用说明
```

## 实现计划

### 第一阶段：核心功能（优先实现）

#### 1. 搭建 FastAPI 基础框架
- [x] 创建 main.py
- [ ] 实现基本路由结构
- [ ] 添加健康检查端点
- [ ] 配置 CORS

#### 2. 实现认证模块
- [ ] 创建 auth.py
- [ ] 实现 refresh_token → access_token 转换
- [ ] 实现 token 自动刷新机制
- [ ] 实现 API key 验证

#### 3. 实现 /v1/chat/completions
- [ ] 创建 converter.py
- [ ] 实现请求格式转换（OpenAI → Google）
- [ ] 实现流式响应转换（Google SSE → OpenAI SSE）
- [ ] 处理 system 消息提取
- [ ] 错误处理和异常映射

#### 4. 实现 /v1/models
- [ ] 调用 fetchAvailableModels 端点
- [ ] 响应格式转换（Google → OpenAI）
- [ ] 模型列表缓存

#### 5. 配置管理
- [ ] 创建 config.py
- [ ] 支持多项目配置
- [ ] 环境变量加载
- [ ] 创建 .env.example

#### 6. 依赖和文档
- [ ] 创建 requirements.txt
- [ ] 创建 README.md
- [ ] 添加使用示例

### 第二阶段：完善功能（后续优化）

- [ ] 非流式响应支持
- [ ] 完整的 usage 统计
- [ ] 请求日志记录
- [ ] 速率限制
- [ ] 更详细的错误处理
- [ ] 单元测试
- [ ] Docker 支持

## 技术栈

### 核心依赖

```txt
fastapi>=0.104.0        # Web框架
uvicorn>=0.24.0         # ASGI服务器
httpx>=0.25.0           # HTTP客户端（支持流式）
python-dotenv>=1.0.0    # 环境变量
pydantic>=2.5.0         # 数据验证
pydantic-settings>=2.1.0 # 配置管理
```

## 关键实现点

### 1. 流式转换

使用 async generator 逐块转换 SSE 数据：

```python
async def google_sse_to_openai(google_stream):
    async for line in google_stream:
        if line.startswith('data: '):
            google_data = json.loads(line[6:])
            openai_data = convert_chunk(google_data)
            yield f"data: {json.dumps(openai_data)}\n\n"
    yield "data: [DONE]\n\n"
```

### 2. Token 管理

后台任务定期刷新 token：

```python
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(token_refresh_task())
```

### 3. 多项目支持

配置文件支持多个 project_id 和 refresh_token：

```env
PROJECTS='[{"project_id":"project1","refresh_token":"token1"},{"project_id":"project2","refresh_token":"token2"}]'
API_KEYS='["key1","key2"]'
```

### 4. 错误映射

Google 错误码转 OpenAI 标准错误格式：

```python
ERROR_MAP = {
    "PERMISSION_DENIED": {"type": "invalid_request_error", "code": 403},
    "RESOURCE_EXHAUSTED": {"type": "rate_limit_error", "code": 429},
    "INVALID_ARGUMENT": {"type": "invalid_request_error", "code": 400},
}
```

## API 端点详细说明

### POST /v1/chat/completions

**请求示例:**
```json
{
  "model": "gemini-2.5-flash",
  "messages": [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ],
  "stream": true,
  "temperature": 0.7,
  "max_tokens": 1000
}
```

**转换为 Google 格式:**
```json
{
  "project": "clear-parser-nsl36",
  "requestId": "agent-xxx",
  "request": {
    "contents": [
      {"role": "user", "parts": [{"text": "Hello!"}]}
    ],
    "systemInstruction": {
      "role": "user",
      "parts": [{"text": "You are a helpful assistant."}]
    },
    "generationConfig": {
      "temperature": 0.7,
      "maxOutputTokens": 1000
    }
  },
  "model": "gemini-2.5-flash"
}
```

### GET /v1/models

**响应示例:**
```json
{
  "object": "list",
  "data": [
    {
      "id": "gemini-2.5-flash",
      "object": "model",
      "created": 1234567890,
      "owned_by": "google"
    },
    {
      "id": "claude-sonnet-4-5",
      "object": "model",
      "created": 1234567890,
      "owned_by": "anthropic"
    }
  ]
}
```

## 配置示例

### .env 文件

```env
# Google API 配置
GOOGLE_API_BASE=https://daily-cloudcode-pa.sandbox.googleapis.com

# 项目配置（JSON数组）
PROJECTS=[{"project_id":"clear-parser-nsl36","refresh_token":"your_refresh_token_here"}]

# API Keys（用于验证OpenAI客户端）
API_KEYS=["sk-custom-key-1","sk-custom-key-2"]

# 服务配置
HOST=0.0.0.0
PORT=8000
```

## 使用示例

### 启动服务

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入实际配置

# 启动服务
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 使用 OpenAI SDK 调用

```python
from openai import OpenAI

client = OpenAI(
    api_key="sk-custom-key-1",
    base_url="http://localhost:8000/v1"
)

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

## 注意事项

### 1. 消除特殊情况

- 不要为每个模型写特殊处理逻辑
- 统一的消息格式转换，不管是 GPT 还是 Claude
- 流式和非流式用同一套转换逻辑

### 2. 数据结构优先

- 先设计好 OpenAI ↔ Google 的数据映射
- 转换逻辑应该是纯函数，无副作用
- 避免在转换过程中修改原始数据

### 3. 向后兼容

- 不破坏 OpenAI SDK 的现有调用方式
- 完全透明的代理，客户端无感知
- 支持 OpenAI API 的所有标准参数

### 4. 实用主义

- 先实现核心的流式聊天功能
- 不要过度设计，不要添加不必要的功能
- 代码简洁，逻辑清晰，易于维护

## 已知限制

1. **模型名称不映射** - 客户端看到的模型名就是 Google 提供的原始名称
2. **仅支持流式** - 第一阶段只实现流式响应，非流式后续添加
3. **基础错误处理** - 第一阶段只做基本的错误映射
4. **无速率限制** - 依赖 Google API 的原生限制

## 后续优化方向

1. **性能优化**
   - 连接池管理
   - 响应缓存
   - 并发控制

2. **功能增强**
   - 支持更多 OpenAI 参数
   - 函数调用支持
   - 图片输入支持

3. **运维支持**
   - 监控和日志
   - 健康检查
   - 优雅关闭

4. **安全加固**
   - 请求签名验证
   - IP 白名单
   - 速率限制

---

**最后更新:** 2025-11-20
**版本:** 1.0
**状态:** 规划完成，准备实施
