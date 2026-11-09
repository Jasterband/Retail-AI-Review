"""黄金集人工标注：列场次材料、读图（含 PDF 首页）、读写标注 JSON。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.config import get_settings

router = APIRouter(prefix="/v1/annotate", tags=["golden-annotate"])

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = ROOT / "docs" / "golden_annotations"

# 金标准标注场次（相对 sample_photos 根）
SESSIONS: Dict[str, Dict[str, Any]] = {
    "hall-183": {
        "id": "hall-183",
        "label": "大讲堂 · 江苏大众 183",
        "project_type": "LECTURE_HALL",
        "meeting_no": "183",
        "rel_dir": "药师大讲堂/大讲堂已上传过的50场会议核销资料/183~2026-6-30~江苏大众医药连锁有限公司核销资料",
        "photos": [
            {"file": "1手册.jpg", "photo_type": "Manual"},
            {"file": "183.png", "photo_type": "EDM"},
            {"file": "2权益-海报.jpg", "photo_type": "Poster"},
            {"file": "3权益-展架.jpg", "photo_type": "Stand"},
            {"file": "4台卡-1.jpg", "photo_type": "TableCard"},
            {"file": "4台卡-2.jpg", "photo_type": "TableCard"},
            {
                "file": "5讲者1-陈丽娟1.jpg",
                "photo_type": "SpeakerTitle",
                "speaker_name": "陈丽娟",
            },
            {
                "file": "5讲者1-陈丽娟2.jpg",
                "photo_type": "SpeakerLecture",
                "speaker_name": "陈丽娟",
            },
            {
                "file": "6讲者2-曹兰飞1.jpg",
                "photo_type": "SpeakerTitle",
                "speaker_name": "曹兰飞",
            },
            {
                "file": "6讲者2-曹兰飞2.jpg",
                "photo_type": "SpeakerLecture",
                "speaker_name": "曹兰飞",
            },
            {
                "file": "7讲者3-单丽丽1.jpg",
                "photo_type": "SpeakerTitle",
                "speaker_name": "单丽丽",
            },
            {
                "file": "7讲者3-单丽丽2.jpg",
                "photo_type": "SpeakerLecture",
                "speaker_name": "单丽丽",
            },
            {
                "file": "8讲者4-杨燕1.jpg",
                "photo_type": "SpeakerTitle",
                "speaker_name": "杨燕",
            },
            {
                "file": "8讲者4-杨燕2.jpg",
                "photo_type": "SpeakerLecture",
                "speaker_name": "杨燕",
            },
            {"file": "9全景照片（36）.jpg", "photo_type": "Panorama"},
            {"file": "10签到表1（35）.jpg", "photo_type": "SignSheet"},
            {"file": "10签到表2（35）.png", "photo_type": "SignSheet"},
        ],
    },
    "micro-000606": {
        "id": "micro-000606",
        "label": "微型 · 太极东大街 000606",
        "project_type": "MICRO",
        "meeting_type": "SINGLE",
        "meeting_no": "000606",
        "rel_dir": "微型药师/合格场次45场次/000606-2026-8-11-成都市-四川太极大药房连锁有限公司锦江区东大街药店-微型药店健康服务赋能计划项目",
        "photos": [
            {"file": "电子日程海报.png", "photo_type": "EDM"},
            {"file": "项目介绍展示.jpeg", "photo_type": "ProjectIntro"},
            {"file": "电子日程海报展示.jpeg", "photo_type": "EDMDisplay"},
            {
                "file": "标题合影.jpeg",
                "photo_type": "SpeakerTitle",
            },
            {"file": "全景照片.jpeg", "photo_type": "Panorama"},
            {"file": "签到表.pdf", "photo_type": "SignSheet", "is_pdf": True},
        ],
    },
}

# 按材料类型推荐的框标签
LABELS_BY_TYPE: Dict[str, List[Dict[str, str]]] = {
    "Manual": [
        {"id": "handbook_cover", "mode": "box", "hint": "手册封面整体"},
        {"id": "handbook_year", "mode": "box", "hint": "年份数字（如 2026）"},
    ],
    "TableCard": [
        {"id": "name_card", "mode": "box", "hint": "单张台卡"},
        {"id": "name_text", "mode": "box", "hint": "姓名文字区"},
    ],
    "Poster": [
        {"id": "poster_panel", "mode": "box", "hint": "先框：海报整体（含背景外的材料本体）"},
        {"id": "bayer_logo", "mode": "box", "hint": "拜耳 Logo"},
        {"id": "date", "mode": "box", "hint": "日期"},
        {"id": "time", "mode": "box", "hint": "时间"},
        {"id": "location", "mode": "box", "hint": "地点"},
        {"id": "speakers", "mode": "box", "hint": "讲者名区域"},
    ],
    "Stand": [
        {"id": "stand_panel", "mode": "box", "hint": "先框：展架整体（材料本体）"},
        {"id": "bayer_logo", "mode": "box", "hint": "拜耳 Logo"},
        {"id": "date", "mode": "box", "hint": "日期"},
        {"id": "time", "mode": "box", "hint": "时间"},
        {"id": "location", "mode": "box", "hint": "地点"},
        {"id": "speakers", "mode": "box", "hint": "讲者名区域"},
    ],
    "EDM": [
        {"id": "edm_panel", "mode": "box", "hint": "先框：电子海报整体"},
        {"id": "bayer_logo", "mode": "box", "hint": "拜耳 Logo"},
        {"id": "date", "mode": "box", "hint": "日期"},
        {"id": "time", "mode": "box", "hint": "时间"},
        {"id": "location", "mode": "box", "hint": "地点"},
        {"id": "speakers", "mode": "box", "hint": "讲者名区域"},
    ],
    "SpeakerTitle": [
        {"id": "speaker", "mode": "box", "hint": "讲者本人（人物）"},
        {"id": "ppt_region", "mode": "box", "hint": "投影/PPT 区域"},
        {"id": "topic_title", "mode": "box", "hint": "讲题标题文字"},
        {"id": "watermark", "mode": "box", "hint": "水印（若有）"},
    ],
    "SpeakerLecture": [
        {"id": "speaker", "mode": "box", "hint": "讲者本人（人物）"},
        {"id": "ppt_region", "mode": "box", "hint": "投影/PPT 区域"},
        {"id": "watermark", "mode": "box", "hint": "水印（若有）"},
    ],
    "Panorama": [
        {"id": "person", "mode": "point", "hint": "点击人头"},
    ],
    "SignSheet": [
        {"id": "start_time", "mode": "box", "hint": "开始时间"},
        {"id": "end_time", "mode": "box", "hint": "结束时间"},
        {"id": "audience_block", "mode": "box", "hint": "听众区（可选）"},
        {"id": "store_names", "mode": "box", "hint": "门店名列（微型）"},
    ],
    "ProjectIntro": [
        {"id": "colorful_ribbon", "mode": "box", "hint": "彩色丝带"},
        {"id": "bayer_logo", "mode": "box", "hint": "拜耳 Logo"},
        {"id": "watermark", "mode": "box", "hint": "水印（若有）"},
    ],
    "EDMDisplay": [
        {"id": "agenda_table", "mode": "box", "hint": "日程表"},
        {"id": "bayer_logo", "mode": "box", "hint": "拜耳 Logo"},
        {"id": "watermark", "mode": "box", "hint": "水印（若有）"},
    ],
}


def _session_dir(session_id: str) -> Path:
    meta = SESSIONS.get(session_id)
    if not meta:
        raise HTTPException(404, "unknown session")
    path = get_settings().sample_photos_root / meta["rel_dir"]
    if not path.is_dir():
        raise HTTPException(404, "session folder missing: {0}".format(path))
    return path


def _ann_path(session_id: str) -> Path:
    return OUT_ROOT / session_id / "annotations.json"


def _empty_annotation(session_id: str) -> dict:
    meta = SESSIONS[session_id]
    photos = {}
    for a in meta["photos"]:
        photos[a["file"]] = {
            "photo_type": a["photo_type"],
            "speaker_name": a.get("speaker_name"),
            "boxes": [],
            "points": [],
            "fields": {},
            "done": False,
            "notes": "",
        }
    return {
        "session_id": session_id,
        "project_type": meta["project_type"],
        "meeting_no": meta["meeting_no"],
        "label": meta["label"],
        "updated_at": None,
        "photos": photos,
    }


def _normalize_annotation(data: dict) -> dict:
    """兼容旧标注文件：assets→photos，session_no→meeting_no。"""
    if "photos" not in data and "assets" in data:
        data["photos"] = data.pop("assets")
    if "meeting_no" not in data and data.get("session_no"):
        data["meeting_no"] = data.pop("session_no")
    if "meeting_notes" not in data and "session_notes" in data:
        data["meeting_notes"] = data.get("session_notes")
    return data


def _pdf_first_jpeg(pdf_bytes: bytes) -> bytes:
    import pypdfium2 as pdfium
    from PIL import Image  # noqa: F401 — via pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    if len(doc) < 1:
        raise ValueError("empty PDF")
    page = doc[0]
    bitmap = page.render(scale=2)
    pil = bitmap.to_pil()
    buf = BytesIO()
    pil.convert("RGB").save(buf, format="JPEG", quality=88)
    return buf.getvalue()


@router.get("/sessions")
def list_sessions() -> dict:
    rows = []
    for sid, meta in SESSIONS.items():
        path = _ann_path(sid)
        done_n = 0
        total = len(meta["photos"])
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            for a in (data.get("photos") or data.get("assets") or {}).values():
                if a.get("done"):
                    done_n += 1
        rows.append(
            {
                "id": sid,
                "label": meta["label"],
                "project_type": meta["project_type"],
                "meeting_no": meta["meeting_no"],
                "asset_count": total,
                "done_count": done_n,
                "has_file": path.exists(),
            }
        )
    return {"sessions": rows, "out_root": str(OUT_ROOT.relative_to(ROOT))}


@router.get("/sessions/{session_id}")
def get_session(session_id: str) -> dict:
    meta = SESSIONS.get(session_id)
    if not meta:
        raise HTTPException(404, "unknown session")
    folder = _session_dir(session_id)
    photos = []
    for a in meta["photos"]:
        p = folder / a["file"]
        photos.append(
            {
                **a,
                "exists": p.exists(),
                "labels": LABELS_BY_TYPE.get(a["photo_type"], []),
            }
        )
    return {
        "id": session_id,
        "label": meta["label"],
        "project_type": meta["project_type"],
        "meeting_no": meta["meeting_no"],
        "photos": photos,
        "annotation_path": str(_ann_path(session_id).relative_to(ROOT)),
    }


@router.get("/sessions/{session_id}/image")
def get_image(session_id: str, file: str):
    folder = _session_dir(session_id)
    # 防路径穿越
    safe = Path(file).name
    path = folder / safe
    if not path.exists():
        raise HTTPException(404, "file not found")
    raw = path.read_bytes()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        try:
            body = _pdf_first_jpeg(raw)
        except Exception as e:
            raise HTTPException(500, "pdf render failed: {0}".format(e))
        return Response(content=body, media_type="image/jpeg")
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return Response(content=raw, media_type=mime)


@router.get("/sessions/{session_id}/annotations")
def get_annotations(session_id: str) -> dict:
    if session_id not in SESSIONS:
        raise HTTPException(404, "unknown session")
    path = _ann_path(session_id)
    if not path.exists():
        data = _empty_annotation(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return data
    return _normalize_annotation(json.loads(path.read_text(encoding="utf-8")))


class AnnotationSave(BaseModel):
    photos: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None


@router.put("/sessions/{session_id}/annotations")
def save_annotations(session_id: str, body: AnnotationSave) -> dict:
    if session_id not in SESSIONS:
        raise HTTPException(404, "unknown session")
    path = _ann_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _empty_annotation(session_id)
    if path.exists():
        existing = _normalize_annotation(json.loads(path.read_text(encoding="utf-8")))
    for fname, payload in (body.photos or {}).items():
        if fname not in existing["photos"]:
            existing["photos"][fname] = payload
        else:
            existing["photos"][fname].update(payload)
    if body.notes is not None:
        existing["meeting_notes"] = body.notes
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    done = sum(1 for a in existing["photos"].values() if a.get("done"))
    return {
        "ok": True,
        "path": str(path.relative_to(ROOT)),
        "updated_at": existing["updated_at"],
        "done_count": done,
        "total": len(existing["photos"]),
    }
