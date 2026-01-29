"""
环境变量认证模块

从环境变量读取认证信息。
"""

import os
from typing import Optional
from auth import Auth


class EnvsAuth(Auth):
    """从环境变量读取认证信息"""

    # 环境变量名称
    TOKEN_ENV_NAME = "GH_COPILOT_TOKEN"

    def __init__(self) -> None:
        self.token_env = self.TOKEN_ENV_NAME

    async def get_token(self) -> Optional[str]:
        """
        获取认证令牌

        Returns:
            环境变量中的令牌，如果未设置则返回 None
        """
        return os.environ.get(self.token_env)
