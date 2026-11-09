"""OpenAI 兼容多模态 Chat Completions 客户端。"""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.config import Settings, get_settings
from app.services.vision.prompts import (
    KEY_FIELDS_ROI_PROMPT,
    NAME_CARD_LOCATE_PROMPT,
    NAME_CARD_ROI_PROMPT,
    SYSTEM,
    user_prompt,
)

logger = logging.getLogger(__name__)


class VisionError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = True):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        data = json.loads(m.group(0))
        if isinstance(data, dict):
            return data
    raise VisionError("MODEL_BAD_RESPONSE", "vision response is not JSON", retryable=True)


def _data_url(image_bytes: bytes, content_type: str) -> str:
    mime = content_type or "image/jpeg"
    if mime == "application/pdf":
        mime = "image/jpeg"
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return "data:{0};base64,{1}".format(mime, b64)


# 偏 OCR / 字段抽取的材料类型
_OCR_TYPES = {
    "Poster",
    "Stand",
    "EDM",
    "EDMDisplay",
    "ProjectIntro",
    "TableCard",
    "Manual",
    "SpeakerTitle",
    "SignSheet",
}
# 偏数人的材料类型
_COUNT_TYPES = {"Panorama"}


class VisionClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()

    def available(self) -> bool:
        return bool(self.settings.openai_api_key)

    def model_for(self, photo_type: str) -> str:
        """双模型分流：全景用 count 模型，其余优先 OCR 模型。"""
        base = self.settings.vision_model
        ocr = (self.settings.vision_ocr_model or "").strip() or base
        count = (self.settings.vision_count_model or "").strip() or base
        if photo_type in _COUNT_TYPES:
            return count
        if photo_type in _OCR_TYPES:
            return ocr
        return base

    def _chat(
        self,
        user_content: List[Dict[str, Any]],
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.settings.openai_api_key:
            raise VisionError(
                "MODEL_UNAVAILABLE",
                "OPENAI_API_KEY not configured",
                retryable=True,
            )
        url = self.settings.openai_base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": "Bearer {0}".format(self.settings.openai_api_key),
            "Content-Type": "application/json",
        }
        payload = {
            "model": model or self.settings.vision_model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_content},
            ],
        }
        last_err: Optional[Exception] = None
        for attempt in range(self.settings.vision_max_retries + 1):
            try:
                with httpx.Client(timeout=self.settings.vision_timeout_sec) as client:
                    resp = client.post(url, headers=headers, json=payload)
                if resp.status_code in (401, 403):
                    raise VisionError(
                        "MODEL_UNAVAILABLE",
                        "auth failed: {0}".format(resp.status_code),
                        retryable=False,
                    )
                if resp.status_code == 429:
                    last_err = VisionError(
                        "MODEL_UNAVAILABLE", "rate limited", retryable=True
                    )
                    continue
                if resp.status_code >= 500:
                    last_err = VisionError(
                        "MODEL_TIMEOUT",
                        "server {0}".format(resp.status_code),
                        retryable=True,
                    )
                    continue
                if resp.status_code >= 400:
                    raise VisionError(
                        "MODEL_UNAVAILABLE",
                        "HTTP {0}: {1}".format(resp.status_code, resp.text[:300]),
                        retryable=False,
                    )
                body = resp.json()
                content = (
                    body.get("choices") or [{}]
                )[0].get("message", {}).get("content") or ""
                return _extract_json(content)
            except VisionError:
                raise
            except httpx.TimeoutException as e:
                last_err = VisionError("MODEL_TIMEOUT", str(e), retryable=True)
            except Exception as e:
                last_err = VisionError("MODEL_UNAVAILABLE", str(e), retryable=True)
                logger.exception("vision attempt %s failed", attempt)

        if isinstance(last_err, VisionError):
            raise last_err
        raise VisionError("MODEL_UNAVAILABLE", "vision failed", retryable=True)

    def analyze(
        self,
        image_bytes: bytes,
        content_type: str,
        photo_type: str,
        project_type: str,
    ) -> Dict[str, Any]:
        model = self.model_for(photo_type)
        data = self._chat(
            [
                {
                    "type": "text",
                    "text": user_prompt(photo_type, project_type),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(image_bytes, content_type)},
                },
            ],
            model=model,
        )
        # 便于调试：记录本张实际用的模型
        if isinstance(data, dict):
            data.setdefault("_vision_model", model)
        return data

    def ocr_key_fields_roi(
        self,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> Dict[str, Any]:
        """对已裁好的字段区 ROI 做关键字段 OCR（日期/时间/地点/讲者）。"""
        model = self.model_for("Poster")
        data = self._chat(
            [
                {"type": "text", "text": KEY_FIELDS_ROI_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(image_bytes, content_type)},
                },
            ],
            model=model,
        )
        return data if isinstance(data, dict) else {}

    def ocr_name_card_roi(
        self,
        image_bytes: bytes,
        content_type: str = "image/jpeg",
    ) -> Dict[str, Any]:
        """对已裁好的单张台卡 ROI 抽取姓名。"""
        model = self.model_for("TableCard")
        data = self._chat(
            [
                {"type": "text", "text": NAME_CARD_ROI_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(image_bytes, content_type)},
                },
            ],
            model=model,
        )
        return data if isinstance(data, dict) else {}

    def locate_name_cards(
        self,
        scene_bytes: bytes,
        ref_bytes: bytes,
        scene_type: str = "image/jpeg",
        ref_type: str = "image/jpeg",
    ) -> Dict[str, Any]:
        """对照单卡参考 crop，在现场图中定位各台卡框。"""
        model = self.model_for("TableCard")
        data = self._chat(
            [
                {"type": "text", "text": NAME_CARD_LOCATE_PROMPT},
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(ref_bytes, ref_type)},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(scene_bytes, scene_type)},
                },
            ],
            model=model,
        )
        return data if isinstance(data, dict) else {}

    def compare_reference(
        self,
        scene_bytes: bytes,
        scene_type: str,
        ref_bytes: bytes,
        ref_type: str,
        question: str,
    ) -> Dict[str, Any]:
        """对照参考图，返回 {score, hit, method, match, confidence}。"""
        data = self._chat(
            [
                {"type": "text", "text": question},
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(ref_bytes, ref_type)},
                },
                {
                    "type": "image_url",
                    "image_url": {"url": _data_url(scene_bytes, scene_type)},
                },
            ]
        )
        match = data.get("match")
        try:
            conf = float(
                data.get("confidence") if data.get("confidence") is not None else 0.5
            )
        except (TypeError, ValueError):
            conf = 0.5
        conf = max(0.0, min(1.0, conf))
        if match is True:
            return {
                "score": round(conf, 4),
                "hit": conf >= 0.6,
                "uncertain": conf < 0.6,
                "method": "vision_ref",
                "raw": data,
            }
        if match is False:
            return {
                "score": round(max(0.0, 1.0 - conf), 4),
                "hit": False,
                "uncertain": conf < 0.55,
                "method": "vision_ref",
                "raw": data,
            }
        return {
            "score": round(conf, 4),
            "hit": False,
            "uncertain": True,
            "method": "vision_ref",
            "raw": data,
        }
