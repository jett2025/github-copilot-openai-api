"""
管理路由

提供运行时配置管理 API，支持模型映射热重载。

浏览器直接访问示例：
- 查看映射: /admin/mapping?api_key=xxx
- 添加映射: /admin/mapping/set?api_key=xxx&from=gpt-4&to=claude-sonnet-4.5
- 删除映射: /admin/mapping/del?api_key=xxx&from=gpt-4
- 重置映射: /admin/mapping/reset?api_key=xxx
"""

from typing import Optional
from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from config import MODEL_MAPPING, load_model_mapping
from middleware.auth import require_api_key
from loguru import logger


router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/mapping")
async def get_mapping(_: None = Depends(require_api_key)):
    """查看当前模型映射"""
    return JSONResponse(content=MODEL_MAPPING)


@router.get("/mapping/set")
async def set_mapping(
    _: None = Depends(require_api_key),
    from_model: str = Query(..., alias="from", description="源模型名"),
    to_model: str = Query(..., alias="to", description="目标模型名"),
):
    """
    添加/更新单个映射

    示例: /admin/mapping/set?api_key=xxx&from=gpt-4&to=claude-sonnet-4.5
    """
    MODEL_MAPPING[from_model] = to_model
    logger.info(f"Model mapping updated: {from_model} -> {to_model}")
    return JSONResponse(content={"status": "ok", "added": {from_model: to_model}, "mapping": MODEL_MAPPING})


@router.get("/mapping/del")
async def del_mapping(
    _: None = Depends(require_api_key),
    from_model: str = Query(..., alias="from", description="要删除的源模型名"),
):
    """
    删除单个映射

    示例: /admin/mapping/del?api_key=xxx&from=gpt-4
    """
    if from_model in MODEL_MAPPING:
        del MODEL_MAPPING[from_model]
        logger.info(f"Model mapping deleted: {from_model}")
        return JSONResponse(content={"status": "ok", "deleted": from_model, "mapping": MODEL_MAPPING})
    return JSONResponse(status_code=404, content={"error": f"'{from_model}' not found"})


@router.get("/mapping/reset")
async def reset_mapping(_: None = Depends(require_api_key)):
    """
    重置为初始配置（环境变量 > 代码默认值）

    示例: /admin/mapping/reset?api_key=xxx
    """
    MODEL_MAPPING.clear()
    MODEL_MAPPING.update(load_model_mapping())
    logger.info(f"Model mapping reset to initial config: {MODEL_MAPPING}")
    return JSONResponse(content={"status": "ok", "mapping": MODEL_MAPPING})
