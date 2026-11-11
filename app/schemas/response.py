from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class FailReason(BaseModel):
    reason_code: Optional[str] = None
    # PE：非 ERROR 时 `{photoTypeName}：{原因}`
    comments: Optional[str] = None
    # 内部 full 保留
    check: Optional[str] = None
    reason_text: Optional[str] = None


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False


class FlaggedPhoto(BaseModel):
    """PE 终态：仅需关注的图（PASS 不下发）。"""

    photo_id: str
    photo_status: Literal["FAIL", "ERROR", "NEED_HUMAN"]
    fail_reasons: List[FailReason] = Field(default_factory=list)


class PhotoResult(BaseModel):
    """内部 full 存库形态。"""

    photo_id: str
    photo_type: str
    photo_type_name: Optional[str] = None
    photo_status: Literal["PASS", "FAIL", "UNCERTAIN", "ERROR", "NEED_HUMAN"]
    fail_reasons: List[FailReason] = Field(default_factory=list)
    checks: Optional[Dict[str, Optional[bool]]] = None
    uncertain_checks: Optional[List[str]] = None
    ocr_fields: Optional[Dict[str, Any]] = None
    ocr_raw: Optional[str] = None
    detections: Optional[Dict[str, Any]] = None
    model_scores: Optional[Dict[str, Any]] = None
    image_dup_hit: Optional[bool] = None
    image_dup_kind: Optional[Literal["exact", "similar"]] = None
    image_dup_score: Optional[float] = None
    image_dup_ref_meeting_id: Optional[str] = None
    image_dup_ref_meeting_no: Optional[str] = None
    topic_text_ocr: Optional[str] = None
    fetch_error: Optional[ErrorBody] = None


# 兼容旧类名
AssetResult = PhotoResult


class RuleResult(BaseModel):
    rule_code: str
    status: Literal["PASS", "FAIL", "SKIP", "UNCERTAIN"]
    passed: Optional[bool] = None
    confidence: Optional[float] = None
    trigger_human: bool = False
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    related_photo_ids: List[str] = Field(default_factory=list)


class RetailMeetingCheckResponse(BaseModel):
    """内部 full 响应（存库 / demo mode=full）。"""

    response_mode: Literal["simple", "full"] = "full"
    task_id: str
    meeting_id: str
    job_id: Optional[int] = None
    attempt_no: Optional[int] = None
    overall_status: Literal["PASS", "FAIL", "NEED_HUMAN", "ERROR"]
    overall_confidence: Optional[float] = None
    model_version: Optional[str] = None
    template_pack_version: Optional[str] = None
    summary_matched: List[str] = Field(default_factory=list)
    summary_failed: List[str] = Field(default_factory=list)
    need_human_reasons: List[str] = Field(default_factory=list)
    error: Optional[ErrorBody] = None
    photo_results: List[PhotoResult] = Field(default_factory=list)
    rule_results: List[RuleResult] = Field(default_factory=list)
    debug: Optional[Dict[str, Any]] = None
    finished_at: Optional[str] = None


class PeResultResponse(BaseModel):
    """AI_接口文档v2 终态 / 轮询结构。"""

    task_id: str
    meeting_id: str
    overall_status: Literal["running", "PASS", "FAIL", "NEED_HUMAN", "ERROR"]
    error: Optional[ErrorBody] = None
    flagged_photos: List[FlaggedPhoto] = Field(default_factory=list)


class RunningResponse(BaseModel):
    task_id: str
    meeting_id: str
    overall_status: Literal["running"] = "running"


class AcceptedResponse(BaseModel):
    task_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorBody
