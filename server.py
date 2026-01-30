"""
GitHub Copilot API 服务入口

提供 OpenAI API 兼容的接口，支持 Chat Completions、Claude Messages 和 Responses API。
"""

from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from loguru import logger
from starlette.middleware.cors import CORSMiddleware

from config import server_config
from routes import (
    auth_router,
    chat_router,
    claude_router,
    responses_router,
    models_router,
    usage_router,
)
from api.chat_stream import (
    close_http_client,
    start_token_refresh_task,
    stop_token_refresh_task,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时
    logger.info("Application starting up...")
    # 启动后台 Token 刷新任务
    await start_token_refresh_task()
    yield
    # 关闭时
    logger.info("Application shutting down...")
    # 停止后台任务
    await stop_token_refresh_task()
    await close_http_client()


# 创建 FastAPI 应用
app = FastAPI(
    title="GitHub Copilot API",
    description="OpenAI API 兼容的 GitHub Copilot 代理服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(claude_router)
app.include_router(responses_router)
app.include_router(models_router)
app.include_router(usage_router)


@app.get("/")
async def root():
    """重定向到设备认证页面"""
    return RedirectResponse(url="/auth/device")


@app.get("/health")
async def health():
    """健康检查端点（无需认证）"""
    return {"status": "ok"}


if __name__ == "__main__":
    host = server_config.host
    port = server_config.port
    logger.info(f"Starting server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
