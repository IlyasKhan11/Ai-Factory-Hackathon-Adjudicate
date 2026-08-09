"""
Turns a list of ContradictionFinding into the single risk_score + risk_tier
the Dossier screen needs. Deliberately simple, explainable weighting — a
judge should be able to see why a score landed where it did, and that
matters more here than sophistication.
"""
from app.models import ContradictionFinding, Verdict, RiskTier, ClaimDossier

VERDICT_WEIGHT = {
    Verdict.CONTRADICTED: 35,
    Verdict.SUSPICIOUS: 20,
    Verdict.OVERSTATED: 15,
    Verdict.CANNOT_DETERMINE: 5,  # unresolved isn't nothing, but isn't guilt either
    Verdict.CONSISTENT: 0,
}

# "We couldn't check it" must not stack into a fake signal. Without this cap,
# a claim that happened to trigger four lookups and resolve none of them
# out-scores a claim with one real red flag — and with Bright Data stubbed,
# EVERY claim currently lands in that state.
UNRESOLVED_CONTRIBUTION_CAP = 10


def score_dossier(claim_id: str, findings: list[ContradictionFinding]) -> ClaimDossier:
    unresolved = [f for f in findings if f.verdict is Verdict.CANNOT_DETERMINE]
    flagged = [f for f in findings if f.verdict not in (Verdict.CONSISTENT, Verdict.CANNOT_DETERMINE)]

    resolved_score = sum(VERDICT_WEIGHT[f.verdict] for f in flagged)
    unresolved_score = min(
        UNRESOLVED_CONTRIBUTION_CAP, VERDICT_WEIGHT[Verdict.CANNOT_DETERMINE] * len(unresolved)
    )
    risk_score = min(100, resolved_score + unresolved_score)

    if risk_score >= 60:
        tier = RiskTier.INVESTIGATE
    elif risk_score >= 25:
        tier = RiskTier.STANDARD
    else:
        tier = RiskTier.FAST_TRACK

    if flagged:
        summary = f"{len(flagged)} finding(s) flagged: " + "; ".join(
            f"{f.field_name} ({f.verdict.value})" for f in flagged
        )
        if unresolved:
            summary += f". {len(unresolved)} further check(s) unresolved."
    elif unresolved:
        # Distinguish "checked and clean" from "never actually checked" — with
        # stubbed evidence this is the honest thing for the Dossier screen to say.
        summary = f"No contradictions found. {len(unresolved)} check(s) could not be resolved against available evidence."
    elif findings:
        summary = "No contradictions found against available evidence."
    else:
        summary = "No checks were run — no verifiable fields were extracted from this call."

    return ClaimDossier(claim_id=claim_id, risk_score=risk_score, risk_tier=tier, findings=findings, summary=summary)
