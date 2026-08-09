"""
Shared helper for getting JSON back out of an LLM response.

Both LLM stages ask for strict JSON and both occasionally get a markdown
fence or a sentence of prose wrapped around it anyway. A parse failure must
never take down a live call — this returns {} and lets the caller carry on
with whatever it already has, which for a demo is always better than a 500
in the middle of the pipeline.
"""
import json
import logging
import re

logger = logging.getLogger("adjudicate")

_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(raw: str) -> dict:
    """Best-effort JSON object out of raw model text. Never raises."""
    if not raw:
        return {}

    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        # Last resort: the outermost {...} in the response, ignoring any
        # lead-in prose the model added despite being told not to.
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            logger.warning("LLM response contained no JSON object: %.200s", raw)
            return {}
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("LLM response was unparseable JSON: %.200s", raw)
            return {}

    return parsed if isinstance(parsed, dict) else {}
