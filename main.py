"""FastAPI 主应用 - OpenAI 兼容的 API 网关"""
import json
import httpx
import logging
from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from config import settings
from converter import RequestConverter, ResponseConverter
from token_manager import get_token_manager, ProjectToken

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


def validate_api_key(authorization: Optional[str]) -> bool:
    """验证 API Key"""
    if not authorization:
        return False

    # 提取 Bearer token
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
            project.project_id
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
        # 流式响应
        return StreamingResponse(
            stream_google_to_openai(
                url=url,
                headers=headers,
                google_request=google_request,
                model=openai_request.get("model", "unknown"),
                project=project
            ),
            media_type="text/event-stream"
        )
    else:
        # 非流式响应
        return await handle_non_stream_request(
            url=url,
            headers=headers,
            google_request=google_request,
            model=openai_request.get("model", "unknown"),
            project=project
        )


async def handle_non_stream_request(
    url: str,
    headers: dict,
    google_request: dict,
    model: str,
    project: ProjectToken
):
    """
    非流式请求处理：Google → OpenAI
    """
    token_manager = get_token_manager()

    async with httpx.AsyncClient(timeout=120.0) as client:
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
                model
            )

            return openai_response

        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Request timeout")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


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
                        if retry_response.status_code != 200:
                            error_body = await retry_response.aread()
                            logger.error(f"Google API error {retry_response.status_code} (retry)")
                            logger.error(f"Error response: {error_body.decode('utf-8', errors='ignore')}")
                            yield f"data: {{\"error\": \"Google API error: {retry_response.status_code}\"}}\n\n"
                            return

                        async for chunk in ResponseConverter.google_sse_to_openai(
                            retry_response.aiter_lines(),
                            model
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
                    model
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
