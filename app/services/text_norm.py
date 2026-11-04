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


def normalize_name(name: str) -> str:
    return re.sub(r"[\s\u3000]+", "", (name or "").strip())


def names_match(a: str, b: str, mode: str = "fuzzy") -> bool:
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


def name_set_equal(ocr_names: Iterable[str], form_names: Iterable[str], mode: str) -> dict:
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
    def digits(x: str) -> str:
        return re.sub(r"\D", "", x or "")

    da, db = digits(a or ""), digits(b or "")
    if len(da) >= 8 and len(db) >= 8:
        return da[:8] == db[:8]
    return bool(da) and bool(db) and da == db


def time_to_minutes(t: Optional[str]) -> Optional[int]:
    if not t:
        return None
    m = re.search(r"(\d{1,2})\s*[:：点]\s*(\d{2})?", t)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2) or 0)
    digits = re.sub(r"\D", "", t)
    if len(digits) >= 3:
        if len(digits) == 3:
            return int(digits[0]) * 60 + int(digits[1:])
        return int(digits[:2]) * 60 + int(digits[2:4])
    return None
