import json
import uuid
import logging
from typing import Dict, Any, AsyncIterator

import httpx
from fastapi import HTTPException

from src.config import settings
from src.token_manager import get_token_manager, ProjectToken


logger = logging.getLogger(__name__)

DEFAULT_USER_AGENT = "antigravity"


def build_gemini_request(model: str, body: Dict[str, Any], project: ProjectToken) -> Dict[str, Any]:
    """
    将标准 Gemini generateContent/streamGenerateContent 请求包装为内部请求格式。
    """
    request_data = {k: v for k, v in body.items() if k != "model"}

    # 确保 contents 存在
    if "contents" not in request_data:
        request_data["contents"] = []

    google_request = {
        "project": project.project_id,
        "requestId": body.get("requestId") or f"agent-{uuid.uuid4()}",
        "model": model,
        "userAgent": body.get("userAgent") or DEFAULT_USER_AGENT,
        "request": request_data
    }
    return google_request


def get_gemini_url(stream: bool) -> str:
    suffix = "/v1internal:streamGenerateContent?alt=sse" if stream else "/v1internal:generateContent"
    return f"{settings.google_api_base}{suffix}"


def unwrap_response_payload(payload: Any) -> Any:
    """
    Antigravity 内部接口通常返回 {"response": {...}}，这里解包为官方 Gemini 公开格式。
    若无 response 字段则原样返回。
    """
    if isinstance(payload, dict) and "response" in payload and isinstance(payload.get("response"), dict):
        return payload["response"]
    return payload


async def proxy_gemini_non_stream(google_request: Dict[str, Any], project: ProjectToken) -> Dict[str, Any]:
    """
    直接调用 Gemini 非流式 generateContent，返回原生响应。
    """
    token_manager = get_token_manager()
    access_token = await token_manager.get_access_token(project)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "antigravity/1.11.3 windows/amd64"
    }
    url = get_gemini_url(stream=False)

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(url, headers=headers, json=google_request)

        if response.status_code in (401, 403):
            logger.warning(f"Auth error {response.status_code}, refreshing token for {project.project_id}")
            new_token = await token_manager.handle_auth_error(project)
            headers["Authorization"] = f"Bearer {new_token}"
            response = await client.post(url, headers=headers, json=google_request)
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

        return unwrap_response_payload(response.json())


async def stream_gemini_raw(
    google_request: Dict[str, Any],
    project: ProjectToken
) -> AsyncIterator[str]:
    """
    直接透传 Gemini SSE（原始 data 行），不做 OpenAI 转换。
    """
    token_manager = get_token_manager()
    access_token = await token_manager.get_access_token(project)

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "antigravity/1.11.3 windows/amd64"
    }
    url = get_gemini_url(stream=True)

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=google_request) as response:
            if response.status_code in (401, 403):
                logger.warning(f"Auth error {response.status_code}, refreshing token for {project.project_id}")
                new_token = await token_manager.handle_auth_error(project)
                headers["Authorization"] = f"Bearer {new_token}"
                async with client.stream("POST", url, headers=headers, json=google_request) as retry_response:
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
                    async for line in retry_response.aiter_lines():
                        if not line:
                            continue
                        try:
                            payload = line
                            if line.startswith("data:"):
                                payload = line.split("data:", 1)[1].strip()
                            if payload.strip() == "[DONE]":
                                yield "data: [DONE]\n\n"
                                continue
                            data_obj = json.loads(payload)
                            unwrapped = unwrap_response_payload(data_obj)
                            yield f"data: {json.dumps(unwrapped, ensure_ascii=False)}\n\n"
                        except Exception as exc:  # pragma: no cover
                            logger.error(f"SSE unwrap error (retry): {exc}")
                            yield line + "\n\n"
                return

            if response.status_code != 200:
                error_body = await response.aread()
                logger.error(f"Google API error {response.status_code}")
                logger.error(f"Error response: {error_body.decode('utf-8', errors='ignore')}")
                yield f"data: {{\"error\": \"Google API error: {response.status_code}\"}}\n\n"
                return

            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    payload = line
                    if line.startswith("data:"):
                        payload = line.split("data:", 1)[1].strip()
                    if payload.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                        continue
                    data_obj = json.loads(payload)
                    unwrapped = unwrap_response_payload(data_obj)
                    yield f"data: {json.dumps(unwrapped, ensure_ascii=False)}\n\n"
                except Exception as exc:  # pragma: no cover
                    logger.error(f"SSE unwrap error: {exc}")
                    yield line + "\n\n"
