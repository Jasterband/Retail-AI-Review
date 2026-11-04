"""按 project_type 执行全部规则。"""

from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from app.services.pipeline.asset_context import AssetContext
from app.services.rules import common, hall, micro
from app.services.rules.base import RuleOutcome
from app.services.rules.registry import list_rule_codes_for_project


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
        "ASSET_TYPE_CHECK": lambda: common.rule_asset_type_check(contexts, options),
        "CLARITY": lambda: common.rule_clarity(contexts, options),
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
        "IMAGE_DUP": lambda: common.rule_image_dup(contexts, snap, refs, options, db),
        "TOPIC_REUSE": lambda: common.rule_topic_reuse(
            contexts, snap, form, refs, options, db
        ),
        "WATERMARK_CONSISTENCY": lambda: common.rule_watermark(
            contexts, form, options
        ),
        "NAME_CARD_SPEAKER_MATCH": lambda: hall.rule_name_card_speaker(
            contexts, form, options
        ),
        "NAME_CARD_TEMPLATE": lambda: hall.rule_name_card_template(contexts, options),
        "HANDBOOK_DETECT": lambda: hall.rule_handbook_detect(contexts),
        "HANDBOOK_NOT_STALE": lambda: hall.rule_handbook_not_stale(contexts),
        "SPEAKER_TOPIC_OCR": lambda: hall.rule_speaker_topic_ocr(
            contexts, form, options
        ),
        "SPEAKER_SHOT_PAIR": lambda: hall.rule_speaker_shot_pair(contexts, form),
        "PPT_TEMPLATE_MATCH": lambda: micro.rule_ppt_template_match(contexts, options),
        "PPT_PAGE_KIND": lambda: micro.rule_ppt_page_kind(contexts, options),
        "SIGNIN_RATIO_AND_STORES": lambda: micro.rule_signin_ratio_and_stores(
            contexts, form, options
        ),
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
            results.append(fn())
    return results
