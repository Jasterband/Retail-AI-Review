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
    "EDM",
    "Poster",
    "Stand",
    "TableCard",
    "Manual",
    "Panorama",
    "SignSheet",
    "SpeakerTitle",
    "SpeakerLecture",
}
_MICRO_REQUIRED_TYPES = {
    "EDM",
    "EDMDisplay",
    "ProjectIntro",
    "Panorama",
    "SignSheet",
    "SpeakerTitle",
}


def rule_asset_missing(
    contexts: List[AssetContext], snap: Optional[dict] = None
) -> RuleOutcome:
    snap = snap or {}
    project_type = snap.get("project_type") or ""
    present = {c.photo_type for c in contexts}
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
        ids = [c.photo_id for c in bad]
        codes = sorted({c.fetch_error_code or "ASSET_MISSING" for c in bad})
        return fail(
            "ASSET_MISSING",
            codes[0],
            "材料下载失败: " + ", ".join(
                "{0}({1})".format(c.photo_id, c.fetch_error_code) for c in bad
            ),
            related=ids,
            evidence={
                "errors": [
                    {
                        "photo_id": c.photo_id,
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
        related=[c.photo_id for c in contexts],
    )


def rule_photo_type_check(
    contexts: List[AssetContext], options: dict
) -> RuleOutcome:
    """材料类型以 PE 声明的 photo_type 为准，不做视觉分类比对。"""
    del options  # 保留签名与引擎一致
    related = [c.photo_id for c in contexts if c.ok]
    if not related:
        return skip("ASSET_TYPE_CHECK", "无可用材料")
    return pass_(
        "ASSET_TYPE_CHECK",
        "以 PE 声明 photo_type 为准，不做视觉分类",
        related=related,
    )


def rule_clarity(contexts: List[AssetContext], options: dict) -> RuleOutcome:
    thr = float(_opts(options).get("clarity_threshold", 0.6))
    blurry = []
    related = []
    for c in contexts:
        if not c.ok:
            continue
        related.append(c.photo_id)
        score = c.clarity_score()
        if score is None:
            continue
        if score < thr:
            blurry.append((c.photo_id, score))
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
        "Poster",
        "Stand",
        "EDM",
        "EDMDisplay",
        "SpeakerTitle",
        "Panorama",
        "SignSheet",
    }
    mode = _opts(options).get("name_match_mode", "fuzzy")
    form_date = form.get("meeting_date")
    form_loc = form.get("meeting_location") or ""
    form_names = [s["speaker_name"] for s in form.get("speakers") or []]
    checked = []
    fails = []
    uncs = []

    for c in contexts:
        if c.photo_type not in types or not c.ok:
            continue
        if c.vision_error:
            uncs.append(c.photo_id)
            continue
        checked.append(c.photo_id)
        if _is_blurry(c, options):
            uncs.append(c.photo_id)
            continue
        of = c.ocr_fields()
        date_ok = True
        loc_ok = True
        names_ok = True
        if of.get("meeting_date") and form_date:
            date_ok = date_equal(of.get("meeting_date"), form_date)
        ocr_loc = of.get("meeting_location") or of.get("location")
        if ocr_loc and form_loc:
            loc_ok = fuzzy_contains(ocr_loc, form_loc) or fuzzy_contains(
                form_loc, ocr_loc
            )
        raw_names = of.get("speaker_names") or []
        if isinstance(raw_names, str):
            ocr_names = [raw_names] if raw_names.strip() else []
        elif isinstance(raw_names, list):
            ocr_names = raw_names
        else:
            ocr_names = []
        if ocr_names and form_names and c.photo_type in (
            "Poster",
            "Stand",
            "EDM",
            "TableCard",
        ):
            cmp = name_set_equal(ocr_names, form_names, mode)
            names_ok = cmp["ok"] or len(cmp["missing"]) == 0
        if not date_ok or not loc_ok or not names_ok:
            fails.append(c.photo_id)

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
    """只比对海报/展架等材料上的日程起止时间；不做时间水印检测。"""
    skew = int(_opts(options).get("watermark_time_skew_minutes", 120))
    start = time_to_minutes(form.get("start_time"))
    end = time_to_minutes(form.get("end_time"))
    if start is None or end is None:
        return skip("TIME_CONSISTENCY", "表单无时段")

    # 日程类材料：比对画面上的 start_time / end_time（不是相机时间水印）
    agenda_types = {"Poster", "Stand", "EDM", "EDMDisplay"}
    related = []
    bad = []
    saw = False
    for c in contexts:
        if not c.ok or c.photo_type not in agenda_types:
            continue
        of = c.ocr_fields()
        times = []
        for key in ("start_time", "end_time"):
            tm = time_to_minutes(of.get(key))
            if tm is not None:
                times.append(tm)
        if not times:
            continue
        saw = True
        related.append(c.photo_id)
        for tm in times:
            if tm < start - skew or tm > end + skew:
                bad.append(c.photo_id)
                break
    if not saw:
        return skip("TIME_CONSISTENCY", "无日程时间可抽")
    if bad:
        return fail(
            "TIME_CONSISTENCY",
            "FIELD_MISMATCH",
            "部分材料日程时间偏离会议时段: {0}".format(bad),
            related=bad,
        )
    return pass_("TIME_CONSISTENCY", "各图日程时间与会议时段一致", related=related)


# 大讲堂海报类须出现的赞助方全称
_BAYER_SPONSOR_TEXT = "拜耳医药保健有限公司"


def _sponsor_text_hit(vision: dict) -> Optional[bool]:
    """True/False/None：赞助方文案是否命中。"""
    flag = vision.get("has_bayer_sponsor")
    if flag is True or flag is False:
        return bool(flag)
    raw = vision.get("sponsor_text") or ""
    of = vision.get("ocr_fields") or {}
    if not raw and isinstance(of, dict):
        raw = of.get("sponsor_text") or ""
    blob = "{0}".format(raw)
    # 兜底：从常见 OCR 拼串里找全称
    for key in ("meeting_location", "chain_or_store_name", "topic_title"):
        if isinstance(of, dict) and of.get(key):
            blob += " {0}".format(of.get(key))
    norm = "".join(ch for ch in blob if not ch.isspace())
    target = "".join(ch for ch in _BAYER_SPONSOR_TEXT if not ch.isspace())
    if not norm:
        return None
    return target in norm


def rule_bayer_logo(
    contexts: List[AssetContext], project_type: str, options: Optional[dict] = None
) -> RuleOutcome:
    """微型：EDM/EDMDisplay/ProjectIntro 查拜耳 Logo；
    大讲堂：EDM/Poster/Stand 查图最下方赞助方文案「拜耳医药保健有限公司」。
    """
    thr = merge_thresholds(options)
    if project_type == "LECTURE_HALL":
        want = {"Poster", "Stand", "EDM"}
        targets = [c for c in contexts if c.photo_type in want and c.ok]
        if not targets:
            return skip("BAYER_LOGO", "无线索材料")
        sponsor_pass = float(thr.get("sponsor_confidence_pass", 0.55))
        hits: List[str] = []
        miss: List[str] = []
        gray: List[str] = []
        evidence_rows: List[dict] = []
        for c in targets:
            flag = _sponsor_text_hit(c.vision)
            conf = c.vision.get("sponsor_confidence")
            try:
                conf_f = float(conf) if conf is not None else 0.8
            except (TypeError, ValueError):
                conf_f = 0.8
            if flag is True:
                if conf_f < sponsor_pass:
                    gray.append(c.photo_id)
                else:
                    hits.append(c.photo_id)
            elif flag is False:
                miss.append(c.photo_id)
            else:
                gray.append(c.photo_id)
            evidence_rows.append(
                {
                    "photo_id": c.photo_id,
                    "kind": "sponsor",
                    "flag": flag,
                    "conf": conf_f,
                    "sponsor_text": c.vision.get("sponsor_text"),
                    "expect": _BAYER_SPONSOR_TEXT,
                }
            )
        if miss:
            return fail(
                "BAYER_LOGO",
                "SPONSOR_MISSING",
                "应检材料底部未检出赞助方「{0}」: {1}".format(
                    _BAYER_SPONSOR_TEXT, miss
                ),
                related=miss,
                evidence={
                    "rows": evidence_rows,
                    "miss": miss,
                    "gray": gray,
                    "hits": hits,
                },
            )
        if gray:
            return uncertain(
                "BAYER_LOGO",
                "SPONSOR_UNCERTAIN",
                "赞助方文案检出置信度灰区",
                related=gray,
                evidence={"rows": evidence_rows, "hits": hits},
            )
        return pass_(
            "BAYER_LOGO",
            "图片最下方赞助方「{0}」均已检出".format(_BAYER_SPONSOR_TEXT),
            related=hits,
            evidence={"rows": evidence_rows},
        )

    # 微型：拜耳 Logo
    want = {"EDM", "EDMDisplay", "ProjectIntro"}
    targets = [c for c in contexts if c.photo_type in want and c.ok]
    if not targets:
        return skip("BAYER_LOGO", "无线索材料")
    logo_pass = float(thr.get("logo_confidence_pass", 0.55))
    hits = []
    miss = []
    gray = []
    evidence_rows = []
    for c in targets:
        tm = (c.template_match or {}).get("bayer_logo") or {}
        # 模版 pack 对照优先
        if tm:
            if tm.get("hit"):
                hits.append(c.photo_id)
            elif tm.get("uncertain"):
                gray.append(c.photo_id)
            else:
                miss.append(c.photo_id)
            evidence_rows.append({"photo_id": c.photo_id, "kind": "logo", "logo": tm})
            continue

        flag = c.vision.get("has_bayer_logo")
        conf = c.vision.get("logo_confidence")
        try:
            conf_f = float(conf) if conf is not None else 0.8
        except (TypeError, ValueError):
            conf_f = 0.8
        if flag is True:
            if conf_f < logo_pass:
                gray.append(c.photo_id)
            else:
                hits.append(c.photo_id)
        elif flag is False:
            miss.append(c.photo_id)
        else:
            gray.append(c.photo_id)
        evidence_rows.append(
            {
                "photo_id": c.photo_id,
                "kind": "logo",
                "vision_only": True,
                "flag": flag,
                "conf": conf_f,
            }
        )
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
    pans = [c for c in contexts if c.photo_type == "Panorama" and c.ok]
    if not pans:
        return skip("PANORAMA_COUNT", "无全景")
    total = 0
    confs = []
    related = []
    for c in pans:
        related.append(c.photo_id)
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
    subtype = snap.get("meeting_type")
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
    from app.services.pipeline.aggregate import merge_signin_sheets

    merged = merge_signin_sheets(contexts, options)
    if not merged:
        return skip("SIGNIN_DURATION", "无签到")
    thr = merge_thresholds(options)
    project_type = snap["project_type"]
    subtype = snap.get("meeting_type")
    need = signin_duration_need(project_type, subtype, thr)
    related = list(merged.get("photo_ids") or [])
    best = merged.get("duration_minutes")
    if best is None:
        return uncertain(
            "SIGNIN_DURATION",
            "BLURRY",
            "签到表模糊或无法可靠读取起止时间",
            related=related,
        )
    best = int(best)
    page_n = int(merged.get("page_count") or len(related) or 1)
    if best <= need:
        return fail(
            "SIGNIN_DURATION",
            "DURATION_BELOW_THRESHOLD",
            "签到时长{0}分钟，未超过{1}（{2}页合并）".format(best, need, page_n),
            related=related,
            evidence={
                "duration": best,
                "need": need,
                "page_count": page_n,
                "pages": merged.get("pages"),
            },
        )
    return pass_(
        "SIGNIN_DURATION",
        "签到时长 {0} 分钟，满足 >{1}（{2}页合并）".format(best, need, page_n),
        related=related,
        evidence={
            "duration": best,
            "need": need,
            "page_count": page_n,
            "pages": merged.get("pages"),
        },
    )


def rule_signin_complete(
    contexts: List[AssetContext], options: dict
) -> RuleOutcome:
    """每张签到表独立做完整性：表头（若有）+ 已占用行四列齐。"""
    from app.services.pipeline.aggregate import _signin_payload, merge_signin_sheets

    merged = merge_signin_sheets(contexts, options)
    if not merged:
        return skip("SIGNIN_COMPLETE", "无签到")
    related = list(merged.get("photo_ids") or [])
    fails: List[str] = []
    uncs: List[str] = []
    page_ev: List[dict] = []
    for c in contexts:
        if c.photo_type != "SignSheet" or not c.ok:
            continue
        if _is_blurry(c, options):
            uncs.append(c.photo_id)
            page_ev.append({"photo_id": c.photo_id, "skipped": "blurry"})
            continue
        p = _signin_payload(c)
        ok = p.get("complete_ok")
        row = {
            "photo_id": c.photo_id,
            "complete_ok": ok,
            "header_complete": p.get("header_complete"),
            "rows_complete": p.get("rows_complete"),
            "incomplete_row_count": p.get("incomplete_row_count"),
        }
        page_ev.append(row)
        if ok is False:
            fails.append(c.photo_id)
        elif ok is None:
            uncs.append(c.photo_id)

    if fails:
        return fail(
            "SIGNIN_COMPLETE",
            "SIGNIN_INCOMPLETE",
            "签到表填写不完整（姓名/职称/连锁/签名或表头缺项），材料: {0}".format(
                fails
            ),
            related=fails,
            evidence={"pages": page_ev},
        )
    if uncs and not fails:
        return uncertain(
            "SIGNIN_COMPLETE",
            "OCR_LOW_CONFIDENCE",
            "签到表完整性无法可靠判定，材料: {0}".format(uncs),
            related=uncs,
            evidence={"pages": page_ev},
        )
    return pass_(
        "SIGNIN_COMPLETE",
        "签到表填写完整（{0}页各自通过）".format(len(related)),
        related=related,
        evidence={"pages": page_ev},
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
    project_id = snap.get("project_id")
    meeting_id = snap["meeting_id"]

    q = select(ImageDupHistory).where(ImageDupHistory.meeting_id != meeting_id)
    if scope == "period" and project_id is not None:
        q = q.where(ImageDupHistory.project_id == project_id)
    history = list(db.scalars(q).all())
    if not history:
        return skip("IMAGE_DUP", "查重库为空（首场）")

    hits = []
    related = []
    for c in contexts:
        if not c.ok or (not c.phash and not c.embedding):
            continue
        related.append(c.photo_id)
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
                    "photo_id": c.photo_id,
                    "ref_meeting_id": href.meeting_id,
                    "ref_meeting_no": href.meeting_no,
                    "kind": kind,
                    "method": "phash",
                    "distance": dist,
                }
            )
        elif best_emb is not None:
            sim, href = best_emb
            hits.append(
                {
                    "photo_id": c.photo_id,
                    "ref_meeting_id": href.meeting_id,
                    "ref_meeting_no": href.meeting_no,
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
                [h["photo_id"] for h in hits]
            ),
            related=[h["photo_id"] for h in hits],
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
        if c.photo_type != "SpeakerTitle" or not c.ok:
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
                "photo_id": c.photo_id,
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
    project_id = snap.get("project_id")
    meeting_id = snap["meeting_id"]
    q = select(TopicHistory).where(
        (TopicHistory.meeting_id.is_(None)) | (TopicHistory.meeting_id != meeting_id)
    )
    if scope == "period" and project_id is not None:
        q = q.where(TopicHistory.project_id == project_id)
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
                    "photo_id": t["photo_id"],
                    "topic": t["topic_raw"],
                    "speaker_name": t.get("speaker_name"),
                    "ref_meeting_no": h.meeting_no,
                    "ref_meeting_id": h.meeting_id,
                    "ref_speaker_name": h.speaker_name,
                }
            )
            break
    related = [t["photo_id"] for t in titles]
    if hits:
        return fail(
            "TOPIC_REUSE",
            "TOPIC_REUSED",
            "讲者照主题与历史会议重复",
            related=[h["photo_id"] for h in hits],
            evidence={"hits": hits},
        )
    return pass_("TOPIC_REUSE", "讲者照 OCR 标题未与历史主题重复", related=related)


