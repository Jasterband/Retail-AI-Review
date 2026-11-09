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
    meeting_no = snap.get("meeting_no")
    project_id = snap.get("project_id")
    speakers = {
        s["speaker_id"]: s for s in (snap.get("form") or {}).get("speakers") or []
    }

    for c in contexts:
        if c.ok and c.phash:
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

        if c.photo_type == "SpeakerTitle" and c.ok:
            topic = (c.ocr_fields() or {}).get("topic_title")
            if not topic:
                continue
            sp = speakers.get(c.speaker_id) or {}
            db.add(
                TopicHistory(
                    meeting_id=meeting_id,
                    meeting_no=meeting_no,
                    project_id=project_id,
                    photo_id=c.photo_id,
                    speaker_name=sp.get("speaker_name") or "",
                    topic_raw=topic,
                    topic_normalized=normalize_topic(topic),
                )
            )
