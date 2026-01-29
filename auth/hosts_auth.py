import os
import json
from typing import Optional
from . import Auth


class HostsAuth(Auth):
    """从 hosts.json 文件读取认证信息"""

    def __init__(self):
        self.hosts_file = self._get_hosts_file_path()
        self.token = None

    async def get_token(self) -> Optional[str]:
        """获取认证令牌"""
        if not os.path.exists(self.hosts_file):
            return None
        if self.token is not None:
            return self.token

        try:
            with open(self.hosts_file, 'r') as f:
                data = json.load(f)
                self.token = data.get("github.com", {}).get("oauth_token")
                return self.token
        except Exception:
            return None

    def _get_hosts_file_path(self) -> str:
        """获取 hosts.json 文件路径"""
        if os.name == 'nt':  # Windows
            if not os.path.exists(os.path.expandvars("%LOCALAPPDATA%\\Local\\github-copilot")):
                os.makedirs(os.path.expandvars("%LOCALAPPDATA%\\Local\\github-copilot"), exist_ok=True)
            return os.path.expandvars(r"%APPDATA%\Local\github-copilot\hosts.json")
        else:  # Unix-like
            if not os.path.exists(os.path.expanduser("~/.config/github-copilot")):
                os.makedirs(os.path.expanduser("~/.config/github-copilot"), exist_ok=True)
            return os.path.expanduser("~/.config/github-copilot/hosts.json")

    def save_token(self, oauth_token: str):
        """保存认证令牌到 hosts.json 文件"""
        data = {"github.com": {"oauth_token": oauth_token}}
        with open(self.hosts_file, 'w') as f:
            f.write(json.dumps(data, indent=2, ensure_ascii=False))
