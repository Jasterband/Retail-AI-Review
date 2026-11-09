"""模版参考图匹配：多尺度 NCC（Pillow+numpy）+ 可选视觉对照。"""

from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from app.services.pipeline.asset_context import AssetContext
from app.services.template_pack import TemplatePack, get_template_pack, pack_version_from_refs
from app.services.vision.client import VisionClient, VisionError

logger = logging.getLogger(__name__)


def _to_gray_array(img: Image.Image, max_side: int) -> np.ndarray:
    g = img.convert("L")
    w, h = g.size
    m = max(w, h)
    if m > max_side:
        scale = max_side / m
        g = g.resize(
            (max(8, int(w * scale)), max(8, int(h * scale))),
            Image.Resampling.BILINEAR,
        )
    arr = np.asarray(g, dtype=np.float32)
    return arr


def _ncc_best(
    scene: np.ndarray, templ: np.ndarray
) -> Tuple[float, int, int]:
    """归一化互相关：返回 (score_0_1, best_y, best_x) 于 scene 坐标系。"""
    th, tw = templ.shape
    sh, sw = scene.shape
    if th >= sh or tw >= sw or th < 4 or tw < 4:
        return 0.0, 0, 0
    t = templ - templ.mean()
    t_std = float(t.std())
    if t_std < 1e-6:
        return 0.0, 0, 0
    t = t / t_std
    best = -1.0
    best_y, best_x = 0, 0
    # 粗网格滑动（性能）
    step_y = max(1, th // 6)
    step_x = max(1, tw // 6)
    for y in range(0, sh - th + 1, step_y):
        for x in range(0, sw - tw + 1, step_x):
            patch = scene[y : y + th, x : x + tw]
            p = patch - patch.mean()
            p_std = float(p.std())
            if p_std < 1e-6:
                continue
            score = float((p * t).mean() / p_std)
            if score > best:
                best = score
                best_y, best_x = y, x
    mapped = float(max(0.0, min(1.0, (best + 1.0) / 2.0)))
    return mapped, best_y, best_x


def _ncc_score(scene: np.ndarray, templ: np.ndarray) -> float:
    """归一化互相关最大值，约 [-1,1]，取 [0,1] 相似度。"""
    score, _, _ = _ncc_best(scene, templ)
    return score


def match_ncc(
    scene_bytes: bytes,
    template_path: Path,
    scales: Tuple[float, ...] = (0.35, 0.5, 0.7, 1.0, 1.3),
) -> Dict[str, Any]:
    located = match_ncc_locate(scene_bytes, template_path, scales=scales)
    return {
        "score": located.get("score", 0.0),
        "method": "ncc",
        "ref": located.get("ref") or template_path.name,
        "hit": bool(located.get("hit")),
        "uncertain": bool(located.get("uncertain")),
        **(
            {"error": located["error"]}
            if located.get("error")
            else {}
        ),
    }


def match_ncc_locate(
    scene_bytes: bytes,
    template_path: Path,
    scales: Tuple[float, ...] = (0.25, 0.35, 0.5, 0.7, 1.0, 1.25),
    max_side: int = 960,
    min_rel_w: float = 0.18,
    min_rel_h: float = 0.03,
    max_rel_w: float = 0.98,
    max_rel_h: float = 0.95,
) -> Dict[str, Any]:
    """NCC 匹配并返回最佳框（原图像素 + 归一化）。

    通过 min/max_rel_* 过滤过小/过大的假阳性尺度（字段区匹配必开）。
    """
    try:
        scene = Image.open(BytesIO(scene_bytes)).convert("RGB")
        templ_img = Image.open(template_path).convert("RGB")
    except Exception as e:
        return {
            "score": 0.0,
            "method": "ncc",
            "error": str(e),
            "hit": False,
            "uncertain": False,
            "ref": template_path.name,
        }

    orig_w, orig_h = scene.size
    scene_g = _to_gray_array(scene, max_side)
    # scene_g 相对原图的缩放
    scale_back_x = orig_w / float(scene_g.shape[1])
    scale_back_y = orig_h / float(scene_g.shape[0])

    tw0, th0 = templ_img.size
    best = 0.0
    best_box = None  # (x0,y0,x1,y1) in original pixels
    for s in scales:
        tw = max(12, int(tw0 * s))
        th = max(12, int(th0 * s))
        tw_g = max(12, int(tw / scale_back_x))
        th_g = max(12, int(th / scale_back_y))
        if tw_g >= scene_g.shape[1] or th_g >= scene_g.shape[0]:
            continue
        # 相对原图的宽高占比（过滤装饰条假阳性）
        rel_w = (tw_g * scale_back_x) / float(orig_w)
        rel_h = (th_g * scale_back_y) / float(orig_h)
        if rel_w < min_rel_w or rel_h < min_rel_h:
            continue
        if rel_w > max_rel_w or rel_h > max_rel_h:
            continue
        t = templ_img.resize((tw_g, th_g), Image.Resampling.BILINEAR)
        t_g = np.asarray(t.convert("L"), dtype=np.float32)
        score, y, x = _ncc_best(scene_g, t_g)
        if score > best:
            best = score
            x0 = int(x * scale_back_x)
            y0 = int(y * scale_back_y)
            x1 = int((x + tw_g) * scale_back_x)
            y1 = int((y + th_g) * scale_back_y)
            best_box = (x0, y0, x1, y1)

    out: Dict[str, Any] = {
        "score": round(best, 4),
        "method": "ncc",
        "ref": template_path.name,
        "hit": best >= 0.62,
        "uncertain": 0.52 <= best < 0.62,
    }
    if best_box is not None:
        x0, y0, x1, y1 = best_box
        out["box_px"] = {"x0": x0, "y0": y0, "x1": x1, "y1": y1}
        out["box_norm"] = {
            "x": round(x0 / float(orig_w), 4),
            "y": round(y0 / float(orig_h), 4),
            "w": round((x1 - x0) / float(orig_w), 4),
            "h": round((y1 - y0) / float(orig_h), 4),
        }
    return out


def match_ncc_locate_multi(
    scene_bytes: bytes,
    template_path: Path,
    *,
    top_k: int = 4,
    scales: Tuple[float, ...] = (0.2, 0.3, 0.45, 0.6, 0.8, 1.0, 1.25),
    max_side: int = 960,
    min_rel_w: float = 0.08,
    min_rel_h: float = 0.05,
    max_rel_w: float = 0.5,
    max_rel_h: float = 0.45,
    min_score: float = 0.52,
    suppress_pad: float = 0.15,
) -> List[Dict[str, Any]]:
    """多实例 NCC：反复取峰值并抑制邻域，用于一张图上多张台卡。"""
    try:
        scene = Image.open(BytesIO(scene_bytes)).convert("RGB")
        templ_img = Image.open(template_path).convert("RGB")
    except Exception as e:
        return [
            {
                "score": 0.0,
                "method": "ncc",
                "error": str(e),
                "hit": False,
                "uncertain": False,
                "ref": template_path.name,
            }
        ]

    orig_w, orig_h = scene.size
    scene_g = _to_gray_array(scene, max_side)
    scale_back_x = orig_w / float(scene_g.shape[1])
    scale_back_y = orig_h / float(scene_g.shape[0])
    tw0, th0 = templ_img.size

    # 预计算各尺度模板
    scale_templates: List[Tuple[float, int, int, np.ndarray]] = []
    for s in scales:
        tw_g = max(12, int((tw0 * s) / scale_back_x))
        th_g = max(12, int((th0 * s) / scale_back_y))
        if tw_g >= scene_g.shape[1] or th_g >= scene_g.shape[0]:
            continue
        rel_w = (tw_g * scale_back_x) / float(orig_w)
        rel_h = (th_g * scale_back_y) / float(orig_h)
        if rel_w < min_rel_w or rel_h < min_rel_h:
            continue
        if rel_w > max_rel_w or rel_h > max_rel_h:
            continue
        t = templ_img.resize((tw_g, th_g), Image.Resampling.BILINEAR)
        t_g = np.asarray(t.convert("L"), dtype=np.float32)
        scale_templates.append((s, tw_g, th_g, t_g))

    if not scale_templates:
        return []

    working = scene_g.copy()
    results: List[Dict[str, Any]] = []
    for _ in range(max(1, top_k)):
        best = 0.0
        best_box_g = None  # x,y,tw,th in gray space
        for _s, tw_g, th_g, t_g in scale_templates:
            score, y, x = _ncc_best(working, t_g)
            if score > best:
                best = score
                best_box_g = (x, y, tw_g, th_g)
        if best_box_g is None or best < min_score:
            break
        x, y, tw_g, th_g = best_box_g
        x0 = int(x * scale_back_x)
        y0 = int(y * scale_back_y)
        x1 = int((x + tw_g) * scale_back_x)
        y1 = int((y + th_g) * scale_back_y)
        results.append(
            {
                "score": round(best, 4),
                "method": "ncc",
                "ref": template_path.name,
                "hit": best >= 0.62,
                "uncertain": 0.52 <= best < 0.62,
                "box_px": {"x0": x0, "y0": y0, "x1": x1, "y1": y1},
                "box_norm": {
                    "x": round(x0 / float(orig_w), 4),
                    "y": round(y0 / float(orig_h), 4),
                    "w": round((x1 - x0) / float(orig_w), 4),
                    "h": round((y1 - y0) / float(orig_h), 4),
                },
            }
        )
        # 抑制已命中区域，避免重复捡同一张卡
        pad_x = max(1, int(tw_g * suppress_pad))
        pad_y = max(1, int(th_g * suppress_pad))
        yy0 = max(0, y - pad_y)
        xx0 = max(0, x - pad_x)
        yy1 = min(working.shape[0], y + th_g + pad_y)
        xx1 = min(working.shape[1], x + tw_g + pad_x)
        working[yy0:yy1, xx0:xx1] = float(np.mean(working))

    return results


def _prefer(
    cv: Optional[Dict[str, Any]],
    vision: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """融合：有视觉高置信优先；否则取较高分。"""
    parts = [x for x in (cv, vision) if x]
    if not parts:
        return {"score": 0.0, "hit": False, "method": "none"}
    # vision match true/false
    best = max(parts, key=lambda d: float(d.get("score") or 0))
    if vision and vision.get("hit") is True and float(vision.get("score") or 0) >= 0.7:
        return {**vision, "cv": cv, "fused": True}
    if cv and cv.get("hit") is True and float(cv.get("score") or 0) >= 0.65:
        return {**cv, "vision": vision, "fused": True}
    out = dict(best)
    out["cv"] = cv
    out["vision"] = vision
    out["fused"] = True
    # 若两边都弱
    if not out.get("hit") and vision and vision.get("hit") is False and cv and not cv.get("hit"):
        out["hit"] = False
    return out


def enrich_contexts_with_templates(
    contexts: List[AssetContext],
    project_type: str,
    vision: Optional[VisionClient] = None,
    refs: Optional[dict] = None,
) -> TemplatePack:
    pack = get_template_pack(pack_version_from_refs(refs))
    for ctx in contexts:
        if not ctx.ok or not ctx.body:
            ctx.template_match = {}
            continue
        hits: Dict[str, Any] = {}

        # Logo：官方参考图 → 视觉对照为主，NCC 为辅
        if pack.logo and ctx.photo_type in {
            "Poster",
            "Stand",
            "EDM",
            "EDMDisplay",
            "ProjectIntro",
        }:
            cv = match_ncc(ctx.body, pack.logo)
            vis = None
            if vision and vision.available():
                try:
                    vis = vision.compare_reference(
                        ctx.body,
                        ctx.content_type,
                        pack.logo.read_bytes(),
                        "image/png",
                        question=(
                            "第一张是拜耳官方 Logo 参考图（Bayer Cross）。"
                            "第二张是现场材料照片。第二张中是否出现拜耳十字 Logo"
                            "（圆形十字/BAYER字样，颜色或底色可变）？"
                            '返回 JSON: {"match": true|false, "confidence": 0~1}'
                        ),
                    )
                except VisionError as e:
                    logger.warning("logo vision ref failed: %s", e)
            hits["bayer_logo"] = _prefer(cv, vis)

        # 大讲堂海报波浪
        if pack.poster_wave and ctx.photo_type in {"Poster", "Stand"}:
            hits["poster_wave"] = match_ncc(ctx.body, pack.poster_wave)

        # 台卡
        if pack.name_card and ctx.photo_type == "TableCard":
            cv = match_ncc(ctx.body, pack.name_card)
            vis = None
            if vision and vision.available():
                try:
                    vis = vision.compare_reference(
                        ctx.body,
                        ctx.content_type,
                        pack.name_card.read_bytes(),
                        "image/jpeg",
                        question=(
                            "第一张是规定台卡模版参考（单卡）。"
                            "第二张是现场台卡照片。第二张中的台卡版式是否与参考同类"
                            "（白底姓名卡+底部装饰）？"
                            '返回 JSON: {"match": true|false, "confidence": 0~1}'
                        ),
                    )
                except VisionError as e:
                    logger.warning("name_card vision ref failed: %s", e)
            hits["name_card"] = _prefer(cv, vis)
            if pack.name_card_border:
                hits["name_card_border"] = match_ncc(ctx.body, pack.name_card_border)

        # 手册封面：当期 / 旧版负样本
        if ctx.photo_type == "Manual":
            if pack.handbook_current:
                cv = match_ncc(ctx.body, pack.handbook_current)
                vis = None
                if vision and vision.available():
                    try:
                        vis = vision.compare_reference(
                            ctx.body,
                            ctx.content_type,
                            pack.handbook_current.read_bytes(),
                            "image/jpeg",
                            question=(
                                "第一张是当期「菁英药师大讲堂」宣传手册封面参考。"
                                "第二张是否为同一版式/同期封面（非明显旧版）？"
                                '返回 JSON: {"match": true|false, "confidence": 0~1}'
                            ),
                        )
                    except VisionError as e:
                        logger.warning("handbook vision ref failed: %s", e)
                hits["handbook_current"] = _prefer(cv, vis)
            if pack.handbook_stale:
                hits["handbook_stale"] = match_ncc(ctx.body, pack.handbook_stale)

        # 微型权益一丝带 / 权益二日程表
        if ctx.photo_type == "ProjectIntro" and pack.equity1_ribbon:
            cv = match_ncc(ctx.body, pack.equity1_ribbon)
            hits["colorful_ribbon"] = cv
        if ctx.photo_type == "EDMDisplay" and pack.equity2_agenda:
            cv = match_ncc(ctx.body, pack.equity2_agenda)
            hits["agenda_table"] = cv

        ctx.template_match = hits
    return pack
