"""
Copilot 用量查询路由

提供 /usage 端点，用于查询 Copilot 的使用量和配额信息。
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from loguru import logger
import aiohttp

from auth.hosts_auth import HostsAuth
from config import copilot_config


router = APIRouter(tags=["usage"])


async def get_copilot_usage() -> dict:
    """
    获取 Copilot 使用量和配额信息

    调用 GitHub API: GET https://api.github.com/copilot_internal/user

    Returns:
        包含使用量信息的字典
    """
    # 获取 GitHub access token
    hosts_auth = HostsAuth()
    access_token = await hosts_auth.get_token()

    if not access_token:
        return {"error": "未找到认证信息，请先完成设备认证"}

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Authorization": f"token {access_token}",
        "editor-version": copilot_config.editor_version,
        "editor-plugin-version": copilot_config.plugin_version,
        "user-agent": f"GitHubCopilotChat/{copilot_config.plugin_version.split('/')[-1]}",
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://api.github.com/copilot_internal/user",
            headers=headers,
        ) as resp:
            if resp.status != 200:
                error_text = await resp.text()
                logger.error(f"获取 Copilot 使用量失败: HTTP {resp.status}, {error_text}")
                return {
                    "error": f"Failed to get usage: HTTP {resp.status}",
                    "detail": error_text,
                }

            usage_data = await resp.json()

            # 解析并格式化返回数据
            quota_snapshots = usage_data.get("quota_snapshots", {})

            def format_quota(name: str, quota: dict) -> dict:
                """格式化单个配额信息"""
                if not quota:
                    return {"name": name, "available": False}

                entitlement = quota.get("entitlement", 0)
                remaining = quota.get("remaining", 0)
                used = entitlement - remaining
                percent_used = (used / entitlement * 100) if entitlement > 0 else 0
                percent_remaining = quota.get("percent_remaining", 0)

                return {
                    "name": name,
                    "available": True,
                    "entitlement": entitlement,
                    "remaining": remaining,
                    "used": used,
                    "percent_used": round(percent_used, 2),
                    "percent_remaining": round(percent_remaining, 2),
                    "unlimited": quota.get("unlimited", False),
                }

            return {
                "copilot_plan": usage_data.get("copilot_plan", "unknown"),
                "quota_reset_date": usage_data.get("quota_reset_date", ""),
                "chat_enabled": usage_data.get("chat_enabled", False),
                "quotas": {
                    "premium_interactions": format_quota(
                        "Premium Interactions",
                        quota_snapshots.get("premium_interactions"),
                    ),
                    "chat": format_quota("Chat", quota_snapshots.get("chat")),
                    "completions": format_quota(
                        "Completions", quota_snapshots.get("completions")
                    ),
                },
                "raw": usage_data,  # 包含原始数据以便调试
            }


@router.get("/usage")
async def usage():
    """
    获取 Copilot 使用量和配额信息

    返回数据包括：
    - copilot_plan: 订阅计划类型
    - quota_reset_date: 配额重置日期
    - quotas: 各类配额使用情况
        - premium_interactions: 高级交互配额
        - chat: 聊天配额
        - completions: 代码补全配额
    """
    try:
        usage_data = await get_copilot_usage()
        return JSONResponse(content=usage_data)
    except Exception as e:
        logger.error(f"获取使用量失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )
