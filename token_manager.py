"""Token 管理模块 - 自动刷新和 Round Robin 负载均衡"""
import json
import time
import asyncio
import httpx
import os
from typing import List, Optional, Dict
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProjectToken:
    """项目 Token 数据类"""
    project_id: str
    refresh_token: str
    access_token: Optional[str] = None
    expires_at: Optional[int] = None


class TokenManager:
    """Token 管理器 - 支持多项目 Round Robin 和自动刷新"""

    def __init__(self, data_file: str = "data/tokens.json"):
        self.data_file = data_file
        self.projects: List[ProjectToken] = []
        self.current_index = 0
        self.refresh_lock = asyncio.Lock()
        self.oauth_config: Dict = {}

        # 加载配置
        self.load_tokens()

    def load_tokens(self):
        """从文件加载 token 配置，如果文件不存在则从环境变量加载"""
        if not os.path.exists(self.data_file):
            logger.warning(f"Token file {self.data_file} not found, loading from environment variables")
            self._load_from_env()
            return

        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self.oauth_config = data.get("oauth_config", {})
            projects_data = data.get("projects", [])

            self.projects = [
                ProjectToken(
                    project_id=p["project_id"],
                    refresh_token=p["refresh_token"],
                    access_token=p.get("access_token"),
                    expires_at=p.get("expires_at")
                )
                for p in projects_data
            ]

            logger.info(f"Loaded {len(self.projects)} projects from {self.data_file}")

        except Exception as e:
            logger.error(f"Failed to load tokens from file: {e}")
            logger.warning("Falling back to environment variables")
            self._load_from_env()

    def _load_from_env(self):
        """从环境变量加载配置（回退方案）"""
        try:
            from config import settings

            # 加载 OAuth 配置
            self.oauth_config = {
                "client_id": settings.oauth_client_id,
                "client_secret": settings.oauth_client_secret,
                "token_url": settings.oauth_token_url
            }

            # 加载项目配置
            projects_data = json.loads(os.getenv("PROJECTS", "[]"))
            self.projects = [
                ProjectToken(
                    project_id=p["project_id"],
                    refresh_token=p["refresh_token"],
                    access_token=p.get("access_token"),
                    expires_at=p.get("expires_at")
                )
                for p in projects_data
            ]

            if len(self.projects) == 0:
                logger.warning("No projects configured! Service will start but API requests will fail.")
                logger.warning("Please configure either data/tokens.json or PROJECTS environment variable.")
            else:
                logger.info(f"Loaded {len(self.projects)} projects from environment variables")
                logger.warning("Using environment variables - tokens will NOT be persisted!")

        except Exception as e:
            logger.error(f"Failed to load from environment: {e}")
            logger.warning("Service will start but API requests will fail until configuration is provided.")
            # 不抛出异常，允许程序启动
            self.projects = []
            self.oauth_config = {}

    def save_tokens(self):
        """保存 token 到文件"""
        try:
            data = {
                "oauth_config": self.oauth_config,
                "projects": [
                    {
                        "project_id": p.project_id,
                        "refresh_token": p.refresh_token,
                        "access_token": p.access_token,
                        "expires_at": p.expires_at
                    }
                    for p in self.projects
                ]
            }

            # 确保目录存在
            os.makedirs(os.path.dirname(self.data_file), exist_ok=True)

            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info(f"Saved tokens to {self.data_file}")

        except Exception as e:
            logger.error(f"Failed to save tokens: {e}")

    def get_next_project(self) -> ProjectToken:
        """Round Robin 获取下一个项目"""
        if not self.projects:
            raise ValueError("No projects configured")

        project = self.projects[self.current_index]
        current = self.current_index
        self.current_index = (self.current_index + 1) % len(self.projects)

        logger.info(f"[Round Robin] 使用项目 [{current + 1}/{len(self.projects)}]: {project.project_id}")
        return project

    def find_project(self, project_id: str) -> Optional[ProjectToken]:
        """查找指定项目"""
        for project in self.projects:
            if project.project_id == project_id:
                return project
        return None

    def is_token_expired(self, project: ProjectToken) -> bool:
        """检查 token 是否过期（提前 5 分钟）"""
        if not project.access_token or not project.expires_at:
            return True

        # 提前 5 分钟刷新
        return project.expires_at < (time.time() + 300)

    async def refresh_access_token(self, project: ProjectToken) -> str:
        """刷新指定项目的 access_token"""
        async with self.refresh_lock:
            # 双重检查：可能其他请求已经刷新了
            if not self.is_token_expired(project):
                logger.info(f"Token for {project.project_id} already refreshed by another request")
                return project.access_token

            logger.info(f"Refreshing access_token for project: {project.project_id}")

            try:
                # 构建刷新请求
                token_url = self.oauth_config.get("token_url", "https://oauth2.googleapis.com/token")
                data = {
                    "client_id": self.oauth_config["client_id"],
                    "client_secret": self.oauth_config["client_secret"],
                    "grant_type": "refresh_token",
                    "refresh_token": project.refresh_token
                }

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        token_url,
                        data=data,
                        headers={"Content-Type": "application/x-www-form-urlencoded"}
                    )

                    if response.status_code != 200:
                        error_msg = f"Failed to refresh token: {response.status_code} {response.text}"
                        logger.error(error_msg)
                        raise Exception(error_msg)

                    token_data = response.json()

                    # 更新 token
                    project.access_token = token_data["access_token"]
                    project.expires_at = int(time.time()) + token_data.get("expires_in", 3599)

                    # 保存到文件
                    self.save_tokens()

                    logger.info(f"Successfully refreshed token for {project.project_id}, expires in {token_data.get('expires_in')}s")
                    return project.access_token

            except Exception as e:
                logger.error(f"Error refreshing token for {project.project_id}: {e}")
                raise

    async def get_access_token(self, project: ProjectToken) -> str:
        """获取 access_token，如果过期则自动刷新"""
        if self.is_token_expired(project):
            logger.info(f"Token expired for {project.project_id}, refreshing...")
            return await self.refresh_access_token(project)

        return project.access_token

    async def handle_auth_error(self, project: ProjectToken) -> str:
        """处理 401/403 错误，强制刷新 token"""
        logger.warning(f"Auth error for {project.project_id}, forcing token refresh")
        return await self.refresh_access_token(project)


# 全局 TokenManager 实例
_token_manager: Optional[TokenManager] = None


def get_token_manager() -> TokenManager:
    """获取全局 TokenManager 实例"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
