"""
Chat Completions 路由

处理 OpenAI API 兼容的 /v1/chat/completions 请求。
"""

import json
from fastapi import APIRouter, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from loguru import logger

from api.chat_stream import run_stream, run
from config import MODEL_MAPPING
from middleware.auth import require_api_key

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat/completions")
async def chat_completions(request: Request, _: None = Depends(require_api_key)) -> StreamingResponse | JSONResponse:
    """处理聊天完成请求，支持 OpenAI API 兼容的流式输出"""
    try:
        logger.debug(
            "Received request: {}", str(await request.body(), encoding="utf-8")
        )

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
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "no messages found",
                        "type": "invalid_request_error",
                    }
                }
            )

        if stream:
            # 处理流式请求
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
