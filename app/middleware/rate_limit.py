"""简单滑动窗口限流（按 Bearer token 或客户端 IP）。"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import get_settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, per_minute: int | None = None):
        super().__init__(app)
        self._hits: Dict[str, Deque[float]] = defaultdict(deque)
        self._per_minute = per_minute

    def _limit(self) -> int:
        if self._per_minute is not None:
            return int(self._per_minute)
        return int(get_settings().rate_limit_per_minute or 0)

    def _key(self, request: Request) -> str:
        auth = request.headers.get("authorization") or ""
        if auth.lower().startswith("bearer "):
            return "tok:" + auth[7:].strip()[:64]
        client = request.client.host if request.client else "unknown"
        return "ip:" + client

    async def dispatch(self, request: Request, call_next) -> Response:
        limit = self._limit()
        path = request.url.path or ""
        # 静态 Demo / 健康检查不限流
        if limit <= 0 or path.startswith(
            ("/demo", "/samples", "/fixtures", "/crop", "/annotate", "/v1/annotate")
        ):
            return await call_next(request)
        if path in {"/", "/docs", "/openapi.json", "/redoc"}:
            return await call_next(request)

        key = self._key(request)
        now = time.time()
        window = self._hits[key]
        while window and now - window[0] > 60.0:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "RATE_LIMITED",
                        "message": "请求过于频繁，请稍后再试（{0}/min）".format(limit),
                        "retryable": True,
                    }
                },
                headers={"Retry-After": "60"},
            )
        window.append(now)
        return await call_next(request)
