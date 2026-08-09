"""
Stage 4 — Judge (AI/ML API)

Compares claimed fields against Bright Data evidence and produces the
contradiction table verdicts.

Runs on AI/ML API, the same key as Stage 2 — the hackathon grants one
provider key, either AI/ML API or Featherless, and this build uses AI/ML
API. There is no Featherless dependency anywhere in this codebase.

The brief's compliance argument still holds and is still worth making in
the writeup: insurers can't send claimant PII to a closed model they can't
audit or self-host, so judgment should run on **open weights**. That's a
property of the model, not the host — set AIML_JUDGE_MODEL to an
open-weight model from the AI/ML catalog (the Kimi K2, Llama, Qwen and
DeepSeek families all qualify; confirm the exact id against their catalog)
and the argument is intact. Just don't let this stage quietly end up on a
closed model, because then the compliance story is gone.

Runs exactly once per call, so it's cheap; the care here is about not
trusting the model's output shape. Claimed values and source URLs come from
OUR pair data, never from the model's echo of it — a model paraphrasing
"AED 12,000" into "12000 AED" would otherwise land in the dossier as the
claimant's own words.
"""
import json
import logging

from app.config import settings
from app.llm import chat_json
from app.models import ExtractedField, EvidenceResult, ContradictionFinding, Verdict

logger = logging.getLogger("adjudicate")

MAX_OUTPUT_TOKENS = 1200
TIMEOUT_S = 45.0

JUDGE_PROMPT = """You are the judgment stage of an insurance FNOL fraud-triage system. You are \
given claimed fields from a claimant's statement and evidence gathered from public sources \
about each one. For each claimed/evidence pair, decide a verdict.

Verdicts (use EXACTLY these strings):
- CONTRADICTED: evidence directly conflicts with what was claimed
- SUSPICIOUS: evidence raises a red flag without directly conflicting (e.g. a business with no
  track record)
- OVERSTATED: a claimed value is higher than evidence supports — include the percentage in
  "detail", e.g. "15%"
- CANNOT_DETERMINE: no reliable evidence was found either way. This is a valid, expected
  outcome — DO NOT guess a verdict just to avoid it.
- CONSISTENT: evidence supports what was claimed, no issue

Rules:
- Never invent evidence beyond what's given to you.
- If an evidence_summary looks like a placeholder or stub (e.g. contains "[STUB]"), you MUST
  return CANNOT_DETERMINE for that pair — a stub is not evidence.
- Return exactly one finding per input pair, and copy field_name back verbatim.
- Output ONLY valid JSON, no prose, no markdown fences. Shape:
  {"findings": [{"field_name": "...", "evidence_value": "...", "verdict": "...",
  "detail": "..." or null, "confidence": 0.0}]}
"""


def _parse_verdict(raw) -> Verdict:
    try:
        return Verdict(str(raw).strip().upper())
    except ValueError:
        # An unknown verdict string used to raise here and take the whole
        # dossier down with it, after the call had already ended.
        logger.warning("judge returned unknown verdict %r — treating as CANNOT_DETERMINE", raw)
        return Verdict.CANNOT_DETERMINE


def _coerce_confidence(value) -> float:
    try:
        return min(max(float(value), 0.0), 1.0)
    except (TypeError, ValueError):
        return 0.5


async def judge(
    claim_id: str, fields: list[ExtractedField], evidence: list[EvidenceResult]
) -> list[ContradictionFinding]:
    field_values = {f.field_name: f.field_value for f in fields}

    pairs: dict[str, dict] = {}
    for ev in evidence:
        # EvidenceResult.claimed_value is the proposition actually checked
        # ("hail on 2024-03-04 at Sharjah"), which is what the judge needs to
        # rule on. The bare extracted field value is only a fallback — asking
        # "does this weather report contradict the string '2024-03-04'?" is
        # not a question with a meaningful answer.
        pairs[ev.field_name] = {
            "field_name": ev.field_name,
            "check": ev.query_type,
            "claimed_value": ev.claimed_value or field_values.get(ev.field_name, ""),
            "evidence_summary": ev.evidence_summary,
            "source_url": ev.source_url,
        }

    if not pairs:
        return []

    parsed = await chat_json(
        model=settings.aiml_judge_model,
        system=JUDGE_PROMPT,
        user=json.dumps(list(pairs.values())),
        max_tokens=MAX_OUTPUT_TOKENS,
        timeout=TIMEOUT_S,
        stage="judge",
    )

    findings: list[ContradictionFinding] = []
    for item in parsed.get("findings", []):
        if not isinstance(item, dict):
            continue
        pair = pairs.get(item.get("field_name"))
        if pair is None:
            logger.warning("judge invented a field we never checked: %r", item.get("field_name"))
            continue
        findings.append(
            ContradictionFinding(
                claim_id=claim_id,
                field_name=pair["field_name"],
                claimed_value=pair["claimed_value"],     # ours, not the model's paraphrase
                evidence_value=str(item.get("evidence_value") or pair["evidence_summary"]),
                verdict=_parse_verdict(item.get("verdict")),
                detail=item.get("detail"),
                source_url=pair["source_url"],
                confidence=_coerce_confidence(item.get("confidence")),
            )
        )
    return findings
