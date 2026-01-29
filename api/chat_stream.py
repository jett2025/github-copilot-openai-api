from functools import cache
from typing import Optional, AsyncGenerator, Dict, Any

import async_lru
import aiohttp
import base64

from api.chat_api import ChatAPI, is_responses_model
from auth.device_auth import DeviceAuth
from auth.envs_auth import EnvsAuth
from auth.hosts_auth import HostsAuth
from loguru import logger


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
            # 保留列表结构，以支持 image_url
            normalized_msg["content"] = content
        elif content is not None:
            normalized_msg["content"] = content
        else:
            # content 为 None 时，对于有 tool_calls 的 assistant 消息保持 None
            # 对于其他消息设置为空字符串
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


async def process_images(messages: list) -> list:
    """处理消息中的图片 URL，将其转换为 Base64 以提高兼容性"""
    async with aiohttp.ClientSession() as session:
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
                                async with session.get(url, timeout=10) as resp:
                                    if resp.status == 200:
                                        data = await resp.read()
                                        mime_type = resp.headers.get("Content-Type", "image/jpeg")
                                        base64_data = base64.b64encode(data).decode("utf-8")
                                        image_url_obj["url"] = f"data:{mime_type};base64,{base64_data}"
                            except Exception:
                                # 下载失败则保持原样，让 GitHub 尝试处理
                                pass
    return messages


async def run_stream(
        data: dict
) -> AsyncGenerator[str, None]:
    """运行流式聊天，返回符合 OpenAI SSE 规范的数据流"""
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

    # 根据模型选择 API 端点
    if is_responses_model(model):
        logger.info(f"Using /responses API for model: {model}")
        async for chunk in chat.responses_stream_chat(normalized_messages, model=model, temperature=temperature, **extra_params):
            yield chunk
    else:
        async for chunk in chat.stream_chat(normalized_messages, model=model, temperature=temperature, **extra_params):
            yield chunk


async def run(
        data: dict
) -> Dict[str, Any]:
    """运行非流式聊天，返回完整的响应"""
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

    # 根据模型选择 API 端点
    if is_responses_model(model):
        logger.info(f"Using /responses API for model: {model}")
        return await chat.responses_chat(normalized_messages, model=model, temperature=temperature, **extra_params)
    else:
        return await chat.chat(normalized_messages, model=model, temperature=temperature, **extra_params)
