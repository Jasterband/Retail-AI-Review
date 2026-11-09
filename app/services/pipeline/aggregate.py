"""规则结果 → overall_status + photo_results + summaries。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome
from app.services.text_norm import (
    date_equal,
    duration_minutes_from_times,
    fuzzy_contains,
    name_set_equal,
    normalize_name,
    normalize_topic,
    time_to_minutes,
)
from app.services.thresholds import merge_thresholds, signin_duration_need


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _coerce_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes"):
            return True
        if s in ("false", "0", "no"):
            return False
        if s in ("null", "none", ""):
            return None
    return None


def _as_name_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        out = []
        for item in value:
            name = normalize_name(item)
            if name:
                out.append(item if isinstance(item, str) else name)
        return out
    return []


def _signin_payload(ctx: AssetContext) -> dict:
    v = ctx.vision or {}
    of = ctx.ocr_fields()
    signin = v.get("signin") if isinstance(v.get("signin"), dict) else {}
    return {
        "start_time": signin.get("start_time") or of.get("start_time"),
        "end_time": signin.get("end_time") or of.get("end_time"),
        "duration_minutes": signin.get("duration_minutes"),
        "audience_count": signin.get("audience_count"),
        "store_names": signin.get("store_names") or [],
    }


def _photo_status_from_rules(
    photo_id: str,
    ctx: AssetContext,
    rules: List[RuleOutcome],
) -> Dict[str, Any]:
    if ctx.fetch_error_code:
        return {
            "photo_status": "ERROR",
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
        if photo_id not in (r.related_photo_ids or []):
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
    return {"photo_status": status, "fail_reasons": fail_reasons}


def _build_checks(
    ctx: AssetContext,
    form: Optional[dict] = None,
    options: Optional[dict] = None,
    *,
    image_dup_hit: bool = False,
    topic_reuse_hit: bool = False,
    project_type: Optional[str] = None,
    meeting_type: Optional[str] = None,
) -> Dict[str, Optional[bool]]:
    """按 docs/检测点清单与photo_results.md 组装单张 checks（不适用则为 null）。"""
    v = ctx.vision or {}
    of = ctx.ocr_fields()
    form = form or {}
    thr = merge_thresholds(options)
    clarity_thr = float(thr.get("clarity_threshold", 0.6))
    skew = int(thr.get("watermark_time_skew_minutes", 120))
    mode = thr.get("name_match_mode", "fuzzy")
    tm = ctx.template_match or {}
    pt = ctx.photo_type

    checks: Dict[str, Optional[bool]] = {
        # 通用
        "type_match": True if pt else None,
        "is_clear": None,
        "image_not_duplicated": not image_dup_hit,
        "has_bayer_logo": _coerce_bool(v.get("has_bayer_logo")),
    }
    score = ctx.clarity_score()
    if score is not None:
        checks["is_clear"] = score >= clarity_thr

    poster_types = {"Poster", "Stand", "EDM", "EDMDisplay"}
    if pt in poster_types:
        form_date = form.get("meeting_date")
        form_loc = form.get("meeting_location") or ""
        form_names = [s["speaker_name"] for s in form.get("speakers") or []]
        start = time_to_minutes(form.get("start_time"))
        end = time_to_minutes(form.get("end_time"))

        if of.get("meeting_date") and form_date:
            checks["date_matches_form"] = date_equal(of.get("meeting_date"), form_date)
        else:
            checks["date_matches_form"] = None

        ocr_loc = of.get("meeting_location") or of.get("location")
        if ocr_loc and form_loc:
            checks["location_matches_form"] = fuzzy_contains(
                ocr_loc, form_loc
            ) or fuzzy_contains(form_loc, ocr_loc)
        else:
            checks["location_matches_form"] = None

        ocr_names = _as_name_list(of.get("speaker_names"))
        if ocr_names and form_names and pt in {"Poster", "Stand", "EDM"}:
            cmp = name_set_equal(ocr_names, form_names, mode)
            checks["speakers_match_form"] = bool(cmp["ok"] or not cmp["missing"])
        else:
            checks["speakers_match_form"] = None

        times = []
        for key in ("start_time", "end_time", "watermark_time"):
            tm_m = time_to_minutes(of.get(key))
            if tm_m is not None:
                times.append(tm_m)
        if times and start is not None and end is not None:
            checks["time_matches_form"] = all(
                start - skew <= t <= end + skew for t in times
            )
        else:
            checks["time_matches_form"] = None

    if pt == "TableCard":
        form_names = [s["speaker_name"] for s in form.get("speakers") or []]
        ocr_names = _as_name_list(
            v.get("name_card_names") or of.get("speaker_names")
        )
        checks["name_card_count_ok"] = (
            len(ocr_names) == len(form_names) if form_names else None
        )
        if ocr_names and form_names:
            checks["name_set_matches_speakers"] = bool(
                name_set_equal(ocr_names, form_names, mode)["ok"]
            )
        else:
            checks["name_set_matches_speakers"] = None
        checks["name_card_template_ok"] = None
        checks["name_card_template_match"] = None

    if pt in ("SpeakerTitle", "SpeakerLecture"):
        speakers = {s["speaker_id"]: s for s in form.get("speakers") or []}
        sp = speakers.get(ctx.speaker_id) or {}
        expected = normalize_topic(sp.get("topic") or "")
        got = normalize_topic(of.get("topic_title") or "")
        if pt == "SpeakerTitle":
            if expected and got:
                checks["topic_matches_form"] = (
                    expected == got or expected in got or got in expected
                )
            else:
                checks["topic_matches_form"] = None
            # 主题库空 / SKIP 时不算命中；命中 FAIL 才 false，能抽到标题则 true
            if topic_reuse_hit:
                checks["topic_not_reused_in_period"] = False
            elif got:
                checks["topic_not_reused_in_period"] = True
            else:
                checks["topic_not_reused_in_period"] = None
        else:
            checks["topic_matches_form"] = None
            checks["topic_not_reused_in_period"] = None

        visible = of.get("speaker_name_on_slide") or (
            (_as_name_list(of.get("speaker_names")) or [None])[0]
        )
        if visible and sp.get("speaker_name"):
            checks["speaker_name_visible_ok"] = bool(
                name_set_equal([visible], [sp["speaker_name"]], mode)["ok"]
                or normalize_name(visible) == normalize_name(sp["speaker_name"])
            )
        elif visible:
            checks["speaker_name_visible_ok"] = True
        else:
            checks["speaker_name_visible_ok"] = None

    if pt == "Panorama":
        pc = v.get("people_count")
        try:
            checks["people_count_recorded"] = pc is not None and int(pc) >= 0
        except (TypeError, ValueError):
            checks["people_count_recorded"] = False

    if pt == "SignSheet":
        signin = _signin_payload(ctx)
        dur = duration_minutes_from_times(
            signin.get("start_time"),
            signin.get("end_time"),
            signin.get("duration_minutes"),
        )
        checks["signin_template_ok"] = _coerce_bool(v.get("signin_template_ok"))
        checks["duration_readable"] = dur is not None
        if dur is None:
            checks["duration_meets_threshold"] = None
        else:
            need = signin_duration_need(
                project_type or "LECTURE_HALL", meeting_type, thr
            )
            checks["duration_meets_threshold"] = dur > need

    if pt == "ProjectIntro":
        ribbon = tm.get("colorful_ribbon") or {}
        checks["has_colorful_ribbon"] = (
            ribbon.get("hit") if ribbon else _coerce_bool(v.get("has_colorful_ribbon"))
        )
        checks["ppt_template_match"] = checks["has_colorful_ribbon"]
        kind = v.get("ppt_page_kind")
        checks["ppt_page_kind_ok"] = (
            kind == "PROJECT_INTRO" if kind else None
        )

    if pt == "EDMDisplay":
        agenda = tm.get("agenda_table") or {}
        checks["has_agenda_table"] = (
            agenda.get("hit") if agenda else _coerce_bool(v.get("has_agenda_table"))
        )
        checks["ppt_template_match"] = checks["has_agenda_table"]
        kind = v.get("ppt_page_kind")
        checks["ppt_page_kind_ok"] = kind == "AGENDA" if kind else None

    if tm.get("bayer_logo"):
        checks["has_bayer_logo"] = tm["bayer_logo"].get("hit")
    if tm.get("poster_wave") and pt in {"Poster", "Stand"}:
        checks["poster_wave_match"] = tm["poster_wave"].get("hit")
    if tm.get("name_card") and pt == "TableCard":
        hit = tm["name_card"].get("hit")
        checks["name_card_template_match"] = hit
        checks["name_card_template_ok"] = hit
    if tm.get("handbook_current") and pt == "Manual":
        checks["handbook_detected"] = tm["handbook_current"].get("hit")

    if pt == "Manual":
        if "handbook_detected" not in checks:
            checks["handbook_detected"] = _coerce_bool(v.get("handbook_ok"))
        need_year = int(get_settings().handbook_current_year)
        year = v.get("handbook_year") or of.get("handbook_year")
        try:
            year_i = int(year) if year is not None else None
        except (TypeError, ValueError):
            year_i = None
            if year is not None:
                m = re.search(r"(20\d{2})", str(year))
                year_i = int(m.group(1)) if m else None
        if year_i is not None:
            checks["handbook_not_stale"] = year_i == need_year
        elif tm.get("handbook_stale"):
            checks["handbook_not_stale"] = not tm["handbook_stale"].get("hit")
        else:
            checks["handbook_not_stale"] = None

    return checks


def build_photo_results(
    contexts: List[AssetContext],
    rules: List[RuleOutcome],
    form: Optional[dict] = None,
    options: Optional[dict] = None,
    *,
    project_type: Optional[str] = None,
    meeting_type: Optional[str] = None,
) -> List[dict]:
    thr = merge_thresholds(options)
    clarity_thr = float(thr.get("clarity_threshold", 0.6))
    out = []
    for ctx in contexts:
        st = _photo_status_from_rules(ctx.photo_id, ctx, rules)
        image_dup_hit = any(
            r.rule_code == "IMAGE_DUP"
            and r.status == "FAIL"
            and ctx.photo_id in (r.related_photo_ids or [])
            for r in rules
        )
        topic_reuse_hit = any(
            r.rule_code == "TOPIC_REUSE"
            and r.status == "FAIL"
            and ctx.photo_id in (r.related_photo_ids or [])
            for r in rules
        )
        topic_text = None
        if ctx.photo_type in ("SpeakerTitle", "SpeakerLecture"):
            topic_text = ctx.ocr_fields().get("topic_title")

        of = dict(ctx.ocr_fields() or {})
        detections: Dict[str, Any] = {}
        if ctx.photo_type == "Panorama":
            pc = (ctx.vision or {}).get("people_count")
            pcc = (ctx.vision or {}).get("people_count_confidence")
            if pc is not None:
                of["people_count"] = pc
                detections["people_count"] = pc
            if pcc is not None:
                detections["people_count_confidence"] = pcc
        if ctx.photo_type == "SignSheet":
            signin = _signin_payload(ctx)
            dur = duration_minutes_from_times(
                signin.get("start_time"),
                signin.get("end_time"),
                signin.get("duration_minutes"),
            )
            if signin.get("start_time"):
                of.setdefault("start_time", signin.get("start_time"))
            if signin.get("end_time"):
                of.setdefault("end_time", signin.get("end_time"))
            if dur is not None:
                of["duration_minutes"] = dur
                detections["duration_minutes"] = dur
            if signin.get("audience_count") is not None:
                of["audience_count"] = signin.get("audience_count")
                detections["audience_count"] = signin.get("audience_count")
            if signin.get("store_names"):
                of["store_names"] = signin.get("store_names")
                detections["store_names"] = signin.get("store_names")

        item = {
            "photo_id": ctx.photo_id,
            "photo_type": ctx.photo_type,
            "photo_status": st["photo_status"],
            "fail_reasons": st["fail_reasons"],
            # 兼容字段：不再做视觉分类，detected_type 回填声明类型
            "detected_type": ctx.photo_type,
            "type_match": True if ctx.photo_type else None,
            "clarity_score": ctx.clarity_score(),
            "is_clear": (
                None
                if ctx.clarity_score() is None
                else ctx.clarity_score() >= clarity_thr
            ),
            "checks": _build_checks(
                ctx,
                form,
                options,
                image_dup_hit=image_dup_hit,
                topic_reuse_hit=topic_reuse_hit,
                project_type=project_type,
                meeting_type=meeting_type,
            ),
            "uncertain_checks": [],
            "ocr_fields": of or None,
            "ocr_raw": None,
            "detections": detections or None,
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
                    if h.get("photo_id") == ctx.photo_id:
                        item["image_dup_kind"] = h.get("kind") or "similar"
                        item["image_dup_score"] = h.get("similarity")
                        if h.get("distance") is not None and h.get("similarity") is None:
                            # 将 phash 距离映射成可读相似度近似：0→1.0，阈值→阈值边缘
                            max_d = float(thr.get("image_phash_max_distance", 10)) or 10.0
                            item["image_dup_score"] = round(
                                max(0.0, 1.0 - float(h["distance"]) / max_d), 4
                            )
                        item["image_dup_ref_meeting_id"] = h.get("ref_meeting_id")
                        item["image_dup_ref_meeting_no"] = h.get("ref_meeting_no")
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
    photos = build_photo_results(
        contexts,
        rules,
        form=snap.get("form") or {},
        options=snap.get("options") or {},
        project_type=snap.get("project_type"),
        meeting_type=snap.get("meeting_type"),
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
        "task_id": snap["task_id"],
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
        "photo_results": photos,
        "rule_results": [r.to_dict() for r in rules],
        "debug": {
            "pipeline_steps": pipeline_steps,
            "notes": "vision + phash/embedding pipeline",
        },
        "finished_at": _utcnow(),
    }
