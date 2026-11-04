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


def _ncc_score(scene: np.ndarray, templ: np.ndarray) -> float:
    """归一化互相关最大值，约 [-1,1]，取 [0,1] 相似度。"""
    th, tw = templ.shape
    sh, sw = scene.shape
    if th >= sh or tw >= sw or th < 4 or tw < 4:
        return 0.0
    t = templ - templ.mean()
    t_std = float(t.std())
    if t_std < 1e-6:
        return 0.0
    t = t / t_std
    best = -1.0
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
    # 映射到 0~1
    return float(max(0.0, min(1.0, (best + 1.0) / 2.0)))


def match_ncc(
    scene_bytes: bytes,
    template_path: Path,
    scales: Tuple[float, ...] = (0.35, 0.5, 0.7, 1.0, 1.3),
) -> Dict[str, Any]:
    try:
        scene = Image.open(BytesIO(scene_bytes)).convert("RGB")
        templ_img = Image.open(template_path).convert("RGB")
    except Exception as e:
        return {"score": 0.0, "method": "ncc", "error": str(e), "hit": False}

    scene_g = _to_gray_array(scene, 960)
    tw0, th0 = templ_img.size
    best = 0.0
    for s in scales:
        tw = max(12, int(tw0 * s))
        th = max(12, int(th0 * s))
        if tw >= scene_g.shape[1] or th >= scene_g.shape[0]:
            continue
        t = templ_img.resize((tw, th), Image.Resampling.BILINEAR)
        t_g = np.asarray(t.convert("L"), dtype=np.float32)
        score = _ncc_score(scene_g, t_g)
        if score > best:
            best = score
    return {
        "score": round(best, 4),
        "method": "ncc",
        "ref": template_path.name,
        "hit": best >= 0.62,
        "uncertain": 0.52 <= best < 0.62,
    }


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
        if pack.logo and ctx.declared_type in {
            "POSTER",
            "STAND",
            "E_POSTER",
            "E_POSTER_DISPLAY",
            "PROJECT_INTRO_DISPLAY",
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
        if pack.poster_wave and ctx.declared_type in {"POSTER", "STAND"}:
            hits["poster_wave"] = match_ncc(ctx.body, pack.poster_wave)

        # 台卡
        if pack.name_card and ctx.declared_type == "NAME_CARD":
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
        if ctx.declared_type == "HANDBOOK":
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
        if ctx.declared_type == "PROJECT_INTRO_DISPLAY" and pack.equity1_ribbon:
            cv = match_ncc(ctx.body, pack.equity1_ribbon)
            hits["colorful_ribbon"] = cv
        if ctx.declared_type == "E_POSTER_DISPLAY" and pack.equity2_agenda:
            cv = match_ncc(ctx.body, pack.equity2_agenda)
            hits["agenda_table"] = cv

        ctx.template_match = hits
    return pack
