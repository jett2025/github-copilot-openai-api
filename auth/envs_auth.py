import os
from typing import Optional
from . import Auth


class EnvsAuth(Auth):
    """从环境变量读取认证信息"""

    def __init__(self):
        self.token_env = "GH_COPILOT_TOKEN"

    async def get_token(self) -> Optional[str]:
        """获取认证令牌"""
        return os.environ.get(self.token_env)
