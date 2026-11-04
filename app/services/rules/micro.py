"""微型药师专用规则。

权益模版检测约定（业务确认）：
- 权益一 PROJECT_INTRO_DISPLAY：规定模版上是否有【彩色丝带/彩色波浪装饰】
- 权益二 E_POSTER_DISPLAY：规定模版上是否有【日程表】
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome, fail, pass_, skip, uncertain
from app.services.rules.common import _is_blurry


def _flag_conf(
    vision: dict, flag_key: str, conf_key: str
) -> Tuple[Optional[bool], float]:
    flag = vision.get(flag_key)
    conf = vision.get(conf_key)
    try:
        conf_f = float(conf) if conf is not None else None
    except (TypeError, ValueError):
        conf_f = None
    if conf_f is None:
        if flag is True:
            conf_f = 0.9
        elif flag is False:
            conf_f = 0.85
        else:
            conf_f = 0.5
    if flag is True:
        conf_f = max(conf_f, 0.75)
    if flag is False:
        conf_f = max(conf_f, 0.7)
    return (flag if isinstance(flag, bool) else None), conf_f


def _equity_feature(ctx: AssetContext) -> Tuple[str, Optional[bool], float, str]:
    """返回 (检测点名, 是否命中, 置信度, 失败文案)。优先模版 pack crop。"""
    if ctx.declared_type == "PROJECT_INTRO_DISPLAY":
        tm = (ctx.template_match or {}).get("colorful_ribbon")
        if tm:
            hit = tm.get("hit")
            score = float(tm.get("score") or 0)
            flag: Optional[bool]
            if hit:
                flag = True
            elif tm.get("uncertain"):
                flag = None
            else:
                flag = False
            return (
                "has_colorful_ribbon",
                flag,
                score,
                "权益一（项目介绍）模版未检出彩色丝带/彩色波浪装饰",
            )
        flag, conf = _flag_conf(
            ctx.vision, "has_colorful_ribbon", "colorful_ribbon_confidence"
        )
        return (
            "has_colorful_ribbon",
            flag,
            conf,
            "权益一（项目介绍）模版未检出彩色丝带/彩色波浪装饰",
        )
    if ctx.declared_type == "E_POSTER_DISPLAY":
        tm = (ctx.template_match or {}).get("agenda_table")
        if tm:
            hit = tm.get("hit")
            score = float(tm.get("score") or 0)
            if hit:
                flag = True
            elif tm.get("uncertain"):
                flag = None
            else:
                flag = False
            return (
                "has_agenda_table",
                flag,
                score,
                "权益二（日程展示）模版未检出日程表",
            )
        flag, conf = _flag_conf(
            ctx.vision, "has_agenda_table", "agenda_table_confidence"
        )
        return (
            "has_agenda_table",
            flag,
            conf,
            "权益二（日程展示）模版未检出日程表",
        )
    return ("", None, 0.0, "")


def rule_ppt_template_match(
    contexts: List[AssetContext], options: dict
) -> RuleOutcome:
    from app.services.thresholds import merge_thresholds

    types = {"E_POSTER_DISPLAY", "PROJECT_INTRO_DISPLAY"}
    targets = [c for c in contexts if c.declared_type in types and c.ok]
    if not targets:
        return skip("PPT_TEMPLATE_MATCH", "无权益一/权益二展示材料")

    thr = merge_thresholds(options)
    thr_pass = float(thr.get("template_similarity_pass", 0.85))
    thr_fail = float(thr.get("template_similarity_fail", 0.65))
    related: List[int] = []
    evidence: dict = {"checks": []}
    fails: List[dict] = []
    uncs: List[dict] = []
    passes: List[dict] = []

    for c in targets:
        related.append(c.asset_id)
        check_name, flag, conf, fail_text = _equity_feature(c)
        item = {
            "asset_id": c.asset_id,
            "declared_type": c.declared_type,
            "check": check_name,
            "flag": flag,
            "confidence": conf,
        }
        evidence["checks"].append(item)

        if _is_blurry(c, options) and flag is not True:
            uncs.append({**item, "reason": "画面模糊，模版特征不可靠"})
            continue

        if flag is True and conf >= thr_pass:
            passes.append(item)
            continue
        if flag is False and conf >= thr_fail:
            fails.append({**item, "reason": fail_text})
            continue
        if flag is True and conf < thr_pass:
            uncs.append({**item, "reason": "特征检出但置信度灰区"})
            continue
        if flag is False and conf < thr_fail:
            uncs.append({**item, "reason": "疑似缺失但置信度低"})
            continue
        uncs.append({**item, "reason": "无法判定彩色丝带或日程表"})

    if fails:
        texts = [f["reason"] for f in fails]
        return fail(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_MISMATCH",
            "；".join(texts),
            conf=min(f["confidence"] for f in fails),
            related=[f["asset_id"] for f in fails],
            evidence=evidence,
        )
    if uncs and not passes:
        return uncertain(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_UNCERTAIN",
            "权益模版特征（彩色丝带/日程表）识别不清",
            related=[u["asset_id"] for u in uncs],
            evidence=evidence,
        )
    if uncs:
        return uncertain(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_UNCERTAIN",
            "部分权益页模版特征灰区",
            related=[u["asset_id"] for u in uncs],
            evidence=evidence,
        )

    # 文案按类型汇总
    bits = []
    for c in targets:
        if c.declared_type == "PROJECT_INTRO_DISPLAY":
            bits.append("权益一检出彩色丝带")
        elif c.declared_type == "E_POSTER_DISPLAY":
            bits.append("权益二检出日程表")
    return pass_(
        "PPT_TEMPLATE_MATCH",
        "、".join(bits) if bits else "权益展示页符合规定模版特征",
        related=related,
        evidence=evidence,
    )


def rule_ppt_page_kind(
    contexts: List[AssetContext], options: dict
) -> RuleOutcome:
    """权益一=项目介绍（丝带页）；权益二=日程页（有日程表）。二者须互补。"""
    types = {"E_POSTER_DISPLAY", "PROJECT_INTRO_DISPLAY"}
    targets = [c for c in contexts if c.declared_type in types and c.ok]
    if len(targets) < 2:
        return skip("PPT_PAGE_KIND", "权益展示页不足两张")

    kinds: List[Tuple[int, Optional[str]]] = []
    related: List[int] = []
    evidence_rows: List[dict] = []

    for c in targets:
        related.append(c.asset_id)
        tm = c.template_match or {}
        ribbon_tm = tm.get("colorful_ribbon") or {}
        agenda_tm = tm.get("agenda_table") or {}
        ribbon, r_conf = _flag_conf(
            c.vision, "has_colorful_ribbon", "colorful_ribbon_confidence"
        )
        agenda, a_conf = _flag_conf(
            c.vision, "has_agenda_table", "agenda_table_confidence"
        )
        # 模版 pack 优先于纯 vision
        if ribbon_tm:
            if ribbon_tm.get("hit"):
                ribbon, r_conf = True, float(ribbon_tm.get("score") or r_conf)
            elif ribbon_tm.get("uncertain"):
                ribbon = None
            else:
                ribbon, r_conf = False, float(ribbon_tm.get("score") or r_conf)
        if agenda_tm:
            if agenda_tm.get("hit"):
                agenda, a_conf = True, float(agenda_tm.get("score") or a_conf)
            elif agenda_tm.get("uncertain"):
                agenda = None
            else:
                agenda, a_conf = False, float(agenda_tm.get("score") or a_conf)

        kind = c.vision.get("ppt_page_kind")

        # 业务特征优先：有日程表 → 日程页；否则有丝带且声明为介绍 → 介绍页
        if agenda is True:
            kind = "AGENDA"
        elif c.declared_type == "PROJECT_INTRO_DISPLAY" and ribbon is True:
            kind = "PROJECT_INTRO"
        elif c.declared_type == "E_POSTER_DISPLAY" and agenda is False and ribbon is True:
            # 只有丝带没有表，不像权益二
            kind = kind or "OTHER"
        elif not kind:
            # 不再仅凭声明类型直接 PASS；特征不足 → OTHER 进灰区
            kind = "OTHER"

        kinds.append((c.asset_id, kind))
        evidence_rows.append(
            {
                "asset_id": c.asset_id,
                "declared_type": c.declared_type,
                "kind": kind,
                "has_colorful_ribbon": ribbon,
                "has_agenda_table": agenda,
                "ribbon_confidence": r_conf,
                "agenda_confidence": a_conf,
            }
        )

    evidence: Dict[str, Any] = {"pages": evidence_rows}

    if any(k is None or k == "OTHER" for _, k in kinds):
        return uncertain(
            "PPT_PAGE_KIND",
            "OCR_LOW_CONFIDENCE",
            "权益页类（介绍/日程）识别不清",
            related=related,
            evidence=evidence,
        )

    values = [k for _, k in kinds]
    if len(set(values)) < 2:
        return fail(
            "PPT_PAGE_KIND",
            "TYPE_MISMATCH",
            "两张权益页页类重复或缺少「项目介绍/日程」组合",
            related=related,
            evidence=evidence,
        )

    if "PROJECT_INTRO" in values and "AGENDA" in values:
        return pass_(
            "PPT_PAGE_KIND",
            "权益一为项目介绍、权益二为日程页",
            related=related,
            evidence=evidence,
        )
    return fail(
        "PPT_PAGE_KIND",
        "TYPE_MISMATCH",
        "页类错误或重复",
        related=related,
        evidence=evidence,
    )


def rule_signin_ratio_and_stores(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    from app.services.thresholds import merge_thresholds

    signs = [c for c in contexts if c.declared_type == "SIGNIN" and c.ok]
    if not signs:
        return skip("SIGNIN_RATIO_AND_STORES", "无签到")
    thr = merge_thresholds(options)
    n_speakers = len(form.get("speakers") or [])
    need_audience = n_speakers * int(thr.get("signin_audience_per_speaker", 6))
    min_stores = int(thr.get("signin_min_store_kinds", 2))
    related = [c.asset_id for c in signs]

    audience = None
    stores = []
    for c in signs:
        if _is_blurry(c, options):
            continue
        signin = c.vision.get("signin") or {}
        ac = signin.get("audience_count")
        if ac is not None:
            try:
                audience = max(audience or 0, int(ac))
            except (TypeError, ValueError):
                pass
        stores.extend(signin.get("store_names") or [])

    if audience is None and not stores:
        return uncertain(
            "SIGNIN_RATIO_AND_STORES",
            "OCR_LOW_CONFIDENCE",
            "签到表听众/门店识别困难",
            related=related,
        )

    uniq_stores = {s.strip() for s in stores if s and str(s).strip()}
    problems = []
    if audience is not None and audience < need_audience:
        problems.append(
            "听众数{0}<讲者数×6（{1}）".format(audience, need_audience)
        )
    if stores and len(uniq_stores) < min_stores:
        problems.append(
            "听众门店种类不足{0}（当前{1}）".format(min_stores, len(uniq_stores))
        )
    if problems:
        return fail(
            "SIGNIN_RATIO_AND_STORES",
            "COUNT_BELOW_THRESHOLD",
            "；".join(problems),
            related=related,
            evidence={
                "audience": audience,
                "need_audience": need_audience,
                "stores": list(uniq_stores),
            },
        )
    return pass_(
        "SIGNIN_RATIO_AND_STORES",
        "签到听众人数与门店种类满足要求",
        related=related,
        evidence={
            "audience": audience,
            "need_audience": need_audience,
            "stores": list(uniq_stores),
        },
    )
