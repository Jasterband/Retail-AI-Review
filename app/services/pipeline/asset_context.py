"""每张材料的分析上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.asset_fetch import FetchedObject, fetch_object
from app.services.clarity_util import compute_clarity_score
from app.services.embedding_util import compute_image_embedding
from app.services.phash_util import compute_phash
from app.services.vision.client import VisionClient, VisionError


@dataclass
class AssetContext:
    photo_id: str
    photo_type: str
    file_url: str
    content_type: str
    speaker_id: Optional[str] = None
    body: Optional[bytes] = None
    fetch_error_code: Optional[str] = None
    fetch_error_message: Optional[str] = None
    vision: Dict[str, Any] = field(default_factory=dict)
    vision_error: Optional[Dict[str, Any]] = None
    phash: Optional[str] = None
    embedding: Optional[bytes] = None
    template_match: Dict[str, Any] = field(default_factory=dict)
    local_clarity: Optional[float] = None

    @property
    def ok(self) -> bool:
        return self.body is not None and self.fetch_error_code is None

    def clarity_score(self) -> Optional[float]:
        # 以本地 Laplacian 为准；Vision 估分不稳定，仅作兜底
        if self.local_clarity is not None:
            return self.local_clarity
        v = self.vision.get("clarity_score")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def detected_type(self) -> Optional[str]:
        return self.vision.get("detected_type")

    def ocr_fields(self) -> Dict[str, Any]:
        of = self.vision.get("ocr_fields") or {}
        return of if isinstance(of, dict) else {}


def build_contexts(
    photos: List[dict],
    project_type: str,
    vision: VisionClient,
) -> List[AssetContext]:
    contexts: List[AssetContext] = []
    for a in photos:
        ctx = AssetContext(
            photo_id=a["photo_id"],
            photo_type=a["photo_type"],
            file_url=a["file_url"],
            content_type=a.get("content_type") or "image/jpeg",
            speaker_id=a.get("speaker_id"),
        )
        fetched: FetchedObject = fetch_object(ctx.file_url, ctx.content_type)
        if fetched.error_code:
            ctx.fetch_error_code = fetched.error_code
            ctx.fetch_error_message = fetched.error_message
            contexts.append(ctx)
            continue

        ctx.body = fetched.body
        ctx.content_type = fetched.content_type
        if fetched.body:
            ctx.phash = compute_phash(fetched.body)
            ctx.embedding = compute_image_embedding(fetched.body)
            ctx.local_clarity = compute_clarity_score(fetched.body)

        try:
            ctx.vision = vision.analyze(
                fetched.body,
                fetched.content_type,
                ctx.photo_type,
                project_type,
            )
        except VisionError as e:
            ctx.vision_error = {
                "code": e.code,
                "message": e.message,
                "retryable": e.retryable,
            }
        contexts.append(ctx)
    return contexts
