"""微型药师专用规则。

枚举检测点：项目介绍展示做 PPT 模版特征（彩色丝带）；EDMDisplay 仅 Logo+查重。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

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


def _project_intro_feature(
    ctx: AssetContext,
) -> Tuple[Optional[bool], float, str]:
    """项目介绍：彩色丝带/波浪装饰。返回 (命中, 置信度, 失败文案)。"""
    tm = (ctx.template_match or {}).get("colorful_ribbon")
    fail_text = "PPT模板特征是否与要求一致：未检出彩色丝带/彩色波浪装饰"
    if tm:
        hit = tm.get("hit")
        score = float(tm.get("score") or 0)
        if hit:
            return True, score, fail_text
        if tm.get("uncertain"):
            return None, score, fail_text
        return False, score, fail_text
    flag, conf = _flag_conf(
        ctx.vision, "has_colorful_ribbon", "colorful_ribbon_confidence"
    )
    return flag, conf, fail_text


def rule_ppt_template_match(
    contexts: List[AssetContext], options: dict
) -> RuleOutcome:
    """枚举检测点 ID18：仅 ProjectIntro → TEMPLATE_MISMATCH。"""
    from app.services.thresholds import merge_thresholds

    targets = [c for c in contexts if c.photo_type == "ProjectIntro" and c.ok]
    if not targets:
        return skip("PPT_TEMPLATE_MATCH", "无项目介绍展示材料")

    thr = merge_thresholds(options)
    thr_pass = float(thr.get("template_similarity_pass", 0.85))
    thr_fail = float(thr.get("template_similarity_fail", 0.65))
    related: List[str] = []
    evidence: dict = {"checks": []}
    fails: List[dict] = []
    uncs: List[dict] = []
    passes: List[dict] = []

    for c in targets:
        related.append(c.photo_id)
        flag, conf, fail_text = _project_intro_feature(c)
        item = {
            "photo_id": c.photo_id,
            "photo_type": c.photo_type,
            "check": "has_colorful_ribbon",
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
        uncs.append({**item, "reason": "模版特征识别不清"})

    if fails:
        return fail(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_MISMATCH",
            "；".join(f["reason"] for f in fails),
            conf=min(f["confidence"] for f in fails),
            related=[f["photo_id"] for f in fails],
            evidence=evidence,
        )
    if uncs and not passes:
        return uncertain(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_UNCERTAIN",
            "项目介绍模版特征识别不清",
            related=[u["photo_id"] for u in uncs],
            evidence=evidence,
        )
    if uncs:
        return uncertain(
            "PPT_TEMPLATE_MATCH",
            "TEMPLATE_UNCERTAIN",
            "部分项目介绍模版特征灰区",
            related=[u["photo_id"] for u in uncs],
            evidence=evidence,
        )
    return pass_(
        "PPT_TEMPLATE_MATCH",
        "项目介绍展示符合规定模版特征",
        related=related,
        evidence=evidence,
    )
