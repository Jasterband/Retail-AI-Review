"""通用规则（LECTURE_HALL + MICRO）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImageDupHistory, TopicHistory
from app.services.embedding_util import embedding_similarity
from app.services.phash_util import phash_distance
from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome, fail, pass_, skip, uncertain
from app.services.text_norm import (
    date_equal,
    fuzzy_contains,
    name_set_equal,
    normalize_name,
    normalize_topic,
    time_to_minutes,
)
from app.services.thresholds import (
    merge_thresholds,
    panorama_need,
    signin_duration_need,
)


def _opts(options: dict) -> dict:
    return options or {}


# 大讲堂必审材料（缺一类即 FAIL；讲者成对另由 SPEAKER_SHOT_PAIR 校验）
_HALL_REQUIRED_TYPES = {
    "E_POSTER",
    "POSTER",
    "STAND",
    "NAME_CARD",
    "HANDBOOK",
    "PANORAMA",
    "SIGNIN",
    "SPEAKER_PHOTO",
}
_MICRO_REQUIRED_TYPES = {
    "E_POSTER",
    "E_POSTER_DISPLAY",
    "PROJECT_INTRO_DISPLAY",
    "PANORAMA",
    "SIGNIN",
    "SPEAKER_PHOTO",
}


def rule_asset_missing(
    contexts: List[AssetContext], snap: Optional[dict] = None
) -> RuleOutcome:
    snap = snap or {}
    project_type = snap.get("project_type") or ""
    present = {c.declared_type for c in contexts}
    required = (
        _HALL_REQUIRED_TYPES
        if project_type == "LECTURE_HALL"
        else _MICRO_REQUIRED_TYPES
        if project_type == "MICRO"
        else set()
    )
    missing_types = sorted(required - present)

    bad = [c for c in contexts if not c.ok]
    if bad:
        ids = [c.asset_id for c in bad]
        codes = sorted({c.fetch_error_code or "ASSET_MISSING" for c in bad})
        return fail(
            "ASSET_MISSING",
            codes[0],
            "材料下载失败: " + ", ".join(
                "{0}({1})".format(c.asset_id, c.fetch_error_code) for c in bad
            ),
            related=ids,
            evidence={
                "errors": [
                    {
                        "asset_id": c.asset_id,
                        "code": c.fetch_error_code,
                        "msg": c.fetch_error_message,
                    }
                    for c in bad
                ],
                "missing_types": missing_types,
            },
        )

    if missing_types:
        # 电子日程等必审类型未提交
        return fail(
            "ASSET_MISSING",
            "ASSET_MISSING",
            "缺少必审材料类型: {0}".format("、".join(missing_types)),
            related=[],
            evidence={"missing_types": missing_types, "present": sorted(present)},
        )

    return pass_(
        "ASSET_MISSING",
        "全部必审材料已提交且可读",
        related=[c.asset_id for c in contexts],
    )


def rule_asset_type_check(
    contexts: List[AssetContext], options: dict
) -> RuleOutcome:
    thr = float(_opts(options).get("human_confidence_threshold", 0.75))
    related = []
    mismatches = []
    uncertain_items = []
    for c in contexts:
        if not c.ok:
            continue
        if c.declared_type == "SIGNIN" and (c.content_type or "").endswith("pdf"):
            continue
        related.append(c.asset_id)
        det = c.detected_type()
        conf = c.vision.get("type_confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        if not det:
            uncertain_items.append(c.asset_id)
            continue
        if det != c.declared_type:
            if conf_f is not None and conf_f < thr:
                uncertain_items.append(c.asset_id)
            else:
                mismatches.append((c.asset_id, c.declared_type, det))
    if mismatches:
        msg = "; ".join(
            "asset {0}: 声明{1}识别为{2}".format(a, d, t) for a, d, t in mismatches
        )
        return fail(
            "ASSET_TYPE_CHECK",
            "TYPE_MISMATCH",
            msg,
            related=[m[0] for m in mismatches],
        )
    if uncertain_items and not mismatches:
        return uncertain(
            "ASSET_TYPE_CHECK",
            "TYPE_UNCERTAIN",
            "材料类型置信度不足: {0}".format(uncertain_items),
            related=uncertain_items,
        )
    if not related:
        return skip("ASSET_TYPE_CHECK", "无可分类材料")
    return pass_("ASSET_TYPE_CHECK", "材料类型与声明一致", related=related)


def rule_clarity(contexts: List[AssetContext], options: dict) -> RuleOutcome:
    thr = float(_opts(options).get("clarity_threshold", 0.6))
    blurry = []
    related = []
    for c in contexts:
        if not c.ok:
            continue
        related.append(c.asset_id)
        score = c.clarity_score()
        if score is None:
            continue
        if score < thr:
            blurry.append((c.asset_id, score))
    if blurry:
        return uncertain(
            "CLARITY",
            "BLURRY",
            "清晰度不足: " + ", ".join(
                "asset {0}={1:.2f}".format(a, s) for a, s in blurry
            ),
            related=[b[0] for b in blurry],
            evidence={"threshold": thr, "scores": blurry},
        )
    if not related:
        return skip("CLARITY", "无可用图片")
    return pass_("CLARITY", "材料清晰度达标", related=related)


def _is_blurry(c: AssetContext, options: dict) -> bool:
    thr = float(_opts(options).get("clarity_threshold", 0.6))
    s = c.clarity_score()
    return s is not None and s < thr


def rule_key_field_match(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    types = {
        "POSTER",
        "STAND",
        "E_POSTER",
        "E_POSTER_DISPLAY",
        "SPEAKER_PHOTO",
        "PANORAMA",
        "SIGNIN",
    }
    mode = _opts(options).get("name_match_mode", "fuzzy")
    form_date = form.get("meeting_date")
    form_loc = form.get("location") or ""
    form_names = [s["speaker_name"] for s in form.get("speakers") or []]
    checked = []
    fails = []
    uncs = []

    for c in contexts:
        if c.declared_type not in types or not c.ok:
            continue
        if c.vision_error:
            uncs.append(c.asset_id)
            continue
        checked.append(c.asset_id)
        if _is_blurry(c, options):
            uncs.append(c.asset_id)
            continue
        of = c.ocr_fields()
        date_ok = True
        loc_ok = True
        names_ok = True
        if of.get("meeting_date") and form_date:
            date_ok = date_equal(of.get("meeting_date"), form_date)
        if of.get("location") and form_loc:
            loc_ok = fuzzy_contains(of["location"], form_loc) or fuzzy_contains(
                form_loc, of["location"]
            )
        ocr_names = of.get("speaker_names") or []
        if ocr_names and form_names and c.declared_type in (
            "POSTER",
            "STAND",
            "E_POSTER",
            "NAME_CARD",
        ):
            cmp = name_set_equal(ocr_names, form_names, mode)
            names_ok = cmp["ok"] or len(cmp["missing"]) == 0
        if not date_ok or not loc_ok or not names_ok:
            fails.append(c.asset_id)

    if fails:
        return fail(
            "KEY_FIELD_MATCH",
            "FIELD_MISMATCH",
            "关键字段与表单不一致，材料: {0}".format(fails),
            related=fails,
        )
    if uncs and not fails:
        return uncertain(
            "KEY_FIELD_MATCH",
            "OCR_LOW_CONFIDENCE",
            "关键字段 OCR 不可靠，材料: {0}".format(uncs),
            related=uncs,
        )
    if not checked:
        return skip("KEY_FIELD_MATCH", "无对应材料")
    return pass_(
        "KEY_FIELD_MATCH",
        "海报/展架等日期地点与表单一致",
        related=checked,
    )


def rule_time_consistency(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    skew = int(_opts(options).get("watermark_time_skew_minutes", 120))
    start = time_to_minutes(form.get("start_time"))
    end = time_to_minutes(form.get("end_time"))
    if start is None or end is None:
        return skip("TIME_CONSISTENCY", "表单无时段")

    related = []
    bad = []
    saw = False
    for c in contexts:
        if not c.ok:
            continue
        of = c.ocr_fields()
        times = []
        for key in ("start_time", "watermark_time"):
            tm = time_to_minutes(of.get(key) if key != "start_time" else of.get(key))
            if key == "watermark_time":
                tm = time_to_minutes(of.get("watermark_time"))
            else:
                tm = time_to_minutes(of.get("start_time"))
            if tm is not None:
                times.append(tm)
        # also end_time from poster
        et = time_to_minutes(of.get("end_time"))
        if et is not None:
            times.append(et)
        if not times:
            continue
        saw = True
        related.append(c.asset_id)
        for tm in times:
            if tm < start - skew or tm > end + skew:
                bad.append(c.asset_id)
                break
    if not saw:
        return skip("TIME_CONSISTENCY", "无时间信息可抽")
    if bad:
        return fail(
            "TIME_CONSISTENCY",
            "FIELD_MISMATCH",
            "部分材料时间偏离会议时段: {0}".format(bad),
            related=bad,
        )
    return pass_("TIME_CONSISTENCY", "各图时间与会议时段一致", related=related)


def rule_bayer_logo(
    contexts: List[AssetContext], project_type: str, options: Optional[dict] = None
) -> RuleOutcome:
    if project_type == "LECTURE_HALL":
        want = {"POSTER", "STAND", "E_POSTER"}
    else:
        want = {"E_POSTER", "E_POSTER_DISPLAY", "PROJECT_INTRO_DISPLAY"}
    targets = [c for c in contexts if c.declared_type in want and c.ok]
    if not targets:
        return skip("BAYER_LOGO", "无线索材料")
    thr = merge_thresholds(options)
    logo_pass = float(thr.get("logo_confidence_pass", 0.55))
    hits = []
    miss = []
    gray = []
    evidence_rows = []
    for c in targets:
        tm = (c.template_match or {}).get("bayer_logo") or {}
        wave = (c.template_match or {}).get("poster_wave") or {}
        # 模版 pack 对照优先
        if tm:
            score = float(tm.get("score") or 0)
            if tm.get("hit"):
                hits.append(c.asset_id)
            elif tm.get("uncertain"):
                gray.append(c.asset_id)
            else:
                # 海报波浪命中可作弱旁证，不单独过
                if wave.get("hit") and score >= 0.45:
                    gray.append(c.asset_id)
                else:
                    miss.append(c.asset_id)
            evidence_rows.append(
                {
                    "asset_id": c.asset_id,
                    "logo": tm,
                    "poster_wave": wave or None,
                }
            )
            continue

        flag = c.vision.get("has_bayer_logo")
        conf = c.vision.get("logo_confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.8
        except (TypeError, ValueError):
            conf_f = 0.8
        if flag is True:
            if conf_f < logo_pass:
                gray.append(c.asset_id)
            else:
                hits.append(c.asset_id)
        elif flag is False:
            miss.append(c.asset_id)
        else:
            gray.append(c.asset_id)
        evidence_rows.append(
            {"asset_id": c.asset_id, "vision_only": True, "flag": flag, "conf": conf_f}
        )
    # 应检材料均需检出（任一缺失 → FAIL）
    if miss:
        return fail(
            "BAYER_LOGO",
            "LOGO_MISSING",
            "应检材料未检出拜耳 Logo: {0}".format(miss),
            related=miss,
            evidence={"rows": evidence_rows, "miss": miss, "gray": gray, "hits": hits},
        )
    if gray:
        return uncertain(
            "BAYER_LOGO",
            "LOGO_UNCERTAIN",
            "Logo 检出置信度灰区",
            related=gray,
            evidence={"rows": evidence_rows, "hits": hits},
        )
    return pass_(
        "BAYER_LOGO",
        "拜耳 Logo 均已检出（对照官方参考图）",
        related=hits,
        evidence={"rows": evidence_rows},
    )


def rule_panorama_count(
    contexts: List[AssetContext], snap: dict, options: dict
) -> RuleOutcome:
    pans = [c for c in contexts if c.declared_type == "PANORAMA" and c.ok]
    if not pans:
        return skip("PANORAMA_COUNT", "无全景")
    total = 0
    confs = []
    related = []
    for c in pans:
        related.append(c.asset_id)
        pc = c.vision.get("people_count")
        try:
            n = int(pc) if pc is not None else 0
        except (TypeError, ValueError):
            n = 0
        total += n
        try:
            confs.append(float(c.vision.get("people_count_confidence") or 0.5))
        except (TypeError, ValueError):
            confs.append(0.5)

    thr = merge_thresholds(options)
    project_type = snap["project_type"]
    subtype = snap.get("meeting_subtype")
    need = panorama_need(project_type, subtype, thr)
    min_people_conf = float(thr.get("panorama_count_min_confidence", 0.7))

    min_conf = min(confs) if confs else 0.0
    if min_conf < min_people_conf:
        return uncertain(
            "PANORAMA_COUNT",
            "COUNT_UNCERTAIN",
            "全景人数置信度低，合计约 {0}（阈值≥{1}）".format(total, need),
            related=related,
            evidence={"total": total, "need": need},
        )
    if total < need:
        return fail(
            "PANORAMA_COUNT",
            "COUNT_BELOW_THRESHOLD",
            "全景合计人数{0}<{1}".format(total, need),
            related=related,
            evidence={"total": total, "need": need},
        )
    return pass_(
        "PANORAMA_COUNT",
        "全景合计 {0} 人，满足 ≥{1}".format(total, need),
        related=related,
        evidence={"total": total, "need": need},
    )


def rule_signin_duration(
    contexts: List[AssetContext], snap: dict, options: dict
) -> RuleOutcome:
    signs = [c for c in contexts if c.declared_type == "SIGNIN" and c.ok]
    if not signs:
        return skip("SIGNIN_DURATION", "无签到")
    thr = merge_thresholds(options)
    project_type = snap["project_type"]
    subtype = snap.get("meeting_subtype")
    need = signin_duration_need(project_type, subtype, thr)

    best = None
    related = [c.asset_id for c in signs]
    for c in signs:
        if _is_blurry(c, options):
            continue
        signin = c.vision.get("signin") or {}
        dur = signin.get("duration_minutes")
        if dur is None:
            st = time_to_minutes(signin.get("start_time"))
            et = time_to_minutes(signin.get("end_time"))
            if st is not None and et is not None:
                dur = et - st if et >= st else et + 24 * 60 - st
        if dur is not None:
            try:
                best = max(best or 0, int(dur))
            except (TypeError, ValueError):
                pass
    if best is None:
        return uncertain(
            "SIGNIN_DURATION",
            "BLURRY",
            "签到表模糊或无法可靠读取起止时间",
            related=related,
        )
    if best <= need:
        return fail(
            "SIGNIN_DURATION",
            "DURATION_BELOW_THRESHOLD",
            "签到时长{0}分钟，未超过{1}".format(best, need),
            related=related,
            evidence={"duration": best, "need": need},
        )
    return pass_(
        "SIGNIN_DURATION",
        "签到时长 {0} 分钟，满足 >{1}".format(best, need),
        related=related,
        evidence={"duration": best, "need": need},
    )


def rule_image_dup(
    contexts: List[AssetContext],
    snap: dict,
    refs: dict,
    options: dict,
    db: Session,
) -> RuleOutcome:
    max_dist = int(_opts(options).get("image_phash_max_distance", 10))
    sim_thr = float(_opts(options).get("image_similarity_threshold", 0.92))
    scope = (refs or {}).get("image_dup_search_scope") or (refs or {}).get(
        "duplicate_search_scope"
    ) or "period"
    period_id = snap.get("period_id")
    meeting_id = snap["meeting_id"]

    q = select(ImageDupHistory).where(ImageDupHistory.meeting_id != meeting_id)
    if scope == "period" and period_id is not None:
        q = q.where(ImageDupHistory.period_id == period_id)
    history = list(db.scalars(q).all())
    if not history:
        return skip("IMAGE_DUP", "查重库为空（首场）")

    hits = []
    related = []
    for c in contexts:
        if not c.ok or (not c.phash and not c.embedding):
            continue
        related.append(c.asset_id)
        best_phash = None  # (dist, kind, hist)
        best_emb = None  # (sim, hist)
        for h in history:
            if c.phash and h.phash:
                dist = phash_distance(c.phash, h.phash)
                if dist <= max_dist and (best_phash is None or dist < best_phash[0]):
                    kind = "exact" if dist == 0 else "similar"
                    best_phash = (dist, kind, h)
            if c.embedding and getattr(h, "embedding", None):
                sim = embedding_similarity(c.embedding, h.embedding)
                if sim is not None and sim >= sim_thr and (
                    best_emb is None or sim > best_emb[0]
                ):
                    best_emb = (sim, h)
        # pHash 优先；否则用 embedding 近似
        if best_phash is not None:
            dist, kind, href = best_phash
            hits.append(
                {
                    "asset_id": c.asset_id,
                    "ref_meeting_id": href.meeting_id,
                    "ref_session_no": href.session_no,
                    "kind": kind,
                    "method": "phash",
                    "distance": dist,
                }
            )
        elif best_emb is not None:
            sim, href = best_emb
            hits.append(
                {
                    "asset_id": c.asset_id,
                    "ref_meeting_id": href.meeting_id,
                    "ref_session_no": href.session_no,
                    "kind": "similar",
                    "method": "embedding",
                    "similarity": round(float(sim), 4),
                }
            )
    if hits:
        return fail(
            "IMAGE_DUP",
            "IMAGE_DUP",
            "发现与其他会议现场照重复/近似: {0}".format(
                [h["asset_id"] for h in hits]
            ),
            related=[h["asset_id"] for h in hits],
            evidence={"hits": hits},
        )
    return pass_(
        "IMAGE_DUP",
        "全部照片未盗用其他会议现场照（pHash+embedding）",
        related=related,
    )


def rule_topic_reuse(
    contexts: List[AssetContext],
    snap: dict,
    form: dict,
    refs: dict,
    options: dict,
    db: Session,
) -> RuleOutcome:
    speakers = {s["speaker_id"]: s for s in form.get("speakers") or []}
    titles = []
    for c in contexts:
        if c.declared_type != "SPEAKER_PHOTO" or not c.ok:
            continue
        if c.speaker_shot_kind and c.speaker_shot_kind != "TITLE_GROUP":
            continue
        of = c.ocr_fields()
        topic = of.get("topic_title") or ""
        if not topic and c.speaker_id in speakers:
            topic = speakers[c.speaker_id].get("topic") or ""
        # prefer OCR
        topic_ocr = of.get("topic_title")
        if not topic_ocr:
            if _is_blurry(c, options):
                continue
            continue
        titles.append(
            {
                "asset_id": c.asset_id,
                "speaker_name": (speakers.get(c.speaker_id) or {}).get(
                    "speaker_name", ""
                ),
                "topic_raw": topic_ocr,
                "topic_normalized": normalize_topic(topic_ocr),
            }
        )

    if not titles:
        return skip("TOPIC_REUSE", "无标题合影或抽不出标题")

    scope = (refs or {}).get("topic_search_scope") or "period"
    period_id = snap.get("period_id")
    meeting_id = snap["meeting_id"]
    q = select(TopicHistory).where(
        (TopicHistory.meeting_id.is_(None)) | (TopicHistory.meeting_id != meeting_id)
    )
    if scope == "period" and period_id is not None:
        q = q.where(TopicHistory.period_id == period_id)
    history = list(db.scalars(q).all())
    if not history:
        return skip("TOPIC_REUSE", "主题库为空")

    hits = []
    for t in titles:
        sp_name = normalize_name(t.get("speaker_name") or "")
        for h in history:
            if not t["topic_normalized"] or t["topic_normalized"] != h.topic_normalized:
                continue
            # 同主题 + 同讲者名（或历史缺讲者名）才判复用
            hist_sp = normalize_name(h.speaker_name or "")
            if hist_sp and sp_name and hist_sp != sp_name:
                continue
            hits.append(
                {
                    "asset_id": t["asset_id"],
                    "topic": t["topic_raw"],
                    "speaker_name": t.get("speaker_name"),
                    "ref_session_no": h.session_no,
                    "ref_meeting_id": h.meeting_id,
                    "ref_speaker_name": h.speaker_name,
                }
            )
            break
    related = [t["asset_id"] for t in titles]
    if hits:
        return fail(
            "TOPIC_REUSE",
            "TOPIC_REUSED",
            "讲者照主题与历史会议重复",
            related=[h["asset_id"] for h in hits],
            evidence={"hits": hits},
        )
    return pass_("TOPIC_REUSE", "讲者照 OCR 标题未与历史主题重复", related=related)


def rule_watermark(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    form_date = form.get("meeting_date")
    form_loc = form.get("location") or ""
    chain = form.get("chain_or_store_name") or ""
    skew = int(_opts(options).get("watermark_time_skew_minutes", 120))
    start = time_to_minutes(form.get("start_time"))
    end = time_to_minutes(form.get("end_time"))

    with_wm = []
    bad = []
    uncs = []
    for c in contexts:
        if not c.ok:
            continue
        of = c.ocr_fields()
        has = of.get("has_watermark")
        if has is not True and not of.get("watermark_date") and not of.get(
            "watermark_location"
        ):
            continue
        with_wm.append(c.asset_id)
        if _is_blurry(c, options):
            uncs.append(c.asset_id)
            continue
        ok = True
        if of.get("watermark_date") and form_date:
            if not date_equal(of.get("watermark_date"), form_date):
                ok = False
        loc = of.get("watermark_location") or ""
        if loc and form_loc:
            if not (
                fuzzy_contains(loc, form_loc)
                or fuzzy_contains(loc, chain)
                or fuzzy_contains(form_loc, loc)
            ):
                ok = False
        wt = time_to_minutes(of.get("watermark_time"))
        if wt is not None and start is not None and end is not None:
            if wt < start - skew or wt > end + skew:
                ok = False
        if not ok:
            bad.append(c.asset_id)

    if not with_wm:
        return skip("WATERMARK_CONSISTENCY", "无水印")
    if bad:
        return fail(
            "WATERMARK_CONSISTENCY",
            "FIELD_MISMATCH",
            "水印日期/地点/时间与表单不符: {0}".format(bad),
            related=bad,
        )
    if uncs:
        return uncertain(
            "WATERMARK_CONSISTENCY",
            "OCR_LOW_CONFIDENCE",
            "水印 OCR 差",
            related=uncs,
        )
    return pass_(
        "WATERMARK_CONSISTENCY",
        "水印日期地点与表单一致",
        related=with_wm,
    )
