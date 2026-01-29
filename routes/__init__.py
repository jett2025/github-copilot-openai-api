"""
路由模块

包含所有 API 路由定义。
"""

from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.claude import router as claude_router
from routes.responses import router as responses_router
from routes.models import router as models_router
from routes.usage import router as usage_router

__all__ = [
    "auth_router",
    "chat_router",
    "claude_router",
    "responses_router",
    "models_router",
    "usage_router",
]
