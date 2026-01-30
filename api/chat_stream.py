"""
聊天流处理模块

提供统一的流式和非流式聊天入口。
"""

from typing import Optional, AsyncGenerator, Dict, Any
import asyncio

import aiohttp
import base64

from api.chat_api import ChatAPI
from auth.device_auth import DeviceAuth
from auth.envs_auth import EnvsAuth
from auth.hosts_auth import HostsAuth
from config import is_responses_model
from loguru import logger


# ==================== 全局 HTTP 连接池 ====================

# 全局 ClientSession 实例（延迟初始化）
_http_client: Optional[aiohttp.ClientSession] = None
_client_lock = asyncio.Lock()

# 连接池配置
HTTP_POOL_CONFIG = {
    "limit": 100,              # 最大连接数
    "limit_per_host": 30,      # 每个主机最大连接数
    "ttl_dns_cache": 300,      # DNS 缓存时间（秒）
    "keepalive_timeout": 60,   # Keep-alive 超时（秒）
}


async def get_http_client() -> aiohttp.ClientSession:
    """
    获取全局 HTTP 客户端（单例模式，线程安全）

    使用连接池复用 TCP 连接，提升性能并减少资源消耗。

    Returns:
        aiohttp.ClientSession 实例
    """
    global _http_client

    if _http_client is None or _http_client.closed:
        async with _client_lock:
            # 双重检查锁定
            if _http_client is None or _http_client.closed:
                connector = aiohttp.TCPConnector(
                    limit=HTTP_POOL_CONFIG["limit"],
                    limit_per_host=HTTP_POOL_CONFIG["limit_per_host"],
                    ttl_dns_cache=HTTP_POOL_CONFIG["ttl_dns_cache"],
                    keepalive_timeout=HTTP_POOL_CONFIG["keepalive_timeout"],
                    enable_cleanup_closed=True,
                )
                timeout = aiohttp.ClientTimeout(total=300, connect=30)
                _http_client = aiohttp.ClientSession(
                    connector=connector,
                    timeout=timeout,
                )
                logger.info("Created global HTTP connection pool")
    return _http_client


async def close_http_client():
    """
    关闭全局 HTTP 客户端

    应在应用关闭时调用此函数释放资源。
    """
    global _http_client

    if _http_client is not None and not _http_client.closed:
        await _http_client.close()
        _http_client = None
        logger.info("Closed global HTTP connection pool")


async def get_token() -> Optional[str]:
    """获取认证令牌"""
    auth_methods = [
        EnvsAuth(),
        HostsAuth(),
        DeviceAuth(),
    ]

    for auth in auth_methods:
        if token := await auth.get_token():
            return token
    return None


# ==================== 模型列表缓存 ====================

# 模型列表缓存
_models_cache: Optional[Dict[str, Any]] = None
_models_cache_time: float = 0
MODELS_CACHE_TTL = 10 * 60  # 缓存 10 分钟


async def get_models(force_refresh: bool = False) -> Dict[str, Any]:
    """
    获取可用模型列表（动态从 GitHub Copilot API 获取，带缓存）

    Args:
        force_refresh: 是否强制刷新缓存

    Returns:
        包含模型列表的字典
    """
    global _models_cache, _models_cache_time
    import time

    # 检查缓存是否有效
    current_time = time.time()
    if not force_refresh and _models_cache is not None:
        if current_time - _models_cache_time < MODELS_CACHE_TTL:
            logger.debug("Returning cached models list")
            return _models_cache

    # 获取 token
    token = await get_token()
    if not token:
        logger.warning("No token available for get_models")
        # 如果有缓存，即使过期也返回
        if _models_cache is not None:
            return _models_cache
        return {"object": "list", "data": []}

    # 从 API 获取模型列表
    chat = ChatAPI(token)
    result = await chat.get_models()

    # 更新缓存
    if result.get("data"):
        _models_cache = result
        _models_cache_time = current_time
        logger.info(f"Updated models cache with {len(result['data'])} models")

    return result


def normalize_messages(messages: list) -> list:
    """规范化消息格式，保留工具调用等关键信息"""
    normalized_messages = []
    for msg in messages:
        normalized_msg = {
            "role": msg.get("role", "user")
        }

        # 处理 content (支持字符串或列表，保留多模态图片信息)
        content = msg.get("content")
        if isinstance(content, list):
            normalized_msg["content"] = content
        elif content is not None:
            normalized_msg["content"] = content
        else:
            # content 为 None 时，对于有 tool_calls 的 assistant 消息保持 None
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                normalized_msg["content"] = None
            else:
                normalized_msg["content"] = ""

        # 处理工具调用 (助手返回的)
        if "tool_calls" in msg:
            normalized_msg["tool_calls"] = msg["tool_calls"]

        # 处理工具响应 (工具角色返回的)
        if "tool_call_id" in msg:
            normalized_msg["tool_call_id"] = msg["tool_call_id"]

        # 处理名称 (可选)
        if "name" in msg:
            normalized_msg["name"] = msg["name"]

        normalized_messages.append(normalized_msg)
    return normalized_messages


