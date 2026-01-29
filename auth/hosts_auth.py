"""
Hosts 文件认证模块

从本地 hosts.json 文件读取和保存认证信息。
"""

import os
import json
from typing import Optional
from auth import Auth


class HostsAuth(Auth):
    """从 hosts.json 文件读取认证信息"""

    def __init__(self) -> None:
        self.hosts_file = self._get_hosts_file_path()
        self.token: Optional[str] = None

    async def get_token(self) -> Optional[str]:
        """
        获取认证令牌

        Returns:
            认证令牌，如果不存在则返回 None
        """
        if not os.path.exists(self.hosts_file):
            return None
        if self.token is not None:
            return self.token

        try:
            with open(self.hosts_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.token = data.get("github.com", {}).get("oauth_token")
                return self.token
        except (json.JSONDecodeError, IOError, OSError):
            return None

    def _get_hosts_file_path(self) -> str:
        """
        获取 hosts.json 文件路径

        优先使用 /app/auth_data 目录（Docker 持久化卷），
        如果不存在则使用系统默认配置目录。

        Returns:
            hosts.json 文件的完整路径
        """
        # Docker 环境：优先使用挂载的持久化卷
        docker_auth_dir = "/app/auth_data"
        if os.path.exists(docker_auth_dir) or os.path.exists("/app"):
            # 在 Docker 容器中运行
            if not os.path.exists(docker_auth_dir):
                os.makedirs(docker_auth_dir, exist_ok=True)
            return os.path.join(docker_auth_dir, "hosts.json")

        # 本地开发环境
        if os.name == "nt":  # Windows
            config_dir = os.path.expandvars(r"%LOCALAPPDATA%\github-copilot")
            if not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            return os.path.join(config_dir, "hosts.json")
        else:  # Unix-like
            config_dir = os.path.expanduser("~/.config/github-copilot")
            if not os.path.exists(config_dir):
                os.makedirs(config_dir, exist_ok=True)
            return os.path.join(config_dir, "hosts.json")

    def save_token(self, oauth_token: str) -> None:
        """
        保存认证令牌到 hosts.json 文件

        Args:
            oauth_token: OAuth 访问令牌
        """
        data = {"github.com": {"oauth_token": oauth_token}}
        with open(self.hosts_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        # 更新缓存
        self.token = oauth_token
