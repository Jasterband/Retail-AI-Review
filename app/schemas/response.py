from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class FailReason(BaseModel):
    check: Optional[str] = None
    reason_code: Optional[str] = None
    reason_text: str


class ErrorBody(BaseModel):
    code: str
    message: str
    retryable: bool = False


class AssetResult(BaseModel):
    asset_id: int
    declared_type: str
    asset_status: Literal["PASS", "FAIL", "UNCERTAIN", "ERROR"]
    fail_reasons: List[FailReason] = Field(default_factory=list)
    detected_type: Optional[str] = None
    type_match: Optional[bool] = None
    clarity_score: Optional[float] = None
    is_clear: Optional[bool] = None
    checks: Optional[Dict[str, Optional[bool]]] = None
    uncertain_checks: Optional[List[str]] = None
    ocr_fields: Optional[Dict[str, Any]] = None
    ocr_raw: Optional[str] = None
    detections: Optional[Dict[str, Any]] = None
    model_scores: Optional[Dict[str, Any]] = None
    image_dup_hit: Optional[bool] = None
    image_dup_kind: Optional[Literal["exact", "similar"]] = None
    image_dup_score: Optional[float] = None
    image_dup_ref_meeting_id: Optional[int] = None
    image_dup_ref_session_no: Optional[str] = None
    topic_reuse_hit: Optional[bool] = None
    topic_reuse_ref_session_no: Optional[str] = None
    topic_text_ocr: Optional[str] = None
    fetch_error: Optional[ErrorBody] = None


class RuleResult(BaseModel):
    rule_code: str
    status: Literal["PASS", "FAIL", "SKIP", "UNCERTAIN"]
    passed: Optional[bool] = None
    confidence: Optional[float] = None
    trigger_human: bool = False
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    related_asset_ids: List[int] = Field(default_factory=list)


class RetailMeetingCheckResponse(BaseModel):
    response_mode: Literal["simple", "full"] = "simple"
    request_id: str
    meeting_id: int
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
    asset_results: List[AssetResult] = Field(default_factory=list)
    rule_results: List[RuleResult] = Field(default_factory=list)
    debug: Optional[Dict[str, Any]] = None
    finished_at: Optional[str] = None


class RunningResponse(BaseModel):
    response_mode: Literal["simple", "full"] = "simple"
    request_id: str
    meeting_id: int
    job_id: int
    overall_status: Optional[None] = None
    processing_status: Literal["RUNNING"] = "RUNNING"
    message: str = "检查进行中"
    asset_results: List = Field(default_factory=list)
    rule_results: List = Field(default_factory=list)


class AcceptedResponse(BaseModel):
    request_id: str
    job_id: int
    attempt_no: int
    status: Literal["ACCEPTED"] = "ACCEPTED"
    message: str = "材料检查任务已受理"


class ErrorEnvelope(BaseModel):
    error: ErrorBody
