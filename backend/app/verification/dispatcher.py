"""
Stage 3 — Go look (dispatcher)

Reads whatever fields Stage 2 managed to extract and decides which Bright
Data lookups are actually worth running. This dynamic branching — a hail
claim triggers weather, a theft claim triggers something else entirely —
is exactly what the brief calls out as the difference between an agent and
a script, and it's what the Bright Data challenge is judged on. Don't
flatten this into "always run all four checks."

Each lookup is isolated. One unimplemented or failing check degrades to
"[STUB] ... " evidence for that check alone, which the Judge stage turns
into CANNOT_DETERMINE. This is what makes a *partial* Bright Data
implementation viable: with only check_weather() written and
BRIGHTDATA_USE_STUB off, you get a real weather verdict plus three
cannot-determines, instead of an exception escaping this function and
costing you every finding including the one that worked.

Lookups run concurrently — with real network calls, four sequential
round-trips is dead air at the end of a demo call.
"""
import asyncio
import logging
from functools import partial
from typing import Awaitable, Callable

from app.models import ExtractedField, EvidenceResult
from app.verification import bright_data_client as bd
from app.verification import weather_client as weather

logger = logging.getLogger("adjudicate")

WEATHER_TRIGGER_CAUSES = {"hail", "flood", "storm", "wind", "lightning", "snow", "rain"}
INCIDENT_TRIGGER_CAUSES = {"collision", "theft", "accident", "vandalism", "break-in", "burglary"}

# Both markers contain "[STUB]" on purpose — the Judge prompt keys on that
# to return CANNOT_DETERMINE rather than ruling on evidence it doesn't have.
NOT_IMPLEMENTED_NOTE = "[STUB] This lookup is not implemented yet — no evidence gathered"
FAILED_NOTE = "[STUB] Lookup failed — no evidence gathered"


def _field_value(fields: list[ExtractedField], name: str) -> str | None:
    matches = [f for f in fields if f.field_name == name]
    return matches[-1].field_value if matches else None  # latest wins (corrections)


async def _guarded(
    lookup: Callable[[], Awaitable[EvidenceResult]],
    *,
    field_name: str,
    query_type: str,
    claimed_value: str,
) -> EvidenceResult:
    """Run one lookup; never let its failure take out the others."""
    try:
        return await lookup()
    except NotImplementedError:
        logger.info("%s lookup not implemented — recording as unresolved", query_type)
        summary = NOT_IMPLEMENTED_NOTE
    except Exception:
        logger.exception("%s lookup failed", query_type)
        summary = FAILED_NOTE

    return EvidenceResult(
        field_name=field_name,
        query_type=query_type,
        claimed_value=claimed_value,
        evidence_summary=summary,
    )


async def dispatch_lookups(fields: list[ExtractedField]) -> list[EvidenceResult]:
    date = _field_value(fields, "date")
    location = _field_value(fields, "location")
    cause = (_field_value(fields, "cause") or "").lower()
    vehicle = _field_value(fields, "vehicle")
    stated_damage = _field_value(fields, "stated_damage")
    repair_shop = _field_value(fields, "repair_shop")

    planned: list[Awaitable[EvidenceResult]] = []

    if date and location and any(w in cause for w in WEATHER_TRIGGER_CAUSES):
        planned.append(
            _guarded(
                # Real implementation (Open-Meteo). The other three lookups
                # are still Bright Data stubs — see weather_client's docstring.
                partial(weather.check_weather, date=date, location=location, claimed_cause=cause),
                field_name="date",
                query_type="weather",
                claimed_value=f"{cause} on {date} at {location}",
            )
        )

    if repair_shop:
        planned.append(
            _guarded(
                partial(bd.check_business, name=repair_shop),
                field_name="repair_shop",
                query_type="business_registry",
                claimed_value=repair_shop,
            )
        )

    if vehicle and stated_damage:
        planned.append(
            _guarded(
                partial(bd.check_market_value, vehicle=vehicle, stated_value=stated_damage),
                field_name="stated_damage",
                query_type="market_value",
                claimed_value=f"{stated_damage} of damage to a {vehicle}",
            )
        )

    if location and any(w in cause for w in INCIDENT_TRIGGER_CAUSES):
        planned.append(
            _guarded(
                partial(bd.check_news, location=location, date=date, cause=cause),
                field_name="location",
                query_type="news",
                claimed_value=f"{cause} near {location}" + (f" on {date}" if date else ""),
            )
        )

    if not planned:
        return []

    return list(await asyncio.gather(*planned))
