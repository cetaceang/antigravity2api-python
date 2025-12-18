"""FastAPI 主应用 - OpenAI 兼容的 API 网关"""
import asyncio
import json
import httpx
import logging
from contextlib import suppress
from pathlib import Path
from fastapi import FastAPI, HTTPException, Header, Request, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import Optional

from src.config import settings
from src.converter import RequestConverter, ResponseConverter
from src.gemini_converter import (
    build_gemini_request,
    proxy_gemini_non_stream,
    stream_gemini_raw
)
from src.token_manager import get_token_manager, ProjectToken
from src.admin.routes import admin_router

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Antigravity to OpenAI API Gateway",
    description="将 Google Gemini API 包装成 OpenAI 标准格式",
    version="1.0.0"
)

# 配置 CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Image generation helpers.
IMAGE_DIR = Path(getattr(settings, "image_dir", "data/images") or "data/images")
MAX_IMAGES = int(getattr(settings, "max_images", 10) or 10)
SSE_HEARTBEAT_INTERVAL = float(getattr(settings, "sse_heartbeat_interval", 15.0) or 15.0)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/images", StaticFiles(directory=str(IMAGE_DIR)), name="images")

# 注册管理面板路由
app.include_router(admin_router, prefix="/admin")


def validate_api_key(
    authorization: Optional[str],
    x_goog_api_key: Optional[str] = None,
    allow_x_goog: bool = False,
    query_key: Optional[str] = None,
    allow_query: bool = False
) -> bool:
    """
    验证 API Key。
    - 默认仅支持 Authorization: Bearer <key>
    - 若 allow_x_goog=True，则同时接受 X-Goog-Api-Key 头
    - 若 allow_query=True，则接受查询参数 key=<key>
    """
    if allow_query and query_key:
        return settings.validate_api_key(query_key)

    if allow_x_goog and x_goog_api_key:
        return settings.validate_api_key(x_goog_api_key)

    if not authorization:
        return False

    if not authorization.startswith("Bearer "):
        return False

    api_key = authorization[7:]  # 去掉 "Bearer " 前缀
    return settings.validate_api_key(api_key)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "antigravity-to-openai"}


