"""规则结果 → overall_status + photo_results + summaries。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.config import get_settings
from app.services.image_dup_policy import dup_category
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
from app.services.thresholds import (
    merge_thresholds,
    signin_audience_need,
    signin_duration_need,
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


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
                    "reason_text": ctx.fetch_error_message or "材料下载失败",
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


def _signin_complete_from_vision(signin: dict, of: dict) -> Optional[bool]:
    """本页填写完整：表头（若有）+ 已占用行除「其他」列外均已填。"""
    explicit = _coerce_bool(signin.get("signin_complete_ok"))
    if explicit is not None:
        return explicit
    header = _coerce_bool(signin.get("header_complete"))
    rows = _coerce_bool(signin.get("rows_complete"))
    if rows is None and header is None:
        # 回退：能读到起止时间 + 有人数/门店/手签 视为大致完整
        start = signin.get("start_time") or of.get("start_time")
        end = signin.get("end_time") or of.get("end_time")
        has_people = signin.get("audience_count") is not None
        hand = _coerce_bool(signin.get("has_handwritten_signatures"))
        if start and end and (has_people or hand is True):
            return True
        if start is None and end is None and has_people is False and hand is False:
            return False
        return None
    if header is False or rows is False:
        return False
    if rows is True and header is not False:
        return True
    return None


def _signin_payload(ctx: AssetContext) -> dict:
    v = ctx.vision or {}
    of = ctx.ocr_fields()
    signin = v.get("signin") if isinstance(v.get("signin"), dict) else {}
    raw_hand = signin.get("has_handwritten_signatures")
    if raw_hand is None:
        raw_hand = v.get("has_handwritten_signatures")
    return {
        "start_time": signin.get("start_time") or of.get("start_time"),
        "end_time": signin.get("end_time") or of.get("end_time"),
        "duration_minutes": signin.get("duration_minutes"),
        "audience_count": signin.get("audience_count"),
        "store_names": signin.get("store_names") or [],
        "has_handwritten_signatures": _coerce_bool(raw_hand),
        "header_complete": _coerce_bool(signin.get("header_complete")),
        "rows_complete": _coerce_bool(signin.get("rows_complete")),
        "incomplete_row_count": signin.get("incomplete_row_count"),
        "complete_ok": _signin_complete_from_vision(signin, of),
        "photo_id": ctx.photo_id,
    }


def merge_signin_sheets(
    contexts: List[AssetContext],
    options: Optional[dict] = None,
) -> Optional[Dict[str, Any]]:
    """多张 SignSheet 合并成一场签到检查（时长取可读最大值；听众人数按页累加；门店并集）。"""
    sheets = [c for c in contexts if c.photo_type == "SignSheet" and c.ok]
    if not sheets:
        return None
    thr = merge_thresholds(options)
    related = [c.photo_id for c in sheets]
    best_dur: Optional[int] = None
    best_start = None
    best_end = None
    audience_sum = 0
    audience_any = False
    stores: List[str] = []
    hand_flags: List[Optional[bool]] = []
    page_rows: List[dict] = []

    for c in sheets:
        p = _signin_payload(c)
        dur = duration_minutes_from_times(
            p.get("start_time"),
            p.get("end_time"),
            p.get("duration_minutes"),
        )
        if dur is not None and (best_dur is None or dur > best_dur):
            best_dur = int(dur)
            best_start = p.get("start_time")
            best_end = p.get("end_time")
        ac = p.get("audience_count")
        if ac is not None:
            try:
                audience_sum += int(ac)
                audience_any = True
            except (TypeError, ValueError):
                pass
        for s in p.get("store_names") or []:
            if s and str(s).strip():
                stores.append(str(s).strip())
        hand_flags.append(p.get("has_handwritten_signatures"))
        page_rows.append(
            {
                "photo_id": c.photo_id,
                "duration_minutes": dur,
                "audience_count": ac,
                "has_handwritten_signatures": p.get("has_handwritten_signatures"),
                "header_complete": p.get("header_complete"),
                "rows_complete": p.get("rows_complete"),
                "incomplete_row_count": p.get("incomplete_row_count"),
                "complete_ok": p.get("complete_ok"),
            }
        )

    if any(x is True for x in hand_flags):
        handwritten: Optional[bool] = True
    elif hand_flags and all(x is False for x in hand_flags):
        handwritten = False
    else:
        handwritten = None

    return {
        "photo_ids": related,
        "page_count": len(sheets),
        "start_time": best_start,
        "end_time": best_end,
        "duration_minutes": best_dur,
        "audience_count": audience_sum if audience_any else None,
        "store_names": sorted({s for s in stores}),
        "has_handwritten_signatures": handwritten,
        "pages": page_rows,
    }


def _build_checks(
    ctx: AssetContext,
    form: Optional[dict] = None,
    options: Optional[dict] = None,
    *,
    image_dup_hit: bool = False,
    project_type: Optional[str] = None,
    meeting_type: Optional[str] = None,
    signin_merged: Optional[Dict[str, Any]] = None,
) -> Dict[str, Optional[bool]]:
    """按 docs/检测点清单与photo_results.md 组装单张 checks（不适用则为 null）。"""
    v = ctx.vision or {}
    of = ctx.ocr_fields()
    form = form or {}
    thr = merge_thresholds(options)
    skew = int(thr.get("watermark_time_skew_minutes", 120))
    mode = thr.get("name_match_mode", "fuzzy")
    tm = ctx.template_match or {}
    pt = ctx.photo_type

    checks: Dict[str, Optional[bool]] = {
        # 台卡/签到表等不参与 IMAGE_DUP → null
        "image_not_duplicated": (not image_dup_hit) if dup_category(pt) else None,
        "has_bayer_logo": None,
        "has_bayer_sponsor": None,
    }
    hall_brand_types = {"Poster", "Stand", "EDM"}
    micro_logo_types = {"EDM", "EDMDisplay", "ProjectIntro"}
    if project_type == "LECTURE_HALL" and pt in hall_brand_types:
        sponsor = _coerce_bool(v.get("has_bayer_sponsor"))
        if sponsor is None:
            raw = v.get("sponsor_text") or ""
            expect = "拜耳医药保健有限公司"
            if raw:
                sponsor = expect.replace(" ", "") in "".join(
                    ch for ch in str(raw) if not ch.isspace()
                )
        checks["has_bayer_sponsor"] = sponsor
    elif project_type == "MICRO" and pt in micro_logo_types:
        checks["has_bayer_logo"] = _coerce_bool(v.get("has_bayer_logo"))
    else:
        checks["has_bayer_logo"] = _coerce_bool(v.get("has_bayer_logo"))

    # EDMDisplay 不做日期/时间/地点对台账
    poster_types = {"Poster", "Stand", "EDM"}
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
        for key in ("start_time", "end_time"):
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

    if pt == "SpeakerTitle":
        speakers = {s["speaker_id"]: s for s in form.get("speakers") or []}
        sp = speakers.get(ctx.speaker_id) or {}
        expected = normalize_topic(sp.get("topic") or "")
        got = normalize_topic(of.get("topic_title") or "")
        if expected and got:
            checks["topic_matches_form"] = (
                expected == got or expected in got or got in expected
            )
        else:
            checks["topic_matches_form"] = None

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

        person = _coerce_bool(v.get("has_speaker_person"))
        date_v = of.get("meeting_date")
        checks["has_speaker_person"] = person
        checks["has_topic_title"] = bool(of.get("topic_title"))
        checks["has_speaker_name"] = bool(visible)
        checks["has_date"] = bool(date_v)
        if person is None:
            checks["speaker_title_composition_ok"] = None
        else:
            checks["speaker_title_composition_ok"] = bool(
                person
                and checks["has_topic_title"]
                and checks["has_speaker_name"]
                and checks["has_date"]
            )

    if pt == "SpeakerLecture":
        person = _coerce_bool(v.get("has_speaker_person"))
        ppt = _coerce_bool(v.get("has_ppt_screen"))
        checks["has_speaker_person"] = person
        checks["has_ppt_screen"] = ppt
        if person is None or ppt is None:
            checks["speaker_lecture_composition_ok"] = None
        else:
            checks["speaker_lecture_composition_ok"] = bool(person and ppt)

    if pt == "Panorama":
        pc = v.get("people_count")
        try:
            checks["people_count_recorded"] = pc is not None and int(pc) >= 0
        except (TypeError, ValueError):
            checks["people_count_recorded"] = False

    if pt == "SignSheet":
        merged = signin_merged or {}
        dur = merged.get("duration_minutes")
        page = _signin_payload(ctx)
        checks["duration_readable"] = dur is not None
        if dur is None:
            checks["duration_meets_threshold"] = None
        else:
            need = signin_duration_need(
                project_type or "LECTURE_HALL", meeting_type, thr
            )
            checks["duration_meets_threshold"] = int(dur) > need
        # 本页列填写完整（仅「其他」列可空）；人数达标是场级合并后另检
        checks["signin_complete_ok"] = page.get("complete_ok")
        audience = merged.get("audience_count")
        if audience is None:
            checks["signin_audience_ok"] = None
        else:
            need_aud = signin_audience_need(
                project_type or "LECTURE_HALL",
                meeting_type,
                form,
                thr,
            )
            checks["signin_audience_ok"] = int(audience) >= need_aud

    if pt == "ProjectIntro":
        ribbon = tm.get("colorful_ribbon") or {}
        checks["has_colorful_ribbon"] = (
            ribbon.get("hit") if ribbon else _coerce_bool(v.get("has_colorful_ribbon"))
        )
        checks["ppt_template_match"] = checks["has_colorful_ribbon"]
        kind = v.get("ppt_page_kind")
        checks["ppt_page_kind_ok"] = kind == "PROJECT_INTRO" if kind else None

    if pt == "EDMDisplay":
        agenda = tm.get("agenda_table") or {}
        checks["has_agenda_table"] = (
            agenda.get("hit") if agenda else _coerce_bool(v.get("has_agenda_table"))
        )
        checks["ppt_template_match"] = checks["has_agenda_table"]
        kind = v.get("ppt_page_kind")
        checks["ppt_page_kind_ok"] = kind == "AGENDA" if kind else None

    if tm.get("bayer_logo") and project_type == "MICRO" and pt in micro_logo_types:
        checks["has_bayer_logo"] = tm["bayer_logo"].get("hit")
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
    signin_merged = merge_signin_sheets(contexts, options)
    out = []
    for ctx in contexts:
        st = _photo_status_from_rules(ctx.photo_id, ctx, rules)
        image_dup_hit = any(
            r.rule_code == "IMAGE_DUP"
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
        if ctx.photo_type == "SignSheet" and signin_merged:
            page = _signin_payload(ctx)
            # 单页 OCR 仍回填本页可读字段；场级合并值写入 detections
            if page.get("start_time"):
                of.setdefault("start_time", page.get("start_time"))
            if page.get("end_time"):
                of.setdefault("end_time", page.get("end_time"))
            if signin_merged.get("start_time"):
                of["start_time"] = signin_merged.get("start_time")
            if signin_merged.get("end_time"):
                of["end_time"] = signin_merged.get("end_time")
            if signin_merged.get("duration_minutes") is not None:
                of["duration_minutes"] = signin_merged["duration_minutes"]
                detections["duration_minutes"] = signin_merged["duration_minutes"]
            if signin_merged.get("audience_count") is not None:
                of["audience_count"] = signin_merged["audience_count"]
                detections["audience_count"] = signin_merged["audience_count"]
            if signin_merged.get("store_names"):
                of["store_names"] = signin_merged["store_names"]
                detections["store_names"] = signin_merged["store_names"]
            detections["signin_page_count"] = signin_merged.get("page_count")
            detections["signin_merged_photo_ids"] = list(
                signin_merged.get("photo_ids") or []
            )
            if page.get("audience_count") is not None:
                detections["audience_count_page"] = page.get("audience_count")
            if page.get("has_handwritten_signatures") is not None:
                detections["has_handwritten_signatures"] = page.get(
                    "has_handwritten_signatures"
                )
            if page.get("header_complete") is not None:
                detections["header_complete"] = page.get("header_complete")
            if page.get("rows_complete") is not None:
                detections["rows_complete"] = page.get("rows_complete")
            if page.get("incomplete_row_count") is not None:
                detections["incomplete_row_count"] = page.get("incomplete_row_count")
            if page.get("complete_ok") is not None:
                detections["signin_complete_ok"] = page.get("complete_ok")

        item = {
            "photo_id": ctx.photo_id,
            "photo_type": ctx.photo_type,
            "photo_type_name": ctx.photo_type_name,
            "photo_status": st["photo_status"],
            "fail_reasons": st["fail_reasons"],
            "checks": _build_checks(
                ctx,
                form,
                options,
                image_dup_hit=image_dup_hit,
                project_type=project_type,
                meeting_type=meeting_type,
                signin_merged=signin_merged if ctx.photo_type == "SignSheet" else None,
            ),
            "uncertain_checks": [],
            "ocr_fields": of or None,
            "ocr_raw": None,
            "detections": detections or None,
            "image_dup_hit": image_dup_hit,
            "topic_text_ocr": topic_text,
            "model_scores": {
                "type_confidence": ctx.vision.get("type_confidence"),
                "logo_confidence": ctx.vision.get("logo_confidence"),
                "template_match": ctx.template_match or None,
                "signin_merged": (
                    {
                        "page_count": signin_merged.get("page_count"),
                        "duration_minutes": signin_merged.get("duration_minutes"),
                        "audience_count": signin_merged.get("audience_count"),
                        "has_handwritten_signatures": signin_merged.get(
                            "has_handwritten_signatures"
                        ),
                    }
                    if ctx.photo_type == "SignSheet" and signin_merged
                    else None
                ),
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
