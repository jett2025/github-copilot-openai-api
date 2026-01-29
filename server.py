import json
import os
import time
import uvicorn
from fastapi import FastAPI
from loguru import logger
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import (
    StreamingResponse,
    HTMLResponse,
    RedirectResponse,
    JSONResponse,
)
from fastapi.templating import Jinja2Templates

from api.chat_stream import run_stream, run
from auth.device_auth import DeviceAuth

app = FastAPI(title="GitHub Copilot API")

DEFAULT_API_KEY = ""

# 默认模型映射配置
DEFAULT_MODEL_MAPPING = {
    "gpt-o4-mini": "claude-opus-4.5",
    "gpt-4o-mini": "claude-opus-4.5",
    "claude-opus-4-5-20251101": "claude-opus-4.5",
    "claude-sonnet-4-5-20250929": "claude-sonnet-4.5",
    "claude-haiku-4-5-20251001": "claude-haiku-4.5",
}

# 从环境变量读取模型映射，支持 JSON 格式
def load_model_mapping() -> dict:
    """从环境变量加载模型映射配置"""
    env_mapping = os.getenv("MODEL_MAPPING", "")
    if env_mapping:
        try:
            custom_mapping = json.loads(env_mapping)
            logger.info(f"Loaded custom model mapping from environment: {custom_mapping}")
            return custom_mapping
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse MODEL_MAPPING environment variable: {e}, using default mapping")
    return DEFAULT_MODEL_MAPPING

MODEL_MAPPING = load_model_mapping()

# 设置模板
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源
    allow_credentials=True,
    allow_methods=["*"],  # 允许所有 HTTP 方法，包括 OPTIONS
    allow_headers=["*"],  # 允许所有请求头
)


@app.get("/", response_class=HTMLResponse)
async def root():
    """重定向到设备认证页面"""
    return RedirectResponse(url="/auth/device")


@app.get("/auth/device", response_class=HTMLResponse)
async def device_auth(request: Request):
    """设备认证页面"""
    auth = DeviceAuth()
    auth_info = await auth.new_get_token()

    if "error" in auth_info:
        return HTMLResponse(content=f"<h1>错误</h1><p>{auth_info['error']}</p>")

    return templates.TemplateResponse(
        "auth.html",
        {
            "request": request,
            "user_code": auth_info["user_code"],
            "verification_uri": auth_info["verification_uri"],
            "device_code": auth_info["device_code"],
        },
    )


@app.post("/auth/confirm/{device_code}")
async def confirm_auth(device_code: str):
    """确认认证"""
    auth = DeviceAuth()
    result = await auth.confirm_token(device_code)
    return JSONResponse(content=result)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """处理聊天完成请求，支持 OpenAI API 兼容的流式输出"""
    try:
        logger.debug(
            "Received request: {}", str(await request.body(), encoding="utf-8")
        )
        # 校验header
        headers = request.headers
        api_key = headers.get("Authorization")
        server_auth_key = os.getenv("API_KEY", DEFAULT_API_KEY)
        if server_auth_key:
            if not api_key:
                return {
                    "error": {
                        "message": "invalid token",
                        "type": "invalid_request_error",
                    }
                }, 401
            if api_key != "Bearer " + server_auth_key:
                return {
                    "error": {
                        "message": "invalid token",
                        "type": "invalid_request_error",
                    }
                }, 401

        data = await request.json()
        model_name = data.get("model", "")
        # 模型映射逻辑
        if model_name in MODEL_MAPPING:
            target_model = MODEL_MAPPING[model_name]
            logger.info(f"Model mapping: {model_name} -> {target_model}")
            data["model"] = target_model
        else:
            logger.info(f"Request model: {model_name}")

        messages = data.get("messages", [])
        stream = data.get("stream", False)
        if not messages:
            logger.debug("No messages received")
            return {
                "error": {
                    "message": "no messages found",
                    "type": "invalid_request_error",
                }
            }, 400

        if stream:
            # 处理流式请求
            # 设置 SSE 响应头
            headers = {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "X-Accel-Buffering": "no",
            }

            async def event_generator():
                try:
                    async for chunk in run_stream(data):
                        logger.debug(chunk)
                        yield chunk
                except Exception as e:
                    logger.exception("Exception occurred: {}", e)
                    error_response = json.dumps(
                        {"error": {"message": str(e), "type": "stream_error"}}
                    )
                    yield f"data: {error_response}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                event_generator(), media_type="text/event-stream", headers=headers
            )
        else:
            # 处理非流式请求
            try:
                response = await run(data)
                logger.debug(f"Non-streaming response: {response}")
                return JSONResponse(content=response)
            except Exception as e:
                logger.exception("Exception occurred: {}", e)
                return JSONResponse(
                    status_code=500,
                    content={"error": {"message": str(e), "type": "server_error"}},
                )
    except ValueError as e:
        logger.exception("Exception occurred: {}", e)
        return JSONResponse(
            status_code=401,
            content={"error": {"message": str(e), "type": "auth_error"}},
        )
    except Exception as e:
        logger.exception("Exception occurred: {}", e)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": "server_error"}},
        )


