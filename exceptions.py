"""
自定义异常类模块

定义项目中使用的所有自定义异常，提供更精确的错误处理。
"""

from typing import Optional


class CopilotAPIError(Exception):
    """Copilot API 基础异常类"""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(CopilotAPIError):
    """认证错误"""

    def __init__(self, message: str = "Authentication failed"):
        super().__init__(message, status_code=401)


class TokenExpiredError(AuthenticationError):
    """令牌过期错误"""

    def __init__(self, message: str = "Token has expired"):
        super().__init__(message)


class InvalidTokenError(AuthenticationError):
    """无效令牌错误"""

    def __init__(self, message: str = "Invalid token"):
        super().__init__(message)


class DeviceAuthError(CopilotAPIError):
    """设备认证错误"""

    def __init__(self, message: str = "Device authentication failed"):
        super().__init__(message, status_code=400)


class DeviceAuthTimeoutError(DeviceAuthError):
    """设备认证超时错误"""

    def __init__(self, message: str = "Device authentication timed out", timeout_seconds: int = 900):
        super().__init__(message)
        self.timeout_seconds = timeout_seconds


class DeviceCodeExpiredError(DeviceAuthError):
    """设备码过期错误"""

    def __init__(self, message: str = "Device code has expired"):
        super().__init__(message)


class APIRequestError(CopilotAPIError):
    """API 请求错误"""

    def __init__(self, message: str, status_code: int = 500):
        super().__init__(message, status_code=status_code)


class ModelNotSupportedError(CopilotAPIError):
    """模型不支持错误"""

    def __init__(self, model: str):
        super().__init__(f"Model '{model}' is not supported", status_code=400)
        self.model = model


class MessageFormatError(CopilotAPIError):
    """消息格式错误"""

    def __init__(self, message: str = "Invalid message format"):
        super().__init__(message, status_code=400)


class StreamError(CopilotAPIError):
    """流式响应错误"""

    def __init__(self, message: str = "Stream processing error"):
        super().__init__(message, status_code=500)


class UpstreamAPIError(CopilotAPIError):
    """上游 API 错误（如 GitHub Copilot API 返回的错误）"""

    def __init__(self, message: str, status_code: int = 500, error_type: str = "upstream_error"):
        super().__init__(message, status_code=status_code)
        self.error_type = error_type

    def to_openai_error(self) -> dict:
        """转换为 OpenAI 兼容的错误格式"""
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "code": self.status_code,
            }
        }
