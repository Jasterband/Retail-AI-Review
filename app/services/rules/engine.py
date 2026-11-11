"""按 project_type 执行全部规则。"""

from __future__ import annotations

from typing import Any, Dict, List, Union

from sqlalchemy.orm import Session

from app.services.pipeline.asset_context import AssetContext
from app.services.rules import common, hall, micro
from app.services.rules.base import RuleOutcome
from app.services.rules.registry import list_rule_codes_for_project


def _as_outcomes(result: Union[RuleOutcome, List[RuleOutcome]]) -> List[RuleOutcome]:
    if isinstance(result, list):
        return result
    return [result]


def run_all_rules(
    snap: Dict[str, Any],
    contexts: List[AssetContext],
    db: Session,
) -> List[RuleOutcome]:
    project_type = snap["project_type"]
    options = snap.get("options") or {}
    refs = snap.get("refs") or {}
    form = snap["form"]
    codes = list_rule_codes_for_project(project_type)

    dispatch = {
        "ASSET_MISSING": lambda: common.rule_asset_missing(contexts, snap),
        "KEY_FIELD_MATCH": lambda: common.rule_key_field_match(contexts, form, options),
        "TIME_CONSISTENCY": lambda: common.rule_time_consistency(
            contexts, form, options
        ),
        "BAYER_LOGO": lambda: common.rule_bayer_logo(
            contexts, project_type, options
        ),
        "PANORAMA_COUNT": lambda: common.rule_panorama_count(
            contexts, snap, options
        ),
        "SIGNIN_DURATION": lambda: common.rule_signin_duration(contexts, snap, options),
        "SIGNIN_COMPLETE": lambda: common.rule_signin_complete(contexts, options),
        "SIGNIN_AUDIENCE": lambda: common.rule_signin_audience(
            contexts, snap, options
        ),
        "IMAGE_DUP": lambda: common.rule_image_dup(contexts, snap, refs, options, db),
        "SPEAKER_COMPOSITION": lambda: common.rule_speaker_composition(
            contexts, options
        ),
        "NAME_CARD_SPEAKER_MATCH": lambda: hall.rule_name_card_speaker(
            contexts, form, options
        ),
        "HANDBOOK_DETECT": lambda: hall.rule_handbook_detect(contexts),
        "HANDBOOK_NOT_STALE": lambda: hall.rule_handbook_not_stale(contexts),
        "SPEAKER_TOPIC_OCR": lambda: hall.rule_speaker_topic_ocr(
            contexts, form, options, project_type
        ),
        "SPEAKER_SHOT_PAIR": lambda: hall.rule_speaker_shot_pair(contexts, form),
        # Excel：仅项目介绍展示做 TEMPLATE_MISMATCH
        "PPT_TEMPLATE_MATCH": lambda: micro.rule_ppt_template_match(contexts, options),
    }

    results: List[RuleOutcome] = []
    for code in codes:
        fn = dispatch.get(code)
        if fn is None:
            results.append(
                RuleOutcome(
                    rule_code=code,
                    status="SKIP",
                    reason_text="未实现",
                )
            )
        else:
            results.extend(_as_outcomes(fn()))
    return results
