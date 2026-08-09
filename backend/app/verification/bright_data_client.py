"""
Stage 3 — Go look (Bright Data client)

STUBBED. Each function's signature and return shape (EvidenceResult) is
final — only the internals need real HTTP calls swapped in once Bright
Data credentials are confirmed. Keeping the stub live (rather than raising)
means the rest of the pipeline — dispatcher, judgment, Supabase
writes, the frontend fields panel — is fully testable today.

The Judge stage (judgment/judge_client.py) already knows to return
CANNOT_DETERMINE whenever it sees an evidence_summary containing "[STUB]",
so running the whole pipeline right now correctly produces "cannot
determine" verdicts everywhere instead of silently fabricating findings.

*** Stubbing is controlled by BRIGHTDATA_USE_STUB, not by whether a key is
set. *** It used to key off `not settings.brightdata_api_key`, which meant
the moment anyone pasted a real BRIGHTDATA_API_KEY into .env — before a
single one of the four TODOs below was written — every lookup started
raising NotImplementedError and Stage 3 died. Having a credential and
having an implementation are different facts. Leave the flag on until the
TODOs are real, then flip it; it also lets you develop the rest of the
pipeline all day without spending Bright Data credits.
"""
import logging

from app.config import settings
from app.models import EvidenceResult

logger = logging.getLogger("adjudicate")

STUB_NOTE = "[STUB] Bright Data lookup not implemented yet — no evidence gathered"


def _use_stub() -> bool:
    """Checked per call, so the flag can't be baked in at import time."""
    if settings.brightdata_use_stub:
        return True
    if not settings.brightdata_api_key:
        logger.warning("BRIGHTDATA_USE_STUB is off but no API key is set — falling back to stub")
        return True
    return False


async def check_weather(date: str, location: str, claimed_cause: str) -> EvidenceResult:
    if _use_stub():
        return EvidenceResult(
            field_name="date",
            query_type="weather",
            claimed_value=f"{claimed_cause} on {date} at {location}",
            evidence_summary=STUB_NOTE,
        )
    # TODO: real Bright Data call — weather-archive dataset/scraper for `location` on `date`,
    # then compare against `claimed_cause` (e.g. hail/rain/snow recorded that day or not).
    raise NotImplementedError("Wire real Bright Data weather lookup here")


async def check_business(name: str) -> EvidenceResult:
    if _use_stub():
        return EvidenceResult(
            field_name="repair_shop",
            query_type="business_registry",
            claimed_value=name,
            evidence_summary=STUB_NOTE,
        )
    # TODO: real Bright Data call — business registry age + review-site presence for `name`.
    raise NotImplementedError("Wire real Bright Data business registry lookup here")


async def check_market_value(vehicle: str, stated_value: str) -> EvidenceResult:
    if _use_stub():
        return EvidenceResult(
            field_name="stated_damage",
            query_type="market_value",
            claimed_value=f"{stated_value} of damage to a {vehicle}",
            evidence_summary=STUB_NOTE,
        )
    # TODO: real Bright Data call — market listings for `vehicle`, compare range vs `stated_value`.
    raise NotImplementedError("Wire real Bright Data market listings lookup here")


async def check_news(location: str, date: str | None, cause: str) -> EvidenceResult:
    if _use_stub():
        return EvidenceResult(
            field_name="location",
            query_type="news",
            claimed_value=f"{cause} near {location}" + (f" on {date}" if date else ""),
            evidence_summary=STUB_NOTE,
        )
    # TODO: real Bright Data call — local news/traffic reports for `location` around `date`.
    raise NotImplementedError("Wire real Bright Data news/traffic lookup here")
