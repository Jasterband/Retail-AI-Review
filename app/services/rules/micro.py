"""微型药师专用规则。

权益模版检测约定（业务确认）：
- 权益一 ProjectIntro：规定模版上是否有【彩色丝带/彩色波浪装饰】
- 权益二 EDMDisplay：规定模版上是否有【日程表】
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome, fail, pass_, skip, uncertain

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
    if ctx.photo_type == "ProjectIntro":
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
    if ctx.photo_type == "EDMDisplay":
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

    types = {"EDMDisplay", "ProjectIntro"}
    targets = [c for c in contexts if c.photo_type in types and c.ok]
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
        related.append(c.photo_id)
        check_name, flag, conf, fail_text = _equity_feature(c)
        item = {
            "photo_id": c.photo_id,
            "photo_type": c.photo_type,
            "check": check_name,
            "flag": flag,
            "confidence": conf,
        }
        evidence["checks"].append(item)

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
            related=[f["photo_id"] for f in fails],
            evidence=evidence,
        )
    if uncs and not passes:
        return uncertain(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_UNCERTAIN",
            "权益模版特征（彩色丝带/日程表）识别不清",
            related=[u["photo_id"] for u in uncs],
            evidence=evidence,
        )
    if uncs:
        return uncertain(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_UNCERTAIN",
            "部分权益页模版特征灰区",
            related=[u["photo_id"] for u in uncs],
            evidence=evidence,
        )

    # 文案按类型汇总
    bits = []
    for c in targets:
        if c.photo_type == "ProjectIntro":
            bits.append("权益一检出彩色丝带")
        elif c.photo_type == "EDMDisplay":
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
    types = {"EDMDisplay", "ProjectIntro"}
    targets = [c for c in contexts if c.photo_type in types and c.ok]
    if len(targets) < 2:
        return skip("PPT_PAGE_KIND", "权益展示页不足两张")

    kinds: List[Tuple[int, Optional[str]]] = []
    related: List[int] = []
    evidence_rows: List[dict] = []

    for c in targets:
        related.append(c.photo_id)
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
        elif c.photo_type == "ProjectIntro" and ribbon is True:
            kind = "PROJECT_INTRO"
        elif c.photo_type == "EDMDisplay" and agenda is False and ribbon is True:
            # 只有丝带没有表，不像权益二
            kind = kind or "OTHER"
        elif not kind:
            # 不再仅凭声明类型直接 PASS；特征不足 → OTHER 进灰区
            kind = "OTHER"

        kinds.append((c.photo_id, kind))
        evidence_rows.append(
            {
                "photo_id": c.photo_id,
                "photo_type": c.photo_type,
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
            "TEMPLATE_UNCERTAIN",
            "权益页类（介绍/日程）识别不清",
            related=related,
            evidence=evidence,
        )

    values = [k for _, k in kinds]
    if len(set(values)) < 2:
        return fail(
            "PPT_PAGE_KIND",
            "TEMPLATE_MISMATCH",
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
        "TEMPLATE_MISMATCH",
        "页类错误或重复",
        related=related,
        evidence=evidence,
    )


def rule_signin_ratio_and_stores(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    """微型签到门店种类（人数改由 SIGNIN_AUDIENCE 单独判定）。"""
    from app.services.pipeline.aggregate import merge_signin_sheets
    from app.services.thresholds import merge_thresholds

    merged = merge_signin_sheets(contexts, options)
    if not merged:
        return skip("SIGNIN_RATIO_AND_STORES", "无签到")
    thr = merge_thresholds(options)
    min_stores = int(thr.get("signin_min_store_kinds", 2))
    related = list(merged.get("photo_ids") or [])
    page_n = int(merged.get("page_count") or len(related) or 1)
    uniq_stores = set(merged.get("store_names") or [])
    evidence = {
        "stores": list(uniq_stores),
        "need_stores": min_stores,
        "page_count": page_n,
        "pages": merged.get("pages"),
    }

    if not uniq_stores:
        return uncertain(
            "SIGNIN_RATIO_AND_STORES",
            "OCR_LOW_CONFIDENCE",
            "签到表听众门店识别困难",
            related=related,
            evidence=evidence,
        )
    if len(uniq_stores) < min_stores:
        return fail(
            "SIGNIN_RATIO_AND_STORES",
            "COUNT_BELOW_THRESHOLD",
            "听众门店种类不足{0}（当前{1}）".format(min_stores, len(uniq_stores)),
            related=related,
            evidence=evidence,
        )
    return pass_(
        "SIGNIN_RATIO_AND_STORES",
        "签到听众门店种类满足要求（{0}页合计）".format(page_n),
        related=related,
        evidence=evidence,
    )