# WATERMARK_CONSISTENCY 已下线：时间/日期/地点水印均不审核。


def _truthy_flag(vision: dict, key: str) -> Optional[bool]:
    flag = vision.get(key)
    if flag is True or flag is False:
        return bool(flag)
    return None


def _speaker_title_composition(c: AssetContext) -> Dict[str, Any]:
    """标题合影须同时有：讲者、标题、讲者姓名、日期。"""
    v = c.vision or {}
    of = c.ocr_fields()
    person = _truthy_flag(v, "has_speaker_person")
    title = of.get("topic_title") or v.get("topic_title")
    name = of.get("speaker_name_on_slide")
    if not name:
        names = of.get("speaker_names")
        if isinstance(names, list) and names:
            name = names[0]
        elif isinstance(names, str) and names.strip():
            name = names.strip()
    date = of.get("meeting_date") or v.get("meeting_date")
    parts = {
        "has_speaker_person": person,
        "has_topic_title": bool(title and str(title).strip()),
        "has_speaker_name": bool(name and str(name).strip()),
        "has_date": bool(date and str(date).strip()),
    }
    missing: List[str] = []
    if person is False:
        missing.append("讲者")
    if not parts["has_topic_title"]:
        missing.append("标题")
    if not parts["has_speaker_name"]:
        missing.append("讲者姓名")
    if not parts["has_date"]:
        missing.append("日期")
    person_unc = person is None
    return {
        "ok": not missing and not person_unc,
        "uncertain": person_unc and not missing,
        "missing": missing,
        "parts": parts,
    }


