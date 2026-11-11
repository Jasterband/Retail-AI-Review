"""药师大讲堂专用规则。"""

from __future__ import annotations

import re
from typing import List, Optional

from app.config import get_settings
from app.services.pipeline.asset_context import AssetContext
from app.services.rules.base import RuleOutcome, fail, pass_, skip, uncertain
from app.services.text_norm import name_set_equal, normalize_topic


def rule_name_card_speaker(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    cards = [c for c in contexts if c.photo_type == "TableCard" and c.ok]
    if not cards:
        return skip("NAME_CARD_SPEAKER_MATCH", "无台卡")
    mode = (options or {}).get("name_match_mode", "fuzzy")
    form_names = [s["speaker_name"] for s in form.get("speakers") or []]
    # merge names from all cards
    ocr_names = []
    related = []
    for c in cards:
        related.append(c.photo_id)
        names = c.vision.get("name_card_names") or c.ocr_fields().get("speaker_names") or []
        ocr_names.extend(names)

    cmp = name_set_equal(ocr_names, form_names, mode)
    if cmp["ok"]:
        return pass_(
            "NAME_CARD_SPEAKER_MATCH",
            "台卡姓名与系统讲者一致（{0}）".format("、".join(form_names)),
            related=related,
            evidence=cmp,
        )
    # high confidence fail if we got some names
    if not ocr_names:
        return uncertain(
            "NAME_CARD_SPEAKER_MATCH",
            "OCR_LOW_CONFIDENCE",
            "台卡未识别到姓名",
            related=related,
            evidence=cmp,
        )
    parts = []
    if cmp["missing"]:
        parts.append("缺少" + "、".join(cmp["missing"]))
    if cmp["extra"]:
        parts.append("多出" + "、".join(cmp["extra"]))
    return fail(
        "NAME_CARD_SPEAKER_MATCH",
        "NAME_SET_MISMATCH",
        "台卡缺少讲者「{0}」".format("、".join(cmp["missing"]))
        if cmp["missing"] and not cmp["extra"]
        else "台卡姓名集合与系统讲者不一致：" + "；".join(parts),
        related=related,
        evidence=cmp,
    )


def rule_handbook_detect(contexts: List[AssetContext]) -> RuleOutcome:
    books = [c for c in contexts if c.photo_type == "Manual"]
    if not books:
        return fail(
            "HANDBOOK_DETECT",
            "ASSET_MISSING",
            "缺少必审手册材料",
            related=[],
        )
    ok_books = [c for c in books if c.ok]
    if not ok_books:
        return fail(
            "HANDBOOK_DETECT",
            "HANDBOOK_NOT_FOUND",
            "手册材料不可读",
            related=[c.photo_id for c in books],
        )
    evidence = []
    for c in ok_books:
        tm = (c.template_match or {}).get("handbook_current") or {}
        # 类型已由 PE 声明为 Manual；是否像手册封面看 handbook_ok / 模版命中
        hit = bool(tm.get("hit")) or bool(c.vision.get("handbook_ok"))
        evidence.append(
            {
                "photo_id": c.photo_id,
                "photo_type": c.photo_type,
                "template_match": tm or None,
                "handbook_ok": c.vision.get("handbook_ok"),
                "hit": hit,
            }
        )
        if hit:
            return pass_(
                "HANDBOOK_DETECT",
                "识别到当期宣传手册",
                related=[c.photo_id],
                evidence={"rows": evidence},
            )
    return fail(
        "HANDBOOK_DETECT",
        "HANDBOOK_NOT_FOUND",
        "未识别为宣传手册封面",
        related=[c.photo_id for c in ok_books],
        evidence={"rows": evidence},
    )


def _extract_handbook_year(c: AssetContext) -> Optional[int]:
    """从 vision / OCR 文本里抽封面年份。"""
    candidates = []
    for key in ("handbook_year",):
        v = c.vision.get(key)
        if v is not None:
            candidates.append(v)
    of = c.ocr_fields()
    for key in ("handbook_year", "meeting_date"):
        v = of.get(key)
        if v is not None:
            candidates.append(v)

    for raw in candidates:
        if isinstance(raw, int) and 2000 <= raw <= 2100:
            return raw
        if isinstance(raw, float) and 2000 <= int(raw) <= 2100:
            return int(raw)
        s = str(raw)
        m = re.search(r"(20\d{2})", s)
        if m:
            return int(m.group(1))
    return None


def rule_handbook_not_stale(contexts: List[AssetContext]) -> RuleOutcome:
    """无旧版负样本时：封面年份须为当期年（默认 2026）。"""
    books = [c for c in contexts if c.photo_type == "Manual"]
    if not books:
        return fail(
            "HANDBOOK_NOT_STALE",
            "ASSET_MISSING",
            "缺少必审手册材料",
            related=[],
        )
    ok_books = [c for c in books if c.ok]
    if not ok_books:
        return fail(
            "HANDBOOK_NOT_STALE",
            "HANDBOOK_NOT_FOUND",
            "手册材料不可读",
            related=[c.photo_id for c in books],
        )

    need_year = int(get_settings().handbook_current_year)
    related = [c.photo_id for c in ok_books]
    evidence = []
    stale = []
    ok_ids = []
    uncs = []

    for c in ok_books:
        year = _extract_handbook_year(c)
        stale_tm = (c.template_match or {}).get("handbook_stale") or {}
        row = {
            "photo_id": c.photo_id,
            "handbook_year": year,
            "need_year": need_year,
            "handbook_stale": stale_tm or None,
        }
        evidence.append(row)

        # 若有旧版负样本且命中更强 → 直接旧版
        if stale_tm.get("hit"):
            stale.append(c.photo_id)
            continue

        if year is None:
            uncs.append(c.photo_id)
            continue
        if year == need_year:
            ok_ids.append(c.photo_id)
        else:
            stale.append(c.photo_id)

    if stale:
        return fail(
            "HANDBOOK_NOT_STALE",
            "HANDBOOK_STALE",
            "手册封面年份不是{0}（疑似旧版）".format(need_year),
            related=stale,
            evidence={"rows": evidence},
        )
    if ok_ids and not uncs:
        return pass_(
            "HANDBOOK_NOT_STALE",
            "手册封面年份为{0}".format(need_year),
            related=related,
            evidence={"rows": evidence},
        )
    return uncertain(
        "HANDBOOK_NOT_STALE",
        "OCR_LOW_CONFIDENCE",
        "手册封面年份识别不清",
        related=uncs or related,
        evidence={"rows": evidence},
    )


def rule_speaker_topic_ocr(
    contexts: List[AssetContext], form: dict, options: dict
) -> RuleOutcome:
    speakers = {s["speaker_id"]: s for s in form.get("speakers") or []}
    photos = [
        c
        for c in contexts
        if c.photo_type == "SpeakerTitle" and c.ok
    ]
    if not photos:
        return skip("SPEAKER_TOPIC_OCR", "无标题合影")

    fails = []
    uncs = []
    related = []
    for c in photos:
        related.append(c.photo_id)
        sp = speakers.get(c.speaker_id)
        if not sp:
            continue
        expected = normalize_topic(sp.get("topic") or "")
        of = c.ocr_fields()
        got = normalize_topic(of.get("topic_title") or "")
        if not got:
            uncs.append(c.photo_id)
            continue
        if expected and got != expected:
            # allow containment
            if expected not in got and got not in expected:
                fails.append(
                    {
                        "photo_id": c.photo_id,
                        "expected": sp.get("topic"),
                        "got": of.get("topic_title"),
                    }
                )
    if fails:
        return fail(
            "SPEAKER_TOPIC_OCR",
            "TOPIC_MISMATCH",
            "课件标题与表单主题不一致",
            related=[f["photo_id"] for f in fails],
            evidence={"fails": fails},
        )
    if uncs and not fails:
        return uncertain(
            "SPEAKER_TOPIC_OCR",
            "OCR_LOW_CONFIDENCE",
            "讲者照标题识别不清",
            related=uncs,
        )
    return pass_(
        "SPEAKER_TOPIC_OCR",
        "讲者课件标题与表单主题一致",
        related=related,
    )


def rule_speaker_shot_pair(
    contexts: List[AssetContext], form: dict
) -> RuleOutcome:
    speakers = form.get("speakers") or []
    if not speakers:
        return skip("SPEAKER_SHOT_PAIR", "无讲者")
    photos = [c for c in contexts if c.photo_type in ("SpeakerTitle", "SpeakerLecture")]
    missing = []
    related = [c.photo_id for c in photos]
    for sp in speakers:
        sid = sp["speaker_id"]
        kinds = {
            c.photo_type
            for c in photos
            if c.speaker_id == sid and c.ok
        }
        need = {"SpeakerTitle", "SpeakerLecture"}
        if not need.issubset(kinds):
            missing.append(
                {
                    "speaker_id": sid,
                    "speaker_name": sp.get("speaker_name"),
                    "have": list(kinds),
                }
            )
    if missing:
        return fail(
            "SPEAKER_SHOT_PAIR",
            "ASSET_MISSING",
            "讲者缺标题合影或授课照: "
            + ", ".join(m["speaker_name"] or str(m["speaker_id"]) for m in missing),
            related=related,
            evidence={"missing": missing},
        )
    return pass_(
        "SPEAKER_SHOT_PAIR",
        "每位讲者均有标题合影与授课照",
        related=related,
    )
