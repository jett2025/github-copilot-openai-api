"""
统一配置管理模块

集中管理所有配置项，包括：
- 环境变量配置
- 模型映射配置
- API 端点配置
"""

import os
import json
from dataclasses import dataclass, field
from typing import Dict
from loguru import logger


@dataclass
class ServerConfig:
    """服务器配置"""
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", 8000)))
    api_key: str = field(default_factory=lambda: os.getenv("API_KEY", ""))


@dataclass
class CopilotConfig:
    """Copilot API 配置"""
    chat_completions_url: str = "https://api.githubcopilot.com/chat/completions"
    responses_url: str = "https://api.githubcopilot.com/responses"
    models_url: str = "https://api.githubcopilot.com/models"
    token_url: str = "https://api.github.com/copilot_internal/v2/token"
    device_code_url: str = "https://github.com/login/device/code"
    oauth_token_url: str = "https://github.com/login/oauth/access_token"
    client_id: str = "Iv1.b507a08c87ecfe98"
    scope: str = "read:user"
    editor_version: str = "vscode/1.104.0"
    plugin_version: str = "copilot-chat/0.25.2025021001"


# 默认模型映射配置
DEFAULT_MODEL_MAPPING: Dict[str, str] = {
    "gpt-o4-mini": "claude-opus-4.5",
    "gpt-4o-mini": "claude-opus-4.5",
    "claude-opus-4-5-20251101": "claude-opus-4.5",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4.5",
    "claude-haiku-4-5-20251001": "claude-haiku-4.5",
}

# 需要使用 /responses API 的模型列表
RESPONSES_API_MODELS = [
    "gpt-5-codex",
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.2-codex",
    "gpt-5.2-codex-max",
]

# 支持的模型列表
SUPPORTED_MODELS = [
    {"id": "gpt-5.1-codex-max", "object": "model"},
    {"id": "gpt-5.2-codex", "object": "model"},
    {"id": "gpt-5.2", "object": "model"},
    {"id": "claude-sonnet-4.5", "object": "model"},
    {"id": "claude-opus-4.5", "object": "model"},
    {"id": "claude-haiku-4.5", "object": "model"},
    {"id": "gemini-3-pro-preview", "object": "model"},
    {"id": "gemini-3-flash-preview", "object": "model"},
]


def load_model_mapping() -> Dict[str, str]:
    """从环境变量加载模型映射配置"""
    env_mapping = os.getenv("MODEL_MAPPING", "")
    if env_mapping:
        try:
            custom_mapping = json.loads(env_mapping)
            logger.info(f"Loaded custom model mapping from environment: {custom_mapping}")
            return custom_mapping
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse MODEL_MAPPING environment variable: {e}, using default mapping")
    return DEFAULT_MODEL_MAPPING.copy()


def is_responses_model(model: str) -> bool:
    """检查模型是否需要使用 /responses API"""
    model_lower = model.lower()
    return any(m in model_lower for m in ["codex"])


# 全局配置实例
server_config = ServerConfig()
copilot_config = CopilotConfig()
MODEL_MAPPING = load_model_mapping()


def update_model_mapping(new_mapping: Dict[str, str]) -> None:
    """热更新模型映射（不重启服务）"""
    MODEL_MAPPING.clear()
    MODEL_MAPPING.update(new_mapping)
    logger.info(f"Model mapping updated: {MODEL_MAPPING}")
