"""
Storage — Supabase (Burhan's existing project: claims, contradictions,
extracted_fields, intake_sessions, verdicts, audit_log)

Column names below are inferred from the team brief + mockup, not read
from the live schema — confirm against the real tables (ask Burhan, or
`supabase db dump` / check the table editor) before this touches prod
data. Likely close, since it follows the field names the brief itself
uses, but "likely close" isn't "confirmed."

*** Persistence here is best-effort by design. *** Until that schema is
confirmed, a wrong column name is a live possibility, and PostgREST reports
it as a 400 at write time — not at import, not at startup. Every function
below degrades to a logged warning instead of an exception so that a schema
mismatch costs you the saved row, never the running demo: the pipeline
holds everything it needs in memory and still returns a dossier over the
WebSocket. Check the logs for "supabase" after any run before trusting that
data landed.
"""
import logging

from supabase import create_client, Client

from app.config import settings
from app.models import ExtractedField, ContradictionFinding, ClaimDossier

logger = logging.getLogger("adjudicate")

_client: Client | None = None
_warned_unconfigured = False


def get_client() -> Client | None:
    """None when Supabase isn't configured — callers run in-memory only."""
    global _client, _warned_unconfigured
    if _client is None:
        if not settings.supabase_url or not settings.supabase_service_key:
            if not _warned_unconfigured:
                logger.warning("Supabase not configured — pipeline will run, nothing will be persisted")
                _warned_unconfigured = True
            return None
        _client = create_client(settings.supabase_url, settings.supabase_service_key)
    return _client


def _write(table: str, op: str, row: dict) -> bool:
    """One insert/update, swallowing schema errors with a loud log line."""
    client = get_client()
    if client is None:
        return False
    try:
        getattr(client.table(table), op)(row).execute()
        return True
    except Exception:
        logger.exception("supabase %s into %s failed — row dropped: %s", op, table, row)
        return False


def start_intake_session(claim_id: str) -> str | None:
    client = get_client()
    if client is None:
        return None
    try:
        res = client.table("intake_sessions").insert({"claim_id": claim_id, "status": "active"}).execute()
    except Exception:
        logger.exception("supabase could not open an intake session for claim %s", claim_id)
        return None
    return res.data[0]["id"] if res.data else None


def end_intake_session(session_id: str) -> None:
    client = get_client()
    if client is None:
        return
    try:
        client.table("intake_sessions").update({"status": "completed"}).eq("id", session_id).execute()
    except Exception:
        logger.exception("supabase could not close intake session %s", session_id)


def save_extracted_field(field: ExtractedField) -> None:
    _write(
        "extracted_fields",
        "insert",
        {
            "session_id": field.session_id,
            "field_name": field.field_name,
            "field_value": field.field_value,
            "confidence": field.confidence,
        },
    )


def save_contradiction(finding: ContradictionFinding) -> None:
    _write(
        "contradictions",
        "insert",
        {
            "claim_id": finding.claim_id,
            "field_name": finding.field_name,
            "claimed_value": finding.claimed_value,
            "evidence_value": finding.evidence_value,
            "verdict": finding.verdict.value,
            "detail": finding.detail,
            "source_url": finding.source_url,
            "confidence": finding.confidence,
        },
    )


def save_dossier(dossier: ClaimDossier) -> None:
    _write(
        "verdicts",
        "insert",
        {
            "claim_id": dossier.claim_id,
            "risk_score": dossier.risk_score,
            "risk_tier": dossier.risk_tier.value,
            "summary": dossier.summary,
        },
    )
    # Separate try: the verdict row is the important one, and a claims row
    # that doesn't exist yet must not take it down with it.
    client = get_client()
    if client is None:
        return
    try:
        client.table("claims").update({"risk_tier": dossier.risk_tier.value}).eq("id", dossier.claim_id).execute()
    except Exception:
        logger.exception("supabase could not stamp risk_tier onto claim %s", dossier.claim_id)


def log_audit_event(claim_id: str, event_type: str, payload: dict) -> None:
    _write("audit_log", "insert", {"claim_id": claim_id, "event_type": event_type, "payload": payload})


def get_latest_verdict(claim_id: str) -> dict | None:
    """Most recent verdict row for a claim, or None."""
    client = get_client()
    if client is None:
        return None
    # Ordering column depends on the unconfirmed schema: created_at is the
    # Supabase convention, id only means "latest" if it's a serial rather
    # than a uuid. Try the right one, fall back rather than 500.
    for order_column in ("created_at", "id"):
        try:
            res = (
                client.table("verdicts")
                .select("*")
                .eq("claim_id", claim_id)
                .order(order_column, desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            logger.warning("verdicts has no usable %s column for ordering", order_column)
            continue
        return res.data[0] if res.data else None
    return None


def get_contradictions(claim_id: str) -> list[dict]:
    """All findings for a claim — the dossier's contradiction table."""
    client = get_client()
    if client is None:
        return []
    try:
        res = client.table("contradictions").select("*").eq("claim_id", claim_id).execute()
    except Exception:
        logger.exception("supabase could not read contradictions for claim %s", claim_id)
        return []
    return res.data or []
