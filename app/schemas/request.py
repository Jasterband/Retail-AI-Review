from __future__ import annotations

from typing import List, Literal, Optional, Set

from pydantic import BaseModel, Field, field_validator, model_validator

ProjectType = Literal["LECTURE_HALL", "MICRO"]
MeetingType = Literal["SINGLE", "DUAL"]  # CRM MeetingType 1/2；大讲堂请求里必须 null

# 与 CRM r_Seminar_Photo.PhotoType 一致
PhotoType = Literal[
    "EDM",
    "Poster",
    "Stand",
    "TableCard",
    "Manual",
    "EDMDisplay",
    "ProjectIntro",
    "Panorama",
    "SignSheet",
    "SpeakerTitle",
    "SpeakerLecture",
]
ContentType = Literal["image/jpeg", "image/jpg", "image/png", "application/pdf"]
ResponseMode = Literal["simple", "full"]

SPEAKER_PHOTO_TYPES: Set[str] = {"SpeakerTitle", "SpeakerLecture"}

HALL_PHOTO_TYPES: Set[str] = {
    "EDM",
    "Poster",
    "Stand",
    "TableCard",
    "Manual",
    "SpeakerTitle",
    "SpeakerLecture",
    "Panorama",
    "SignSheet",
}
MICRO_PHOTO_TYPES: Set[str] = {
    "EDM",
    "EDMDisplay",
    "ProjectIntro",
    "SpeakerTitle",
    "Panorama",
    "SignSheet",
}

class Speaker(BaseModel):
    speaker_id: str = Field(min_length=1, max_length=36)  # CRM SpeakerID
    speaker_name: str = Field(max_length=20)  # SpeakerName
    topic: str = Field(max_length=50)  # Topic
    store_name: str = Field(max_length=50)  # StoreName
    service_minutes: int  # ServiceMinutes
    identity_name: str = Field(max_length=10)  # CRM IdentityName NotNull
    lecture_fee: float  # CRM LectureFee NotNull
    tax: float  # CRM Tax NotNull


class MeetingForm(BaseModel):
    meeting_name: str = Field(max_length=50)  # MeetingName
    meeting_date: str = Field(
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description="YYYY-MM-DD；CRM MeetingDate",
    )
    start_time: str = Field(max_length=5, pattern=r"^\d{2}:\d{2}$")  # StartTime
    end_time: str = Field(max_length=5, pattern=r"^\d{2}:\d{2}$")  # EndTime
    # CRM 为 ChainName + PharmacyName 两列；API 合成一列由 PE 按项目类型填入
    chain_or_store_name: str = Field(max_length=50)
    meeting_location: str = Field(max_length=200)  # MeetingLocation
    remark: Optional[str] = Field(default=None, max_length=200)  # Remark
    total_attendees: int  # TotalAttendees
    speakers: List[Speaker] = Field(min_length=1)


class PhotoItem(BaseModel):
    photo_id: str = Field(min_length=1, max_length=36)  # PhotoID
    photo_type: PhotoType  # 与 CRM PhotoType 同值
    file_url: str = Field(max_length=1000)  # FileUrl；须 s3://
    content_type: ContentType  # 由 FileExt 映射的 MIME
    sort: int = Field(ge=1)  # CRM Sort NotNull
    speaker_id: Optional[str] = Field(default=None, max_length=36)

    @field_validator("file_url")
    @classmethod
    def must_be_s3(cls, v: str) -> str:
        if not v.startswith("s3://"):
            raise ValueError("file_url must start with s3://")
        return v

    @model_validator(mode="after")
    def speaker_fields(self) -> "PhotoItem":
        if self.photo_type in SPEAKER_PHOTO_TYPES and self.speaker_id is None:
            raise ValueError(
                "{0} 须带 speaker_id".format(self.photo_type)
            )
        return self


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
    response_mode: ResponseMode = "simple"
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
    """POST /v1/retail_meeting_checks 请求体。

    字段名与 photo_type 枚举对齐 CRM 数据字典。
    """

    task_id: str = Field(min_length=8, max_length=50)  # CRM TaskID / 幂等键
    meeting_id: str = Field(min_length=1, max_length=36)  # MeetingID
    meeting_no: str = Field(max_length=20)  # MeetingNo
    project_type: ProjectType  # ProjectType（值：LECTURE_HALL|MICRO）
    meeting_type: Optional[MeetingType] = None  # MeetingType → SINGLE|DUAL；大讲堂 null
    project_id: str = Field(min_length=1, max_length=36)  # ProjectID
    form: MeetingForm
    photos: List[PhotoItem] = Field(min_length=1)
    refs: Optional[Refs] = None
    options: Optional[Options] = None

    @model_validator(mode="after")
    def check_type_and_photos(self) -> "RetailMeetingCheckRequest":
        if self.project_type == "MICRO" and self.meeting_type not in (
            "SINGLE",
            "DUAL",
        ):
            raise ValueError("meeting_type is required for MICRO (SINGLE|DUAL)")
        if self.project_type == "LECTURE_HALL" and self.meeting_type is not None:
            raise ValueError("meeting_type must be null for LECTURE_HALL")

        allowed = (
            HALL_PHOTO_TYPES
            if self.project_type == "LECTURE_HALL"
            else MICRO_PHOTO_TYPES
        )
        bad = sorted(
            {p.photo_type for p in self.photos if p.photo_type not in allowed}
        )
        if bad:
            raise ValueError(
                "photo_type 与 project_type={0} 不匹配: {1}".format(
                    self.project_type, ", ".join(bad)
                )
            )
        return self
