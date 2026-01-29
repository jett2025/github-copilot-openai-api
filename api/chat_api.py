from typing import List, Dict, Any, AsyncGenerator, Union
import time
import json
import aiohttp
import async_lru
from loguru import logger

# 需要使用 /responses API 的模型列表
RESPONSES_API_MODELS = [
    "gpt-5-codex",
    "gpt-5.1-codex",
    "gpt-5.1-codex-max",
    "gpt-5.2-codex",
    "gpt-5.2-codex-max",
]


def is_responses_model(model: str) -> bool:
    """检查模型是否需要使用 /responses API"""
    model_lower = model.lower()
    return any(m in model_lower for m in ["codex"])


class ChatAPI:
    """聊天 API 实现"""

    def __init__(self, token):
        self.token = token

    async def stream_chat(
            self,
            messages: List[Dict[str, Any]],
            model: str = "gpt-4",
            temperature: float = 0.7,
            **kwargs
    ) -> AsyncGenerator[str, None]:
        """将 GitHub Copilot API 转换为 OpenAI API 兼容的流式聊天接口"""
        # 首先获取 Copilot token
        copilot_token = await self.get_copilot_token()
        if not copilot_token:
            raise ValueError("No Copilot token")

        headers = {
            "authorization": f"Bearer {copilot_token}",
            "accept-language": "en-US,en;q=0.9",
            "editor-plugin-version": "copilot-chat/0.25.2025021001",
            "openai-intent": "conversation-panel",
            "editor-version": "vscode/1.98.0-insider",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        # 检查是否包含图片请求，如果包含则添加必要的 Header
        is_vision = False
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        is_vision = True
                        break
            if is_vision:
                break
        
        if is_vision:
            headers["Copilot-Vision-Request"] = "true"

        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "stream": True,
        }
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        logger.debug(f"Chat API stream request: model={model}, messages_count={len(messages)}, tools_count={len(kwargs.get('tools', []))}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url="https://api.githubcopilot.com/chat/completions",
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    # 详细记录错误信息用于调试
                    logger.error(f"Chat API error: model={model}, status={response.status}, error={error_text}")
                    # 记录消息结构以便调试
                    for i, msg in enumerate(messages):
                        msg_info = f"msg[{i}]: role={msg.get('role')}, has_content={msg.get('content') is not None}, has_tool_calls={'tool_calls' in msg}"
                        logger.debug(msg_info)
                    raise ValueError(f"status code ：{response.status}，error message：{error_text}")

                async for line in response.content:
                    try:
                        line = line.decode('utf-8').strip()
                        if not line:
                            continue

                        if line.startswith('data: '):
                            data = line[6:].strip()
                        else:
                            # 兼容 Cherry Studio 等可能出现的非标准格式
                            data = line.strip()

                        if data == '[DONE]':
                            yield 'data: [DONE]\n\n'
                            break

                        try:
                            chunk = json.loads(data)
                        except json.JSONDecodeError:
                            # 如果这一行不是有效的 JSON，跳过
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

                    except Exception as e:
                        continue

    @async_lru.alru_cache(ttl=2 * 60 * 60)
    async def get_copilot_token(self) -> str:
        """获取 Copilot token"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                    url="https://api.github.com/copilot_internal/v2/token",
                    headers={
                        "Authorization": f"Bearer {self.token}",
                        "Accept": "application/json",
                        "User-Agent": "Mozilla/5.0",
                    }
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(
                        f"Get token error, status code: {response.status}, error messaget Copilot: {error_text}")

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
        # 首先获取 Copilot token
        copilot_token = await self.get_copilot_token()
        if not copilot_token:
            raise ValueError("No Copilot token")

        headers = {
            "authorization": f"Bearer {copilot_token}",
            "accept-language": "en-US,en;q=0.9",
            "editor-plugin-version": "copilot-chat/0.25.2025021001",
            "openai-intent": "conversation-panel",
            "editor-version": "vscode/1.98.0-insider",
            "content-type": "application/json",
            "accept": "application/json",
        }

        # 检查是否包含图片请求，如果包含则添加必要的 Header
        is_vision = False
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        is_vision = True
                        break
            if is_vision:
                break

        if is_vision:
            headers["Copilot-Vision-Request"] = "true"

        payload = {
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "stream": False,
        }
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        logger.debug(f"Chat API payload: model={model}, tools_count={len(kwargs.get('tools', []))}")

        async with aiohttp.ClientSession() as session:
            async with session.post(
                    url="https://api.githubcopilot.com/chat/completions",
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

                # 构造符合 OpenAI API 规范的响应格式
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

    def _convert_messages_to_responses_input(
            self,
            messages: List[Dict[str, Any]]
    ) -> tuple[str, List[Dict[str, Any]]]:
        """将 Chat Completions 格式的 messages 转换为 Responses API 格式的 input

        返回: (instructions, input) - system prompt 和 input 列表

        Responses API 格式说明:
        - 用户消息: {"role": "user", "content": [...]}
        - 助手消息: {"type": "message", "role": "assistant", "content": [...]}
        - 工具调用: {"type": "function_call", "call_id": "...", "name": "...", "arguments": "..."}
        - 工具结果: {"type": "function_call_output", "call_id": "...", "output": "..."}
        """
        instructions = ""
        input_items = []

        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            if role == "system":
                # system 消息转为 instructions
                if isinstance(content, list):
                    instructions = "".join(
                        item.get("text", "") for item in content if item.get("type") == "text"
                    )
                else:
                    instructions = content

            elif role == "tool":
                # Chat Completions 的 tool 消息 -> Responses API 的 function_call_output
                tool_call_id = msg.get("tool_call_id", "")
                output = content if isinstance(content, str) else json.dumps(content)
                input_items.append({
                    "type": "function_call_output",
                    "call_id": tool_call_id,
                    "output": output
                })

            elif role == "assistant":
                # 处理 tool_calls - 转换为 function_call items
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id", "")
                        tc_function = tc.get("function", {})
                        input_items.append({
                            "type": "function_call",
                            "call_id": tc_id,
                            "name": tc_function.get("name", ""),
                            "arguments": tc_function.get("arguments", "{}")
                        })

                # 如果有文本内容，添加为 message item
                if content:
                    converted_content = self._convert_content_types(content, role)
                    input_items.append({
                        "type": "message",
                        "role": role,
                        "content": converted_content if isinstance(converted_content, list) else [{"type": "output_text", "text": converted_content}]
                    })

            else:
                # user 消息
                converted_content = self._convert_content_types(content, role)
                input_items.append({
                    "role": role,
                    "content": converted_content
                })

        return instructions, input_items

    def _convert_content_types(self, content: Any, role: str) -> Any:
        """转换 content 中的类型以适配 Responses API

        Responses API 支持的类型:
        - input_text: 用户输入文本
        - input_image: 用户输入图片
        - input_file: 用户输入文件
        - output_text: 助手输出文本
        - refusal: 拒绝响应
        - summary_text: 摘要文本
        """
        if isinstance(content, str):
            return content

        if not isinstance(content, list):
            return content

        converted = []
        for item in content:
            if not isinstance(item, dict):
                converted.append(item)
                continue

            item_type = item.get("type", "")

            if item_type == "text":
                # 根据角色转换类型
                if role == "assistant":
                    converted.append({
                        "type": "output_text",
                        "text": item.get("text", "")
                    })
                else:
                    converted.append({
                        "type": "input_text",
                        "text": item.get("text", "")
                    })
            elif item_type == "image_url":
                # 转换图片格式
                image_url = item.get("image_url", {})
                url = image_url.get("url", "") if isinstance(image_url, dict) else image_url
                converted.append({
                    "type": "input_image",
                    "image_url": url
                })
            elif item_type in ("input_text", "output_text", "input_image", "input_file", "refusal", "summary_text"):
                # 已经是正确的类型，直接保留
                converted.append(item)
            else:
                # 其他类型尝试原样保留
                converted.append(item)

        return converted

    def _convert_tools_for_responses(self, tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """将 Chat Completions 格式的 tools 转换为 Responses API 格式

        Chat Completions 格式:
        {"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}

        Responses API 格式:
        {"type": "function", "name": "...", "description": "...", "parameters": {...}}
        """
        converted = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                func = tool["function"]
                converted.append({
                    "type": "function",
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {})
                })
            else:
                # 已经是正确格式或其他类型，原样保留
                converted.append(tool)
        return converted

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

        headers = {
            "authorization": f"Bearer {copilot_token}",
            "accept-language": "en-US,en;q=0.9",
            "editor-plugin-version": "copilot-chat/0.25.2025021001",
            "openai-intent": "conversation-panel",
            "editor-version": "vscode/1.104.0",
            "content-type": "application/json",
            "accept": "text/event-stream",
        }

        # 转换消息格式
        instructions, input_items = self._convert_messages_to_responses_input(messages)

        payload = {
            "model": model,
            "stream": True,
        }

        # 如果有 instructions，添加到 payload
        if instructions:
            payload["instructions"] = instructions

        # 添加工具定义（需要转换格式）
        if "tools" in kwargs:
            payload["tools"] = self._convert_tools_for_responses(kwargs["tools"])
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        # input 可以是字符串或消息列表
        if len(input_items) == 1 and input_items[0]["role"] == "user":
            # 简单情况：只有一条用户消息
            content = input_items[0]["content"]
            if isinstance(content, str):
                payload["input"] = content
            else:
                payload["input"] = input_items
        else:
            payload["input"] = input_items

        logger.debug(f"Responses API payload: {json.dumps(payload, ensure_ascii=False)}")

        # 创建自定义的 TCPConnector，增加缓冲区大小
        connector = aiohttp.TCPConnector(limit=100)
        timeout = aiohttp.ClientTimeout(total=300)

        async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
            async with session.post(
                    url="https://api.githubcopilot.com/responses",
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(f"Responses API error, status: {response.status}, message: {error_text}")

                # 使用 iter_any() 来避免 "Chunk too big" 错误
                buffer = ""
                async for chunk in response.content.iter_any():
                    try:
                        buffer += chunk.decode('utf-8')

                        # 按行分割处理
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

                            # 解析 Responses API 的流式输出并转换为 Chat Completions 格式
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
        """从 Responses API 的流式 chunk 中提取内容（文本或工具调用）

        返回: {"content": "text"} 或 {"tool_calls": [...]} 或 None
        """
        # Responses API 流式输出格式可能有多种形式
        # 1. {"type": "response.output_text.delta", "delta": "text"}
        # 2. {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
        # 3. {"type": "response.function_call_arguments.delta", ...}
        # 4. {"type": "response.output_item.added", "item": {"type": "function_call", ...}}

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

        headers = {
            "authorization": f"Bearer {copilot_token}",
            "accept-language": "en-US,en;q=0.9",
            "editor-plugin-version": "copilot-chat/0.25.2025021001",
            "openai-intent": "conversation-panel",
            "editor-version": "vscode/1.104.0",
            "content-type": "application/json",
            "accept": "application/json",
        }

        # 转换消息格式
        instructions, input_items = self._convert_messages_to_responses_input(messages)

        payload = {
            "model": model,
            "stream": False,
        }

        if instructions:
            payload["instructions"] = instructions

        # 添加工具定义（需要转换格式）
        if "tools" in kwargs:
            payload["tools"] = self._convert_tools_for_responses(kwargs["tools"])
        if "tool_choice" in kwargs:
            payload["tool_choice"] = kwargs["tool_choice"]

        if len(input_items) == 1 and input_items[0]["role"] == "user":
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
                    url="https://api.githubcopilot.com/responses",
                    headers=headers,
                    json=payload
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise ValueError(f"Responses API error, status: {response.status}, message: {error_text}")

                response_data = await response.json()
                logger.debug(f"Responses API response: {json.dumps(response_data, ensure_ascii=False)}")

                # 从 Responses API 响应中提取内容
                extracted = self._extract_responses_full_content(response_data)

                # 构建 message 对象
                message = {
                    "role": "assistant",
                    "content": extracted["content"],
                }
                if extracted["tool_calls"]:
                    message["tool_calls"] = extracted["tool_calls"]

                # 确定 finish_reason
                finish_reason = "tool_calls" if extracted["tool_calls"] else "stop"

                # 转换为 Chat Completions 格式
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
        """从 Responses API 的完整响应中提取内容（文本和工具调用）

        返回: {"content": "text", "tool_calls": [...]}
        """
        result = {"content": None, "tool_calls": None}

        # 尝试使用 output_text 快捷方式
        if "output_text" in response_data:
            result["content"] = response_data["output_text"]

        # 从 output 数组中提取
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
                # Responses API 的工具调用格式
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
