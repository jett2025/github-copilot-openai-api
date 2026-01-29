"""
GitHub Copilot Chat API 客户端

提供与 GitHub Copilot API 交互的功能。
"""

from typing import List, Dict, Any, AsyncGenerator
import time
import json
import aiohttp
import async_lru
from loguru import logger

from config import copilot_config, is_responses_model
from services.message_converter import (
    convert_openai_to_responses_format,
    convert_tools_for_responses,
)


class ChatAPI:
    """聊天 API 实现"""

    def __init__(self, token: str):
        self.token = token

    def _build_base_headers(self, copilot_token: str, accept: str = "application/json") -> Dict[str, str]:
        """
        构建基础请求头

        Args:
            copilot_token: Copilot 令牌
            accept: Accept 头部值

        Returns:
            请求头字典
        """
        return {
            "authorization": f"Bearer {copilot_token}",
            "accept-language": "en-US,en;q=0.9",
            "editor-plugin-version": copilot_config.plugin_version,
            "openai-intent": "conversation-panel",
            "editor-version": copilot_config.editor_version,
            "content-type": "application/json",
            "accept": accept,
        }

    def _check_vision_request(self, messages: List[Dict[str, Any]]) -> bool:
        """
        检查消息中是否包含图片请求

        Args:
            messages: 消息列表

        Returns:
            是否包含图片
        """
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        return True
        return False

    def _build_payload(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        temperature: float,
        stream: bool,
        **kwargs
    ) -> Dict[str, Any]:
        """
        构建请求载荷

        Args:
            messages: 消息列表
            model: 模型名称
            temperature: 温度参数
            stream: 是否流式
            **kwargs: 额外参数

        Returns:
            请求载荷字典
        """
        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "stream": stream,
        }
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]
        return payload

    async def stream_chat(
            self,
            messages: List[Dict[str, Any]],
            model: str = "gpt-4",
            temperature: float = 0.7,
            **kwargs
    ) -> AsyncGenerator[str, None]:
        """将 GitHub Copilot API 转换为 OpenAI API 兼容的流式聊天接口"""
        copilot_token = await self.get_copilot_token()
        if not copilot_token:
            raise ValueError("No Copilot token")

        headers = self._build_base_headers(copilot_token, accept="text/event-stream")

        # 检查是否包含图片请求
        if self._check_vision_request(messages):
            headers["Copilot-Vision-Request"] = "true"

        payload = self._build_payload(messages, model, temperature, stream=True, **kwargs)

        logger.debug(f"Chat API stream request: model={model}, messages_count={len(messages)}, tools_count={len(kwargs.get('tools', []))}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url=copilot_config.chat_completions_url,
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Chat API error: model={model}, status={response.status}, error={error_text}")
                    for i, msg in enumerate(messages):
                        msg_info = f"msg[{i}]: role={msg.get('role')}, has_content={msg.get('content') is not None}, has_tool_calls={'tool_calls' in msg}"
                        logger.debug(msg_info)
                    raise ValueError(f"status code：{response.status}，error message：{error_text}")

                async for line in response.content:
                    try:
                        line = line.decode('utf-8').strip()
                        if not line:
                            continue

                        if line.startswith('data: '):
                            data = line[6:].strip()
                        else:
                            data = line.strip()

                        if data == '[DONE]':
                            yield 'data: [DONE]\n\n'
                            break

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            continue

                        if not chunk.get('choices'):
                            continue

                        delta = chunk['choices'][0].get('delta', {})
                        content = delta.get('content')
                        tool_calls = delta.get('tool_calls')
                        reasoning_content = delta.get('reasoning_content')

                        if not any([content is not None, tool_calls is not None, reasoning_content is not None]):
                            continue

                        response_delta = {}
                        if content is not None:
                            response_delta['content'] = content
                        if tool_calls is not None:
                            response_delta['tool_calls'] = tool_calls
                        if reasoning_content is not None:
                            response_delta['reasoning_content'] = reasoning_content

                        response_chunk = {
                            'id': f"chatcmpl-{int(time.time() * 1000)}",
                            'object': 'chat.completion.chunk',
                            'created': int(time.time()),
                            'model': model,
                            'choices': [
                                {
                                    'index': 0,
                                    'delta': response_delta,
                                    'finish_reason': chunk['choices'][0].get('finish_reason')
                                }
                            ]
                        }
                        yield f"data: {json.dumps(response_chunk)}\n\n"

                    except Exception:
                        continue

    @async_lru.alru_cache(ttl=2 * 60 * 60)
    async def get_copilot_token(self) -> str:
        """获取 Copilot token"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    url=copilot_config.token_url,
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept": "application/json",
                        "User-Agent": "Mozilla/5.0",
                    }
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(
                        f"Get token error, status code: {response.status}, error message: {error_text}")

                data = await response.json()
                token = data.get("token")
                logger.info(f"Get Copilot token: {token}")
                if not token:
                    raise ValueError("No token")
                return token

    async def chat(
            self,
            messages: List[Dict[str, Any]],
            model: str = "gpt-4",
            temperature: float = 0.7,
            **kwargs
    ) -> Dict[str, Any]:
        """非流式聊天接口，返回完整的响应"""
        copilot_token = await self.get_copilot_token()
        if not copilot_token:
            raise ValueError("No Copilot token")

        headers = self._build_base_headers(copilot_token, accept="application/json")

        # 检查是否包含图片请求
        if self._check_vision_request(messages):
            headers["Copilot-Vision-Request"] = "true"

        payload = self._build_payload(messages, model, temperature, stream=False, **kwargs)

        logger.debug(f"Chat API payload: model={model}, tools_count={len(kwargs.get('tools', []))}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url=copilot_config.chat_completions_url,
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Chat API error: model={model}, status={response.status}, payload_keys={list(payload.keys())}")
                    raise ValueError(f"status code：{response.status}，error message：{error_text}")

                response_data = await response.json()
                choice = response_data.get("choices", [{}])[0]
                message = choice.get("message", {})

                return {
                    "id": f"chatcmpl-{int(time.time() * 1000)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": message.get("content"),
                                "tool_calls": message.get("tool_calls"),
                                "reasoning_content": message.get("reasoning_content")
                            },
                            "finish_reason": choice.get("finish_reason", "stop")
                        }
                    ],
                    "usage": response_data.get("usage", {})
                }

    # ==================== Responses API 方法 ====================

    async def responses_stream_chat(
            self,
            messages: List[Dict[str, Any]],
            model: str = "gpt-5-codex",
            temperature: float = 0.7,
            **kwargs
    ) -> AsyncGenerator[str, None]:
        """使用 /responses API 的流式聊天接口，输出转换为 Chat Completions 格式"""
        copilot_token = await self.get_copilot_token()
        if not copilot_token:
            raise ValueError("No Copilot token")

        headers = self._build_base_headers(copilot_token, accept="text/event-stream")

        # 转换消息格式
        instructions, input_items = convert_openai_to_responses_format(messages)

        payload = {
            "model": model,
            "stream": True,
        }

        if instructions:
            payload["instructions"] = instructions

        # 添加工具定义（需要转换格式）
        if "tools" in kwargs:
            payload["tools"] = convert_tools_for_responses(kwargs["tools"])
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        # input 可以是字符串或消息列表
        if len(input_items) == 1 and input_items[0].get("role") == "user":
            content = input_items[0]["content"]
            if isinstance(content, str):
                payload["input"] = content
            else:
                payload["input"] = input_items
        else:
            payload["input"] = input_items

        logger.debug(f"Responses API payload: {json.dumps(payload, ensure_ascii=False)}")

        connector = aiohttp.TCPConnector(limit=100)
        timeout = aiohttp.ClientTimeout(total=300)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(
                    url=copilot_config.responses_url,
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(f"Responses API error, status: {response.status}, message: {error_text}")

                buffer = ""
                async for chunk in response.content.iter_any():
                    try:
                        buffer += chunk.decode('utf-8')

                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if not line:
                                continue

                            if line.startswith('data: '):
                                data = line[6:].strip()
                            else:
                                data = line.strip()

                            if data == '[DONE]':
                                yield 'data: [DONE]\n\n'
                                return

                            try:
                                chunk_json = json.loads(data)
                            except json.JSONDecodeError:
                                continue

                            extracted = self._extract_responses_content(chunk_json)
                            if extracted is None:
                                continue

                            response_delta = {}
                            if "content" in extracted:
                                response_delta["content"] = extracted["content"]
                            if "tool_calls" in extracted:
                                response_delta["tool_calls"] = extracted["tool_calls"]

                            if not response_delta:
                                continue

                            response_chunk = {
                                'id': f"chatcmpl-{int(time.time() * 1000)}",
                                'object': 'chat.completion.chunk',
                                'created': int(time.time()),
                                'model': model,
                                'choices': [
                                    {
                                        'index': 0,
                                        'delta': response_delta,
                                        'finish_reason': None
                                    }
                                ]
                            }
                            yield f"data: {json.dumps(response_chunk)}\n\n"

                    except Exception as e:
                        logger.debug(f"Responses stream parse error: {e}")
                        continue

    def _extract_responses_content(self, chunk: Dict[str, Any]) -> Dict[str, Any] | None:
        """从 Responses API 的流式 chunk 中提取内容"""
        chunk_type = chunk.get("type", "")

        # 文本增量
        if chunk_type == "response.output_text.delta":
            return {"content": chunk.get("delta", "")}

        if chunk_type == "content_block_delta":
            delta = chunk.get("delta", {})
            if delta.get("type") == "text_delta":
                return {"content": delta.get("text", "")}

        # 工具调用开始
        if chunk_type == "response.output_item.added":
            item = chunk.get("item", {})
            if item.get("type") == "function_call":
                return {
                    "tool_calls": [{
                        "index": chunk.get("output_index", 0),
                        "id": item.get("call_id", item.get("id", "")),
                        "type": "function",
                        "function": {
                            "name": item.get("name", ""),
                            "arguments": ""
                        }
                    }]
                }

        # 工具调用参数增量
        if chunk_type == "response.function_call_arguments.delta":
            return {
                "tool_calls": [{
                    "index": chunk.get("output_index", 0),
                    "function": {
                        "arguments": chunk.get("delta", "")
                    }
                }]
            }

        # 尝试从 output 中提取
        if "output" in chunk:
            output = chunk["output"]
            if isinstance(output, list):
                for item in output:
                    if item.get("type") == "message":
                        content = item.get("content", [])
                        for c in content:
                            if c.get("type") == "output_text":
                                return {"content": c.get("text", "")}

        return None

    async def responses_chat(
            self,
            messages: List[Dict[str, Any]],
            model: str = "gpt-5-codex",
            temperature: float = 0.7,
            **kwargs
    ) -> Dict[str, Any]:
        """使用 /responses API 的非流式聊天接口，输出转换为 Chat Completions 格式"""
        copilot_token = await self.get_copilot_token()
        if not copilot_token:
            raise ValueError("No Copilot token")

        headers = self._build_base_headers(copilot_token, accept="application/json")

        # 转换消息格式
        instructions, input_items = convert_openai_to_responses_format(messages)

        payload = {
            "model": model,
            "stream": False,
        }

        if instructions:
            payload["instructions"] = instructions

        # 添加工具定义（需要转换格式）
        if "tools" in kwargs:
            payload["tools"] = convert_tools_for_responses(kwargs["tools"])
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        if len(input_items) == 1 and input_items[0].get("role") == "user":
            content = input_items[0]["content"]
            if isinstance(content, str):
                payload["input"] = content
            else:
                payload["input"] = input_items
        else:
            payload["input"] = input_items

        logger.debug(f"Responses API payload: {json.dumps(payload, ensure_ascii=False)}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url=copilot_config.responses_url,
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(f"Responses API error, status: {response.status}, message: {error_text}")

                response_data = await response.json()
                logger.debug(f"Responses API response: {json.dumps(response_data, ensure_ascii=False)}")

                extracted = self._extract_responses_full_content(response_data)

                message = {
                    "role": "assistant",
                    "content": extracted["content"],
                }
                if extracted["tool_calls"]:
                    message["tool_calls"] = extracted["tool_calls"]

                finish_reason = "tool_calls" if extracted["tool_calls"] else "stop"

                return {
                    "id": f"chatcmpl-{int(time.time() * 1000)}",
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "message": message,
                            "finish_reason": finish_reason
                        }
                    ],
                    "usage": response_data.get("usage", {})
                }

    def _extract_responses_full_content(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """从 Responses API 的完整响应中提取内容"""
        result = {"content": None, "tool_calls": None}

        if "output_text" in response_data:
            result["content"] = response_data["output_text"]

        output = response_data.get("output", [])
        texts = []
        tool_calls = []

        for item in output:
            item_type = item.get("type", "")

            if item_type == "message":
                content = item.get("content", [])
                for c in content:
                    if c.get("type") == "output_text":
                        texts.append(c.get("text", ""))

            elif item_type == "function_call":
                tool_calls.append({
                    "id": item.get("call_id", item.get("id", "")),
                    "type": "function",
                    "function": {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", "{}")
                    }
                })

        if texts and result["content"] is None:
            result["content"] = "".join(texts)

        if tool_calls:
            result["tool_calls"] = tool_calls

        return result