# 图片下载安全限制
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
IMAGE_DOWNLOAD_TIMEOUT = 10  # 秒


async def process_images(messages: list, session: aiohttp.ClientSession = None) -> list:
    """
    处理消息中的图片 URL，将其转换为 Base64 以提高兼容性

    Args:
        messages: 消息列表
        session: 可选的 aiohttp ClientSession，用于连接复用

    安全限制:
        - 最大图片大小: 10MB
        - 下载超时: 10秒
    """
    # 如果没有传入 session，使用全局连接池
    if session is None:
        session = await get_http_client()

    timeout = aiohttp.ClientTimeout(total=IMAGE_DOWNLOAD_TIMEOUT)

    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "image_url":
                    image_url_obj = item.get("image_url", {})
                    url = image_url_obj.get("url")
                    # 如果是远程 URL 且不是 Base64，则尝试下载并转换
                    if url and url.startswith("http") and not url.startswith("data:"):
                        try:
                            async with session.get(url, timeout=timeout) as resp:
                                if resp.status == 200:
                                    # 检查 Content-Length 头
                                    content_length = resp.headers.get("Content-Length")
                                    if content_length and int(content_length) > MAX_IMAGE_SIZE:
                                        logger.warning(f"Image too large (Content-Length: {content_length}), skipping: {url[:100]}")
                                        continue

                                    # 流式读取并检查大小
                                    chunks = []
                                    total_size = 0
                                    async for chunk in resp.content.iter_chunked(64 * 1024):  # 64KB chunks
                                        total_size += len(chunk)
                                        if total_size > MAX_IMAGE_SIZE:
                                            logger.warning(f"Image exceeded {MAX_IMAGE_SIZE} bytes during download, skipping: {url[:100]}")
                                            break
                                        chunks.append(chunk)
                                    else:
                                        # 只有在没有超出限制时才处理
                                        data = b"".join(chunks)
                                        mime_type = resp.headers.get("Content-Type", "image/jpeg")
                                        # 确保 mime_type 是有效的图片类型
                                        if not mime_type.startswith("image/"):
                                            mime_type = "image/jpeg"
                                        base64_data = base64.b64encode(data).decode("utf-8")
                                        image_url_obj["url"] = f"data:{mime_type};base64,{base64_data}"
                        except asyncio.TimeoutError:
                            logger.warning(f"Image download timeout: {url[:100]}")
                        except Exception as e:
                            # 下载失败则保持原样，让 GitHub 尝试处理
                            logger.debug(f"Image download failed: {e}")
    return messages


async def _prepare_request(data: dict) -> tuple[ChatAPI, list, str, float, dict]:
    """
    准备请求所需的参数

    Args:
        data: 请求数据

    Returns:
        (ChatAPI 实例, 处理后的消息, 模型名称, 温度, 额外参数)

    Raises:
        ValueError: 认证失败或消息为空
    """
    token = await get_token()
    if not token:
        raise ValueError("未能获取有效的认证令牌")

    chat = ChatAPI(token)
    messages = data.get("messages", [])
    model = data.get("model", "gpt-4")
    temperature = data.get("temperature", 0.7)

    if not messages:
        raise ValueError("not found any message")

    # 规范化消息格式并处理图片
    normalized_messages = normalize_messages(messages)
    normalized_messages = await process_images(normalized_messages)

    extra_params = {}
    if "tools" in data:
        extra_params["tools"] = data["tools"]
    if "tool_choice" in data:
        extra_params["tool_choice"] = data["tool_choice"]

    return chat, normalized_messages, model, temperature, extra_params


async def run_stream(data: dict) -> AsyncGenerator[str, None]:
    """运行流式聊天，返回符合 OpenAI SSE 规范的数据流"""
    chat, messages, model, temperature, extra_params = await _prepare_request(data)

    # 根据模型选择 API 端点
    if is_responses_model(model):
        logger.info(f"Using /responses API for model: {model}")
        async for chunk in chat.responses_stream_chat(messages, model=model, temperature=temperature, **extra_params):
            yield chunk
    else:
        async for chunk in chat.stream_chat(messages, model=model, temperature=temperature, **extra_params):
            yield chunk


async def run(data: dict) -> Dict[str, Any]:
    """运行非流式聊天，返回完整的响应"""
    chat, messages, model, temperature, extra_params = await _prepare_request(data)

    # 根据模型选择 API 端点
    if is_responses_model(model):
        logger.info(f"Using /responses API for model: {model}")
        return await chat.responses_chat(messages, model=model, temperature=temperature, **extra_params)
    else:
        return await chat.chat(messages, model=model, temperature=temperature, **extra_params)
