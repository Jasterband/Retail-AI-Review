from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api.annotate import router as annotate_router
from app.api.crop_tool import router as crop_router
from app.api.retail_meeting_checks import router as checks_router
from app.config import get_settings
from app.db import init_db
from app.middleware.rate_limit import RateLimitMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    logger.info("DB ready; retail meeting check service %s", __version__)
    yield


app = FastAPI(
    title="药师会零售会议材料检查 API",
    version=__version__,
    description="PE → AI。路径 /v1/retail_meeting_checks；Demo：/demo/；裁剪：/crop/；标注：/annotate/",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(checks_router)
app.include_router(crop_router)
app.include_router(annotate_router)


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/demo/")


@app.get("/v1/demo_config")
def demo_config():
    """给 Demo 前端用的本地配置（Token 取自环境，勿用于生产暴露）。"""
    settings = get_settings()
    tokens = sorted(settings.token_set)
    ocr = (settings.vision_ocr_model or "").strip() or settings.vision_model
    count = (settings.vision_count_model or "").strip() or settings.vision_model
    return {
        "api_base": "",
        "default_token": tokens[0] if tokens else "dev-token-change-me",
        "vision_configured": bool(settings.openai_api_key),
        "vision_model": settings.vision_model,
        "vision_ocr_model": ocr,
        "vision_count_model": count,
        "dual_vision": ocr != count,
        "model_version": settings.model_version,
        "handbook_current_year": settings.handbook_current_year,
    }


def _validation_message(exc: RequestValidationError) -> str:
    msgs = []
    for err in exc.errors():
        msg = str(err.get("msg") or "")
        if msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :]
        loc = ".".join(str(x) for x in (err.get("loc") or ()) if x != "body")
        if loc and msg and loc not in msg:
            msgs.append("{0}: {1}".format(loc, msg))
        elif msg:
            msgs.append(msg)
    return "; ".join(msgs) or "请求体不合法"


@app.exception_handler(RequestValidationError)
async def validation_handler(_request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "SCHEMA_INVALID",
                "message": _validation_message(exc),
                "retryable": False,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(_request: Request, exc: HTTPException):
    # 鉴权等已包装为 {error:{...}} 时原样返回，匹配 AI_接口文档v2
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(Exception)
async def unhandled(_request: Request, exc: Exception):
    logger.exception("unhandled: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "internal error",
                "retryable": True,
            }
        },
    )


# 静态资源（挂在路由之后；样例在 零售照片ai审核/）
_settings = get_settings()
_hall = _settings.hall_samples_dir
_micro = _settings.micro_samples_dir
_fixtures = ROOT / "docs" / "fixtures"
_demo = ROOT / "demo"
_crop = ROOT / "tools" / "crop"
_annotate = ROOT / "tools" / "annotate"

if _hall.is_dir():
    app.mount("/samples/hall", StaticFiles(directory=str(_hall)), name="samples_hall")
if _micro.is_dir():
    app.mount("/samples/micro", StaticFiles(directory=str(_micro)), name="samples_micro")
if _fixtures.is_dir():
    app.mount("/fixtures", StaticFiles(directory=str(_fixtures)), name="fixtures")
if _demo.is_dir():
    app.mount("/demo", StaticFiles(directory=str(_demo), html=True), name="demo")
if _crop.is_dir():
    app.mount("/crop", StaticFiles(directory=str(_crop), html=True), name="crop")
if _annotate.is_dir():
    app.mount(
        "/annotate", StaticFiles(directory=str(_annotate), html=True), name="annotate"
    )
