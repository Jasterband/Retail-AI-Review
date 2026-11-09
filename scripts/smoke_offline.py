#!/usr/bin/env python3
"""不依赖 Vision Key 的冒烟：读图、pHash、无 Key → ERROR。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import AiCheckJob
from app.services.asset_fetch import fetch_object
from app.services.check_runner import run_check_sync
from app.services.phash_util import compute_phash, phash_distance


def main() -> int:
    get_settings.cache_clear()
    settings = get_settings()
    assert (settings.asset_root / "docs/fixtures/s3_local_map.json").exists()

    poster = fetch_object(
        "s3://pe-meetings/hall/143/poster.jpg", "image/jpeg"
    )
    assert poster.body, poster.error_message
    print("fetch poster ok", len(poster.body), "bytes")

    pdf = fetch_object(
        "s3://pe-meetings/micro/000606/signin.pdf", "application/pdf"
    )
    assert pdf.body and pdf.content_type == "image/jpeg", pdf.error_message
    print("fetch pdf→jpeg ok", len(pdf.body), "bytes")

    h1 = compute_phash(poster.body)
    h2 = compute_phash(poster.body)
    assert h1 and phash_distance(h1, h2) == 0
    print("phash ok", h1)

    missing = fetch_object("s3://pe-meetings/no/such.jpg", "image/jpeg")
    assert missing.error_code == "S3_NOT_FOUND"
    print("missing map ok")

    # 无 Key：提交任务应 ERROR
    init_db()
    fixture = json.loads(
        (ROOT / "docs/fixtures/hall-meirui-pass.json").read_text(encoding="utf-8")
    )
    fixture["task_id"] = "req-smoke-nokey-001"
    db = SessionLocal()
    try:
        job = AiCheckJob(
            meeting_id=fixture["meeting_id"],
            attempt_no=1,
            task_id=fixture["task_id"],
            pe_snapshot=fixture,
            processing_status="RUNNING",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        jid = job.id
    finally:
        db.close()

    # ensure no key for this run
    import os

    os.environ["OPENAI_API_KEY"] = ""
    get_settings.cache_clear()
    run_check_sync(jid)

    db = SessionLocal()
    try:
        job = db.get(AiCheckJob, jid)
        assert job is not None
        assert job.overall_status == "ERROR", job.overall_status
        assert (job.final_response_json or {}).get("error", {}).get("code") == (
            "MODEL_UNAVAILABLE"
        )
        print("no-key ERROR path ok")
    finally:
        db.close()

    print("ALL SMOKE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
