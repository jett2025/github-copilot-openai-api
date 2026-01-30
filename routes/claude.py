"""
Claude Messages 路由

处理 Claude API 兼容的 /v1/messages 请求。
"""

import json
import time
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from loguru import logger

from api.chat_stream import run_stream, run
from config import MODEL_MAPPING
from exceptions import UpstreamAPIError
from middleware.auth import require_api_key
from services.message_converter import (
    convert_claude_to_openai_messages,
    convert_claude_to_openai_tools,
    convert_openai_to_claude_response,
)

router = APIRouter(prefix="/v1", tags=["claude"])


@router.post("/messages", response_model=None)
async def claude_messages(request: Request, _: None = Depends(require_api_key)):
    """处理 Claude API 兼容的消息请求"""
    try:
        # 解析 Claude 请求
        claude_data = await request.json()
        model_name = claude_data.get("model", "")
        target_model = MODEL_MAPPING.get(model_name, model_name)

        if model_name != target_model:
            logger.info(f"Claude model mapping: {model_name} -> {target_model}")
        else:
            logger.info(f"Claude request model: {model_name}")

        # 转换消息格式 (Claude -> OpenAI)
        messages = convert_claude_to_openai_messages(claude_data)
        stream = claude_data.get("stream", False)

        # 构造内部处理数据
        internal_data = {
            "model": target_model,
            "messages": messages,
            "stream": stream,
            "temperature": claude_data.get("temperature", 0.7),
        }

        # 转换工具定义 (Claude -> OpenAI)
        claude_tools = claude_data.get("tools", [])
        if claude_tools:
            internal_data["tools"] = convert_claude_to_openai_tools(claude_tools)

        if stream:
            return StreamingResponse(
                _claude_stream_generator(internal_data, target_model),
                media_type="text/event-stream"
            )
        else:
            response = await run(internal_data)
            claude_response = convert_openai_to_claude_response(response, target_model)
            return JSONResponse(content=claude_response)

    except UpstreamAPIError as e:
        logger.error(f"Upstream API error: {e.message}")
        # Claude API 错误格式
        return JSONResponse(
            status_code=e.status_code,
            content={
                "type": "error",
                "error": {
                    "type": e.error_type,
                    "message": e.message,
                }
            },
        )
    except Exception as e:
        logger.exception("Claude API Exception: {}", e)
        return JSONResponse(
            status_code=500,
            content={
                "type": "error",
                "error": {
                    "type": "server_error",
                    "message": str(e),
                }
            },
        )


async def _claude_stream_generator(internal_data: dict, target_model: str):
    """生成 Claude 格式的流式响应"""
    yield f'event: message_start\ndata: {{"type": "message_start", "message": {{"id": "msg_{int(time.time())}", "type": "message", "role": "assistant", "content": [], "model": "{target_model}", "usage": {{"input_tokens": 0, "output_tokens": 0}}}}}}\n\n'

    content_index = 0
    current_tool_call = None
    has_text_block = False

    try:
        async for chunk_str in run_stream(internal_data):
            if chunk_str.startswith("data: "):
                data_content = chunk_str[6:].strip()
                if data_content == "[DONE]":
                    break
                try:
                    chunk_json = json.loads(data_content)
                except json.JSONDecodeError:
                    continue

                # 检查是否是错误响应
                if "error" in chunk_json:
                    error_info = chunk_json["error"]
                    yield f'event: error\ndata: {{"type": "error", "error": {{"type": "{error_info.get("type", "server_error")}", "message": {json.dumps(error_info.get("message", "Unknown error"))}}}}}\n\n'
                    return

                delta = chunk_json.get("choices", [{}])[0].get("delta", {})

                # 处理文本内容
                text_content = delta.get("content")
                if text_content:
                    if not has_text_block:
                        yield f'event: content_block_start\ndata: {{"type": "content_block_start", "index": {content_index}, "content_block": {{"type": "text", "text": ""}}}}\n\n'
                        has_text_block = True
                    yield f'event: content_block_delta\ndata: {{"type": "content_block_delta", "index": {content_index}, "delta": {{"type": "text_delta", "text": {json.dumps(text_content)}}}}}\n\n'

                # 处理工具调用
                tool_calls = delta.get("tool_calls")
                if tool_calls:
                    for tc in tool_calls:
                        tc_id = tc.get("id")
                        tc_function = tc.get("function", {})
                        tc_name = tc_function.get("name")
                        tc_args = tc_function.get("arguments", "")

                        if tc_id:
                            # 新的工具调用开始
                            if has_text_block:
                                yield f'event: content_block_stop\ndata: {{"type": "content_block_stop", "index": {content_index}}}\n\n'
                                content_index += 1
                                has_text_block = False

                            current_tool_call = {"id": tc_id, "name": tc_name, "input": ""}
                            yield f'event: content_block_start\ndata: {{"type": "content_block_start", "index": {content_index}, "content_block": {{"type": "tool_use", "id": "{tc_id}", "name": "{tc_name}", "input": {{}}}}}}\n\n'

                        if tc_args and current_tool_call:
                            current_tool_call["input"] += tc_args
                            yield f'event: content_block_delta\ndata: {{"type": "content_block_delta", "index": {content_index}, "delta": {{"type": "input_json_delta", "partial_json": {json.dumps(tc_args)}}}}}\n\n'

    except UpstreamAPIError as e:
        logger.error(f"Upstream API error in Claude stream: {e.message}")
        yield f'event: error\ndata: {{"type": "error", "error": {{"type": "{e.error_type}", "message": {json.dumps(e.message)}}}}}\n\n'
        return
    except Exception as e:
        logger.exception("Claude stream error: {}", e)
        yield f'event: error\ndata: {{"type": "error", "error": {{"type": "server_error", "message": {json.dumps(str(e))}}}}}\n\n'
        return

    # 关闭所有 content block
    if has_text_block or current_tool_call:
        yield f'event: content_block_stop\ndata: {{"type": "content_block_stop", "index": {content_index}}}\n\n'

    stop_reason = "tool_use" if current_tool_call else "end_turn"
    yield f'event: message_delta\ndata: {{"type": "message_delta", "delta": {{"stop_reason": "{stop_reason}", "stop_sequence": null}}, "usage": {{"output_tokens": 0}}}}\n\n'
    yield f'event: message_stop\ndata: {{"type": "message_stop"}}\n\n'
