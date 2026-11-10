from __future__ import annotations

import uuid
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
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
) -> AcceptedResponse:
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


@router.get("/v1/retail_meeting_checks/{task_id}")
def get_check(
    task_id: str,
    mode: Literal["simple", "full"] = Query(default="simple"),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
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
