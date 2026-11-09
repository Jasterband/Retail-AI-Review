"""关键字段 / 台卡：模版 crop → NCC 定位 → ROI OCR。

流程（海报/展架/电子日程）：
1. 用字段区参考 crop（综合块，或 时间/地点/日程 分块）在整图上做多尺度 NCC
2. 取出命中框（略外扩）形成 ROI
3. 对 ROI 调 Vision，只抽 meeting_date / start_time / end_time /
   meeting_location / speaker_names
4. 写回 AssetContext.vision["ocr_fields"]（有值才覆盖）

流程（台卡 TableCard）：
1. 用单张台卡参考 crop（name_card_one_roi）在整图上多实例 NCC
2. 每张命中卡裁 ROI
3. 对 ROI 抽姓名 → 合并为 name_card_names
"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image

from app.services.pipeline.asset_context import AssetContext
from app.services.template_match import match_ncc_locate, match_ncc_locate_multi
from app.services.template_pack import TemplatePack
from app.services.vision.client import VisionClient, VisionError

logger = logging.getLogger(__name__)

_FIELD_TYPES = {"Poster", "Stand", "EDM", "EDMDisplay"}

# 现场照片透视/遮挡多，综合块难命中；分块锚点更稳
_SCALES = (0.12, 0.18, 0.25, 0.35, 0.5, 0.7, 1.0, 1.3)
_HIT = 0.58
_UNC = 0.48

# 单卡参考很小（~288px），4K 现场单卡常到 1500px+，尺度要拉大
_NAME_CARD_SCALES = (2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0)
_NAME_CARD_MIN_SCORE = 0.58
_NAME_CARD_TOP_K = 4
_NAME_CARD_ASPECT_MIN = 1.2
_NAME_CARD_ASPECT_MAX = 3.2


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

    # 台卡：单卡 crop 多实例定位 → 逐卡 ROI OCR 姓名
    _enrich_name_cards(contexts, pack, vision)


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


def _names_from_roi_payload(data: Dict[str, Any]) -> List[str]:
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


def _box_aspect_ok(box: Dict[str, float]) -> bool:
    w = float(box.get("w") or 0.0)
    h = float(box.get("h") or 0.0)
    if w <= 0 or h <= 0:
        return False
    aspect = w / h
    return _NAME_CARD_ASPECT_MIN <= aspect <= _NAME_CARD_ASPECT_MAX


def _boxes_from_ncc(scene_bytes: bytes, crop_path: Path) -> List[Dict[str, Any]]:
    located = match_ncc_locate_multi(
        scene_bytes,
        crop_path,
        top_k=_NAME_CARD_TOP_K,
        scales=_NAME_CARD_SCALES,
        min_rel_w=0.15,
        min_rel_h=0.12,
        max_rel_w=0.5,
        max_rel_h=0.55,
        min_score=_NAME_CARD_MIN_SCORE,
        suppress_pad=0.45,
    )
    out: List[Dict[str, Any]] = []
    for loc in located:
        box = loc.get("box_norm")
        if not isinstance(box, dict) or not _box_aspect_ok(box):
            continue
        out.append(
            {
                "box_norm": box,
                "score": float(loc.get("score") or 0.0),
                "method": "ncc",
                "name_hint": None,
            }
        )
    return out


def _downscale_jpeg(image_bytes: bytes, max_side: int = 1280) -> bytes:
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
    im.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _boxes_from_vision(
    vision: VisionClient,
    scene_bytes: bytes,
    ref_bytes: bytes,
) -> List[Dict[str, Any]]:
    # 缩小整图，布局更易被模型看全
    scene_small = _downscale_jpeg(scene_bytes, 1280)
    ref_small = _downscale_jpeg(ref_bytes, 512)
    try:
        data = vision.locate_name_cards(scene_small, ref_small)
    except VisionError as e:
        logger.warning("name card locate failed: %s", e)
        return []
    cards = data.get("cards") if isinstance(data, dict) else None
    if not isinstance(cards, list):
        # 模型偶发只回单个 name，视为定位失败
        logger.warning("name card locate bad payload keys=%s", list(data.keys()) if isinstance(data, dict) else type(data))
        return []
    out: List[Dict[str, Any]] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        box = card.get("box_norm")
        if not isinstance(box, dict):
            continue
        try:
            norm = {
                "x": float(box.get("x")),
                "y": float(box.get("y")),
                "w": float(box.get("w")),
                "h": float(box.get("h")),
            }
        except (TypeError, ValueError):
            continue
        if norm["w"] <= 0.05 or norm["h"] <= 0.05:
            continue
        if norm["x"] < 0 or norm["y"] < 0 or norm["x"] + norm["w"] > 1.05:
            continue
        out.append(
            {
                "box_norm": {
                    "x": round(max(0.0, norm["x"]), 4),
                    "y": round(max(0.0, norm["y"]), 4),
                    "w": round(min(1.0, norm["w"]), 4),
                    "h": round(min(1.0, norm["h"]), 4),
                },
                "score": 0.9,
                "method": "vision_ref",
                "name_hint": _normalize_name_token(card.get("name")),
            }
        )
    return _dedupe_boxes(out)


def _box_iou(a: Dict[str, float], b: Dict[str, float]) -> float:
    ax2 = a["x"] + a["w"]
    ay2 = a["y"] + a["h"]
    bx2 = b["x"] + b["w"]
    by2 = b["y"] + b["h"]
    ix1, iy1 = max(a["x"], b["x"]), max(a["y"], b["y"])
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def _dedupe_boxes(boxes: List[Dict[str, Any]], iou_thr: float = 0.45) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    for box in boxes:
        bn = box.get("box_norm") or {}
        if any(_box_iou(bn, k.get("box_norm") or {}) >= iou_thr for k in kept):
            continue
        kept.append(box)
    return kept


def _boxes_grid_fallback(n: int = 4) -> List[Dict[str, Any]]:
    """桌面四宫格兜底：常见 2x2 摆放。"""
    if n <= 0:
        return []
    # 略向中心收一点，避开桌边
    cells = [
        (0.04, 0.04, 0.46, 0.46),
        (0.50, 0.04, 0.46, 0.46),
        (0.04, 0.50, 0.46, 0.46),
        (0.50, 0.50, 0.46, 0.46),
    ]
    out = []
    for x, y, w, h in cells[: max(1, min(4, n))]:
        out.append(
            {
                "box_norm": {"x": x, "y": y, "w": w, "h": h},
                "score": 0.4,
                "method": "grid_2x2",
                "name_hint": None,
            }
        )
    return out


def _enrich_name_cards(
    contexts: List[AssetContext],
    pack: TemplatePack,
    vision: VisionClient,
) -> None:
    crop_path = pack.name_card
    if crop_path is None or not crop_path.is_file():
        return
    ref_bytes = crop_path.read_bytes()

    for ctx in contexts:
        if not ctx.ok or not ctx.body or ctx.photo_type != "TableCard":
            continue

        # 台卡姓名：参考 crop 对照定位各卡框 → 逐张 ROI OCR。
        # 优先 Vision 标框；失败再 NCC；若最终姓名仍 <2，用 2x2 网格兜底重跑。
        boxes = _boxes_from_vision(vision, ctx.body, ref_bytes)
        locate_method = "vision_ref"
        if len(boxes) < 2:
            ncc_boxes = _boxes_from_ncc(ctx.body, crop_path)
            if len(ncc_boxes) > len(boxes):
                boxes = ncc_boxes
                locate_method = "ncc"

        names, cards_meta = _ocr_name_card_boxes(vision, ctx, boxes, crop_path.name)
        # 大讲堂常见 4 张；姓名少于 3 时用 2x2 网格兜底，取更好的结果
        if len(names) < 3:
            grid_names, grid_meta = _ocr_name_card_boxes(
                vision, ctx, _boxes_grid_fallback(4), crop_path.name
            )
            if len(grid_names) > len(names):
                names, cards_meta = grid_names, grid_meta
                locate_method = "grid_2x2"

        tm = dict(ctx.template_match or {})
        tm["name_card_rois"] = {
            "ref": crop_path.name,
            "locate_method": locate_method,
            "cards": cards_meta,
            "names": names,
        }
        ctx.template_match = tm
        if not ctx.vision:
            ctx.vision = {}
        if names:
            prev = ctx.vision.get("name_card_names")
            prev_list: List[str] = []
            if isinstance(prev, list):
                prev_list = [x for x in (_normalize_name_token(n) for n in prev) if x]
            elif isinstance(prev, str):
                tok = _normalize_name_token(prev)
                if tok:
                    prev_list = [tok]
            if not prev_list or len(names) >= len(prev_list):
                ctx.vision["name_card_names"] = names
            of = ctx.vision.get("ocr_fields")
            if not isinstance(of, dict):
                of = {}
            else:
                of = dict(of)
            of["speaker_names"] = ctx.vision.get("name_card_names") or names
            ctx.vision["ocr_fields"] = of


def _ocr_name_card_boxes(
    vision: VisionClient,
    ctx: AssetContext,
    boxes: List[Dict[str, Any]],
    ref_name: str,
) -> Tuple[List[str], List[Dict[str, Any]]]:
    names: List[str] = []
    cards_meta: List[Dict[str, Any]] = []
    for loc in boxes:
        box = loc.get("box_norm") or {}
        item: Dict[str, Any] = {
            "score": loc.get("score"),
            "hit": True,
            "box_norm": box,
            "ref": ref_name,
            "method": loc.get("method"),
        }
        hint = loc.get("name_hint")
        roi = _crop_roi_jpeg(ctx.body or b"", box, pad=0.06)
        if not roi:
            if hint and hint not in names:
                names.append(hint)
                item["ocr"] = {"names": [hint], "from": "locate_hint"}
            cards_meta.append(item)
            continue
        try:
            data = vision.ocr_name_card_roi(roi, "image/jpeg")
        except VisionError as e:
            logger.warning(
                "name card ROI OCR failed photo_id=%s: %s",
                ctx.photo_id,
                e,
            )
            item["ocr_error"] = {"code": e.code, "message": e.message}
            if hint and hint not in names:
                names.append(hint)
                item["ocr"] = {"names": [hint], "from": "locate_hint"}
            cards_meta.append(item)
            continue
        got = _names_from_roi_payload(data if isinstance(data, dict) else {})
        if not got and hint:
            got = [hint]
        item["ocr"] = {"names": got, "raw": data if isinstance(data, dict) else None}
        for n in got:
            if n not in names:
                names.append(n)
        cards_meta.append(item)
    return names, cards_meta
