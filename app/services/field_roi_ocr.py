"""关键字段 / 台卡 OCR。

流程（海报/展架/电子日程）：
1. 用字段区参考 crop（综合块，或 时间/地点/日程 分块）在整图上做多尺度 NCC
2. 取出命中框（略外扩）形成 ROI
3. 对 ROI 调 Vision，只抽 meeting_date / start_time / end_time /
   meeting_location / speaker_names
4. 写回 AssetContext.vision["ocr_fields"]（有值才覆盖）

流程（台卡 TableCard）：
整图 Vision 抽取 name_card_names，再与 form.speakers 比对；**不裁框**。
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from app.services.pipeline.asset_context import AssetContext
from app.services.template_match import match_ncc_locate
from app.services.template_pack import TemplatePack
from app.services.vision.client import VisionClient, VisionError

logger = logging.getLogger(__name__)

_FIELD_TYPES = {"Poster", "Stand", "EDM", "EDMDisplay"}

# 现场照片透视/遮挡多，综合块难命中；分块锚点更稳
_SCALES = (0.12, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0, 1.3)
_HIT = 0.58
_UNC = 0.48


def _pick_crops(pack: TemplatePack, photo_type: str) -> List[Tuple[str, Path]]:
    """返回 [(role, path), ...]；优先分块，再综合块兜底。"""
    root = pack.root
    hall = root / "lecture_hall"
    micro = root / "micro"
    out: List[Tuple[str, Path]] = []

    def add(role: str, *cands: Optional[Path]) -> None:
        for p in cands:
            if p is not None and p.is_file():
                out.append((role, p))
                return

    if photo_type in {"Poster", "Stand"}:
        add("time", hall / "poster_meeting_time_crop.jpg")
        add("location", hall / "poster_meeting_location_crop.jpg")
        add("agenda", hall / "poster_agenda_table_crop.jpg")
        add("key_fields", pack.poster_key_fields, pack.edm_key_fields)
    else:  # EDM / EDMDisplay
        add("key_fields", pack.edm_key_fields, pack.micro_edm_key_fields, pack.poster_key_fields)
        add("time", hall / "poster_meeting_time_crop.jpg")
        add("location", hall / "poster_meeting_location_crop.jpg")
        add("agenda", hall / "poster_agenda_table_crop.jpg")
        # 微型电子日程整块
        add("micro_key", pack.micro_edm_key_fields)
    return out


def _crop_roi_jpeg(
    image_bytes: bytes,
    box_norm: Dict[str, float],
    pad: float = 0.05,
) -> Optional[bytes]:
    """按归一化框裁 ROI，略外扩，输出 JPEG bytes。"""
    try:
        im = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return None
    w, h = im.size
    x = float(box_norm.get("x") or 0.0) - pad
    y = float(box_norm.get("y") or 0.0) - pad
    bw = float(box_norm.get("w") or 0.0) + 2 * pad
    bh = float(box_norm.get("h") or 0.0) + 2 * pad
    # 时间/地点小块：向下多扩一点，吃到内容行
    if bh < 0.12:
        bh = min(0.18, bh + 0.06)
        y = max(0.0, y - 0.01)
    x0 = max(0, int(x * w))
    y0 = max(0, int(y * h))
    x1 = min(w, int((x + bw) * w))
    y1 = min(h, int((y + bh) * h))
    if x1 - x0 < 24 or y1 - y0 < 24:
        return None
    roi = im.crop((x0, y0, x1, y1))
    mw = max(roi.size)
    if mw > 1600:
        s = 1600.0 / mw
        roi = roi.resize(
            (max(1, int(roi.size[0] * s)), max(1, int(roi.size[1] * s))),
            Image.Resampling.BILINEAR,
        )
    buf = BytesIO()
    roi.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _merge_ocr(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(dst or {})
    for k in (
        "meeting_date",
        "start_time",
        "end_time",
        "meeting_location",
        "speaker_names",
    ):
        v = src.get(k)
        if v is None or v == "" or v == []:
            continue
        if k == "speaker_names" and isinstance(v, str):
            v = [v]
        if k == "speaker_names" and isinstance(v, list):
            cleaned = []
            for x in v:
                if not isinstance(x, str):
                    continue
                s = x.strip()
                if not s or s == "全体":
                    continue
                cleaned.append(s)
            if not cleaned:
                continue
            # 合并讲者名
            prev = out.get("speaker_names") or []
            if isinstance(prev, str):
                prev = [prev]
            merged_names = list(prev) if isinstance(prev, list) else []
            for n in cleaned:
                if n not in merged_names:
                    merged_names.append(n)
            out[k] = merged_names
            continue
        # 已有非空则不覆盖（先命中的分块优先）
        if out.get(k):
            continue
        out[k] = v
    return out


def _usable(loc: Dict[str, Any]) -> bool:
    score = float(loc.get("score") or 0.0)
    return score >= _UNC or bool(loc.get("hit")) or bool(loc.get("uncertain"))


def enrich_contexts_with_field_roi_ocr(
    contexts: List[AssetContext],
    pack: TemplatePack,
    vision: VisionClient,
) -> None:
    """对海报类材料：字段区 crop 匹配 → ROI OCR → 合并到 vision.ocr_fields。"""
    if not vision.available():
        return

    for ctx in contexts:
        if not ctx.ok or not ctx.body or ctx.photo_type not in _FIELD_TYPES:
            continue

        crops = _pick_crops(pack, ctx.photo_type)
        if not crops:
            continue

        tm = dict(ctx.template_match or {})
        key_meta: Dict[str, Any] = {"anchors": {}}
        merged: Dict[str, Any] = {}
        if isinstance(ctx.vision, dict):
            raw_of = ctx.vision.get("ocr_fields")
            if isinstance(raw_of, dict):
                merged = dict(raw_of)

        for role, crop_path in crops:
            # 分块：时间/地点条要够宽；日程/综合块要够高
            if role in {"time", "location"}:
                size_kw = {"min_rel_w": 0.25, "min_rel_h": 0.025, "max_rel_h": 0.25}
            elif role in {"agenda", "key_fields", "micro_key"}:
                size_kw = {"min_rel_w": 0.25, "min_rel_h": 0.12, "max_rel_h": 0.85}
            else:
                size_kw = {}
            located = match_ncc_locate(
                ctx.body,
                crop_path,
                scales=_SCALES,
                **size_kw,
            )
            # 用字段专用阈值覆盖 hit/uncertain
            score = float(located.get("score") or 0.0)
            located["hit"] = score >= _HIT
            located["uncertain"] = _UNC <= score < _HIT
            key_meta["anchors"][role] = {
                "score": located.get("score"),
                "hit": located.get("hit"),
                "uncertain": located.get("uncertain"),
                "ref": located.get("ref"),
                "box_norm": located.get("box_norm"),
            }
            if not _usable(located):
                continue
            box = located.get("box_norm")
            if not box:
                continue
            roi = _crop_roi_jpeg(ctx.body, box)
            if not roi:
                continue
            try:
                data = vision.ocr_key_fields_roi(roi, "image/jpeg")
            except VisionError as e:
                logger.warning(
                    "field ROI OCR failed photo_id=%s role=%s: %s",
                    ctx.photo_id,
                    role,
                    e,
                )
                key_meta["anchors"][role]["ocr_error"] = {
                    "code": e.code,
                    "message": e.message,
                }
                continue
            if isinstance(data, dict):
                merged = _merge_ocr(merged, data)
                key_meta["anchors"][role]["ocr"] = {
                    k: data.get(k)
                    for k in (
                        "meeting_date",
                        "start_time",
                        "end_time",
                        "meeting_location",
                        "speaker_names",
                    )
                }

        key_meta["ocr_fields"] = {
            k: merged.get(k)
            for k in (
                "meeting_date",
                "start_time",
                "end_time",
                "meeting_location",
                "speaker_names",
            )
        }
        tm["key_fields"] = key_meta
        ctx.template_match = tm
        if not ctx.vision:
            ctx.vision = {}
        ctx.vision["ocr_fields"] = merged

    # 台卡：整图抽姓名（不裁框）
    _enrich_name_cards(contexts, vision)


def _normalize_name_token(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or s.lower() in {"null", "none"}:
        return None
    # 去掉常见分隔空格
    s = s.replace(" ", "").replace("\u3000", "")
    if len(s) < 2:
        return None
    return s


def _names_from_payload(data: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    primary = _normalize_name_token(data.get("name"))
    if primary:
        out.append(primary)
    raw = data.get("name_card_names")
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        for item in raw:
            n = _normalize_name_token(item)
            if n and n not in out:
                out.append(n)
    return out


def _existing_vision_names(ctx: AssetContext) -> List[str]:
    """首轮 analyze 若已抽出姓名，可作为兜底。"""
    out: List[str] = []
    raw = (ctx.vision or {}).get("name_card_names")
    if isinstance(raw, str):
        raw = [raw]
    if isinstance(raw, list):
        for item in raw:
            n = _normalize_name_token(item)
            if n and n not in out:
                out.append(n)
    of = ctx.ocr_fields()
    for item in of.get("speaker_names") or []:
        n = _normalize_name_token(item)
        if n and n not in out:
            out.append(n)
    return out


def _downscale_jpeg(image_bytes: bytes, max_side: int = 1600) -> bytes:
    try:
        im = Image.open(BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return image_bytes
    w, h = im.size
    m = max(w, h)
    if m <= max_side:
        return image_bytes
    s = max_side / float(m)
    im = im.resize(
        (max(1, int(w * s)), max(1, int(h * s))),
        Image.Resampling.BILINEAR,
    )
    buf = BytesIO()
    im.save(buf, format="JPEG", quality=88)
    return buf.getvalue()


def _enrich_name_cards(
    contexts: List[AssetContext],
    vision: VisionClient,
) -> None:
    """台卡整图 OCR 姓名 → name_card_names；与 form 比对在规则层完成。"""
    for ctx in contexts:
        if not ctx.ok or not ctx.body or ctx.photo_type != "TableCard":
            continue

        names: List[str] = []
        raw_payload: Optional[Dict[str, Any]] = None
        method = "full_image"
        err: Optional[Dict[str, Any]] = None
        try:
            small = _downscale_jpeg(ctx.body, 1600)
            raw_payload = vision.ocr_name_cards_full(small, "image/jpeg")
            names = _names_from_payload(
                raw_payload if isinstance(raw_payload, dict) else {}
            )
        except VisionError as e:
            logger.warning(
                "name card full OCR failed photo_id=%s: %s",
                ctx.photo_id,
                e,
            )
            err = {"code": e.code, "message": e.message}
            method = "vision_error"

        if not names:
            fallback = _existing_vision_names(ctx)
            if fallback:
                names = fallback
                method = "analyze_fallback"

        tm = dict(ctx.template_match or {})
        tm["name_card_ocr"] = {
            "method": method,
            "names": names,
            "raw": raw_payload if isinstance(raw_payload, dict) else None,
            "error": err,
        }
        ctx.template_match = tm

        if not ctx.vision:
            ctx.vision = {}
        if names:
            ctx.vision["name_card_names"] = names
            of = ctx.vision.get("ocr_fields")
            if not isinstance(of, dict):
                of = {}
            else:
                of = dict(of)
            of["speaker_names"] = names
            ctx.vision["ocr_fields"] = of
