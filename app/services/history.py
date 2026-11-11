"""审后写入 image_dup_history。"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models import ImageDupHistory
from app.services.image_dup_policy import dup_category
from app.services.pipeline.asset_context import AssetContext


def persist_histories(
    db: Session,
    snap: dict,
    contexts: List[AssetContext],
) -> None:
    meeting_id = snap["meeting_id"]
    meeting_no = snap.get("meeting_no")
    project_id = snap.get("project_id")

    for c in contexts:
        # 仅入库参与 IMAGE_DUP 的类型（有人/无人材料）
        if c.ok and c.phash and dup_category(c.photo_type):
            db.add(
                ImageDupHistory(
                    meeting_id=meeting_id,
                    meeting_no=meeting_no,
                    project_id=project_id,
                    photo_id=c.photo_id,
                    photo_type=c.photo_type,
                    phash=c.phash,
                    embedding=c.embedding,
                )
            )
