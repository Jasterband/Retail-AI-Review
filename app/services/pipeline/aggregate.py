"""规则结果 → overall_status + asset_results + summaries。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome
from app.services.text_norm import (
    date_equal,
    fuzzy_contains,
    name_set_equal,
    normalize_topic,
    time_to_minutes,
)
from app.services.thresholds import merge_thresholds


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _asset_status_from_rules(
    asset_id: int,
    ctx: AssetContext,
    rules: List[RuleOutcome],
) -> Dict[str, Any]:
    if ctx.fetch_error_code:
        return {
            "asset_status": "ERROR",
            "fail_reasons": [
                {
                    "check": None,
                    "reason_code": ctx.fetch_error_code,
                    "reason_text": ctx.fetch_error_message
                    or "材料下载失败",
                }
            ],
        }

    fail_reasons: List[dict] = []
    has_fail = False
    has_uncertain = False
    for r in rules:
        if asset_id not in (r.related_asset_ids or []):
            continue
        if r.status == "FAIL":
            has_fail = True
            fail_reasons.append(
                {
                    "check": r.rule_code,
                    "reason_code": r.reason_code,
                    "reason_text": r.reason_text or r.rule_code,
                }
            )
        elif r.status == "UNCERTAIN":
            has_uncertain = True
            fail_reasons.append(
                {
                    "check": r.rule_code,
                    "reason_code": r.reason_code,
                    "reason_text": r.reason_text or r.rule_code,
                }
            )

    if has_fail:
        status = "FAIL"
    elif has_uncertain:
        status = "UNCERTAIN"
    else:
        status = "PASS"
        fail_reasons = []
    return {"asset_status": status, "fail_reasons": fail_reasons}


def _build_checks(
    ctx: AssetContext,
    form: Optional[dict] = None,
    options: Optional[dict] = None,
    *,
    image_dup_hit: bool = False,
) -> Dict[str, Optional[bool]]:
    v = ctx.vision or {}
    of = ctx.ocr_fields()
    form = form or {}
    thr = merge_thresholds(options)
    clarity_thr = float(thr.get("clarity_threshold", 0.6))
    skew = int(thr.get("watermark_time_skew_minutes", 120))
    mode = thr.get("name_match_mode", "fuzzy")

    checks: Dict[str, Optional[bool]] = {
        "type_match": (
            None
            if not ctx.detected_type()
            else ctx.detected_type() == ctx.declared_type
        ),
        "is_clear": None,
        "image_not_duplicated": not image_dup_hit,
        "has_bayer_logo": v.get("has_bayer_logo"),
    }
    score = ctx.clarity_score()
    if score is not None:
        checks["is_clear"] = score >= clarity_thr

    poster_types = {"POSTER", "STAND", "E_POSTER", "E_POSTER_DISPLAY"}
    if ctx.declared_type in poster_types:
        form_date = form.get("meeting_date")
        form_loc = form.get("location") or ""
        form_names = [s["speaker_name"] for s in form.get("speakers") or []]
        start = time_to_minutes(form.get("start_time"))
        end = time_to_minutes(form.get("end_time"))

        if of.get("meeting_date") and form_date:
            checks["date_matches_form"] = date_equal(of.get("meeting_date"), form_date)
        else:
            checks["date_matches_form"] = None

        if of.get("location") and form_loc:
            checks["location_matches_form"] = fuzzy_contains(
                of["location"], form_loc
            ) or fuzzy_contains(form_loc, of["location"])
        else:
            checks["location_matches_form"] = None

        ocr_names = of.get("speaker_names") or []
        if ocr_names and form_names and ctx.declared_type in {
            "POSTER",
            "STAND",
            "E_POSTER",
        }:
            checks["speakers_match_form"] = bool(
                name_set_equal(ocr_names, form_names, mode)["ok"]
                or not name_set_equal(ocr_names, form_names, mode)["missing"]
            )
        else:
            checks["speakers_match_form"] = None

        times = []
        for key in ("start_time", "end_time", "watermark_time"):
            tm = time_to_minutes(of.get(key))
            if tm is not None:
                times.append(tm)
        if times and start is not None and end is not None:
            checks["time_matches_form"] = all(
                start - skew <= tm <= end + skew for tm in times
            )
        else:
            checks["time_matches_form"] = None

    if ctx.declared_type == "NAME_CARD":
        form_names = [s["speaker_name"] for s in form.get("speakers") or []]
        ocr_names = v.get("name_card_names") or of.get("speaker_names") or []
        if ocr_names and form_names:
            checks["name_set_matches_speakers"] = bool(
                name_set_equal(ocr_names, form_names, mode)["ok"]
            )
        else:
            checks["name_set_matches_speakers"] = None

    if ctx.declared_type == "SPEAKER_PHOTO" and of.get("topic_title"):
        speakers = {s["speaker_id"]: s for s in form.get("speakers") or []}
        sp = speakers.get(ctx.speaker_id) or {}
        expected = normalize_topic(sp.get("topic") or "")
        got = normalize_topic(of.get("topic_title") or "")
        if expected and got:
            checks["topic_matches_form"] = expected == got or expected in got or got in expected
        else:
            checks["topic_matches_form"] = None

    # 微型权益：一查彩色丝带，二查日程表（模版 pack 优先）
    tm = ctx.template_match or {}
    if ctx.declared_type == "PROJECT_INTRO_DISPLAY":
        ribbon = tm.get("colorful_ribbon") or {}
        checks["has_colorful_ribbon"] = (
            ribbon.get("hit")
            if ribbon
            else v.get("has_colorful_ribbon")
        )
        checks["ppt_template_match"] = checks["has_colorful_ribbon"]
    if ctx.declared_type == "E_POSTER_DISPLAY":
        agenda = tm.get("agenda_table") or {}
        checks["has_agenda_table"] = (
            agenda.get("hit") if agenda else v.get("has_agenda_table")
        )
        checks["ppt_template_match"] = checks["has_agenda_table"]
    if tm.get("bayer_logo"):
        checks["has_bayer_logo"] = tm["bayer_logo"].get("hit")
    if tm.get("poster_wave"):
        checks["poster_wave_match"] = tm["poster_wave"].get("hit")
    if tm.get("name_card"):
        checks["name_card_template_match"] = tm["name_card"].get("hit")
    if tm.get("handbook_current"):
        checks["handbook_detected"] = tm["handbook_current"].get("hit")
    if ctx.declared_type == "HANDBOOK":
        from app.config import get_settings

        need_year = int(get_settings().handbook_current_year)
        year = v.get("handbook_year") or of.get("handbook_year")
        try:
            year_i = int(year) if year is not None else None
        except (TypeError, ValueError):
            year_i = None
            if year is not None:
                import re

                m = re.search(r"(20\d{2})", str(year))
                year_i = int(m.group(1)) if m else None
        if year_i is not None:
            checks["handbook_not_stale"] = year_i == need_year
        elif tm.get("handbook_stale"):
            checks["handbook_not_stale"] = not tm["handbook_stale"].get("hit")
        else:
            checks["handbook_not_stale"] = None
    return checks


def build_asset_results(
    contexts: List[AssetContext],
    rules: List[RuleOutcome],
    form: Optional[dict] = None,
    options: Optional[dict] = None,
) -> List[dict]:
    thr = merge_thresholds(options)
    clarity_thr = float(thr.get("clarity_threshold", 0.6))
    out = []
    for ctx in contexts:
        st = _asset_status_from_rules(ctx.asset_id, ctx, rules)
        image_dup_hit = any(
            r.rule_code == "IMAGE_DUP"
            and r.status == "FAIL"
            and ctx.asset_id in (r.related_asset_ids or [])
            for r in rules
        )
        topic_reuse_hit = any(
            r.rule_code == "TOPIC_REUSE"
            and r.status == "FAIL"
            and ctx.asset_id in (r.related_asset_ids or [])
            for r in rules
        )
        topic_text = None
        if ctx.declared_type == "SPEAKER_PHOTO":
            topic_text = ctx.ocr_fields().get("topic_title")

        item = {
            "asset_id": ctx.asset_id,
            "declared_type": ctx.declared_type,
            "asset_status": st["asset_status"],
            "fail_reasons": st["fail_reasons"],
            "detected_type": ctx.detected_type(),
            "type_match": (
                None
                if not ctx.detected_type()
                else ctx.detected_type() == ctx.declared_type
            ),
            "clarity_score": ctx.clarity_score(),
            "is_clear": (
                None
                if ctx.clarity_score() is None
                else ctx.clarity_score() >= clarity_thr
            ),
            "checks": _build_checks(
                ctx, form, options, image_dup_hit=image_dup_hit
            ),
            "uncertain_checks": [],
            "ocr_fields": ctx.ocr_fields() or None,
            "ocr_raw": None,
            "detections": None,
            "image_dup_hit": image_dup_hit,
            "topic_reuse_hit": topic_reuse_hit,
            "topic_text_ocr": topic_text,
            "model_scores": {
                "type_confidence": ctx.vision.get("type_confidence"),
                "logo_confidence": ctx.vision.get("logo_confidence"),
                "template_match": ctx.template_match or None,
            },
            "fetch_error": (
                {
                    "code": ctx.fetch_error_code,
                    "message": ctx.fetch_error_message or "",
                    "retryable": False,
                }
                if ctx.fetch_error_code
                else None
            ),
        }
        # enrich image_dup refs from evidence
        for r in rules:
            if r.rule_code == "IMAGE_DUP" and r.status == "FAIL" and r.evidence:
                for h in r.evidence.get("hits") or []:
                    if h.get("asset_id") == ctx.asset_id:
                        item["image_dup_kind"] = h.get("kind") or "similar"
                        item["image_dup_score"] = h.get("similarity")
                        if h.get("distance") is not None and h.get("similarity") is None:
                            # 将 phash 距离映射成可读相似度近似：0→1.0，阈值→阈值边缘
                            max_d = float(thr.get("image_phash_max_distance", 10)) or 10.0
                            item["image_dup_score"] = round(
                                max(0.0, 1.0 - float(h["distance"]) / max_d), 4
                            )
                        item["image_dup_ref_meeting_id"] = h.get("ref_meeting_id")
                        item["image_dup_ref_session_no"] = h.get("ref_session_no")
        out.append(item)
    return out


def aggregate_overall(rules: List[RuleOutcome]) -> Dict[str, Any]:
    """按契约聚合 overall_status。"""
    # system-level: ASSET_MISSING hard fail with S3 can be ERROR if all failed?
    # Plan: ASSET_MISSING FAIL is business FAIL; MODEL errors handled before rules.

    has_fail = any(r.status == "FAIL" and not r.trigger_human for r in rules)
    has_uncertain = any(
        r.status == "UNCERTAIN" or r.trigger_human for r in rules
    )

    if has_fail:
        overall = "FAIL"
    elif has_uncertain:
        overall = "NEED_HUMAN"
    else:
        overall = "PASS"

    confs = [r.confidence for r in rules if r.confidence is not None and r.status != "SKIP"]
    overall_confidence = min(confs) if confs else None

    summary_matched = []
    summary_failed = []
    need_human = []
    for r in rules:
        if r.status == "PASS" and r.reason_text:
            summary_matched.append(r.reason_text)
        elif r.status == "FAIL" and r.reason_text:
            summary_failed.append(r.reason_text)
        elif r.status == "UNCERTAIN" and r.reason_text:
            need_human.append(r.reason_text)

    return {
        "overall_status": overall,
        "overall_confidence": overall_confidence,
        "summary_matched": summary_matched[:12],
        "summary_failed": summary_failed,
        "need_human_reasons": need_human,
    }


def build_full_response(
    snap: dict,
    job_id: int,
    attempt_no: int,
    contexts: List[AssetContext],
    rules: List[RuleOutcome],
    pipeline_steps: List[dict],
    error: Optional[dict] = None,
) -> dict:
    settings = get_settings()
    assets = build_asset_results(
        contexts,
        rules,
        form=snap.get("form") or {},
        options=snap.get("options") or {},
    )
    if error:
        overall = {
            "overall_status": "ERROR",
            "overall_confidence": None,
            "summary_matched": [],
            "summary_failed": [],
            "need_human_reasons": [],
        }
    else:
        overall = aggregate_overall(rules)

    refs = snap.get("refs") or {}
    return {
        "response_mode": "full",
        "request_id": snap["request_id"],
        "meeting_id": snap["meeting_id"],
        "job_id": job_id,
        "attempt_no": attempt_no,
        "overall_status": overall["overall_status"] if not error else "ERROR",
        "overall_confidence": overall.get("overall_confidence"),
        "model_version": settings.model_version,
        "template_pack_version": refs.get("template_pack_version"),
        "summary_matched": overall["summary_matched"],
        "summary_failed": overall["summary_failed"],
        "need_human_reasons": overall["need_human_reasons"],
        "error": error,
        "asset_results": assets,
        "rule_results": [r.to_dict() for r in rules],
        "debug": {
            "pipeline_steps": pipeline_steps,
            "notes": "vision + phash/embedding pipeline",
        },
        "finished_at": _utcnow(),
    }
