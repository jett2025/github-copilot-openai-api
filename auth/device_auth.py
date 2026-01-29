"""
GitHub 设备认证模块

实现 OAuth 设备授权流程。
"""

import asyncio
from typing import Optional, Dict, TypedDict

import aiohttp
from auth.hosts_auth import HostsAuth
from auth import Auth
from config import copilot_config
from exceptions import DeviceAuthError, DeviceAuthTimeoutError, DeviceCodeExpiredError


class DeviceCodeResponse(TypedDict):
    """设备码响应类型"""
    device_code: str
    user_code: str
    verification_uri: str
    expires_in: int
    interval: int


class AuthConfirmResult(TypedDict, total=False):
    """认证确认结果类型"""
    success: bool
    token: Optional[str]
    error: Optional[str]


class DeviceAuth(Auth):
    """GitHub 设备认证"""

    # 默认超时时间（秒）
    DEFAULT_TIMEOUT = 900  # 15 分钟
    # 默认轮询间隔（秒）
    DEFAULT_INTERVAL = 5

    def __init__(self):
        self.client_id = copilot_config.client_id
        self.scope = copilot_config.scope

    async def get_token(self) -> Optional[str]:
        """
        获取认证令牌 - 仅从已保存的状态中获取

        设备认证通常需要通过 /auth/device 页面完成，
        这里我们不再主动发起交互式请求，以避免在 Docker 等非交互环境下报错。

        Returns:
            认证令牌，如果未认证则返回 None
        """
        return await HostsAuth().get_token()

    async def new_get_token(self) -> Dict[str, str | int]:
        """
        获取设备认证信息，用于 Web 界面认证流程

        Returns:
            包含设备码信息的字典，或包含错误信息的字典
        """
        device_code_resp = await self._get_device_code()
        if not device_code_resp:
            return {"error": "获取设备码失败"}

        return {
            "device_code": device_code_resp["device_code"],
            "user_code": device_code_resp["user_code"],
            "verification_uri": device_code_resp["verification_uri"],
            "expires_in": device_code_resp.get("expires_in", self.DEFAULT_TIMEOUT),
            "interval": device_code_resp.get("interval", self.DEFAULT_INTERVAL),
        }

    async def confirm_token(self, device_code: str, timeout: Optional[int] = None) -> AuthConfirmResult:
        """
        确认并获取访问令牌，用于 Web 界面认证确认后的处理

        Args:
            device_code: 设备码
            timeout: 超时时间（秒），默认使用 DEFAULT_TIMEOUT

        Returns:
            认证结果字典
        """
        timeout = timeout or self.DEFAULT_TIMEOUT
        try:
            token = await self._poll_token(device_code, timeout=timeout)
            if token:
                return {"success": True, "token": token}
            return {"success": False, "error": "认证失败，请重试"}
        except DeviceAuthTimeoutError:
            return {"success": False, "error": "认证超时，请重新开始"}
        except DeviceCodeExpiredError:
            return {"success": False, "error": "设备码已过期，请重新开始"}
        except DeviceAuthError as e:
            return {"success": False, "error": str(e)}

    async def _get_device_code(self) -> Optional[DeviceCodeResponse]:
        """
        获取设备码

        Returns:
            设备码响应，失败返回 None
        """
        async with aiohttp.ClientSession() as session:
            async with session.post(
                copilot_config.device_code_url,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "client_id": self.client_id,
                    "scope": self.scope,
                },
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return DeviceCodeResponse(
                    device_code=data["device_code"],
                    user_code=data["user_code"],
                    verification_uri=data["verification_uri"],
                    expires_in=data.get("expires_in", self.DEFAULT_TIMEOUT),
                    interval=data.get("interval", self.DEFAULT_INTERVAL),
                )

    async def _poll_token(
        self,
        device_code: str,
        timeout: int = DEFAULT_TIMEOUT,
        interval: int = DEFAULT_INTERVAL,
    ) -> Optional[str]:
        """
        轮询获取访问令牌

        Args:
            device_code: 设备码
            timeout: 超时时间（秒）
            interval: 轮询间隔（秒）

        Returns:
            访问令牌

        Raises:
            DeviceAuthTimeoutError: 认证超时
            DeviceCodeExpiredError: 设备码过期
            DeviceAuthError: 其他认证错误
        """
        start_time = asyncio.get_event_loop().time()

        async with aiohttp.ClientSession() as session:
            while True:
                # 检查超时
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed >= timeout:
                    raise DeviceAuthTimeoutError(timeout_seconds=timeout)

                async with session.post(
                    copilot_config.oauth_token_url,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    json={
                        "client_id": self.client_id,
                        "device_code": device_code,
                        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    },
                ) as resp:
                    if resp.status != 200:
                        raise DeviceAuthError(f"OAuth 请求失败，状态码: {resp.status}")

                    data = await resp.json()

                    if "error" in data:
                        error = data["error"]
                        if error == "authorization_pending":
                            # 用户尚未完成授权，继续轮询
                            await asyncio.sleep(interval)
                            continue
                        elif error == "slow_down":
                            # 请求太频繁，增加间隔
                            interval = min(interval + 5, 30)
                            await asyncio.sleep(interval)
                            continue
                        elif error == "expired_token":
                            raise DeviceCodeExpiredError()
                        elif error == "access_denied":
                            raise DeviceAuthError("用户拒绝了授权请求")
                        else:
                            raise DeviceAuthError(f"认证错误: {error}")

                    # 成功获取令牌
                    access_token = data.get("access_token")
                    if access_token:
                        # 保存到 hosts 文件
                        HostsAuth().save_token(access_token)
                        return access_token

                    raise DeviceAuthError("响应中没有访问令牌")
