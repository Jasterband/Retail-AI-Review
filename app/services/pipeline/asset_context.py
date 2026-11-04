"""每张材料的分析上下文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.services.asset_fetch import FetchedObject, fetch_object
from app.services.embedding_util import compute_image_embedding
from app.services.phash_util import compute_phash
from app.services.vision.client import VisionClient, VisionError


@dataclass
class AssetContext:
    asset_id: int
    declared_type: str
    s3_uri: str
    content_type: str
    speaker_id: Optional[int] = None
    speaker_shot_kind: Optional[str] = None
    body: Optional[bytes] = None
    fetch_error_code: Optional[str] = None
    fetch_error_message: Optional[str] = None
    vision: Dict[str, Any] = field(default_factory=dict)
    vision_error: Optional[Dict[str, Any]] = None
    phash: Optional[str] = None
    embedding: Optional[bytes] = None
    template_match: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.body is not None and self.fetch_error_code is None

    def clarity_score(self) -> Optional[float]:
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
    assets: List[dict],
    project_type: str,
    vision: VisionClient,
) -> List[AssetContext]:
    contexts: List[AssetContext] = []
    for a in assets:
        ctx = AssetContext(
            asset_id=a["asset_id"],
            declared_type=a["asset_type"],
            s3_uri=a["s3_uri"],
            content_type=a.get("content_type") or "image/jpeg",
            speaker_id=a.get("speaker_id"),
            speaker_shot_kind=a.get("speaker_shot_kind"),
        )
        fetched: FetchedObject = fetch_object(ctx.s3_uri, ctx.content_type)
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

        try:
            ctx.vision = vision.analyze(
                fetched.body,
                fetched.content_type,
                ctx.declared_type,
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
