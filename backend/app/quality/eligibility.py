"""Questionnaire evaluation — deterministic, independent of price.

A vendor's "yes" is not enough where evidence is required: the attached certificate is
read by the model, its expiry date is grounded in the document, and compared to the RFx
date here. Missing mandatory answers stay PENDING; they never auto-pass.
"""
from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, Field


class AnswerEvaluation(BaseModel):
    qid: str
    question: str
    mandatory: bool
    answer: Any = None
    status: str          # PASS / FAIL / PENDING / NOT_APPLICABLE / NEEDS_REVIEW
    reason: str
    evidence: Optional[dict[str, Any]] = None
    reviewer_comment: Optional[str] = None
    overridden: bool = False


class VendorEligibility(BaseModel):
    vendor_id: str
    status: str          # ELIGIBLE / INELIGIBLE / PENDING
    reasons: list[str] = Field(default_factory=list)
    quality_score: float = 0
    answers: list[AnswerEvaluation] = Field(default_factory=list)


def _rule(q: dict, ans: Any) -> tuple[str, str]:
    rule = q.get("pass_rule", {})
    if ans is None or ans == "":
        return "PENDING", "No answer submitted"
    if "equals" in rule:
        ok = ans == rule["equals"]
        return ("PASS", "Answered yes") if ok else ("FAIL", f"Answered {'no' if ans is False else ans!r}")
    try:
        v = float(ans)
    except (TypeError, ValueError):
        return "NEEDS_REVIEW", f"Non-numeric answer {ans!r}"
    if "max" in rule and v > rule["max"]:
        return "FAIL", f"{v:g} exceeds maximum {rule['max']}"
    if "min" in rule and v < rule["min"]:
        return "FAIL", f"{v:g} below minimum {rule['min']}"
    return "PASS", f"{v:g} meets requirement"


def evaluate_vendor(vendor_id: str, questionnaire: list[dict], answers: dict[str, Any], evidence: dict[str, dict],
                    reference_date: str, overrides: Optional[dict[str, dict]] = None,
                    review_below: float = 70) -> VendorEligibility:
    overrides = overrides or {}
    ref = date.fromisoformat(reference_date)
    evals: list[AnswerEvaluation] = []
    for q in questionnaire:
        ans = answers.get(q["qid"])
        status, reason = _rule(q, ans)
        ev = None
        need = q.get("pass_rule", {}).get("evidence")
        if need and status == "PASS":
            e = evidence.get(need)
            if not e:
                status, reason = "PENDING", "Answered yes, but no evidence document attached"
            elif e.get("status") == "AI_UNAVAILABLE":
                status, reason = "PENDING", "Evidence attached but not yet verified (AI extraction unavailable)"
                ev = e
            elif e.get("status") != "SUCCEEDED" or not e.get("valid_until"):
                status, reason = "NEEDS_REVIEW", "Evidence could not be read reliably"
                ev = e
            else:
                ev = e
                try:
                    vu = date.fromisoformat(e["valid_until"])
                except ValueError:
                    vu = None
                if vu is None:
                    status, reason = "NEEDS_REVIEW", f"Unparseable expiry date {e['valid_until']!r}"
                elif vu < ref:
                    status, reason = "FAIL", (f"Vendor answered yes, but the attached certificate expired on {vu:%d %b %Y} "
                                              f"(before RFx date {ref:%d %b %Y})")
                elif (e.get("confidence") or 100) < review_below:
                    status, reason = "NEEDS_REVIEW", f"Certificate valid until {vu:%d %b %Y}, but extraction confidence is low"
                else:
                    reason = f"Certificate {e.get('number') or ''} valid until {vu:%d %b %Y}".replace("  ", " ")
        o = overrides.get(q["qid"])
        ae = AnswerEvaluation(qid=q["qid"], question=q["text"], mandatory=q["mandatory"], answer=ans,
                              status=status, reason=reason, evidence=ev)
        if o and o.get("status"):
            ae.reviewer_comment = o.get("comment")
            if o["status"] != status:
                ae.reason = f"Reviewer set {o['status']} (system: {status} — {reason})"
                ae.status, ae.overridden = o["status"], True
        evals.append(ae)

    mand = [e for e in evals if e.mandatory]
    fails = [e for e in mand if e.status == "FAIL"]
    pend = [e for e in mand if e.status in ("PENDING", "NEEDS_REVIEW")]
    if fails:
        st = "INELIGIBLE"
        reasons = [f"{e.qid} FAIL — {e.reason}" for e in fails]
    elif pend:
        st = "PENDING"
        reasons = [f"{e.qid} {e.status} — {e.reason}" for e in pend]
    else:
        st, reasons = "ELIGIBLE", ["All mandatory requirements passed"]
    applicable = [e for e in evals if e.status != "NOT_APPLICABLE"]
    score = round(100 * sum(1 for e in applicable if e.status == "PASS") / max(1, len(applicable)), 1)
    return VendorEligibility(vendor_id=vendor_id, status=st, reasons=reasons, quality_score=score, answers=evals)
