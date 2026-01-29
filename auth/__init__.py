"""
GitHub Copilot 认证实现
"""

from abc import ABC, abstractmethod
from typing import Optional


class Auth(ABC):
    """认证基类"""

    @abstractmethod
    async def get_token(self) -> Optional[str]:
        """获取认证令牌"""
        pass
