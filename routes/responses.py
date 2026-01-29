"""
Responses API 路由

处理 OpenAI Responses API 请求。
"""

import json
import time
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from loguru import logger

from api.chat_stream import run_stream, run
from middleware.auth import require_api_key

router = APIRouter(prefix="/v1", tags=["responses"])


@router.post("/responses")
async def responses_api(request: Request, _: None = Depends(require_api_key)) -> StreamingResponse | JSONResponse:
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

            return StreamingResponse(
                event_generator(), media_type="text/event-stream", headers=headers
            )
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
