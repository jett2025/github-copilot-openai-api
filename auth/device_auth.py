from typing import Optional, Dict

import aiohttp
from auth.hosts_auth import HostsAuth
from . import Auth


class DeviceAuth(Auth):
    """GitHub 设备认证"""

    def __init__(self):
        self.client_id = "Iv1.b507a08c87ecfe98"
        self.scope = "read:user"

    async def get_token(self) -> Optional[str]:
        """获取认证令牌 - 仅从已保存的状态中获取"""
        # 设备认证通常需要通过 /auth/device 页面完成
        # 这里我们不再主动发起交互式请求，以避免在 Docker 等非交互环境下报错
        return await HostsAuth().get_token()
        
    async def new_get_token(self) -> Dict:
        """获取设备认证信息，用于Web界面认证流程"""
        # 获取设备码
        device_code_resp = await self._get_device_code()
        if not device_code_resp:
            return {"error": "获取设备码失败"}
            
        return {
            "device_code": device_code_resp['device_code'],
            "user_code": device_code_resp['user_code'],
            "verification_uri": device_code_resp['verification_uri'],
            "expires_in": device_code_resp.get('expires_in', 900),
            "interval": device_code_resp.get('interval', 5)
        }
        
    async def confirm_token(self, device_code: str) -> Dict:
        """确认并获取访问令牌，用于Web界面认证确认后的处理"""
        token = await self._poll_token(device_code)
        if token:
            return {"success": True, "token": token}
        return {"success": False, "error": "认证失败，请重试"}

    async def _get_device_code(self) -> Optional[Dict]:
        """获取设备码"""
        async with aiohttp.ClientSession() as session:
            async with session.post(
                    "https://github.com/login/device/code",
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
                return await resp.json()

    async def _poll_token(self, device_code: str) -> Optional[str]:
        """轮询获取访问令牌"""
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.post(
                        "https://github.com/login/oauth/access_token",
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
                        return None

                    data = await resp.json()
                    if "error" in data:
                        if data["error"] == "authorization_pending":
                            continue
                        return None
                    # 保存到 hosts 文件
                    HostsAuth().save_token(data["access_token"])
                    return data.get("access_token")
