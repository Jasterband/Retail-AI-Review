"""审核阈值默认值（可被请求 options 覆盖）。"""

from __future__ import annotations

from typing import Any, Dict, Optional


# 与 docs/03-rule-matrix.md / docs/thresholds.md 对齐
DEFAULTS: Dict[str, Any] = {
    "human_confidence_threshold": 0.75,
    # 海报等日程起止时间容差；不做时间水印检测
    "watermark_time_skew_minutes": 120,
    "name_match_mode": "fuzzy",
    "image_phash_max_distance": 10,
    "image_similarity_threshold": 0.92,
    "template_similarity_pass": 0.85,
    "template_similarity_fail": 0.65,
    "ncc_hit_threshold": 0.62,
    "ncc_uncertain_threshold": 0.52,
    "panorama_count_min_confidence": 0.70,
    "panorama_need_lecture_hall": 35,
    "panorama_need_micro_single": 6,
    "panorama_need_micro_dual": 12,
    "signin_duration_lecture_hall": 120,
    "signin_duration_micro_single": 30,
    "signin_duration_micro_dual": 60,
    "signin_audience_per_speaker": 6,
    "logo_confidence_pass": 0.55,
    "sponsor_confidence_pass": 0.55,
}


def merge_thresholds(options: Optional[dict] = None) -> Dict[str, Any]:
    out = dict(DEFAULTS)
    if not options:
        return out
    for k, v in options.items():
        if v is not None:
            out[k] = v
    return out


def panorama_need(project_type: str, meeting_type: Optional[str], thr: dict) -> int:
    if project_type == "LECTURE_HALL":
        return int(thr["panorama_need_lecture_hall"])
    if meeting_type == "DUAL":
        return int(thr["panorama_need_micro_dual"])
    return int(thr["panorama_need_micro_single"])


def signin_duration_need(
    project_type: str, meeting_type: Optional[str], thr: dict
) -> int:
    if project_type == "LECTURE_HALL":
        return int(thr["signin_duration_lecture_hall"])
    if meeting_type == "DUAL":
        return int(thr["signin_duration_micro_dual"])
    return int(thr["signin_duration_micro_single"])


def signin_audience_need(
    project_type: str,
    meeting_type: Optional[str],
    form: Optional[dict],
    thr: dict,
) -> int:
    """签到表听众人数下限：大讲堂 ≥35；微型 ≥ 讲者数×6（与门店规则一致）。"""
    if project_type == "LECTURE_HALL":
        return int(thr["panorama_need_lecture_hall"])
    form = form or {}
    n_speakers = len(form.get("speakers") or [])
    per = int(thr.get("signin_audience_per_speaker", 6))
    if n_speakers > 0:
        return n_speakers * per
    return panorama_need(project_type, meeting_type, thr)
