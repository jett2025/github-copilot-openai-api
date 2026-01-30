"""
Models 路由

处理模型列表请求，动态从 GitHub Copilot API 获取可用模型。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger

from api.chat_stream import get_models
from config import SUPPORTED_MODELS

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models")
async def models() -> JSONResponse:
    """
    返回支持的模型列表

    优先从 GitHub Copilot API 动态获取，如果失败则回退到静态列表。
    注意：此端点不需要认证，用于健康检查和客户端模型发现。
    """
    try:
        # 动态获取模型列表
        result = await get_models()

        # 如果获取成功且有数据，返回动态结果
        if result.get("data"):
            logger.debug(f"Returning {len(result['data'])} models from API")
            return JSONResponse(content=result)

        # 如果动态获取失败或为空，回退到静态列表
        logger.warning("Dynamic models fetch returned empty, falling back to static list")
        return JSONResponse(content={
            "object": "list",
            "data": SUPPORTED_MODELS,
        })

    except Exception as e:
        # 发生异常时回退到静态列表
        logger.error(f"Failed to fetch models dynamically: {e}, falling back to static list")
        return JSONResponse(content={
            "object": "list",
            "data": SUPPORTED_MODELS,
        })
