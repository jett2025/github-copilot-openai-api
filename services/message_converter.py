"""
消息格式转换服务

处理 OpenAI 和 Claude API 之间的消息格式转换。
"""

import json
import time
from typing import Any, Dict, List


def convert_claude_to_openai_messages(claude_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    将 Claude API 格式的消息转换为 OpenAI 格式

    Args:
        claude_data: Claude API 请求数据

    Returns:
        OpenAI 格式的消息列表
    """
    messages = []

    # 处理 system prompt
    system_prompt = claude_data.get("system")
    if system_prompt:
        if isinstance(system_prompt, list):
            system_text = "".join(
                [item.get("text", "") for item in system_prompt if item.get("type") == "text"]
            )
            messages.append({"role": "system", "content": system_text})
        else:
            messages.append({"role": "system", "content": system_prompt})

    # 处理用户和助手消息
    for msg in claude_data.get("messages", []):
        role = msg.get("role")
        content = msg.get("content")

        # 转换 Claude 的 content 结构为 OpenAI 结构
        if isinstance(content, list):
            new_content = []
            tool_calls = []

            for item in content:
                item_type = item.get("type")

                if item_type == "text":
                    new_content.append({"type": "text", "text": item.get("text", "")})

                elif item_type == "image":
                    # Claude 格式: {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "..."}}
                    # OpenAI 格式: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
                    source = item.get("source", {})
                    if source.get("type") == "base64":
                        media_type = source.get("media_type")
                        data = source.get("data")
                        new_content.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:{media_type};base64,{data}"}
                        })

                elif item_type == "tool_use":
                    # Claude tool_use -> OpenAI tool_calls
                    tool_calls.append({
                        "id": item.get("id"),
                        "type": "function",
                        "function": {
                            "name": item.get("name"),
                            "arguments": json.dumps(item.get("input", {}))
                        }
                    })

                elif item_type == "tool_result":
                    # Claude tool_result -> OpenAI tool message
                    tool_content = item.get("content", "")
                    if isinstance(tool_content, list):
                        tool_content = "".join(
                            [c.get("text", "") for c in tool_content if c.get("type") == "text"]
                        )
                    messages.append({
                        "role": "tool",
                        "tool_call_id": item.get("tool_use_id"),
                        "content": tool_content
                    })
                    continue  # tool_result 单独处理，不加入当前消息

            if tool_calls:
                # 助手消息包含工具调用
                msg_obj = {"role": role, "content": None, "tool_calls": tool_calls}
                if new_content:
                    # 如果同时有文本内容
                    text_content = "".join([c.get("text", "") for c in new_content if c.get("type") == "text"])
                    if text_content:
                        msg_obj["content"] = text_content
                messages.append(msg_obj)
            elif new_content:
                messages.append({"role": role, "content": new_content})
        else:
            messages.append({"role": role, "content": content})

    return messages


def convert_claude_to_openai_tools(claude_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 Claude API 格式的工具定义转换为 OpenAI 格式

    Args:
        claude_tools: Claude API 工具定义列表

    Returns:
        OpenAI 格式的工具定义列表
    """
    openai_tools = []
    for tool in claude_tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": tool.get("name"),
                "description": tool.get("description", ""),
                "parameters": tool.get("input_schema", {})
            }
        })
    return openai_tools


def convert_openai_to_claude_response(response: Dict[str, Any], model: str) -> Dict[str, Any]:
    """
    将 OpenAI API 响应转换为 Claude 格式

    Args:
        response: OpenAI API 响应
        model: 模型名称

    Returns:
        Claude 格式的响应
    """
    message = response.get("choices", [{}])[0].get("message", {})
    text_content = message.get("content", "")
    tool_calls = message.get("tool_calls") or []  # 确保不为 None

    # 构建 Claude 响应内容
    claude_content = []

    if text_content:
        claude_content.append({"type": "text", "text": text_content})

    # 转换工具调用 (OpenAI -> Claude)
    for tc in tool_calls:
        tc_function = tc.get("function", {})
        try:
            tc_input = json.loads(tc_function.get("arguments", "{}"))
        except json.JSONDecodeError:
            tc_input = {}
        claude_content.append({
            "type": "tool_use",
            "id": tc.get("id"),
            "name": tc_function.get("name"),
            "input": tc_input
        })

    stop_reason = "tool_use" if tool_calls else "end_turn"

    return {
        "id": f"msg_{int(time.time())}",
        "type": "message",
        "role": "assistant",
        "content": claude_content,
        "model": model,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": response.get("usage", {}).get("prompt_tokens", 0),
            "output_tokens": response.get("usage", {}).get("completion_tokens", 0),
        },
    }


def convert_openai_to_responses_format(
    messages: List[Dict[str, Any]]
) -> tuple[str, List[Dict[str, Any]]]:
    """
    将 Chat Completions 格式的 messages 转换为 Responses API 格式

    Args:
        messages: OpenAI Chat Completions 格式的消息列表

    Returns:
        (instructions, input) - system prompt 和 input 列表
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
                converted_content = _convert_content_types(content, role)
                input_items.append({
                    "type": "message",
                    "role": role,
                    "content": converted_content if isinstance(converted_content, list) else [{"type": "output_text", "text": converted_content}]
                })

        else:
            # user 消息
            converted_content = _convert_content_types(content, role)
            input_items.append({
                "role": role,
                "content": converted_content
            })

    return instructions, input_items


def _convert_content_types(content: Any, role: str) -> Any:
    """
    转换 content 中的类型以适配 Responses API

    Args:
        content: 消息内容
        role: 消息角色

    Returns:
        转换后的内容
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


def convert_tools_for_responses(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将 Chat Completions 格式的 tools 转换为 Responses API 格式

    Args:
        tools: Chat Completions 格式的工具列表

    Returns:
        Responses API 格式的工具列表
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
