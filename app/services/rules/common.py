"""通用规则（LECTURE_HALL + MICRO）。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ImageDupHistory
from app.services.embedding_util import embedding_similarity
from app.services.image_dup_policy import (
    DUP_EXACT_ONLY,
    dup_category,
)
from app.services.phash_util import phash_distance
from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome, fail, pass_, skip, uncertain
from app.services.text_norm import (
    date_equal,
    fuzzy_contains,
    name_set_equal,
    normalize_name,
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


def rule_key_field_match(
    contexts: List[AssetContext], form: dict, options: dict
) -> List[RuleOutcome]:
    """对台账字段拆码：DATE / LOCATION / SPEAKER_NAME（时间见 TIME_CONSISTENCY）。

    适用材料对齐《按材料类型-图像检测清单_枚举检测点》检测点定义表。
    """
    date_types = {"SpeakerTitle", "EDM", "Poster", "Stand", "SignSheet"}
    loc_types = {"EDM", "Poster", "Stand", "SignSheet"}
    # 海报类比姓名集合；标题合影比该讲者姓名（台卡另走 NAME_SET_MISMATCH）
    poster_name_types = {"EDM", "Poster", "Stand"}
    title_name_types = {"SpeakerTitle"}

    mode = _opts(options).get("name_match_mode", "fuzzy")
    form_date = form.get("meeting_date")
    form_loc = form.get("meeting_location") or ""
    form_names = [s["speaker_name"] for s in form.get("speakers") or []]
    speakers_by_id = {
        s["speaker_id"]: s for s in form.get("speakers") or [] if s.get("speaker_id")
    }

    date_fails: List[str] = []
    loc_fails: List[str] = []
    name_fails: List[str] = []
    related: List[str] = []
    uncs: List[str] = []
    saw = False

    for c in contexts:
        if not c.ok:
            continue
        pt = c.photo_type
        if pt not in date_types | loc_types | poster_name_types | title_name_types:
            continue
        if c.vision_error:
            uncs.append(c.photo_id)
            continue
        of = c.ocr_fields()
        related.append(c.photo_id)
        saw = True

        if pt in date_types and of.get("meeting_date") and form_date:
            if not date_equal(of.get("meeting_date"), form_date):
                date_fails.append(c.photo_id)

        if pt in loc_types:
            ocr_loc = of.get("meeting_location") or of.get("location")
            if ocr_loc and form_loc:
                if not (
                    fuzzy_contains(ocr_loc, form_loc)
                    or fuzzy_contains(form_loc, ocr_loc)
                ):
                    loc_fails.append(c.photo_id)

        if pt in poster_name_types and form_names:
            raw_names = of.get("speaker_names") or []
            if isinstance(raw_names, str):
                ocr_names = [raw_names] if raw_names.strip() else []
            elif isinstance(raw_names, list):
                ocr_names = raw_names
            else:
                ocr_names = []
            if ocr_names:
                cmp = name_set_equal(ocr_names, form_names, mode)
                if not (cmp["ok"] or len(cmp["missing"]) == 0):
                    name_fails.append(c.photo_id)

        if pt in title_name_types:
            sp = speakers_by_id.get(c.speaker_id) or {}
            expect = sp.get("speaker_name")
            visible = of.get("speaker_name_on_slide")
            if not visible:
                names = of.get("speaker_names")
                if isinstance(names, list) and names:
                    visible = names[0]
                elif isinstance(names, str) and names.strip():
                    visible = names.strip()
            if visible and expect:
                ok = name_set_equal([visible], [expect], mode)["ok"] or (
                    normalize_name(visible) == normalize_name(expect)
                )
                if not ok:
                    name_fails.append(c.photo_id)

    outcomes: List[RuleOutcome] = []
    if date_fails:
        outcomes.append(
            fail(
                "KEY_FIELD_MATCH",
                "DATE_MISMATCH",
                "日期是否和表单一致：不一致材料 {0}".format(date_fails),
                related=date_fails,
            )
        )
    if loc_fails:
        outcomes.append(
            fail(
                "KEY_FIELD_MATCH",
                "LOCATION_MISMATCH",
                "地点是否和表单一致：不一致材料 {0}".format(loc_fails),
                related=loc_fails,
            )
        )
    if name_fails:
        outcomes.append(
            fail(
                "KEY_FIELD_MATCH",
                "SPEAKER_NAME_MISMATCH",
                "讲者姓名是否与表单一致：不一致材料 {0}".format(name_fails),
                related=name_fails,
            )
        )
    if outcomes:
        return outcomes
    if uncs:
        return [
            uncertain(
                "KEY_FIELD_MATCH",
                "OCR_LOW_CONFIDENCE",
                "关键字段 OCR 不可靠，材料: {0}".format(uncs),
                related=uncs,
            )
        ]
    if not saw:
        return [skip("KEY_FIELD_MATCH", "无对应材料")]
    return [
        pass_(
            "KEY_FIELD_MATCH",
            "日期/地点/讲者姓名与表单一致",
            related=related,
        )
    ]


def rule_time_consistency(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    """比对材料上的日程起止时间 → TIME_MISMATCH；不做时间水印检测。"""
    skew = int(_opts(options).get("watermark_time_skew_minutes", 120))
    start = time_to_minutes(form.get("start_time"))
    end = time_to_minutes(form.get("end_time"))
    if start is None or end is None:
        return skip("TIME_CONSISTENCY", "表单无时段")

    # EDMDisplay 不做日程时间对台账；签到表/海报类做
    agenda_types = {"Poster", "Stand", "EDM", "SignSheet"}
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
            "TIME_MISMATCH",
            "时间是否和表单一致：不一致材料 {0}".format(bad),
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
            "OCR_LOW_CONFIDENCE",
            "签到表无法可靠读取起止时间",
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
    contexts: List[AssetContext],
    options: dict,
) -> RuleOutcome:
    """签到表填写完整：每页独立；除「其他」列外，表头（若有）与已占用行均须填齐。"""
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

    evidence = {"pages": page_ev, "page_count": len(related)}
    if fails:
        return fail(
            "SIGNIN_COMPLETE",
            "SIGNIN_INCOMPLETE",
            "签到表填写不完整（除「其他」外均须填写），材料: {0}".format(fails),
            related=fails,
            evidence=evidence,
        )
    if uncs:
        return uncertain(
            "SIGNIN_COMPLETE",
            "OCR_LOW_CONFIDENCE",
            "签到表填写完整性无法可靠判定，材料: {0}".format(uncs),
            related=uncs,
            evidence=evidence,
        )
    return pass_(
        "SIGNIN_COMPLETE",
        "签到表填写完整（{0}页各自通过）".format(len(related)),
        related=related,
        evidence=evidence,
    )


def rule_signin_audience(
    contexts: List[AssetContext],
    snap: dict,
    options: dict,
) -> RuleOutcome:
    """签到表听众人数：多页合计达标（大讲堂≥35；微型≥讲者×6）。"""
    from app.services.pipeline.aggregate import merge_signin_sheets
    from app.services.thresholds import merge_thresholds, signin_audience_need

    merged = merge_signin_sheets(contexts, options)
    if not merged:
        return skip("SIGNIN_AUDIENCE", "无签到")
    related = list(merged.get("photo_ids") or [])
    form = snap.get("form") or {}
    thr = merge_thresholds(options)
    need_aud = signin_audience_need(
        snap.get("project_type") or "LECTURE_HALL",
        snap.get("meeting_type"),
        form,
        thr,
    )
    page_n = int(merged.get("page_count") or len(related) or 1)
    audience = merged.get("audience_count")
    evidence = {
        "audience_count": audience,
        "need_audience": need_aud,
        "page_count": page_n,
        "pages": merged.get("pages"),
    }
    if audience is None:
        return uncertain(
            "SIGNIN_AUDIENCE",
            "COUNT_UNCERTAIN",
            "签到表听众人数无法可靠读取",
            related=related,
            evidence=evidence,
        )
    if int(audience) < need_aud:
        return fail(
            "SIGNIN_AUDIENCE",
            "SIGNIN_COUNT_BELOW",
            "签到表听众数{0}<要求{1}（{2}页合计）".format(
                audience, need_aud, page_n
            ),
            related=related,
            evidence=evidence,
        )
    return pass_(
        "SIGNIN_AUDIENCE",
        "签到表听众人数达标（{0}页合计{1}≥{2}）".format(
            page_n, audience, need_aud
        ),
        related=related,
        evidence=evidence,
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

    # 库按有人/无人分组，本场每张只与同组历史比
    hist_by_cat: Dict[str, List[ImageDupHistory]] = {"people": [], "material": []}
    for h in history:
        cat = dup_category(h.photo_type)
        if cat:
            hist_by_cat[cat].append(h)

    hits = []
    related = []
    for c in contexts:
        cat = dup_category(c.photo_type)
        if not c.ok or not cat or (not c.phash and not c.embedding):
            continue
        related.append(c.photo_id)
        peers = hist_by_cat.get(cat) or []
        if not peers:
            continue

        exact_only = c.photo_type in DUP_EXACT_ONLY
        # 海报/电子海报/展架：仅 pHash 完全一致；其余：pHash≤阈值，必要时 embedding
        phash_limit = 0 if exact_only else max_dist
        best_phash = None  # (dist, kind, hist)
        best_emb = None  # (sim, hist)
        for h in peers:
            if c.phash and h.phash:
                dist = phash_distance(c.phash, h.phash)
                if dist <= phash_limit and (
                    best_phash is None or dist < best_phash[0]
                ):
                    kind = "exact" if dist == 0 else "similar"
                    best_phash = (dist, kind, h)
            if (
                not exact_only
                and c.embedding
                and getattr(h, "embedding", None)
            ):
                sim = embedding_similarity(c.embedding, h.embedding)
                if sim is not None and sim >= sim_thr and (
                    best_emb is None or sim > best_emb[0]
                ):
                    best_emb = (sim, h)
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
                    "dup_category": cat,
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
                    "dup_category": cat,
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
        "未盗用其他会议同组材料（有人/无人分组；海报类仅完全一致）",
        related=related,
    )


# WATERMARK_CONSISTENCY 已下线：时间/日期/地点水印均不审核。
# TOPIC_REUSE 已下线：主题跨会复用不再审核。


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
            "COMPOSITION_MISSING",
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
