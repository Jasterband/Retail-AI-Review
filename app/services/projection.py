"""将存库的 full 响应投影为 PE（AI_接口文档v2）或内部 full。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Literal, Optional

from app.services.reason_comments import comments_for_reason_code

# v2 §7 对外系统码只保留这两类；其余模型/损坏类收口为 INTERNAL_ERROR
_PE_SYSTEM_CODE_MAP = {
    "S3_NOT_FOUND": "S3_NOT_FOUND",
    "S3_CORRUPT": "INTERNAL_ERROR",
    "MODEL_TIMEOUT": "INTERNAL_ERROR",
    "MODEL_UNAVAILABLE": "INTERNAL_ERROR",
    "INTERNAL_ERROR": "INTERNAL_ERROR",
}


def _map_system_error(error: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not error or not isinstance(error, dict):
        return None
    raw = str(error.get("code") or "INTERNAL_ERROR")
    code = _PE_SYSTEM_CODE_MAP.get(raw, "INTERNAL_ERROR")
    return {
        "code": code,
        "message": error.get("message") or code,
        "retryable": bool(error.get("retryable", code == "INTERNAL_ERROR")),
    }


def _pe_photo_status(raw: Optional[str]) -> Optional[str]:
    """内部 UNCERTAIN → PE NEED_HUMAN；PASS 不下发。"""
    if raw in ("FAIL", "ERROR", "NEED_HUMAN"):
        return raw
    if raw == "UNCERTAIN":
        return "NEED_HUMAN"
    return None


def project_pe_response(full: Dict[str, Any]) -> Dict[str, Any]:
    """AI_接口文档v2：flagged_photos + overall_status；ERROR 时 flagged 为空。"""
    overall = full.get("overall_status") or "ERROR"
    out: Dict[str, Any] = {
        "task_id": full["task_id"],
        "meeting_id": full["meeting_id"],
        "overall_status": overall,
        "flagged_photos": [],
    }

    if overall == "ERROR":
        mapped = _map_system_error(full.get("error"))
        if mapped:
            out["error"] = mapped
        else:
            out["error"] = {
                "code": "INTERNAL_ERROR",
                "message": "internal error",
                "retryable": True,
            }
        return out

    if full.get("error") is not None:
        mapped = _map_system_error(full.get("error"))
        if mapped:
            out["error"] = mapped

    flagged = []
    for a in full.get("photo_results") or []:
        pe_status = _pe_photo_status(a.get("photo_status"))
        if not pe_status:
            continue
        reasons = []
        for fr in a.get("fail_reasons") or []:
            if not isinstance(fr, dict):
                continue
            code = fr.get("reason_code")
            item: Dict[str, Any] = {"reason_code": code}
            if pe_status != "ERROR":
                comments = comments_for_reason_code(
                    code,
                    photo_type_name=a.get("photo_type_name") or a.get("photoTypeName"),
                    photo_type=a.get("photo_type") or a.get("photoType"),
                )
                if comments:
                    item["comments"] = comments
            reasons.append(item)
        flagged.append(
            {
                "photo_id": a["photo_id"],
                "photo_status": pe_status,
                "fail_reasons": reasons,
            }
        )
    out["flagged_photos"] = flagged
    return out


def project_response(
    full: Dict[str, Any],
    mode: Literal["simple", "full", "pe"] = "pe",
) -> Dict[str, Any]:
    if mode == "full":
        out = deepcopy(full)
        out["response_mode"] = "full"
        return out
    # simple / pe：对外契约均为 v2 flagged_photos
    return project_pe_response(full)
