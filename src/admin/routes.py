"""管理面板路由"""
import hashlib
import uuid
import urllib.parse
import httpx
import random
import string
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeSerializer

from src.config import settings
from src.token_manager import get_token_manager

# OAuth 配置（复用 scripts/oauth_server.py 的配置）
OAUTH_CLIENT_ID = "1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com"
OAUTH_CLIENT_SECRET = "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"
OAUTH_SCOPES = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/cclog",
    "https://www.googleapis.com/auth/experimentsandconfigs"
]

# 存储 OAuth state
oauth_states = {}

# 路由器
admin_router = APIRouter(tags=["admin"])

# 模板目录
templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))


# ============ Session 管理 ============

def get_secret_key() -> str:
    """获取签名密钥"""
    if settings.api_keys:
        return hashlib.sha256(settings.api_keys[0].encode()).hexdigest()
    return "default-secret-key-change-me"

def get_serializer() -> URLSafeSerializer:
    """获取序列化器"""
    return URLSafeSerializer(get_secret_key())

def create_session_token() -> str:
    """创建会话 token"""
    serializer = get_serializer()
    return serializer.dumps({"logged_in": True, "timestamp": datetime.now().isoformat()})

def verify_session_token(token: str) -> bool:
    """验证会话 token"""
    if not token:
        return False
    try:
        serializer = get_serializer()
        data = serializer.loads(token)
        return data.get("logged_in", False)
    except Exception:
        return False

def get_current_user(request: Request) -> bool:
    """检查用户是否已登录"""
    token = request.cookies.get("admin_session")
    return verify_session_token(token)


# ============ 登录相关 ============

@admin_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = None):
    """登录页面"""
    if get_current_user(request):
        return RedirectResponse(url="/admin/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": error})

@admin_router.post("/login")
async def login(request: Request, password: str = Form(...)):
    """处理登录"""
    if settings.validate_api_key(password):
        response = RedirectResponse(url="/admin/", status_code=302)
        response.set_cookie(
            key="admin_session",
            value=create_session_token(),
            httponly=True,
            max_age=86400  # 24小时
        )
        return response
    return RedirectResponse(url="/admin/login?error=密码错误", status_code=302)

@admin_router.get("/logout")
async def logout():
    """登出"""
    response = RedirectResponse(url="/admin/login", status_code=302)
    response.delete_cookie("admin_session")
    return response


# ============ 主面板 ============

@admin_router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """主面板"""
    if not get_current_user(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    token_manager = get_token_manager()
    projects = token_manager.get_all_projects()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "projects": projects,
        "current_time": datetime.now()
    })


# ============ Token 管理 ============

@admin_router.post("/token/{project_id}/toggle")
async def toggle_token(request: Request, project_id: str):
    """切换 token 启用状态"""
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="未登录")

    token_manager = get_token_manager()
    new_state = token_manager.toggle_project(project_id)

    if new_state is None:
        raise HTTPException(status_code=404, detail="项目不存在")

    return RedirectResponse(url="/admin/", status_code=302)

@admin_router.post("/token/{project_id}/delete")
async def delete_token(request: Request, project_id: str):
    """删除 token"""
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="未登录")

    token_manager = get_token_manager()
    success = token_manager.delete_project(project_id)

    if not success:
        raise HTTPException(status_code=404, detail="项目不存在")

    return RedirectResponse(url="/admin/", status_code=302)

@admin_router.post("/token/{project_id}/edit")
async def edit_token(request: Request, project_id: str, new_project_id: str = Form(...)):
    """编辑项目 ID"""
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="未登录")

    token_manager = get_token_manager()
    success = token_manager.update_project_id(project_id, new_project_id)

    if not success:
        raise HTTPException(status_code=404, detail="项目不存在")

    return RedirectResponse(url="/admin/", status_code=302)


