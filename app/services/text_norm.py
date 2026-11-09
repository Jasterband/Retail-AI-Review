"""姓名模糊匹配与主题归一化。"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set


def normalize_topic(text: str) -> str:
    if not text:
        return ""
    t = text.strip().lower()
    t = re.sub(r"[\s\u3000]+", "", t)
    t = re.sub(r"[，。、；：！？,.!?;:'\"「」『』（）()【】\[\]《》<>·…—\-_/\\]", "", t)
    return t


def _as_name_text(name: object) -> str:
    if name is None:
        return ""
    if isinstance(name, str):
        return name
    if isinstance(name, dict):
        for key in ("name", "speaker_name", "text", "value"):
            val = name.get(key)
            if isinstance(val, str) and val.strip():
                return val
        return ""
    return str(name)


def normalize_name(name: object) -> str:
    return re.sub(r"[\s\u3000]+", "", _as_name_text(name).strip())


def names_match(a: object, b: object, mode: str = "fuzzy") -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    if mode == "exact":
        return na == nb
    if na == nb:
        return True
    if abs(len(na) - len(nb)) <= 1 and (na in nb or nb in na):
        return True
    return False


def name_set_equal(ocr_names: Iterable[object], form_names: Iterable[object], mode: str) -> dict:
    ocr = [normalize_name(x) for x in ocr_names if normalize_name(x)]
    form = [normalize_name(x) for x in form_names if normalize_name(x)]
    matched_form: Set[str] = set()
    matched_ocr: Set[str] = set()
    for fn in form:
        for on in ocr:
            if on in matched_ocr:
                continue
            if names_match(fn, on, mode):
                matched_form.add(fn)
                matched_ocr.add(on)
                break
    missing = [n for n in form if n not in matched_form]
    extra = [n for n in ocr if n not in matched_ocr]
    return {
        "ok": not missing and not extra and len(form) > 0,
        "missing": missing,
        "extra": extra,
        "names_ocr": list(ocr),
        "names_form": list(form),
    }


def fuzzy_contains(haystack: str, needle: str) -> bool:
    h = normalize_topic(haystack)
    n = normalize_topic(needle)
    if not h or not n:
        return False
    return n in h or h in n


def date_equal(a: Optional[str], b: Optional[str]) -> bool:
    def ymd(x: str) -> str:
        m = re.search(r"(\d{4})\D*?(\d{1,2})\D*?(\d{1,2})", x or "")
        if m:
            return "{0}{1:02d}{2:02d}".format(
                m.group(1), int(m.group(2)), int(m.group(3))
            )
        digits = re.sub(r"\D", "", x or "")
        return digits[:8] if len(digits) >= 8 else digits

    da, db = ymd(a or ""), ymd(b or "")
    if len(da) >= 8 and len(db) >= 8:
        return da[:8] == db[:8]
    return bool(da) and bool(db) and da == db


def time_to_minutes(t: Optional[str]) -> Optional[int]:
    if not t:
        return None
    m = re.search(r"(\d{1,2})\s*[:：点]\s*(\d{2})?", str(t))
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    digits = re.sub(r"\D", "", str(t))
    if len(digits) >= 3:
        if len(digits) == 3:
            return int(digits[0]) * 60 + int(digits[1:])
        return int(digits[:2]) * 60 + int(digits[2:4])
    return None


def parse_time_pair(
    start: Optional[str], end: Optional[str] = None
) -> tuple[Optional[int], Optional[int]]:
    """解析起止时间；支持单字段「14:00-16:10」或「14:00至16:10」。"""
    st = time_to_minutes(start)
    et = time_to_minutes(end)
    if et is None and start:
        m = re.search(
            r"(\d{1,2}\s*[:：点]\s*\d{0,2}).{0,6}?(\d{1,2}\s*[:：点]\s*\d{0,2})",
            str(start),
        )
        if m:
            st = time_to_minutes(m.group(1))
            et = time_to_minutes(m.group(2))
    return st, et


def duration_minutes_from_times(
    start: Optional[str],
    end: Optional[str] = None,
    duration: Optional[object] = None,
) -> Optional[int]:
    if duration is not None:
        try:
            return int(duration)
        except (TypeError, ValueError):
            pass
    st, et = parse_time_pair(start, end)
    if st is None or et is None:
        return None
    if et >= st:
        return et - st
    return et + 24 * 60 - st
