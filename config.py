"""配置管理模块"""
import json
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings


class ProjectConfig:
    """项目配置"""
    def __init__(self, project_id: str, access_token: str):
        self.project_id = project_id
        self.access_token = access_token


class Settings(BaseSettings):
    """应用配置"""

    # Google API 配置（可选，默认使用 daily-cloudcode-pa.sandbox.googleapis.com）
    google_api_base: str = Field(
        default="https://daily-cloudcode-pa.sandbox.googleapis.com",
        description="Google API 基础URL"
    )

    # OAuth 配置（用于刷新 access_token）
    oauth_client_id: str = Field(
        default="1071006060591-tmhssin2h21lcre235vtolojh4g403ep.apps.googleusercontent.com",
        alias="OAUTH_CLIENT_ID"
    )
    oauth_client_secret: str = Field(
        default="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",
        alias="OAUTH_CLIENT_SECRET"
    )
    oauth_token_url: str = Field(
        default="https://oauth2.googleapis.com/token",
        alias="OAUTH_TOKEN_URL"
    )

    # 项目配置（JSON字符串）
    projects_json: str = Field(
        default='[{"project_id":"clear-parser-nsl36","access_token":""}]',
        alias="PROJECTS"
    )

    # API Keys（JSON字符串）
    api_keys_json: str = Field(
        default='["sk-test-key"]',
        alias="API_KEYS"
    )

    # 服务配置
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def projects(self) -> List[ProjectConfig]:
        """解析项目配置"""
        data = json.loads(self.projects_json)
        return [ProjectConfig(**item) for item in data]

    @property
    def api_keys(self) -> List[str]:
        """解析API密钥"""
        return json.loads(self.api_keys_json)

    def get_project(self, project_id: str) -> ProjectConfig:
        """获取指定项目配置"""
        for project in self.projects:
            if project.project_id == project_id:
                return project
        raise ValueError(f"Project {project_id} not found")

    def validate_api_key(self, api_key: str) -> bool:
        """验证API密钥"""
        return api_key in self.api_keys


# 全局配置实例
settings = Settings()