def _speaker_lecture_composition(c: AssetContext) -> Dict[str, Any]:
    """授课照须同时有：讲者 + PPT/投影。"""
    v = c.vision or {}
    person = _truthy_flag(v, "has_speaker_person")
    ppt = _truthy_flag(v, "has_ppt_screen")
    missing = []
    if person is False:
        missing.append("讲者")
    if ppt is False:
        missing.append("PPT")
    uncertain = (person is None or ppt is None) and not missing
    ok = person is True and ppt is True
    return {
        "ok": ok,
        "uncertain": uncertain and not ok,
        "missing": missing if not ok else [],
        "parts": {"has_speaker_person": person, "has_ppt_screen": ppt},
    }


def rule_speaker_composition(
    contexts: List[AssetContext], options: Optional[dict] = None
) -> RuleOutcome:
    """讲者照构图：标题合影=人+标题+姓名+日期；授课照=人+PPT。"""
    titles = [c for c in contexts if c.photo_type == "SpeakerTitle" and c.ok]
    lectures = [c for c in contexts if c.photo_type == "SpeakerLecture" and c.ok]
    if not titles and not lectures:
        return skip("SPEAKER_COMPOSITION", "无讲者照")

    fails = []
    uncs = []
    related = []
    evidence_rows = []
    for c in titles:
        related.append(c.photo_id)
        if _is_blurry(c, options or {}):
            uncs.append(c.photo_id)
            evidence_rows.append({"photo_id": c.photo_id, "kind": "title", "blurry": True})
            continue
        comp = _speaker_title_composition(c)
        evidence_rows.append({"photo_id": c.photo_id, "kind": "title", **comp})
        if comp["ok"]:
            continue
        if comp["uncertain"]:
            uncs.append(c.photo_id)
        else:
            fails.append(
                {
                    "photo_id": c.photo_id,
                    "kind": "SpeakerTitle",
                    "missing": comp["missing"],
                }
            )

    for c in lectures:
        related.append(c.photo_id)
        if _is_blurry(c, options or {}):
            uncs.append(c.photo_id)
            evidence_rows.append(
                {"photo_id": c.photo_id, "kind": "lecture", "blurry": True}
            )
            continue
        comp = _speaker_lecture_composition(c)
        evidence_rows.append({"photo_id": c.photo_id, "kind": "lecture", **comp})
        if comp["ok"]:
            continue
        if comp["uncertain"]:
            uncs.append(c.photo_id)
        else:
            fails.append(
                {
                    "photo_id": c.photo_id,
                    "kind": "SpeakerLecture",
                    "missing": comp["missing"],
                }
            )

    if fails:
        bits = []
        for f in fails:
            need = (
                "讲者+标题+讲者姓名+日期"
                if f["kind"] == "SpeakerTitle"
                else "讲者+PPT"
            )
            bits.append(
                "{0}缺{1}（须同时有{2}）".format(
                    f["photo_id"], "、".join(f["missing"]) or "要素", need
                )
            )
        return fail(
            "SPEAKER_COMPOSITION",
            "TYPE_MISMATCH",
            "；".join(bits),
            related=[f["photo_id"] for f in fails],
            evidence={"rows": evidence_rows, "fails": fails},
        )
    if uncs:
        return uncertain(
            "SPEAKER_COMPOSITION",
            "OCR_LOW_CONFIDENCE",
            "讲者照构图要素识别不清",
            related=uncs,
            evidence={"rows": evidence_rows},
        )
    return pass_(
        "SPEAKER_COMPOSITION",
        "标题合影含讲者/标题/姓名/日期；授课照含讲者与PPT",
        related=related,
        evidence={"rows": evidence_rows},
    )
