"""
Offline pipeline check — makes ZERO API calls, spends ZERO credits.

Covers everything between Stage 2's output and the dossier: which lookups
the dispatcher decides to run, what the judge would be asked, how malformed
model output is handled, and how findings score. Run it after touching
dispatcher.py, scoring.py, llm_json.py or the EvidenceResult shape.

    python smoke_test.py

Needs only pydantic + python-dotenv, so it works before Speechmatics or
Supabase are configured.
"""
import asyncio

from app.llm_json import parse_json_object
from app.models import ContradictionFinding, ExtractedField, Verdict
from app.scoring import score_dossier
from app.verification.dispatcher import dispatch_lookups

SESSION = "smoke-session"

# The exact demo claim from the mockup: hail / Corolla / Al Noor Auto Works.
DEMO_FIELDS = [
    ExtractedField(session_id=SESSION, field_name="date", field_value="2024-03-04", confidence=0.9),
    ExtractedField(session_id=SESSION, field_name="location", field_value="Sharjah", confidence=0.8),
    ExtractedField(session_id=SESSION, field_name="cause", field_value="hail", confidence=0.95),
    ExtractedField(session_id=SESSION, field_name="vehicle", field_value="2019 Toyota Corolla", confidence=0.9),
    ExtractedField(session_id=SESSION, field_name="stated_damage", field_value="AED 12,000", confidence=0.85),
    ExtractedField(session_id=SESSION, field_name="repair_shop", field_value="Al Noor Auto Works", confidence=0.8),
]


def check_dispatch() -> None:
    """Dynamic branching: a hail claim must NOT trigger the news/theft lookup."""
    print("== Stage 3 dispatch (hail claim)")
    evidence = asyncio.run(dispatch_lookups(DEMO_FIELDS))
    for e in evidence:
        print(f"   {e.query_type:18} field={e.field_name:14} checked: {e.claimed_value!r}")

    kinds = {e.query_type for e in evidence}
    assert "weather" in kinds, "hail must trigger the weather lookup"
    assert "news" not in kinds, "hail must NOT trigger the news lookup — that's the theft/collision branch"
    print(f"   -> {len(evidence)} lookups, news branch correctly skipped\n")

    print("== what Stage 4 gets asked to judge")
    for e in evidence:
        # This must be the proposition, not the bare field value: judging
        # "does this weather report contradict '2024-03-04'?" is meaningless.
        print(f"   {e.field_name:14} -> {e.claimed_value!r}")
    print()


def check_json_parsing() -> None:
    """A model that ignores 'JSON only' must never crash the pipeline."""
    print("== LLM output robustness")
    cases = [
        ('clean json', '{"fields": [{"field_name": "date", "field_value": "2024-03-04"}]}', True),
        ('markdown fenced', '```json\n{"fields": []}\n```', True),
        ('prose lead-in', 'Sure! Here you go:\n{"fields": []}', True),
        ('refusal', 'I cannot help with that.', False),
        ('empty', '', False),
    ]
    for label, raw, should_parse in cases:
        result = parse_json_object(raw)
        ok = ("fields" in result) is should_parse
        print(f"   {'OK ' if ok else 'FAIL'} {label:16} -> {result}")
        assert ok, f"{label} parsed unexpectedly"
    print()


def check_scoring() -> None:
    print("== Stage 5 scoring")

    def findings(*verdicts):
        return [
            ContradictionFinding(
                claim_id="smoke", field_name=f"field_{i}", claimed_value="x",
                evidence_value="y", verdict=v, confidence=0.8,
            )
            for i, v in enumerate(verdicts)
        ]

    cases = [
        ("all stubbed (today)", findings(*[Verdict.CANNOT_DETERMINE] * 4)),
        ("one contradiction", findings(Verdict.CONTRADICTED, Verdict.CONSISTENT)),
        ("contradicted+overstated", findings(Verdict.CONTRADICTED, Verdict.OVERSTATED, Verdict.CANNOT_DETERMINE)),
        ("all clean", findings(Verdict.CONSISTENT, Verdict.CONSISTENT)),
        ("nothing extracted", []),
    ]
    for label, f in cases:
        d = score_dossier("smoke", f)
        print(f"   {label:24} score={d.risk_score:3}  {d.risk_tier.value:11}  {d.summary}")

    # Unresolved checks must not stack into a fake risk signal.
    stubbed = score_dossier("smoke", findings(*[Verdict.CANNOT_DETERMINE] * 8))
    assert stubbed.risk_tier.value == "fast_track", "8 unresolved checks should not imply risk"
    print()


if __name__ == "__main__":
    check_dispatch()
    check_json_parsing()
    check_scoring()
    print("All offline checks passed — no credits spent.")
