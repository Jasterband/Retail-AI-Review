"""PE → AI 请求体：与药师会交互 JSON 同构（camelCase + 数字枚举 + 嵌套照片）。"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.pe_normalize import (
    infer_content_type,
    legacy_flat_to_pe_envelope,
    pe_request_to_pipeline_snap,
    validate_file_url,
)

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

# 兼容旧代码 import
ProjectType = Literal["LECTURE_HALL", "MICRO"]
MeetingType = Literal["SINGLE", "DUAL"]


# 缺省中文名（夹具补全 / comments 前缀兜底）
PHOTO_TYPE_NAME_DEFAULTS: Dict[str, str] = {
    "EDM": "电子日程海报",
    "Poster": "日程海报",
    "Stand": "日程展架",
    "TableCard": "台卡",
    "Manual": "手册",
    "EDMDisplay": "电子日程海报展示",
    "ProjectIntro": "项目介绍展示",
    "Panorama": "参会人员全景",
    "SignSheet": "签到表",
    "SpeakerTitle": "标题合影",
    "SpeakerLecture": "讲课照片",
}

# 必审类型（缺一类 → 受理拒绝 ASSET_MISSING，不创建 task_id）
HALL_REQUIRED_TYPES: Set[str] = set(HALL_PHOTO_TYPES)
MICRO_REQUIRED_TYPES: Set[str] = set(MICRO_PHOTO_TYPES)


class PePhoto(BaseModel):
    model_config = ConfigDict(extra="ignore")

    photoId: str = Field(min_length=1, max_length=36)
    photoType: PhotoType
    photoTypeName: str = Field(min_length=1, max_length=50)
    fileUrl: str = Field(max_length=1000)
    fileName: Optional[str] = None

    @field_validator("fileUrl")
    @classmethod
    def check_file_url(cls, v: str) -> str:
        return validate_file_url(v)


class Speaker(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speakerId: str = Field(min_length=1, max_length=36)
    identityName: Optional[str] = Field(default=None, max_length=10)
    storeName: str = Field(max_length=50)
    speakerName: str = Field(max_length=20)
    topic: str = Field(max_length=50)
    serviceMinutes: int
    lectureFee: Optional[float] = None
    tax: Optional[float] = None
    photos: List[PePhoto] = Field(default_factory=list)


class Project(BaseModel):
    model_config = ConfigDict(extra="ignore")

    projectId: str = Field(min_length=1, max_length=36)
    projectType: int = Field(ge=1, le=2)  # 1 大讲堂；2 微型
    projectName: str = Field(min_length=1, max_length=100)
    startDate: Optional[str] = None
    endDate: Optional[str] = None


class Meeting(BaseModel):
    model_config = ConfigDict(extra="ignore")

    meetingId: str = Field(min_length=1, max_length=36)
    meetingNo: str = Field(min_length=1, max_length=20)
    meetingName: str = Field(min_length=1, max_length=50)
    meetingType: int = Field(ge=0, le=2)  # 0 大讲堂；1 单讲；2 双讲
    meetingTypeName: Optional[str] = None
    meetingDate: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    startTime: str = Field(max_length=5, pattern=r"^\d{2}:\d{2}$")
    endTime: str = Field(max_length=5, pattern=r"^\d{2}:\d{2}$")
    durationMinutes: int
    chainName: Optional[str] = Field(default=None, max_length=50)
    pharmacyName: Optional[str] = Field(default=None, max_length=50)
    meetingLocation: str = Field(max_length=200)
    remark: Optional[str] = Field(default=None, max_length=200)
    totalAttendees: int
    otherCost: Optional[float] = None


class Refs(BaseModel):
    model_config = ConfigDict(extra="ignore")

    template_pack_version: Optional[str] = None
    logo_ref_s3: Optional[str] = None
    image_dup_search_scope: Literal["period", "all"] = "period"
    duplicate_search_scope: Optional[Literal["period", "all"]] = None


class Options(BaseModel):
    model_config = ConfigDict(extra="ignore")

    human_confidence_threshold: float = 0.75
    # 仅用于海报等材料上的日程起止时间容差；不做时间水印检测
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


class RetailMeetingCheckRequest(BaseModel):
    """与药师会交互 JSON 同构。task_id 由 AI 生成，不在请求体。"""

    model_config = ConfigDict(extra="ignore")

    project: Project
    meeting: Meeting
    speakers: List[Speaker] = Field(min_length=1)
    meetingPhotos: List[PePhoto]  # v2 必填（可为空数组，但键须存在）
    refs: Optional[Refs] = None
    options: Optional[Options] = None

    @model_validator(mode="before")
    @classmethod
    def coerce_legacy_or_pass(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        # 已是 PE 信封
        if "project" in data and "meeting" in data:
            return data
        # 旧扁平夹具 / 中间形态 → 提成 PE 信封
        return legacy_flat_to_pe_envelope(data)

    @model_validator(mode="after")
    def check_types_and_photos(self) -> "RetailMeetingCheckRequest":
        pt = self.project.projectType
        mt = self.meeting.meetingType
        if pt == 1 and mt != 0:
            raise ValueError("projectType=1（大讲堂）时 meetingType 须为 0")
        if pt == 2 and mt not in (1, 2):
            raise ValueError("projectType=2（微型）时 meetingType 须为 1 或 2")

        if pt == 1:
            if not (self.meeting.chainName or "").strip():
                raise ValueError("大讲堂须提供 chainName")
        else:
            if not (self.meeting.pharmacyName or self.meeting.chainName or "").strip():
                raise ValueError("微型须提供 pharmacyName")

        flat = self.pipeline_photos()
        if not flat:
            raise ValueError("须提供 speakers[].photos 与/或 meetingPhotos")

        allowed = HALL_PHOTO_TYPES if pt == 1 else MICRO_PHOTO_TYPES
        bad = sorted({p["photo_type"] for p in flat if p["photo_type"] not in allowed})
        if bad:
            raise ValueError(
                "photoType 与 projectType={0} 不匹配: {1}".format(pt, ", ".join(bad))
            )
        for p in flat:
            if p["photo_type"] in SPEAKER_PHOTO_TYPES and not p.get("speaker_id"):
                raise ValueError("{0} 须挂在对应 speakers[].photos 下".format(p["photo_type"]))
        return self

    def missing_required_photo_types(self) -> List[str]:
        """必审类型缺失列表（受理前校验）。"""
        present = {p["photo_type"] for p in self.pipeline_photos()}
        required = (
            HALL_REQUIRED_TYPES
            if self.project.projectType == 1
            else MICRO_REQUIRED_TYPES
        )
        return sorted(required - present)

    def pipeline_photos(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        n = 1
        for sp in self.speakers:
            for p in sp.photos:
                out.append(
                    {
                        "photo_id": p.photoId,
                        "photo_type": p.photoType,
                        "photo_type_name": p.photoTypeName,
                        "file_url": p.fileUrl,
                        "content_type": infer_content_type(p.fileUrl, p.fileName),
                        "sort": n,
                        "speaker_id": sp.speakerId,
                    }
                )
                n += 1
        for p in self.meetingPhotos:
            out.append(
                {
                    "photo_id": p.photoId,
                    "photo_type": p.photoType,
                    "photo_type_name": p.photoTypeName,
                    "file_url": p.fileUrl,
                    "content_type": infer_content_type(p.fileUrl, p.fileName),
                    "sort": n,
                    "speaker_id": None,
                }
            )
            n += 1
        return out

    def to_pipeline_snap(self) -> Dict[str, Any]:
        return pe_request_to_pipeline_snap(self)

    # --- 兼容旧调用方属性名 ---
    @property
    def meeting_id(self) -> str:
        return self.meeting.meetingId

    @property
    def project_type(self) -> str:
        return "LECTURE_HALL" if self.project.projectType == 1 else "MICRO"

    def flattened_photos(self) -> List[Dict[str, Any]]:
        return self.pipeline_photos()
