"""将存库的 full 响应投影为 simple / full。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Literal


def project_response(
    full: Dict[str, Any],
    mode: Literal["simple", "full"],
) -> Dict[str, Any]:
    out = deepcopy(full)
    out["response_mode"] = mode

    if mode == "full":
        return out

    out.pop("debug", None)
    out.pop("overall_confidence", None)
    out.pop("model_version", None)
    out.pop("template_pack_version", None)

    assets = []
    for a in out.get("asset_results") or []:
        assets.append(
            {
                "asset_id": a["asset_id"],
                "declared_type": a["declared_type"],
                "asset_status": a["asset_status"],
                "fail_reasons": a.get("fail_reasons") or [],
            }
        )
    out["asset_results"] = assets

    rules = []
    for r in out.get("rule_results") or []:
        rules.append(
            {
                "rule_code": r["rule_code"],
                "passed": r.get("passed"),
                "status": r["status"],
                "reason_code": r.get("reason_code"),
                "reason_text": r.get("reason_text"),
                "related_asset_ids": r.get("related_asset_ids") or [],
            }
        )
    out["rule_results"] = rules
    return out