@app.post("/v1/messages")
async def claude_messages(request: Request):
    """处理 Claude API 兼容的消息请求"""
    try:
        # 1. 认证
        headers = request.headers
        api_key = headers.get("Authorization")
        server_auth_key = os.getenv("API_KEY", DEFAULT_API_KEY)
        if server_auth_key:
            if not api_key or api_key != "Bearer " + server_auth_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "error": {
                            "message": "invalid token",
                            "type": "authentication_error",
                        }
                    },
                )

        # 2. 解析 Claude 请求
        claude_data = await request.json()
        model_name = claude_data.get("model", "")
        target_model = MODEL_MAPPING.get(model_name, model_name)
        if model_name != target_model:
            logger.info(f"Claude model mapping: {model_name} -> {target_model}")
        else:
            logger.info(f"Claude request model: {model_name}")

        # 转换消息格式 (Claude -> OpenAI)
        messages = []
        system_prompt = claude_data.get("system")
        if system_prompt:
            # 统一处理 system prompt，确保 content 是字符串
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
            internal_data["tools"] = openai_tools

        if stream:

            async def claude_event_generator():
                yield f'event: message_start\ndata: {{"type": "message_start", "message": {{"id": "msg_{int(time.time())}", "type": "message", "role": "assistant", "content": [], "model": "{target_model}", "usage": {{"input_tokens": 0, "output_tokens": 0}}}}}}\n\n'

                content_index = 0
                tool_index = 0
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
                                    tc_index = tc.get("index", 0)
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

                except Exception as e:
                    logger.exception("Claude stream error: {}", e)

                # 关闭所有 content block
                if has_text_block or current_tool_call:
                    yield f'event: content_block_stop\ndata: {{"type": "content_block_stop", "index": {content_index}}}\n\n'

                stop_reason = "tool_use" if current_tool_call else "end_turn"
                yield f'event: message_delta\ndata: {{"type": "message_delta", "delta": {{"stop_reason": "{stop_reason}", "stop_sequence": null}}, "usage": {{"output_tokens": 0}}}}\n\n'
                yield f'event: message_stop\ndata: {{"type": "message_stop"}}\n\n'

            return StreamingResponse(
                claude_event_generator(), media_type="text/event-stream"
            )
        else:
            response = await run(internal_data)
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

            claude_response = {
                "id": f"msg_{int(time.time())}",
                "type": "message",
                "role": "assistant",
                "content": claude_content,
                "model": target_model,
                "stop_reason": stop_reason,
                "usage": {
                    "input_tokens": response.get("usage", {}).get("prompt_tokens", 0),
                    "output_tokens": response.get("usage", {}).get("completion_tokens", 0),
                },
            }
            return JSONResponse(content=claude_response)

    except Exception as e:
        logger.exception("Claude API Exception: {}", e)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": "server_error"}},
        )


@app.get("/v1/models")
async def models():
    """返回支持的模型列表"""
    return {
        "object": "list",
        "data": [
            {"id": "gpt-5.1-codex-max", "object": "model"},
            {"id": "gpt-5.2-codex", "object": "model"},
            {"id": "gpt-5.2", "object": "model"},
            {"id": "claude-sonnet-4.5", "object": "model"},
            {"id": "claude-opus-4.5", "object": "model"},
            {"id": "claude-haiku-4.5", "object": "model"},
            {"id": "gemini-3-pro-preview", "object": "model"},
            {"id": "gemini-3-flash-preview", "object": "model"},
        ],
    }


@app.post("/v1/responses")
async def responses_api(request: Request):
    """处理 OpenAI Responses API 请求，转发到 /chat/completions 处理"""
    try:
        data = await request.json()
        model = data.get("model", "")
        input_data = data.get("input", "")
        instructions = data.get("instructions", "")
        stream = data.get("stream", False)

        # 将 Responses API 格式转换为 Chat Completions 格式
        messages = []
        if instructions:
            messages.append({"role": "system", "content": instructions})

        if isinstance(input_data, str):
            messages.append({"role": "user", "content": input_data})
        elif isinstance(input_data, list):
            messages.extend(input_data)

        # 构造 chat completions 请求数据
        chat_data = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }

        logger.info(f"Responses API -> Chat Completions: model={model}, stream={stream}")

        if stream:
            headers = {
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            }

            async def event_generator():
                try:
                    async for chunk in run_stream(chat_data):
                        yield chunk
                except Exception as e:
                    logger.exception("Responses stream error: {}", e)
                    yield f'data: {json.dumps({"error": {"message": str(e)}})}\n\n'
                yield "data: [DONE]\n\n"

            return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)
        else:
            response = await run(chat_data)
            # 转换为 Responses API 格式
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            return JSONResponse(content={
                "id": response.get("id", f"resp_{int(time.time())}"),
                "object": "response",
                "created_at": response.get("created", int(time.time())),
                "model": model,
                "output": [
                    {
                        "type": "message",
                        "role": "assistant",
                        "content": [{"type": "output_text", "text": content}]
                    }
                ],
                "output_text": content,
                "usage": response.get("usage", {})
            })

    except Exception as e:
        logger.exception("Responses API error: {}", e)
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(e), "type": "server_error"}}
        )


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", 8000))
    logger.debug(f"Starting server on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)
