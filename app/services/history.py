"""审后写入 image_dup_history / topic_history。"""

from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models import ImageDupHistory, TopicHistory
from app.services.pipeline.asset_context import AssetContext
from app.services.text_norm import normalize_topic


def persist_histories(
    db: Session,
    snap: dict,
    contexts: List[AssetContext],
) -> None:
    meeting_id = snap["meeting_id"]
    session_no = snap.get("session_no")
    period_id = snap.get("period_id")
    speakers = {
        s["speaker_id"]: s for s in (snap.get("form") or {}).get("speakers") or []
    }

    for c in contexts:
        if c.ok and c.phash:
            db.add(
                ImageDupHistory(
                    meeting_id=meeting_id,
                    session_no=session_no,
                    period_id=period_id,
                    asset_id=c.asset_id,
                    asset_type=c.declared_type,
                    phash=c.phash,
                    embedding=c.embedding,
                )
            )

        if (
            c.declared_type == "SPEAKER_PHOTO"
            and c.ok
            and (not c.speaker_shot_kind or c.speaker_shot_kind == "TITLE_GROUP")
        ):
            topic = (c.ocr_fields() or {}).get("topic_title")
            if not topic:
                continue
            sp = speakers.get(c.speaker_id) or {}
            db.add(
                TopicHistory(
                    meeting_id=meeting_id,
                    session_no=session_no,
                    period_id=period_id,
                    asset_id=c.asset_id,
                    speaker_name=sp.get("speaker_name") or "",
                    topic_raw=topic,
                    topic_normalized=normalize_topic(topic),
                )
            )
