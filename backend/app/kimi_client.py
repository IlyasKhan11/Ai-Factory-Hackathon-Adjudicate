"""
Stage 2 — Understand (AI/ML API, Kimi K2.6)

Turns messy live-call transcript text into the boring, checkable fields
Stage 3 needs. Fires only on *finalized* transcript segments (never on
partials), and only when enough new speech has accumulated — main.py owns
that throttle, see config.extraction_* for why it matters to the credit
budget.

Deliberately built on the same pattern as your OLS thesis pipeline's
kimi_client.py: cumulative transcript sent each call (lets the model catch
corrections like "actually it was the 4th, not the 3rd"), strict JSON out,
confidence per field, nothing invented.

Never raises on a bad model response — a malformed JSON blob costs you the
fields from one turn, not the call.
"""
import logging

from app.config import settings
from app.llm import chat_json
from app.models import ExtractedField

logger = logging.getLogger("adjudicate")

FIELD_SCHEMA = ["date", "location", "vehicle", "cause", "injuries", "stated_damage", "repair_shop"]

# The schema above is 7 short fields; anything beyond this is the model
# padding, and padding is billed. Caps the output side of the credit spend.
MAX_OUTPUT_TOKENS = 700

# Below this there is nothing extractable ("Hello?" / "Can you hear me?"),
# so don't spend a call finding that out.
MIN_TRANSCRIPT_CHARS = 40

EXTRACTION_PROMPT = """You are the field-extraction stage of an insurance FNOL (First Notice \
of Loss) intake system. You read a live call transcript between an adjuster and a claimant and \
pull out the following fields, and ONLY these fields, when the claimant has actually stated them:

- date: date of loss, normalized to YYYY-MM-DD if a specific date is determinable
- location: where the incident happened
- vehicle: year/make/model of the vehicle involved
- cause: what caused the damage/loss (a few words, e.g. "hail", "rear collision", "theft")
- injuries: "none claimed" or a short description
- stated_damage: the amount the claimant states, with currency
- repair_shop: name of any repair shop mentioned

Rules:
- Only include a field if the claimant (or the adjuster relaying claimant info) actually said
  it. Do not infer or guess unstated fields.
- Give each field a confidence 0-1 reflecting how explicit and unambiguous the statement was.
- If speech is garbled or has false starts, lower confidence rather than guessing the "clean"
  intended version.
- Output ONLY valid JSON, no prose, no markdown fences. Shape:
  {"fields": [{"field_name": "...", "field_value": "...", "confidence": 0.0}]}
- Return every field you can support from the transcript so far, including ones you returned
  before — the caller keeps the latest value per field, so a corrected value simply replaces
  the earlier one.
"""


def _coerce_confidence(value) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.5


async def extract_fields(session_id: str, cumulative_transcript: str) -> list[ExtractedField]:
    if len(cumulative_transcript.strip()) < MIN_TRANSCRIPT_CHARS:
        return []

    parsed = await chat_json(
        model=settings.aiml_kimi_model,
        system=EXTRACTION_PROMPT,
        user=cumulative_transcript,
        max_tokens=MAX_OUTPUT_TOKENS,
        stage="extract",
    )

    fields: list[ExtractedField] = []
    for f in parsed.get("fields", []):
        if not isinstance(f, dict) or f.get("field_name") not in FIELD_SCHEMA:
            continue  # ignore anything outside the agreed schema
        value = f.get("field_value")
        if value in (None, ""):
            continue
        fields.append(
            ExtractedField(
                session_id=session_id,
                field_name=f["field_name"],
                field_value=str(value),
                confidence=_coerce_confidence(f.get("confidence")),
            )
        )
    return fields
