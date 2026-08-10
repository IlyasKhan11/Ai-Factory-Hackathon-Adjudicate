"""
Stage 3 — Go look: weather verification (Open-Meteo historical archive)

The real implementation of the weather check. Given a claimed date, location
and cause, it pulls the actual recorded weather for that place on that day
and hands the judge real evidence — which is what turns "CANNOT_DETERMINE"
into a defensible "CONTRADICTED".

Why not Bright Data: their API and MCP hosts do not resolve from either the
dev machine or the deploy environment (connection never opens — a common
ISP-level block on proxy/scraping providers in some regions). The Bright
Data path is still scaffolded in bright_data_client.py for the other three
lookups; if the network allows it later, this module's signature is the
contract to implement against.

Open-Meteo needs no API key and no account:
  - geocoding:  https://geocoding-api.open-meteo.com/v1/search
  - archive:    https://archive-api.open-meteo.com/v1/archive

Free for non-commercial use, so it costs nothing against the hackathon
budget.
"""
import logging
from datetime import date as date_cls, datetime, timedelta

import httpx

from app.models import EvidenceResult

logger = logging.getLogger("adjudicate")

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
SOURCE_URL = "https://open-meteo.com/en/docs/historical-weather-api"

TIMEOUT_S = 20.0

# The archive lags real time by a few days; asking for yesterday returns
# nulls rather than an error, which would read as "no rain" and produce a
# false contradiction. Refuse to rule on anything inside this window.
ARCHIVE_LAG_DAYS = 6

# Below this, the day was effectively dry — not evidence for a storm claim.
TRACE_PRECIPITATION_MM = 1.0

# Causes this check can actually speak to. "hail" is the demo case.
PRECIPITATION_CAUSES = {
    "hail", "rain", "storm", "flood", "snow", "lightning", "thunder",
    # Must stay in step with the dispatcher's WEATHER_TRIGGER_CAUSES. A
    # claimant blaming "severe weather" is making exactly the kind of
    # assertion the archive can settle — declining it here meant the
    # dispatcher fired the lookup and this function refused it.
    "weather",
}


def _unresolved(claimed: str, reason: str) -> EvidenceResult:
    """No usable evidence — marked so the judge returns CANNOT_DETERMINE."""
    return EvidenceResult(
        field_name="date",
        query_type="weather",
        claimed_value=claimed,
        evidence_summary=f"[STUB] Weather record unavailable — {reason}",
    )


async def _geocode(client: httpx.AsyncClient, location: str) -> tuple[float, float, str] | None:
    """
    Resolve a free-text location to coordinates.

    Claimants give street-level detail ("Shahrah-e-Faisal, Karachi") that
    a gazetteer won't match, so fall back to the trailing component — the
    city — which is the right granularity for weather anyway.
    """
    candidates = [location]
    if "," in location:
        candidates.append(location.rsplit(",", 1)[-1].strip())

    for candidate in candidates:
        try:
            resp = await client.get(GEOCODE_URL, params={"name": candidate, "count": 1})
            resp.raise_for_status()
            results = (resp.json() or {}).get("results") or []
        except Exception:
            logger.exception("geocoding failed for %r", candidate)
            continue
        if results:
            hit = results[0]
            label = ", ".join(
                p for p in (hit.get("name"), hit.get("admin1"), hit.get("country")) if p
            )
            return float(hit["latitude"]), float(hit["longitude"]), label
    return None


async def check_weather(date: str, location: str, claimed_cause: str) -> EvidenceResult:
    """
    Compare a claimed weather event against the historical record.

    Returns real evidence when the record supports a judgement, and
    explicitly-unresolved evidence otherwise — never a guess.
    """
    claimed = f"{claimed_cause} on {date} at {location}"

    cause = (claimed_cause or "").lower()
    if not any(word in cause for word in PRECIPITATION_CAUSES):
        return _unresolved(claimed, f"'{claimed_cause}' is not a weather event this check can verify")

    try:
        loss_date = datetime.strptime(date.strip(), "%Y-%m-%d").date()
    except ValueError:
        return _unresolved(claimed, f"date {date!r} is not a usable calendar date")

    if loss_date > date_cls.today() - timedelta(days=ARCHIVE_LAG_DAYS):
        # Silence here is missing data, not absence of rain.
        return _unresolved(claimed, "the date is too recent for the historical archive")

    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        located = await _geocode(client, location)
        if located is None:
            return _unresolved(claimed, f"could not resolve location {location!r}")
        lat, lon, place = located

        try:
            resp = await client.get(
                ARCHIVE_URL,
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "start_date": date, "end_date": date,
                    "daily": "precipitation_sum,rain_sum,snowfall_sum,temperature_2m_max,wind_gusts_10m_max",
                    "timezone": "auto",
                },
            )
            resp.raise_for_status()
            daily = (resp.json() or {}).get("daily") or {}
        except Exception:
            logger.exception("weather archive lookup failed for %s on %s", place, date)
            return _unresolved(claimed, "the weather archive could not be reached")

    def value(key):
        series = daily.get(key) or []
        return series[0] if series and series[0] is not None else None

    precipitation = value("precipitation_sum")
    if precipitation is None:
        return _unresolved(claimed, f"no recorded observations for {place} on {date}")

    rain, snow = value("rain_sum"), value("snowfall_sum")
    temp_max, gusts = value("temperature_2m_max"), value("wind_gusts_10m_max")

    measurements = [f"total precipitation {precipitation} mm"]
    if rain is not None:
        measurements.append(f"rain {rain} mm")
    if snow is not None:
        measurements.append(f"snowfall {snow} cm")
    if temp_max is not None:
        measurements.append(f"maximum temperature {temp_max}°C")
    if gusts is not None:
        measurements.append(f"peak wind gusts {gusts} km/h")

    reading = f"Recorded weather for {place} on {date}: " + ", ".join(measurements) + "."

    if precipitation == 0:
        # State the conclusion plainly. The judge rules on the summary text,
        # so burying it in numbers invites a hedge.
        verdict_hint = (
            f" No precipitation of any kind was recorded on this date, which is inconsistent "
            f"with a claimed {claimed_cause} event."
        )
    elif precipitation < TRACE_PRECIPITATION_MM:
        # 0.2mm is a damp windscreen, not a storm. Calling that "consistent"
        # would hand the judge a false exoneration.
        verdict_hint = (
            f" Only trace precipitation was recorded, far below what a claimed "
            f"{claimed_cause} event would produce."
        )
    elif temp_max is not None and temp_max > 30 and "hail" in cause:
        verdict_hint = (
            f" Precipitation was recorded, but a maximum temperature of {temp_max}°C makes "
            f"hail highly improbable."
        )
    else:
        verdict_hint = (
            f" Precipitation was recorded on this date, consistent with a claimed "
            f"{claimed_cause} event."
        )

    return EvidenceResult(
        field_name="date",
        query_type="weather",
        claimed_value=claimed,
        evidence_summary=reading + verdict_hint,
        source_url=SOURCE_URL,
        raw={"place": place, "precipitation_mm": precipitation, "temp_max_c": temp_max},
    )
