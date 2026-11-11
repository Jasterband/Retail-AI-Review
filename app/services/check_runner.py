"""异步检查 runner：本地读图 + 多模态视觉 + 规则聚合。"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import SessionLocal
from app.models import AiArtifact, AiAssetResult, AiCheckJob, AiRuleResult, AiStepLog
from app.services.callback import post_callback
from app.services.history import persist_histories
from app.services.field_roi_ocr import enrich_contexts_with_field_roi_ocr
from app.services.pipeline.aggregate import build_full_response
from app.services.pipeline.asset_context import AssetContext, build_contexts
from app.services.rules.engine import run_all_rules
from app.services.template_match import enrich_contexts_with_templates
from app.services.vision.client import VisionClient, VisionError

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _log_step(
    db: Session,
    job_id: int,
    name: str,
    status: str,
    message: str = "",
    detail: Dict[str, Any] | None = None,
) -> AiStepLog:
    step = AiStepLog(
        job_id=job_id,
        step_name=name,
        status=status,
        message=message,
        detail_json=detail,
        finished_at=_utcnow() if status != "RUNNING" else None,
    )
    db.add(step)
    db.commit()
    return step


def _persist_results(
    db: Session,
    job: AiCheckJob,
    full: dict,
) -> None:
    for a in full.get("photo_results") or []:
        db.add(
            AiAssetResult(
                job_id=job.id,
                photo_id=a["photo_id"],
                declared_type=a.get("photo_type") or a.get("declared_type"),
                detected_type=None,
                type_match=None,
                clarity_score=None,
                is_clear=None,
                photo_status=a.get("photo_status"),
                checks=a.get("checks"),
                fail_reasons=a.get("fail_reasons"),
                ocr_fields=a.get("ocr_fields"),
                detections=a.get("detections"),
                image_dup_hit=bool(a.get("image_dup_hit")),
                topic_text_ocr=a.get("topic_text_ocr"),
            )
        )
    for r in full.get("rule_results") or []:
        db.add(
            AiRuleResult(
                job_id=job.id,
                rule_code=r["rule_code"],
                passed=r.get("passed"),
                status=r["status"],
                confidence=r.get("confidence"),
                trigger_human=bool(r.get("trigger_human")),
                reason_code=r.get("reason_code"),
                reason_text=r.get("reason_text"),
                evidence=r.get("evidence"),
                related_photo_ids=r.get("related_photo_ids"),
            )
        )


def run_check_sync(job_id: int) -> None:
    settings = get_settings()
    db: Session = SessionLocal()
    pipeline_steps: List[dict] = []
    try:
        job = db.get(AiCheckJob, job_id)
        if job is None:
            logger.error("job %s not found", job_id)
            return

        snap = job.pe_snapshot
        _log_step(db, job.id, "accept", "OK", "job accepted")

        vision = VisionClient(settings)
        if not vision.available():
            err = {
                "code": "MODEL_UNAVAILABLE",
                "message": "OPENAI_API_KEY not configured",
                "retryable": True,
            }
            full = build_full_response(
                snap,
                job.id,
                job.attempt_no,
                [],
                [],
                [{"step": "vision", "ok": False, "error": err}],
                error=err,
            )
            job.processing_status = "DONE"
            job.overall_status = "ERROR"
            job.error_code = err["code"]
            job.error_message = err["message"]
            job.final_response_json = full
            job.finished_at = _utcnow()
            job.model_version = settings.model_version
            db.commit()
            _maybe_callback(job, full)
            return

        t0 = time.time()
        try:
            contexts = build_contexts(
                snap.get("photos") or [],
                snap["project_type"],
                vision,
            )
        except VisionError as e:
            err = {
                "code": e.code,
                "message": e.message,
                "retryable": e.retryable,
            }
            full = build_full_response(
                snap,
                job.id,
                job.attempt_no,
                [],
                [],
                [{"step": "vision", "ok": False, "error": err}],
                error=err,
            )
            job.processing_status = "DONE"
            job.overall_status = "ERROR"
            job.error_code = e.code
            job.error_message = e.message
            job.final_response_json = full
            job.finished_at = _utcnow()
            db.commit()
            _maybe_callback(job, full)
            return

        pipeline_steps.append(
            {
                "step": "fetch_and_vision",
                "ms": int((time.time() - t0) * 1000),
                "ok": True,
                "photos": len(contexts),
            }
        )

        # v2：S3 取图失败 → 整场 ERROR（flagged_photos 为空，看顶层 error）
        s3_bad = [
            c
            for c in contexts
            if c.fetch_error_code in ("S3_NOT_FOUND", "S3_CORRUPT", "ASSET_MISSING")
        ]
        if s3_bad:
            c0 = s3_bad[0]
            raw_code = c0.fetch_error_code or "S3_NOT_FOUND"
            err = {
                "code": "S3_NOT_FOUND" if raw_code == "S3_NOT_FOUND" else raw_code,
                "message": c0.fetch_error_message
                or "对象不存在或无法下载: {0}".format(c0.file_url),
                "retryable": False,
            }
            full = build_full_response(
                snap,
                job.id,
                job.attempt_no,
                contexts,
                [],
                pipeline_steps,
                error=err,
            )
            job.processing_status = "DONE"
            job.overall_status = "ERROR"
            job.error_code = err["code"]
            job.error_message = err["message"]
            job.final_response_json = full
            job.finished_at = _utcnow()
            db.commit()
            _maybe_callback(job, full)
            return

        t_tpl = time.time()
        pack = enrich_contexts_with_templates(
            contexts,
            snap["project_type"],
            vision,
            snap.get("refs") or {},
        )
        pipeline_steps.append(
            {
                "step": "template_match",
                "ms": int((time.time() - t_tpl) * 1000),
                "ok": True,
                "pack": pack.as_dict(),
            }
        )

        # 关键字段：字段区 crop 定位 → ROI OCR（覆盖/补全 ocr_fields）
        t_roi = time.time()
        enrich_contexts_with_field_roi_ocr(contexts, pack, vision)
        pipeline_steps.append(
            {
                "step": "field_roi_ocr",
                "ms": int((time.time() - t_roi) * 1000),
                "ok": True,
            }
        )

        # 若全部 vision 失败且有 body → MODEL error
        vision_failed = [
            c for c in contexts if c.ok and c.vision_error and not c.vision
        ]
        readable = [c for c in contexts if c.ok]
        if readable and len(vision_failed) == len(readable):
            ve = vision_failed[0].vision_error or {}
            err = {
                "code": ve.get("code") or "MODEL_UNAVAILABLE",
                "message": ve.get("message") or "all vision calls failed",
                "retryable": bool(ve.get("retryable", True)),
            }
            full = build_full_response(
                snap,
                job.id,
                job.attempt_no,
                contexts,
                [],
                pipeline_steps,
                error=err,
            )
            job.processing_status = "DONE"
            job.overall_status = "ERROR"
            job.error_code = err["code"]
            job.error_message = err["message"]
            job.final_response_json = full
            job.finished_at = _utcnow()
            for c in contexts:
                if c.vision:
                    db.add(
                        AiArtifact(
                            job_id=job.id,
                            photo_id=c.photo_id,
                            artifact_type="vision_raw",
                            payload_json=c.vision,
                        )
                    )
            db.commit()
            _maybe_callback(job, full)
            return

        for c in contexts:
            if c.vision:
                db.add(
                    AiArtifact(
                        job_id=job.id,
                        photo_id=c.photo_id,
                        artifact_type="vision_raw",
                        payload_json=c.vision,
                    )
                )
            if c.vision_error:
                db.add(
                    AiArtifact(
                        job_id=job.id,
                        photo_id=c.photo_id,
                        artifact_type="vision_error",
                        payload_json=c.vision_error,
                    )
                )
        db.commit()

        t1 = time.time()
        rules = run_all_rules(snap, contexts, db)
        pipeline_steps.append(
            {
                "step": "rules",
                "ms": int((time.time() - t1) * 1000),
                "ok": True,
                "count": len(rules),
            }
        )

        full = build_full_response(
            snap, job.id, job.attempt_no, contexts, rules, pipeline_steps
        )

        _persist_results(db, job, full)
        if full["overall_status"] in ("PASS", "FAIL", "NEED_HUMAN"):
            persist_histories(db, snap, contexts)

        job.processing_status = "DONE"
        job.overall_status = full["overall_status"]
        job.overall_confidence = full.get("overall_confidence")
        job.model_version = full.get("model_version")
        job.template_pack_version = full.get("template_pack_version")
        job.final_response_json = full
        job.finished_at = _utcnow()
        db.commit()
        logger.info("job %s done overall=%s", job.task_id, job.overall_status)
        _maybe_callback(job, full)

    except Exception:
        logger.exception("job %s failed", job_id)
        db.rollback()
        job = db.get(AiCheckJob, job_id)
        if job:
            err = {
                "code": "INTERNAL_ERROR",
                "message": "runner crashed",
                "retryable": True,
            }
            full = {
                "response_mode": "full",
                "task_id": job.task_id,
                "meeting_id": job.meeting_id,
                "job_id": job.id,
                "attempt_no": job.attempt_no,
                "overall_status": "ERROR",
                "summary_matched": [],
                "summary_failed": [],
                "need_human_reasons": [],
                "error": err,
                "photo_results": [],
                "rule_results": [],
                "finished_at": _utcnow().isoformat(),
            }
            job.processing_status = "DONE"
            job.overall_status = "ERROR"
            job.error_code = "INTERNAL_ERROR"
            job.error_message = "runner crashed"
            job.final_response_json = full
            job.finished_at = _utcnow()
            db.commit()
            _maybe_callback(job, full)
    finally:
        db.close()


def _maybe_callback(job: AiCheckJob, full: dict) -> None:
    if not job.callback_url:
        return
    # 对外回调固定 AI_接口文档v2（flagged_photos）；full 仅内部调试
    mode = ((job.pe_snapshot or {}).get("options") or {}).get("response_mode", "pe")
    if mode == "simple":
        mode = "pe"
    post_callback(job.callback_url, job.task_id, full, mode)


async def schedule_check(job_id: int) -> None:
    await asyncio.to_thread(run_check_sync, job_id)
