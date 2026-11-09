"""将存库的 full 响应投影为 simple / full。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Literal


def project_response(
    full: Dict[str, Any],
    mode: Literal["simple", "full"],
) -> Dict[str, Any]:
    if mode == "full":
        out = deepcopy(full)
        out["response_mode"] = "full"
        return out

    # PE simple 最瘦：对齐 + 整场结论 + 按图 status/reason_code
    photos = []
    for a in full.get("photo_results") or []:
        reasons = [
            {"reason_code": fr.get("reason_code")}
            for fr in (a.get("fail_reasons") or [])
            if isinstance(fr, dict)
        ]
        photos.append(
            {
                "photo_id": a["photo_id"],
                "photo_status": a["photo_status"],
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
