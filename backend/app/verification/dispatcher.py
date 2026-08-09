"""
Stage 3 — Go look (dispatcher)

Reads whatever fields Stage 2 managed to extract and decides which Bright
Data lookups are actually worth running. This dynamic branching — a hail
claim triggers weather, a theft claim triggers something else entirely —
is exactly what the brief calls out as the difference between an agent and
a script, and it's what the Bright Data challenge is judged on. Don't
flatten this into "always run all four checks."
"""
from app.models import ExtractedField, EvidenceResult
from app.verification import bright_data_client as bd

WEATHER_TRIGGER_CAUSES = {"hail", "flood", "storm", "wind", "lightning", "snow", "rain"}
INCIDENT_TRIGGER_CAUSES = {"collision", "theft", "accident", "vandalism", "break-in", "burglary"}


def _field_value(fields: list[ExtractedField], name: str) -> str | None:
    matches = [f for f in fields if f.field_name == name]
    return matches[-1].field_value if matches else None  # latest wins (corrections)


async def dispatch_lookups(fields: list[ExtractedField]) -> list[EvidenceResult]:
    results: list[EvidenceResult] = []

    date = _field_value(fields, "date")
    location = _field_value(fields, "location")
    cause = (_field_value(fields, "cause") or "").lower()
    vehicle = _field_value(fields, "vehicle")
    stated_damage = _field_value(fields, "stated_damage")
    repair_shop = _field_value(fields, "repair_shop")

    if date and location and any(w in cause for w in WEATHER_TRIGGER_CAUSES):
        results.append(await bd.check_weather(date=date, location=location, claimed_cause=cause))

    if repair_shop:
        results.append(await bd.check_business(name=repair_shop))

    if vehicle and stated_damage:
        results.append(await bd.check_market_value(vehicle=vehicle, stated_value=stated_damage))

    if location and any(w in cause for w in INCIDENT_TRIGGER_CAUSES):
        results.append(await bd.check_news(location=location, date=date, cause=cause))

    return results
