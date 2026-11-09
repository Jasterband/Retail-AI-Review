#!/usr/bin/env python3
"""用伪造 vision JSON 跑规则聚合，验证 PASS / IMAGE_DUP 命中（不调模型）。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.db import SessionLocal, init_db
from app.models import ImageDupHistory
from app.services.history import persist_histories
from app.services.phash_util import compute_phash
from app.services.pipeline.aggregate import build_full_response
from app.services.pipeline.asset_context import AssetContext
from app.services.rules.engine import run_all_rules
from app.services.asset_fetch import fetch_object


def _ctx(asset: dict, vision: dict, body=None) -> AssetContext:
    c = AssetContext(
        photo_id=asset["photo_id"],
        photo_type=asset["photo_type"],
        file_url=asset["file_url"],
        content_type=asset.get("content_type") or "image/jpeg",
        speaker_id=asset.get("speaker_id"),
        body=body or b"x",
        vision=vision,
        phash=compute_phash(body) if body else "ffffffffffffffff",
    )
    return c


def hall_contexts(snap: dict) -> list:
    form = snap["form"]
    names = [s["speaker_name"] for s in form["speakers"]]
    poster = fetch_object("s3://pe-meetings/hall/143/poster.jpg", "image/jpeg")
    assert poster.body
    out = []
    for a in snap["photos"]:
        t = a["photo_type"]
        v = {
            "clarity_score": 0.92,
            "detected_type": t,
            "type_confidence": 0.95,
            "has_bayer_logo": t in ("Poster", "Stand", "EDM"),
            "logo_confidence": 0.9,
            "handbook_ok": True if t == "Manual" else None,
            "handbook_year": 2026 if t == "Manual" else None,
            "ocr_fields": {
                "meeting_date": form.get("meeting_date") or "2026-06-23",
                "start_time": form.get("start_time") or "14:00",
                "end_time": form.get("end_time") or "16:10",
                "meeting_location": form["meeting_location"],
                "speaker_names": names,
                "has_watermark": False,
            },
            "people_count": 36 if t == "Panorama" else None,
            "people_count_confidence": 0.85,
            "name_card_names": names if t == "TableCard" else None,
            "is_standard_name_card_style": True if t == "TableCard" else None,
            "name_card_style_confidence": 0.9,
            "signin": {
                "start_time": form.get("start_time") or "14:00",
                "end_time": form.get("end_time") or "16:10",
                "duration_minutes": 130,
                "audience_count": 31,
                "store_names": ["美锐A", "美锐B"],
            }
            if t == "SignSheet"
            else None,
        }
        if t == "SpeakerTitle":
            sp = next(
                s for s in form["speakers"] if s["speaker_id"] == a["speaker_id"]
            )
            v["ocr_fields"]["topic_title"] = sp["topic"]
            v["ocr_fields"]["speaker_name_on_slide"] = sp["speaker_name"]
        body = poster.body if t == "Poster" else poster.body
        # unique-ish phash per type by using real file when possible
        fo = fetch_object(a["file_url"], a.get("content_type") or "image/jpeg")
        body = fo.body or poster.body
        out.append(_ctx(a, v, body))
    return out


def main() -> int:
    init_db()
    snap = json.loads(
        (ROOT / "docs/fixtures/hall-meirui-pass.json").read_text(encoding="utf-8")
    )
    ctxs = hall_contexts(snap)
    db = SessionLocal()
    try:
        # clear histories for meeting
        from sqlalchemy import delete

        db.execute(delete(ImageDupHistory))
        db.commit()
        rules = run_all_rules(snap, ctxs, db)
        full = build_full_response(snap, 1, 1, ctxs, rules, [])
        print("overall", full["overall_status"])
        for r in full["rule_results"]:
            print(" ", r["rule_code"], r["status"], r.get("reason_text", "")[:60])
        assert full["overall_status"] == "PASS", full["overall_status"]
        hb = [r for r in rules if r.rule_code.startswith("Manual")]
        assert all(r.status == "PASS" for r in hb), [
            (r.rule_code, r.status, r.reason_text) for r in hb
        ]
        # 资产 checks 应回填关键字段
        poster_ar = next(
            a for a in full["photo_results"] if a["photo_type"] == "Poster"
        )
        assert poster_ar["checks"].get("date_matches_form") is True
        assert poster_ar["checks"].get("has_bayer_logo") is True

        persist_histories(db, snap, ctxs)
        db.commit()

        # second meeting same poster → IMAGE_DUP FAIL
        snap2 = json.loads(
            (ROOT / "docs/fixtures/dup-hit.json").read_text(encoding="utf-8")
        )
        fo = fetch_object(snap2["photos"][0]["file_url"], "image/jpeg")
        ctx2 = [
            _ctx(
                snap2["photos"][0],
                {
                    "clarity_score": 0.9,
                    "detected_type": "Poster",
                    "type_confidence": 0.9,
                    "has_bayer_logo": True,
                    "ocr_fields": {"meeting_date": "2026-04-18", "has_watermark": False},
                },
                fo.body,
            )
        ]
        rules2 = run_all_rules(snap2, ctx2, db)
        dup = next(r for r in rules2 if r.rule_code == "IMAGE_DUP")
        assert dup.status == "FAIL", dup
        print("IMAGE_DUP hit ok")
    finally:
        db.close()

    print("MOCK RULES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
