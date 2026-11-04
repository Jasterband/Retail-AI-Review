from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class Speaker(BaseModel):
    speaker_id: int
    speaker_name: str
    topic: str
    store_name: str
    service_minutes: int
    role_title: Optional[str] = None
    fee: Optional[float] = None
    tax: Optional[float] = None


class MeetingForm(BaseModel):
    meeting_name: str = Field(max_length=50)
    meeting_date: str
    start_time: str
    end_time: str
    chain_or_store_name: str
    location: str
    remark: Optional[str] = None
    total_attendees: int
    speakers: List[Speaker] = Field(min_length=1)


class AssetItem(BaseModel):
    asset_id: int
    asset_type: str
    s3_uri: str
    content_type: str
    sort_no: Optional[int] = None
    speaker_id: Optional[int] = None
    speaker_shot_kind: Optional[Literal["TITLE_GROUP", "LECTURING"]] = None

    @field_validator("s3_uri")
    @classmethod
    def must_be_s3(cls, v: str) -> str:
        if not v.startswith("s3://"):
            raise ValueError("s3_uri must start with s3://")
        return v


class Refs(BaseModel):
    template_pack_version: Optional[str] = None
    logo_ref_s3: Optional[str] = None
    topic_search_scope: Literal["period", "all"] = "period"
    image_dup_search_scope: Literal["period", "all"] = "period"
    duplicate_search_scope: Optional[Literal["period", "all"]] = None


class Options(BaseModel):
    clarity_threshold: float = 0.6
    human_confidence_threshold: float = 0.75
    watermark_time_skew_minutes: int = 120
    name_match_mode: Literal["exact", "fuzzy"] = "fuzzy"
    response_mode: Literal["simple", "full"] = "simple"
    image_phash_max_distance: int = 10
    image_similarity_threshold: float = 0.92
    template_similarity_pass: float = 0.85
    template_similarity_fail: float = 0.65
    panorama_need_lecture_hall: int = 35
    panorama_need_micro_single: int = 6
    panorama_need_micro_dual: int = 12
    signin_duration_lecture_hall: int = 120
    signin_duration_micro_single: int = 30
    signin_duration_micro_dual: int = 60
    signin_audience_per_speaker: int = 6
    signin_min_store_kinds: int = 2


class RetailMeetingCheckRequest(BaseModel):
    request_id: str = Field(min_length=8, max_length=64)
    meeting_id: int = Field(ge=1)
    session_no: str = Field(max_length=20)
    project_type: Literal["LECTURE_HALL", "MICRO"]
    meeting_subtype: Optional[Literal["SINGLE", "DUAL"]] = None
    period_id: int = Field(ge=1)
    form: MeetingForm
    assets: List[AssetItem] = Field(min_length=1)
    refs: Optional[Refs] = None
    options: Optional[Options] = None

    @model_validator(mode="after")
    def check_subtype(self) -> "RetailMeetingCheckRequest":
        if self.project_type == "MICRO" and self.meeting_subtype not in (
            "SINGLE",
            "DUAL",
        ):
            raise ValueError("meeting_subtype is required for MICRO (SINGLE|DUAL)")
        if self.project_type == "LECTURE_HALL" and self.meeting_subtype is not None:
            raise ValueError("meeting_subtype must be null for LECTURE_HALL")
        return self
