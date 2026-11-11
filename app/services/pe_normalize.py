"""PE 交互 JSON ↔ 内部管道 snap（snake_case + LECTURE_HALL/MICRO）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.schemas.request import RetailMeetingCheckRequest


def validate_file_url(v: str) -> str:
    if v.startswith("s3://") or v.startswith("https://") or v.startswith("http://"):
        return v
    raise ValueError("fileUrl must be s3:// or http(s)://")


def infer_content_type(
    file_url: str, file_name: Optional[str] = None
) -> str:
    name = (file_name or file_url).rsplit("/", 1)[-1].lower().split("?", 1)[0]
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".jpg") or name.endswith(".jpeg"):
        return "image/jpeg"
    return "image/jpeg"


_KEY_MAP = {
    "projectId": "project_id",
    "projectType": "project_type",
    "meetingId": "meeting_id",
    "meetingNo": "meeting_no",
    "meetingType": "meeting_type",
    "meetingName": "meeting_name",
    "meetingDate": "meeting_date",
    "startTime": "start_time",
    "endTime": "end_time",
    "chainName": "chain_name",
    "pharmacyName": "pharmacy_name",
    "chainOrStoreName": "chain_or_store_name",
    "meetingLocation": "meeting_location",
    "totalAttendees": "total_attendees",
    "meetingPhotos": "meeting_photos",
    "speakerId": "speaker_id",
    "identityName": "identity_name",
    "storeName": "store_name",
    "speakerName": "speaker_name",
    "serviceMinutes": "service_minutes",
    "lectureFee": "lecture_fee",
    "photoId": "photo_id",
    "photoType": "photo_type",
    "fileUrl": "file_url",
    "fileName": "file_name",
    "contentType": "content_type",
    "photoTypeName": "photo_type_name",
}


def _rename_keys(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_rename_keys(x) for x in obj]
    if not isinstance(obj, dict):
        return obj
    out: Dict[str, Any] = {}
    for k, v in obj.items():
        out[_KEY_MAP.get(k, k)] = _rename_keys(v)
    return out


def _as_int_project_type(value: Any) -> int:
    if value in (1, 2):
        return int(value)
    if isinstance(value, str):
        s = value.strip().upper()
        if s in ("1", "LECTURE_HALL", "HALL"):
            return 1
        if s in ("2", "MICRO"):
            return 2
    raise ValueError("projectType 须为 1（大讲堂）或 2（微型）")


def _as_int_meeting_type(value: Any, project_type: int) -> int:
    if value in (0, 1, 2):
        return int(value)
    if value is None or value == "":
        return 0 if project_type == 1 else 1
    if isinstance(value, str):
        s = value.strip().upper()
        if s in ("0", "LECTURE_HALL", "HALL"):
            return 0
        if s in ("1", "SINGLE"):
            return 1
        if s in ("2", "DUAL"):
            return 2
    raise ValueError("meetingType 须为 0/1/2")


def legacy_flat_to_pe_envelope(data: Dict[str, Any]) -> Dict[str, Any]:
    """旧扁平请求 / snake_case 夹具 → PE {project,meeting,speakers,meetingPhotos}。"""
    raw = _rename_keys(dict(data))

    # 已是信封
    if isinstance(raw.get("project"), dict) and isinstance(raw.get("meeting"), dict):
        return {
            "project": raw["project"],
            "meeting": raw["meeting"],
            "speakers": raw.get("speakers") or (raw.get("form") or {}).get("speakers") or [],
            "meetingPhotos": raw.get("meeting_photos") or raw.get("meetingPhotos") or [],
            "refs": raw.get("refs"),
            "options": raw.get("options"),
        }

    form = raw.get("form") or {}
    if not isinstance(form, dict):
        form = {}

    pt = _as_int_project_type(raw.get("project_type") or form.get("project_type") or 1)
    mt = _as_int_meeting_type(raw.get("meeting_type"), pt)

    speakers_in = form.get("speakers") or raw.get("speakers") or []
    speakers_out: List[Dict[str, Any]] = []
    nested_from_speakers = False
    for sp in speakers_in:
        if not isinstance(sp, dict):
            continue
        photos = sp.get("photos") or []
        if photos:
            nested_from_speakers = True
        speakers_out.append(
            {
                "speakerId": sp.get("speaker_id") or sp.get("speakerId"),
                "identityName": sp.get("identity_name") or sp.get("identityName") or "",
                "storeName": sp.get("store_name") or sp.get("storeName") or "",
                "speakerName": sp.get("speaker_name") or sp.get("speakerName") or "",
                "topic": sp.get("topic") or "",
                "serviceMinutes": sp.get("service_minutes")
                if sp.get("service_minutes") is not None
                else sp.get("serviceMinutes") or 0,
                "lectureFee": sp.get("lecture_fee", sp.get("lectureFee")),
                "tax": sp.get("tax"),
                "photos": [
                    {
                        "photoId": p.get("photo_id") or p.get("photoId"),
                        "photoType": p.get("photo_type") or p.get("photoType"),
                        "fileUrl": p.get("file_url") or p.get("fileUrl"),
                        "fileName": p.get("file_name") or p.get("fileName"),
                        "photoTypeName": p.get("photo_type_name")
                        or p.get("photoTypeName")
                        or p.get("photo_type")
                        or p.get("photoType")
                        or "材料",
                    }
                    for p in photos
                    if isinstance(p, dict)
                ],
            }
        )

    meeting_photos: List[Dict[str, Any]] = []
    for p in raw.get("meeting_photos") or []:
        if isinstance(p, dict):
            meeting_photos.append(
                {
                    "photoId": p.get("photo_id") or p.get("photoId"),
                    "photoType": p.get("photo_type") or p.get("photoType"),
                    "fileUrl": p.get("file_url") or p.get("fileUrl"),
                    "fileName": p.get("file_name") or p.get("fileName"),
                    "photoTypeName": p.get("photo_type_name")
                    or p.get("photoTypeName")
                    or p.get("photo_type")
                    or p.get("photoType")
                    or "材料",
                }
            )

    # 旧顶层扁平 photos：按 speaker_id 拆回 speakers / meetingPhotos
    if not nested_from_speakers and not meeting_photos:
        by_speaker: Dict[str, List[dict]] = {}
        for p in raw.get("photos") or []:
            if not isinstance(p, dict):
                continue
            item = {
                "photoId": p.get("photo_id") or p.get("photoId"),
                "photoType": p.get("photo_type") or p.get("photoType"),
                "photoTypeName": p.get("photo_type_name")
                or p.get("photoTypeName")
                or p.get("photo_type")
                or p.get("photoType")
                or "材料",
                "fileUrl": p.get("file_url") or p.get("fileUrl"),
                "fileName": p.get("file_name") or p.get("fileName"),
            }
            sid = p.get("speaker_id") or p.get("speakerId")
            if sid:
                by_speaker.setdefault(str(sid), []).append(item)
            else:
                meeting_photos.append(item)
        for sp in speakers_out:
            sid = str(sp.get("speakerId") or "")
            if sid in by_speaker:
                sp["photos"] = by_speaker[sid]

    chain = form.get("chain_or_store_name") or form.get("chain_name") or raw.get("chain_name")
    pharmacy = form.get("pharmacy_name") or raw.get("pharmacy_name")
    if pt == 1:
        chain_name, pharmacy_name = chain, pharmacy
    else:
        # 旧夹具常把药店名塞在 chain_or_store_name
        chain_name, pharmacy_name = form.get("chain_name"), pharmacy or chain

    return {
        "project": {
            "projectId": raw.get("project_id") or "legacy",
            "projectType": pt,
            "projectName": raw.get("project_name"),
        },
        "meeting": {
            "meetingId": raw.get("meeting_id"),
            "meetingNo": raw.get("meeting_no") or "",
            "meetingName": form.get("meeting_name") or "",
            "meetingType": mt,
            "meetingDate": form.get("meeting_date") or "1970-01-01",
            "startTime": form.get("start_time") or "00:00",
            "endTime": form.get("end_time") or "00:00",
            "chainName": chain_name,
            "pharmacyName": pharmacy_name,
            "meetingLocation": form.get("meeting_location") or "",
            "remark": form.get("remark"),
            "totalAttendees": form.get("total_attendees")
            if form.get("total_attendees") is not None
            else 0,
        },
        "speakers": speakers_out,
        "meetingPhotos": meeting_photos,
        "refs": raw.get("refs"),
        "options": raw.get("options"),
    }


def pe_request_to_pipeline_snap(req: "RetailMeetingCheckRequest") -> Dict[str, Any]:
    """PE 请求 → 管道使用的 snake_case snap。"""
    pt_code = req.project.projectType
    mt_code = req.meeting.meetingType
    project_type = "LECTURE_HALL" if pt_code == 1 else "MICRO"
    if mt_code == 0:
        meeting_type = None
    elif mt_code == 1:
        meeting_type = "SINGLE"
    else:
        meeting_type = "DUAL"

    if project_type == "MICRO":
        chain = (req.meeting.pharmacyName or req.meeting.chainName or "").strip()
    else:
        chain = (req.meeting.chainName or "").strip()

    speakers = []
    for sp in req.speakers:
        speakers.append(
            {
                "speaker_id": sp.speakerId,
                "identity_name": sp.identityName,
                "store_name": sp.storeName,
                "speaker_name": sp.speakerName,
                "topic": sp.topic,
                "service_minutes": sp.serviceMinutes,
                "lecture_fee": sp.lectureFee,
                "tax": sp.tax,
            }
        )

    snap: Dict[str, Any] = {
        "project_id": req.project.projectId,
        "project_type": project_type,
        "meeting_id": req.meeting.meetingId,
        "meeting_no": req.meeting.meetingNo,
        "meeting_type": meeting_type,
        "form": {
            "meeting_name": req.meeting.meetingName,
            "meeting_date": req.meeting.meetingDate,
            "start_time": req.meeting.startTime,
            "end_time": req.meeting.endTime,
            "chain_or_store_name": chain,
            "meeting_location": req.meeting.meetingLocation,
            "remark": req.meeting.remark,
            "total_attendees": req.meeting.totalAttendees,
            "speakers": speakers,
        },
        "photos": req.pipeline_photos(),
    }
    if req.refs is not None:
        snap["refs"] = req.refs.model_dump(mode="json")
    if req.options is not None:
        snap["options"] = req.options.model_dump(mode="json")
    return snap
