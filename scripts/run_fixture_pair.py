#!/usr/bin/env python3
"""跑指定夹具并写入 runs 目录。"""

from __future__ import annotations

import json
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import AiCheckJob
from app.services.check_runner import run_check_sync

FIXTURES = [
    ("hall-183", ROOT / "docs/fixtures/hall-183-pass.json"),
    ("micro-000606", ROOT / "docs/fixtures/micro-000090-pass.json"),
]


def _rule_summary(full: dict) -> list:
    rows = []
    for r in full.get("rule_results") or []:
        rows.append(
            {
                "rule_code": r.get("rule_code"),
                "status": r.get("status"),
                "reason_text": r.get("reason_text"),
                "related_asset_ids": r.get("related_asset_ids"),
            }
        )
    return rows


def run_one(label: str, path: Path, out_dir: Path) -> dict:
    get_settings.cache_clear()
    settings = get_settings()
    if not settings.openai_api_key:
        raise SystemExit("OPENAI_API_KEY 未配置，无法真跑")

    fixture = json.loads(path.read_text(encoding="utf-8"))
    fixture["request_id"] = "req-run-{0}-{1}".format(
        label, uuid.uuid4().hex[:8]
    )
    # 要看 checks / ocr，强制 full
    opts = dict(fixture.get("options") or {})
    opts["response_mode"] = "full"
    fixture["options"] = opts

    init_db()
    db = SessionLocal()
    try:
        max_attempt = db.scalar(
            select(func.max(AiCheckJob.attempt_no)).where(
                AiCheckJob.meeting_id == fixture["meeting_id"]
            )
        )
        job = AiCheckJob(
            meeting_id=fixture["meeting_id"],
            attempt_no=int(max_attempt or 0) + 1,
            request_id=fixture["request_id"],
            pe_snapshot=fixture,
            processing_status="RUNNING",
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        jid = job.id
        rid = job.request_id
    finally:
        db.close()

    print("=== {0} job_id={1} request_id={2} ===".format(label, jid, rid))
    t0 = time.time()
    run_check_sync(jid)
    elapsed = time.time() - t0

    db = SessionLocal()
    try:
        job = db.get(AiCheckJob, jid)
        assert job is not None
        full = job.final_response_json or {}
        summary = {
            "label": label,
            "fixture": str(path.relative_to(ROOT)),
            "request_id": rid,
            "job_id": jid,
            "elapsed_sec": round(elapsed, 1),
            "processing_status": job.processing_status,
            "overall_status": job.overall_status,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "model_version": job.model_version,
            "rule_results": _rule_summary(full),
            "asset_results_brief": [
                {
                    "asset_id": a.get("asset_id"),
                    "declared_type": a.get("declared_type"),
                    "asset_status": a.get("asset_status"),
                    "checks": a.get("checks"),
                    "ocr_fields": a.get("ocr_fields"),
                    "fail_reasons": a.get("fail_reasons"),
                }
                for a in (full.get("asset_results") or [])
            ],
        }
        (out_dir / "{0}.full.json".format(label)).write_text(
            json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (out_dir / "{0}.summary.json".format(label)).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(
            "done {0}: overall={1} rules={2} elapsed={3}s".format(
                label, job.overall_status, len(summary["rule_results"]), round(elapsed, 1)
            )
        )
        return summary
    finally:
        db.close()


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "runs" / "20261102-hall143-micro606"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    all_sum = []
    for label, path in FIXTURES:
        all_sum.append(run_one(label, path, out_dir))
    (out_dir / "overview.json").write_text(
        json.dumps(all_sum, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
