"""
API 认证中间件

提供统一的 API 密钥验证功能，消除路由中的重复代码。
"""

from typing import Optional, Tuple
from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from config import server_config


def verify_api_key(request: Request) -> Tuple[bool, Optional[str]]:
    """
    验证请求中的 API 密钥

    Args:
        request: FastAPI 请求对象

    Returns:
        Tuple[bool, Optional[str]]: (验证是否成功, 错误消息)
    """
    server_auth_key = server_config.api_key

    # 如果没有配置 API 密钥，则跳过验证
    if not server_auth_key:
        return True, None

    # 获取请求中的 Authorization header
    auth_header = request.headers.get("Authorization")

    if not auth_header:
        return False, "Missing Authorization header"

    # 支持 Bearer token 格式
    expected_token = f"Bearer {server_auth_key}"
    if auth_header != expected_token:
        # 也支持 x-api-key 格式
        x_api_key = request.headers.get("x-api-key")
        if x_api_key != server_auth_key:
            return False, "Invalid API key"

    return True, None


def require_api_key(request: Request) -> None:
    """
    要求 API 密钥验证的依赖项

    用于 FastAPI 依赖注入，验证失败时抛出 HTTPException

    Args:
        request: FastAPI 请求对象

    Raises:
        HTTPException: 验证失败时抛出 401 错误
    """
    is_valid, error_message = verify_api_key(request)
    if not is_valid:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": error_message or "Invalid token",
                    "type": "authentication_error",
                }
            }
        )


class AuthMiddleware(BaseHTTPMiddleware):
    """
    认证中间件

    可用于对指定路径进行统一的 API 密钥验证。
    """

    def __init__(self, app, protected_paths: Optional[list] = None):
        """
        初始化认证中间件

        Args:
            app: FastAPI 应用实例
            protected_paths: 需要保护的路径列表，默认为 ["/v1/"]
        """
        super().__init__(app)
        self.protected_paths = protected_paths or ["/v1/"]

    async def dispatch(self, request: Request, call_next):
        """处理请求"""
        # 检查是否需要验证
        path = request.url.path
        needs_auth = any(path.startswith(p) for p in self.protected_paths)

        if needs_auth:
            is_valid, error_message = verify_api_key(request)
            if not is_valid:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "message": error_message or "Invalid token",
                            "type": "authentication_error",
                        }
                    }
                )

        response = await call_next(request)
        return response
