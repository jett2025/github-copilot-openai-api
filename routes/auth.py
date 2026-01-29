"""
认证路由

处理设备认证和令牌确认等功能。
"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from auth.device_auth import DeviceAuth

router = APIRouter(prefix="/auth", tags=["auth"])

# 设置模板
templates = Jinja2Templates(directory="templates")


@router.get("/device", response_class=HTMLResponse)
async def device_auth(request: Request) -> HTMLResponse:
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


@router.post("/confirm/{device_code}")
async def confirm_auth(device_code: str) -> JSONResponse:
    """确认认证"""
    auth = DeviceAuth()
    result = await auth.confirm_token(device_code)
    return JSONResponse(content=result)
