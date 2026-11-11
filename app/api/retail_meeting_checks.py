from __future__ import annotations

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth import require_token
from app.db import get_db
from app.models import AiCheckJob
from app.schemas.request import RetailMeetingCheckRequest
from app.schemas.response import AcceptedResponse, RunningResponse
from app.services.check_runner import schedule_check
from app.services.projection import project_response

router = APIRouter(tags=["RetailMeetingChecks"])


def _new_task_id() -> str:
    # 8~50；req- + uuid4 hex
    return "req-" + uuid.uuid4().hex


@router.get("/health")
def health(_: str = Depends(require_token)) -> dict:
    return {"status": "ok"}


@router.post(
    "/v1/retail_meeting_checks",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
)
def create_check(
    body: RetailMeetingCheckRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
    x_callback_url: Optional[str] = Header(default=None, alias="X-Callback-URL"),
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    # v2：缺必审材料 → 受理拒绝，无 task_id
    missing = body.missing_required_photo_types()
    if missing:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "ASSET_MISSING",
                    "message": "缺少必审材料: {0}".format(", ".join(missing)),
                    "retryable": False,
                }
            },
        )

    if idempotency_key:
        existing = db.scalar(
            select(AiCheckJob).where(
                text(
                    "json_extract(pe_snapshot, '$.idempotency_key') = :k"
                ).bindparams(k=idempotency_key)
            )
        )
        if existing:
            return AcceptedResponse(task_id=existing.task_id)

    task_id = _new_task_id()
    # 入库 snap 为管道形态；HTTP 契约为 PE 交互 JSON
    snap = body.to_pipeline_snap()
    snap["task_id"] = task_id
    if idempotency_key:
        snap["idempotency_key"] = idempotency_key

    max_attempt = db.scalar(
        select(func.max(AiCheckJob.attempt_no)).where(
            AiCheckJob.meeting_id == body.meeting.meetingId
        )
    )
    attempt_no = int(max_attempt or 0) + 1

    job = AiCheckJob(
        meeting_id=body.meeting.meetingId,
        attempt_no=attempt_no,
        task_id=task_id,
        pe_snapshot=snap,
        processing_status="RUNNING",
        callback_url=x_callback_url,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(schedule_check, job.id)

    return AcceptedResponse(task_id=job.task_id)


def _get_check_result(
    task_id: str,
    mode: Literal["pe", "simple", "full"],
    db: Session,
):
    job = db.scalar(select(AiCheckJob).where(AiCheckJob.task_id == task_id))
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "error": {
                    "code": "NOT_FOUND",
                    "message": "unknown task_id",
                    "retryable": False,
                }
            },
        )

    if job.processing_status == "RUNNING" or job.final_response_json is None:
        return RunningResponse(task_id=job.task_id, meeting_id=job.meeting_id)

    return project_response(job.final_response_json, mode)


@router.get("/v1/retail_meeting_checks/{task_id}/results")
def get_check_results(
    task_id: str,
    mode: Literal["pe", "simple", "full"] = Query(default="pe"),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    """AI_接口文档v2 轮询路径。"""
    return _get_check_result(task_id, mode, db)


@router.get("/v1/retail_meeting_checks/{task_id}")
def get_check_legacy(
    task_id: str,
    mode: Literal["pe", "simple", "full"] = Query(default="pe"),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    """兼容旧轮询路径；行为同 `/results`。"""
    return _get_check_result(task_id, mode, db)
