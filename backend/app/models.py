"""
Shared data shapes for the pipeline. These mirror Burhan's Supabase schema
(claims, contradictions, extracted_fields, intake_sessions, verdicts, audit_log)
as described in the team chat — confirm exact column names against the live
schema before wiring supabase_client.py for real; field names below are the
best inference from the brief and may need small renames to match.
"""
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class Verdict(str, Enum):
    CONTRADICTED = "CONTRADICTED"
    SUSPICIOUS = "SUSPICIOUS"
    OVERSTATED = "OVERSTATED"          # carries a percentage in `detail`
    CANNOT_DETERMINE = "CANNOT_DETERMINE"
    CONSISTENT = "CONSISTENT"           # checked, no contradiction found


class RiskTier(str, Enum):
    FAST_TRACK = "fast_track"
    STANDARD = "standard"
    INVESTIGATE = "investigate"


class TranscriptTurn(BaseModel):
    speaker: str            # "adjuster" | "caller" — mapped from Speechmatics raw speaker id
    text: str
    start_time: float
    end_time: float
    is_final: bool


class ExtractedField(BaseModel):
    session_id: str
    field_name: str         # date, location, vehicle, cause, injuries, stated_damage, repair_shop, ...
    field_value: str
    confidence: float       # 0-1
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EvidenceResult(BaseModel):
    """One Bright Data lookup result, feeding into the Judge stage."""
    field_name: str
    query_type: str         # "weather" | "business_registry" | "market_value" | "news"
    claimed_value: str
    evidence_summary: str
    source_url: Optional[str] = None
    raw: Optional[dict] = None


class ContradictionFinding(BaseModel):
    claim_id: str
    field_name: str
    claimed_value: str
    evidence_value: str
    verdict: Verdict
    detail: Optional[str] = None       # e.g. "15%" for OVERSTATED
    source_url: Optional[str] = None
    confidence: float


class ClaimDossier(BaseModel):
    claim_id: str
    risk_score: int                     # 0-100
    risk_tier: RiskTier
    findings: list[ContradictionFinding]
    summary: str
