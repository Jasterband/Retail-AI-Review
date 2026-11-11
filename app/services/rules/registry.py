"""按 project_type 列出应跑的规则（与 docs/03-rule-matrix.md 对齐的骨架）。"""

from __future__ import annotations

COMMON = [
    "ASSET_MISSING",
    "KEY_FIELD_MATCH",
    "TIME_CONSISTENCY",
    "BAYER_LOGO",
    "PANORAMA_COUNT",
    "SIGNIN_DURATION",
    "SIGNIN_COMPLETE",
    "SIGNIN_AUDIENCE",
    "IMAGE_DUP",
    "SPEAKER_COMPOSITION",
    "SPEAKER_TOPIC_OCR",  # 大讲堂海报类 + 微型 EDM / 讲者标题
]

LECTURE_HALL_ONLY = [
    "NAME_CARD_SPEAKER_MATCH",
    "HANDBOOK_DETECT",
    "HANDBOOK_NOT_STALE",
    "SPEAKER_SHOT_PAIR",
]

# 微型仅 ProjectIntro 做 TEMPLATE_MISMATCH；EDMDisplay 只查 Logo+查重
MICRO_ONLY = [
    "PPT_TEMPLATE_MATCH",
]


def list_rule_codes_for_project(project_type: str) -> list[str]:
    if project_type == "LECTURE_HALL":
        return COMMON + LECTURE_HALL_ONLY
    if project_type == "MICRO":
        return COMMON + MICRO_ONLY
    return list(COMMON)
