"""
Shared LLM client — AI/ML API (https://aimlapi.com).

The hackathon grants ONE provider key, either AI/ML API or Featherless, not
both. This build uses AI/ML API, so both LLM stages go through here:
Stage 2 (understand / extract fields) and Stage 4 (judge / contradictions).
The API is OpenAI-compatible, so this is a thin POST to
{base}/chat/completions with a Bearer key.

Every paid token in this pipeline flows through this one function, which
makes it the single place to cap spend, log usage, or swap models if
credits run low.
"""
import logging

import httpx

from app.config import settings
from app.llm_json import parse_json_object

logger = logging.getLogger("adjudicate")


async def chat_json(
    *,
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    timeout: float = 30.0,
    stage: str = "llm",
) -> dict:
    """
    One chat completion, parsed as a JSON object. Returns {} rather than
    raising when the model ignores the "JSON only" instruction — a bad
    response should cost one stage's output, never the whole call.

    Raises only on transport/HTTP errors, which callers treat as stage
    failures.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(
            f"{settings.aiml_api_base}/chat/completions",
            headers={"Authorization": f"Bearer {settings.aiml_api_key}"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": 0,
                "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    # Credit visibility: with one shared budget across both stages, you want
    # to see what each call actually cost while testing.
    usage = data.get("usage") or {}
    if usage:
        logger.info(
            "%s [%s]: %s tokens (prompt %s / completion %s)",
            stage, model, usage.get("total_tokens"),
            usage.get("prompt_tokens"), usage.get("completion_tokens"),
        )

    choices = data.get("choices") or []
    if not choices:
        logger.warning("%s: response had no choices: %.200s", stage, data)
        return {}

    return parse_json_object(choices[0].get("message", {}).get("content", ""))
