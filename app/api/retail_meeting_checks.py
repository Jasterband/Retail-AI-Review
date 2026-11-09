from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import require_token
from app.db import get_db
from app.models import AiCheckJob
from app.schemas.request import RetailMeetingCheckRequest
from app.schemas.response import AcceptedResponse, ErrorEnvelope, RunningResponse
from app.services.check_runner import schedule_check
from app.services.projection import project_response

router = APIRouter(tags=["RetailMeetingChecks"])


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
    if idempotency_key and idempotency_key != body.task_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "error": {
                    "code": "IDEMPOTENCY_MISMATCH",
                    "message": "Idempotency-Key 须与 task_id 一致",
                    "retryable": False,
                }
            },
        )

    existing = db.scalar(
        select(AiCheckJob).where(AiCheckJob.task_id == body.task_id)
    )
    if existing:
        return AcceptedResponse(task_id=existing.task_id)

    max_attempt = db.scalar(
        select(func.max(AiCheckJob.attempt_no)).where(
            AiCheckJob.meeting_id == body.meeting_id
        )
    )
    attempt_no = int(max_attempt or 0) + 1

    job = AiCheckJob(
        meeting_id=body.meeting_id,
        attempt_no=attempt_no,
        task_id=body.task_id,
        pe_snapshot=body.model_dump(mode="json"),
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