@app.post("/v1/chat/completions")
async def chat_completions(
    request: Request,
    authorization: Optional[str] = Header(None)
):
    """
    OpenAI 兼容的聊天补全端点

    将 OpenAI 格式的请求转换为 Google Gemini 格式并代理
    """
    # 验证 API Key
    if not validate_api_key(authorization):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 解析请求体
    try:
        openai_request = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    model_name = openai_request.get("model", "unknown")
    is_image_model = RequestConverter.is_image_model(model_name)
    configured_base_url = (getattr(settings, "image_base_url", "") or "").strip()
    image_base_url = configured_base_url or str(request.base_url).rstrip("/")

    # 使用 TokenManager 获取项目（Round Robin）
    token_manager = get_token_manager()
    project = token_manager.get_next_project()

    # 确保 token 有效
    try:
        access_token = await token_manager.get_access_token(project)
    except Exception as e:
        logger.error(f"Failed to get access token: {e}")
        raise HTTPException(status_code=500, detail="Failed to get access token")

    # 转换请求格式
    try:
        google_request, url_suffix = RequestConverter.openai_to_google(
            openai_request,
            project.project_id,
            session_id=getattr(project, "session_id", None),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request conversion failed: {str(e)}")

    # 构建完整 URL
    url = f"{settings.google_api_base}{url_suffix}"

    # 构建请求头（模拟 antigravity 客户端）
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "antigravity/1.11.3 windows/amd64"
    }

    # 判断是否流式响应
    is_stream = openai_request.get("stream", False)

    if is_stream:
        if is_image_model:
            return StreamingResponse(
                stream_image_to_openai(
                    url=url,
                    headers=headers,
                    google_request=google_request,
                    model=model_name,
                    project=project,
                    image_base_url=image_base_url,
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
            )
        return StreamingResponse(
            stream_google_to_openai(
                url=url,
                headers=headers,
                google_request=google_request,
                model=model_name,
                project=project,
            ),
            media_type="text/event-stream",
        )
    else:
        # 非流式响应
        return await handle_non_stream_request(
            url=url,
            headers=headers,
            google_request=google_request,
            model=model_name,
            project=project,
            image_base_url=image_base_url,
        )


@app.post("/v1/models/{model}:generateContent")
@app.post("/v1beta/models/{model}:generateContent")
async def gemini_generate_content(
    model: str,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
    key: Optional[str] = Query(None)
):
    """
    Gemini 原生非流式 generateContent 入口，透传标准 Gemini 请求并返回原生响应。
    """
    if not validate_api_key(authorization, x_goog_api_key, allow_x_goog=True, query_key=key, allow_query=True):
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    token_manager = get_token_manager()
    project = token_manager.get_next_project()

    try:
        google_request = build_gemini_request(model, body, project)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request build failed: {str(e)}")

    return await proxy_gemini_non_stream(google_request, project)


@app.post("/v1/models/{model}:streamGenerateContent")
@app.post("/v1beta/models/{model}:streamGenerateContent")
async def gemini_stream_generate_content(
    model: str,
    request: Request,
    authorization: Optional[str] = Header(None),
    x_goog_api_key: Optional[str] = Header(None, alias="x-goog-api-key"),
    key: Optional[str] = Query(None)
):
    """
    Gemini 原生流式 generateContent 入口，透传标准 Gemini 请求并返回原始 SSE。
    """
    if not validate_api_key(authorization, x_goog_api_key, allow_x_goog=True, query_key=key, allow_query=True):
        raise HTTPException(status_code=401, detail="Invalid API key")

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {str(e)}")

    token_manager = get_token_manager()
    project = token_manager.get_next_project()

    try:
        google_request = build_gemini_request(model, body, project)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Request build failed: {str(e)}")

    return StreamingResponse(
        stream_gemini_raw(google_request, project),
        media_type="text/event-stream"
    )


async def handle_non_stream_request(
    url: str,
    headers: dict,
    google_request: dict,
    model: str,
    project: ProjectToken,
    image_base_url: str,
):
    """
    非流式请求处理：Google → OpenAI
    """
    token_manager = get_token_manager()

    timeout = 300.0 if (isinstance(google_request, dict) and google_request.get("requestType") == "image_gen") else 120.0

    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            # 记录请求详情
            logger.debug(f"Sending request to Google API")
            logger.debug(f"URL: {url}")
            logger.debug(f"Request body: {json.dumps(google_request, indent=2, ensure_ascii=False)}")

            response = await client.post(url, headers=headers, json=google_request)

            # 检查响应状态
            if response.status_code in (401, 403):
                # Token 失效，刷新后重试
                logger.warning(f"Auth error {response.status_code}, refreshing token for {project.project_id}")
                new_token = await token_manager.handle_auth_error(project)
                headers["Authorization"] = f"Bearer {new_token}"

                # 重试请求
                response = await client.post(url, headers=headers, json=google_request)

                # 如果重试后仍然是 401/403，禁用该项目
                if response.status_code in (401, 403):
                    token_manager.disable_project(
                        project,
                        f"Auth failed after token refresh: {response.status_code}"
                    )

            if response.status_code != 200:
                error_body = response.text
                logger.error(f"Google API error {response.status_code}")
                logger.error(f"Error response: {error_body}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Google API error: {error_body}"
                )

            google_response = response.json()

            # 转换为 OpenAI 格式
            openai_response = ResponseConverter.google_non_stream_to_openai(
                google_response,
                model,
                session_id=getattr(project, "session_id", None),
                image_base_url=image_base_url,
                image_dir=str(IMAGE_DIR),
                max_images=MAX_IMAGES,
            )

            return openai_response

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


async def stream_image_to_openai(
    url: str,
    headers: dict,
    google_request: dict,
    model: str,
    project: ProjectToken,
    image_base_url: str,
):
    """
    Wrap a non-stream image generation upstream response into OpenAI SSE chunks.
    """
    heartbeat = SSE_HEARTBEAT_INTERVAL
    try:
        heartbeat = float(heartbeat)
    except Exception:
        heartbeat = 15.0
    if heartbeat <= 0:
        heartbeat = 15.0

    task = asyncio.create_task(
        handle_non_stream_request(
            url=url,
            headers=headers,
            google_request=google_request,
            model=model,
            project=project,
            image_base_url=image_base_url,
        )
    )

    try:
        while True:
            done, _pending = await asyncio.wait({task}, timeout=heartbeat)
            if task in done:
                openai_response = task.result()

                request_id = openai_response.get("id")
                created = openai_response.get("created")
                usage = openai_response.get("usage")

                content = ""
                finish_reason = "stop"
                choices = openai_response.get("choices") or []
                if choices:
                    finish_reason = choices[0].get("finish_reason") or "stop"
                    message = choices[0].get("message") or {}
                    content = message.get("content") or ""

                yield "data: " + json.dumps(
                    {
                        "id": request_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": model,
                        "choices": [
                            {
                                "index": 0,
                                "delta": {"content": content},
                                "finish_reason": None,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ) + "\n\n"

                final_chunk = {
                    "id": request_id,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish_reason,
                        }
                    ],
                }
                if usage is not None:
                    final_chunk["usage"] = usage

                yield "data: " + json.dumps(final_chunk, ensure_ascii=False) + "\n\n"
                yield "data: [DONE]\n\n"
                return

            yield ": heartbeat\n\n"

    except asyncio.CancelledError:
        task.cancel()
        with suppress(Exception):
            await task
        raise
    except Exception as exc:
        task.cancel()
        with suppress(Exception):
            await task
        detail = getattr(exc, "detail", None) or str(exc)
        yield "data: " + json.dumps({"error": detail}, ensure_ascii=False) + "\n\n"
        yield "data: [DONE]\n\n"
        return


async def stream_google_to_openai(
    url: str,
    headers: dict,
    google_request: dict,
    model: str,
    project: ProjectToken
):
    """
    流式代理：Google SSE → OpenAI SSE
    """
    token_manager = get_token_manager()

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            # 记录请求详情
            logger.debug(f"Sending streaming request to Google API")
            logger.debug(f"URL: {url}")
            logger.debug(f"Request body: {json.dumps(google_request, indent=2, ensure_ascii=False)}")

            async with client.stream(
                "POST",
                url,
                headers=headers,
                json=google_request
            ) as response:
                # 检查响应状态
                if response.status_code in (401, 403):
                    # Token 失效，刷新后重试
                    logger.warning(f"Auth error {response.status_code}, refreshing token for {project.project_id}")
                    new_token = await token_manager.handle_auth_error(project)
                    headers["Authorization"] = f"Bearer {new_token}"

                    # 重试请求
                    async with client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json=google_request
                    ) as retry_response:
                        # 如果重试后仍然是 401/403，禁用该项目
                        if retry_response.status_code in (401, 403):
                            token_manager.disable_project(
                                project,
                                f"Auth failed after token refresh: {retry_response.status_code}"
                            )
                            error_body = await retry_response.aread()
                            logger.error(f"Google API error {retry_response.status_code} (retry)")
                            logger.error(f"Error response: {error_body.decode('utf-8', errors='ignore')}")
                            yield f"data: {{\"error\": \"Auth failed, project disabled\"}}\n\n"
                            return

                        if retry_response.status_code != 200:
                            error_body = await retry_response.aread()
                            logger.error(f"Google API error {retry_response.status_code} (retry)")
                            logger.error(f"Error response: {error_body.decode('utf-8', errors='ignore')}")
                            yield f"data: {{\"error\": \"Google API error: {retry_response.status_code}\"}}\n\n"
                            return

                        async for chunk in ResponseConverter.google_sse_to_openai(
                            retry_response.aiter_lines(),
                            model,
                            session_id=getattr(project, "session_id", None),
                        ):
                            yield chunk
                    return

                if response.status_code != 200:
                    error_body = await response.aread()
                    logger.error(f"Google API error {response.status_code}")
                    logger.error(f"Error response: {error_body.decode('utf-8', errors='ignore')}")
                    yield f"data: {{\"error\": \"Google API error: {response.status_code}\"}}\n\n"
                    return

                # 转换并流式输出
                async for chunk in ResponseConverter.google_sse_to_openai(
                    response.aiter_lines(),
                    model,
                    session_id=getattr(project, "session_id", None),
                ):
                    yield chunk

        except httpx.TimeoutException:
            yield f"data: {{\"error\": \"Request timeout\"}}\n\n"
        except Exception as e:
            yield f"data: {{\"error\": \"Stream error: {str(e)}\"}}\n\n"


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(None)):
    """
    OpenAI 兼容的模型列表端点

    从 Google API 获取可用模型列表并转换为 OpenAI 格式
    """
    # 验证 API Key
    if not validate_api_key(authorization):
        raise HTTPException(status_code=401, detail="Invalid API key")

    # 使用 TokenManager 获取项目
    token_manager = get_token_manager()
    project = token_manager.get_next_project()

    # 确保 token 有效
    try:
        access_token = await token_manager.get_access_token(project)
    except Exception as e:
        logger.error(f"Failed to get access token: {e}")
        raise HTTPException(status_code=500, detail="Failed to get access token")

    # 构建请求
    url = f"{settings.google_api_base}/v1internal:fetchAvailableModels"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "antigravity/1.11.3 windows/amd64"
    }
    body = {"project": project.project_id}

    # 请求 Google API
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(url, headers=headers, json=body)

            if response.status_code in (401, 403):
                # Token 失效，刷新后重试
                logger.warning(f"Auth error {response.status_code}, refreshing token for {project.project_id}")
                access_token = await token_manager.handle_auth_error(project)
                headers["Authorization"] = f"Bearer {access_token}"
                response = await client.post(url, headers=headers, json=body)

                # 如果重试后仍然是 401/403，禁用该项目
                if response.status_code in (401, 403):
                    token_manager.disable_project(
                        project,
                        f"Auth failed after token refresh: {response.status_code}"
                    )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Google API error: {response.text}"
                )

            google_response = response.json()

            # 转换为 OpenAI 格式
            openai_response = ResponseConverter.google_models_to_openai(google_response)

            return openai_response

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.host, port=settings.port)
