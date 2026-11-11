"""将存库的 full 响应投影为 simple / full。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Literal

from app.services.reason_comments import comments_for_reason_code


def project_response(
    full: Dict[str, Any],
    mode: Literal["simple", "full"],
) -> Dict[str, Any]:
    if mode == "full":
        out = deepcopy(full)
        out["response_mode"] = "full"
        return out

    # PE simple：整场结论 + 仅下发不合格/待人工/系统错误图；PASS 图不下发
    photos = []
    for a in full.get("photo_results") or []:
        photo_status = a.get("photo_status")
        if photo_status == "PASS":
            continue
        reasons = []
        for fr in a.get("fail_reasons") or []:
            if not isinstance(fr, dict):
                continue
            code = fr.get("reason_code")
            item: Dict[str, Any] = {"reason_code": code}
            # ERROR 图 / 系统错误码：不写 comments（用顶层 error）
            if photo_status != "ERROR":
                comments = comments_for_reason_code(
                    code,
                    photo_type_name=a.get("photo_type_name") or a.get("photoTypeName"),
                )
                if comments:
                    item["comments"] = comments
            reasons.append(item)
        photos.append(
            {
                "photo_id": a["photo_id"],
                "photo_status": photo_status,
                "fail_reasons": reasons,
            }
        )

    out: Dict[str, Any] = {
        "task_id": full["task_id"],
        "meeting_id": full["meeting_id"],
        "overall_status": full["overall_status"],
        "photo_results": photos,
    }
    if full.get("error") is not None:
        out["error"] = full["error"]
    return out
