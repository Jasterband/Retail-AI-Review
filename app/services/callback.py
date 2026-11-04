"""终态 HMAC 回调。"""

from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

import httpx

from app.config import get_settings
from app.services.projection import project_response

logger = logging.getLogger(__name__)


def sign_body(body: bytes, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return "sha256=" + digest


def post_callback(
    callback_url: str,
    request_id: str,
    full_response: Dict[str, Any],
    response_mode: str = "simple",
) -> None:
    settings = get_settings()
    payload = project_response(full_response, response_mode if response_mode in ("simple", "full") else "simple")
    import json

    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Request-Id": request_id,
    }
    if settings.callback_hmac_secret:
        headers["X-Signature"] = sign_body(raw, settings.callback_hmac_secret)

    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(callback_url, content=raw, headers=headers)
        if resp.status_code >= 300:
            logger.warning(
                "callback non-2xx %s for %s: %s",
                resp.status_code,
                request_id,
                resp.text[:200],
            )
        else:
            logger.info("callback ok for %s", request_id)
    except Exception:
        logger.exception("callback failed for %s", request_id)
