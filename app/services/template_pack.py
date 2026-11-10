"""本地模版 pack（docs/templates/{version}/）。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional

from app.config import get_settings


@dataclass(frozen=True)
class TemplatePack:
    version: str
    root: Path
    logo: Optional[Path]
    name_card: Optional[Path]  # 仅供台卡 ROI 定位抽姓名，非版式规则
    handbook_current: Optional[Path]
    handbook_stale: Optional[Path]
    equity1_ribbon: Optional[Path]
    equity1_full: Optional[Path]
    equity2_agenda: Optional[Path]
    equity2_full: Optional[Path]
    # 关键字段区（会议时间/地点/日程讲者）参考 crop
    poster_key_fields: Optional[Path]
    edm_key_fields: Optional[Path]
    micro_edm_key_fields: Optional[Path]

    def as_dict(self) -> Dict[str, Optional[str]]:
        def rel(p: Optional[Path]) -> Optional[str]:
            if p is None:
                return None
            try:
                return str(p.relative_to(get_settings().asset_root))
            except ValueError:
                return str(p)

        return {
            "version": self.version,
            "logo": rel(self.logo),
            "name_card": rel(self.name_card),
            "handbook_current": rel(self.handbook_current),
            "handbook_stale": rel(self.handbook_stale),
            "equity1_ribbon": rel(self.equity1_ribbon),
            "equity2_agenda": rel(self.equity2_agenda),
            "poster_key_fields": rel(self.poster_key_fields),
            "edm_key_fields": rel(self.edm_key_fields),
            "micro_edm_key_fields": rel(self.micro_edm_key_fields),
        }


def _first_existing(root: Path, *rels: str) -> Optional[Path]:
    for rel in rels:
        p = root / rel
        if p.is_file():
            return p
    return None


@lru_cache
def get_template_pack(version: str = "2026Q2") -> TemplatePack:
    settings = get_settings()
    root = settings.asset_root / "docs" / "templates" / version
    return TemplatePack(
        version=version,
        root=root,
        logo=_first_existing(root, "logo/bayer_logo.png", "logo/bayer_logo.jpg"),
        name_card=_first_existing(root, "lecture_hall/name_card_one_roi.jpg"),
        handbook_current=_first_existing(
            root, "lecture_hall/handbook_cover_current.jpg"
        ),
        handbook_stale=_first_existing(
            root, "lecture_hall/handbook_cover_stale_neg.jpg"
        ),
        equity1_ribbon=_first_existing(
            root, "micro/equity1_colorful_ribbon_crop.jpg"
        ),
        equity1_full=_first_existing(root, "micro/equity1_screen_full.jpg"),
        equity2_agenda=_first_existing(
            root, "micro/equity2_agenda_table_crop.jpg"
        ),
        equity2_full=_first_existing(root, "micro/equity2_screen_full.jpg"),
        poster_key_fields=_first_existing(
            root, "lecture_hall/poster_key_fields_crop.jpg"
        ),
        edm_key_fields=_first_existing(
            root,
            "lecture_hall/edm_key_fields_crop.jpg",
            "lecture_hall/poster_key_fields_crop.jpg",
        ),
        micro_edm_key_fields=_first_existing(
            root, "micro/edm_key_fields_crop.jpg"
        ),
    )


def pack_version_from_refs(refs: Optional[dict]) -> str:
    if refs and refs.get("template_pack_version"):
        return str(refs["template_pack_version"])
    return "2026Q2"