@admin_router.get("/token/{project_id}/quota")
async def get_token_quota(request: Request, project_id: str):
    """获取指定 Token 的模型配额信息"""
    if not get_current_user(request):
        raise HTTPException(status_code=401, detail="未登录")

    token_manager = get_token_manager()
    project = token_manager.find_project(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    # 确保 token 有效
    try:
        access_token = await token_manager.get_access_token(project)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取 access_token 失败: {str(e)}")

    # 请求 Google API 获取模型列表
    url = f"{settings.google_api_base}/v1internal:fetchAvailableModels"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip",
        "User-Agent": "antigravity/1.11.3 windows/amd64"
    }
    body = {"project": project.project_id}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(url, headers=headers, json=body)

            if response.status_code != 200:
                raise HTTPException(status_code=response.status_code, detail=f"Google API 错误: {response.text}")

            data = response.json()
            models = data.get("models", {})

            # 过滤 Claude 和 Gemini 模型
            claude_models = []
            gemini_models = []

            for model_id, model_info in models.items():
                # 跳过没有配额信息的模型
                if "quotaInfo" not in model_info:
                    continue

                model_data = {
                    "id": model_id,
                    "displayName": model_info.get("displayName", model_id),
                    "remainingFraction": model_info["quotaInfo"].get("remainingFraction", 1),
                    "resetTime": model_info["quotaInfo"].get("resetTime")
                }

                # 根据模型 ID 分类
                if "claude" in model_id.lower():
                    claude_models.append(model_data)
                elif "gemini" in model_id.lower():
                    gemini_models.append(model_data)

            return {
                "claude": claude_models,
                "gemini": gemini_models
            }

    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="请求超时")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"错误: {str(e)}")


# ============ OAuth 认证 ============

def generate_project_id() -> str:
    """生成随机 project_id"""
    adjectives = ["useful", "bright", "swift", "calm", "bold"]
    nouns = ["fuze", "wave", "spark", "flow", "core"]
    random_adj = random.choice(adjectives)
    random_noun = random.choice(nouns)
    random_chars = "".join(random.choices(string.ascii_lowercase + string.digits, k=5))
    return f"{random_adj}-{random_noun}-{random_chars}"


@admin_router.get("/oauth/start", response_class=HTMLResponse)
async def oauth_start(request: Request):
    """生成 OAuth 授权链接"""
    if not get_current_user(request):
        return RedirectResponse(url="/admin/login", status_code=302)

    # 生成 state 防 CSRF
    state = str(uuid.uuid4())
    oauth_states[state] = datetime.now()

    # 获取回调 URL
    host = request.headers.get("host", "localhost:8000")
    scheme = request.headers.get("x-forwarded-proto", "http")
    callback_url = f"{scheme}://{host}/admin/oauth/callback"

    # 构建授权 URL
    params = {
        "access_type": "offline",
        "client_id": OAUTH_CLIENT_ID,
        "prompt": "consent",
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": " ".join(OAUTH_SCOPES),
        "state": state
    }
    auth_url = f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"

    return templates.TemplateResponse("oauth.html", {
        "request": request,
        "auth_url": auth_url
    })


@admin_router.get("/oauth/callback")
async def oauth_callback(request: Request, code: str = None, state: str = None, error: str = None):
    """OAuth 回调处理"""
    # 验证 state
    if state not in oauth_states:
        return templates.TemplateResponse("oauth_result.html", {
            "request": request,
            "success": False,
            "message": "无效的 state 参数"
        })

    del oauth_states[state]

    if error:
        return templates.TemplateResponse("oauth_result.html", {
            "request": request,
            "success": False,
            "message": f"授权失败: {error}"
        })

    if not code:
        return templates.TemplateResponse("oauth_result.html", {
            "request": request,
            "success": False,
            "message": "未收到授权码"
        })

    # 获取回调 URL
    host = request.headers.get("host", "localhost:8000")
    scheme = request.headers.get("x-forwarded-proto", "http")
    callback_url = f"{scheme}://{host}/admin/oauth/callback"

    # 用授权码换取 token
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": OAUTH_CLIENT_ID,
                    "client_secret": OAUTH_CLIENT_SECRET,
                    "redirect_uri": callback_url,
                    "grant_type": "authorization_code"
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if response.status_code != 200:
                return templates.TemplateResponse("oauth_result.html", {
                    "request": request,
                    "success": False,
                    "message": f"Token 交换失败: {response.text}"
                })

            token_data = response.json()
            project_id = generate_project_id()
            expires_at = int(datetime.now().timestamp()) + token_data.get("expires_in", 3599)

            # 保存到 TokenManager
            token_manager = get_token_manager()
            token_manager.add_project(
                project_id=project_id,
                refresh_token=token_data.get("refresh_token"),
                access_token=token_data.get("access_token"),
                expires_at=expires_at
            )

            return templates.TemplateResponse("oauth_result.html", {
                "request": request,
                "success": True,
                "message": f"授权成功！已添加项目: {project_id}"
            })

    except Exception as e:
        return templates.TemplateResponse("oauth_result.html", {
            "request": request,
            "success": False,
            "message": f"发生错误: {str(e)}"
        })
