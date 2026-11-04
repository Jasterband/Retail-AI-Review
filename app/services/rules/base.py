from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RuleOutcome:
    rule_code: str
    status: str  # PASS | FAIL | SKIP | UNCERTAIN
    passed: Optional[bool] = None
    confidence: Optional[float] = None
    trigger_human: bool = False
    reason_code: Optional[str] = None
    reason_text: Optional[str] = None
    evidence: Optional[Dict[str, Any]] = None
    related_asset_ids: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_code": self.rule_code,
            "passed": self.passed,
            "status": self.status,
            "confidence": self.confidence,
            "trigger_human": self.trigger_human,
            "reason_code": self.reason_code,
            "reason_text": self.reason_text,
            "evidence": self.evidence or {},
            "related_asset_ids": self.related_asset_ids,
        }


def skip(code: str, text: str = "不适用或材料缺失", related: Optional[List[int]] = None) -> RuleOutcome:
    return RuleOutcome(
        rule_code=code,
        status="SKIP",
        passed=None,
        reason_text=text,
        related_asset_ids=related or [],
    )


def pass_(
    code: str,
    text: str,
    conf: float = 0.9,
    related: Optional[List[int]] = None,
    evidence: Optional[dict] = None,
) -> RuleOutcome:
    return RuleOutcome(
        rule_code=code,
        status="PASS",
        passed=True,
        confidence=conf,
        reason_text=text,
        related_asset_ids=related or [],
        evidence=evidence,
    )


def fail(
    code: str,
    reason_code: str,
    text: str,
    conf: float = 0.9,
    related: Optional[List[int]] = None,
    evidence: Optional[dict] = None,
) -> RuleOutcome:
    return RuleOutcome(
        rule_code=code,
        status="FAIL",
        passed=False,
        confidence=conf,
        reason_code=reason_code,
        reason_text=text,
        related_asset_ids=related or [],
        evidence=evidence,
    )


def uncertain(
    code: str,
    reason_code: str,
    text: str,
    conf: float = 0.5,
    related: Optional[List[int]] = None,
    evidence: Optional[dict] = None,
) -> RuleOutcome:
    return RuleOutcome(
        rule_code=code,
        status="UNCERTAIN",
        passed=None,
        confidence=conf,
        trigger_human=True,
        reason_code=reason_code,
        reason_text=text,
        related_asset_ids=related or [],
        evidence=evidence,
    )
