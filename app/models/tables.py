from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class AiCheckJob(Base):
    __tablename__ = "ai_check_job"
    __table_args__ = (
        UniqueConstraint("task_id", name="uq_ai_task_id"),
        UniqueConstraint("meeting_id", "attempt_no", name="uq_ai_meeting_attempt"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    task_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    pe_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="RUNNING"
    )
    overall_status: Mapped[Optional[str]] = mapped_column(String(16))
    overall_confidence: Mapped[Optional[float]] = mapped_column(Float)
    model_version: Mapped[Optional[str]] = mapped_column(String(64))
    template_pack_version: Mapped[Optional[str]] = mapped_column(String(32))
    callback_url: Mapped[Optional[str]] = mapped_column(String(512))
    final_response_json: Mapped[Optional[dict]] = mapped_column(JSON)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[Optional[str]] = mapped_column(String(64))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    photo_results: Mapped[List["AiAssetResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    rule_results: Mapped[List["AiRuleResult"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    step_logs: Mapped[List["AiStepLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    artifacts: Mapped[List["AiArtifact"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class AiAssetResult(Base):
    __tablename__ = "ai_asset_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("ai_check_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[str] = mapped_column(String(36), nullable=False)
    declared_type: Mapped[Optional[str]] = mapped_column(String(32))
    detected_type: Mapped[Optional[str]] = mapped_column(String(32))
    type_match: Mapped[Optional[bool]] = mapped_column(Boolean)
    clarity_score: Mapped[Optional[float]] = mapped_column(Float)
    is_clear: Mapped[Optional[bool]] = mapped_column(Boolean)
    photo_status: Mapped[Optional[str]] = mapped_column(String(16))
    checks: Mapped[Optional[dict]] = mapped_column(JSON)
    fail_reasons: Mapped[Optional[list]] = mapped_column(JSON)
    ocr_fields: Mapped[Optional[dict]] = mapped_column(JSON)
    detections: Mapped[Optional[dict]] = mapped_column(JSON)
    image_dup_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    topic_text_ocr: Mapped[Optional[str]] = mapped_column(Text)

    job: Mapped["AiCheckJob"] = relationship(back_populates="photo_results")


class AiRuleResult(Base):
    __tablename__ = "ai_rule_result"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("ai_check_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[Optional[bool]] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    trigger_human: Mapped[bool] = mapped_column(Boolean, default=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(64))
    reason_text: Mapped[Optional[str]] = mapped_column(Text)
    evidence: Mapped[Optional[dict]] = mapped_column(JSON)
    related_photo_ids: Mapped[Optional[list]] = mapped_column(JSON)

    job: Mapped["AiCheckJob"] = relationship(back_populates="rule_results")


class AiStepLog(Base):
    __tablename__ = "ai_step_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("ai_check_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_name: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    message: Mapped[Optional[str]] = mapped_column(Text)
    detail_json: Mapped[Optional[dict]] = mapped_column(JSON)

    job: Mapped["AiCheckJob"] = relationship(back_populates="step_logs")


class AiArtifact(Base):
    __tablename__ = "ai_artifact"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("ai_check_job.id", ondelete="CASCADE"), nullable=False, index=True
    )
    photo_id: Mapped[Optional[str]] = mapped_column(String(36))
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_json: Mapped[Optional[dict]] = mapped_column(JSON)
    file_url: Mapped[Optional[str]] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    job: Mapped["AiCheckJob"] = relationship(back_populates="artifacts")


class ImageDupHistory(Base):
    __tablename__ = "image_dup_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    meeting_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    meeting_no: Mapped[Optional[str]] = mapped_column(String(20))
    project_id: Mapped[Optional[str]] = mapped_column(String(36), index=True)
    photo_id: Mapped[Optional[str]] = mapped_column(String(36))
    photo_type: Mapped[Optional[str]] = mapped_column(String(32))
    phash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    embedding: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

