"""
Models 路由

处理模型列表请求。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config import SUPPORTED_MODELS

router = APIRouter(prefix="/v1", tags=["models"])


@router.get("/models")
async def models() -> JSONResponse:
    """返回支持的模型列表"""
    return JSONResponse(content={
        "object": "list",
        "data": SUPPORTED_MODELS,
    })
