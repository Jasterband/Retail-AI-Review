"""IMAGE_DUP 比对策略：跨会 1×库；有人/无人分组；海报类仅完全一致。"""

from __future__ import annotations

from typing import Optional

# 有人物：讲者照 / 授课照 / 全景 → 只与同类比（pHash 近似 + embedding）
DUP_CATEGORY_PEOPLE = frozenset({"SpeakerTitle", "SpeakerLecture", "Panorama"})

# 无人物材料：手册 / 海报 / 展架 / 介绍 / 台卡 / 签到表 → 只与同类比
# Excel：所有照片均做 IMAGE_DUP
DUP_CATEGORY_MATERIAL = frozenset(
    {
        "Manual",
        "Poster",
        "Stand",
        "EDM",
        "EDMDisplay",
        "ProjectIntro",
        "TableCard",
        "SignSheet",
    }
)

# 海报 / 电子海报 / 展架：不做余弦，仅 pHash 完全一致（distance == 0）
DUP_EXACT_ONLY = frozenset({"EDM", "Poster", "Stand", "EDMDisplay"})

DUP_CATEGORY_ALL = DUP_CATEGORY_PEOPLE | DUP_CATEGORY_MATERIAL


def dup_category(photo_type: Optional[str]) -> Optional[str]:
    if not photo_type:
        return None
    if photo_type in DUP_CATEGORY_PEOPLE:
        return "people"
    if photo_type in DUP_CATEGORY_MATERIAL:
        return "material"
    return None


def uses_embedding_dup(photo_type: Optional[str]) -> bool:
    """是否对该类型算 embedding 并做余弦近似查重。"""
    return dup_category(photo_type) is not None and photo_type not in DUP_EXACT_ONLY
