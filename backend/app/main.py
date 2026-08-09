"""
FastAPI backend — wires all 5 stages together behind one WebSocket for
Live Intake and one REST endpoint for the Dossier/Verdict screen.

Flow:
  1. Frontend opens /ws/intake/{claim_id}, starts sending binary audio frames.
  2. Backend relays audio to Speechmatics, relays partial/final transcript
     turns back to the frontend as JSON over the same socket.
  3. On *final* turns (never partials), backend re-runs field extraction
     (Kimi via AI/ML API) against the cumulative transcript and pushes
     updated fields back. Extraction is throttled — see config.extraction_*
     — because it is the only repeating paid call in the pipeline.
  4. Frontend sends {"type": "end_call"} when the adjuster ends the call.
  5. Backend runs one final extraction over the complete transcript, then
     Bright Data lookups -> judgment (AI/ML API) -> scores the dossier ->
     saves to Supabase -> sends the dossier back over the same socket.
  6. GET /claims/{claim_id}/dossier rebuilds the same dossier shape from
     Supabase for the separate Dossier screen, since screens navigate
     separately and won't share the live socket.

Failure policy for the live path: the call must always end in a dossier.
Persistence failures are logged and swallowed (see supabase_client), and a
failure in stages 3/4 produces a dossier with no findings plus an explicit
{"type": "error"} frame — never a dropped socket with nothing on screen.
"""
import asyncio
import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models import AnalyzeRequest, TranscriptTurn, ExtractedField
from app.speechmatics_client import LiveTranscriber
from app.kimi_client import extract_fields
from app.verification.dispatcher import dispatch_lookups
from app.judgment.judge_client import judge
from app.scoring import score_dossier
from app import supabase_client as db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("adjudicate")

app = FastAPI(title="Adjudicate Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten to the native.builder preview domain before submission
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _db(fn, *args):
    """
    Run a blocking Supabase call off the event loop.

    supabase-py is synchronous: called directly from the WebSocket handler
    every insert stalls audio relay for a full HTTP round-trip. Errors are
    already swallowed inside supabase_client; this catches anything left.
    """
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception:
        logger.exception("supabase call %s failed", getattr(fn, "__name__", fn))
        return None


@app.get("/health")
def health():
    gaps = settings.missing_for_stage()
    return {"status": "ok" if not gaps else "incomplete_config", "missing": gaps}


@app.get("/claims/{claim_id}/dossier")
def get_dossier(claim_id: str):
    """
    Same shape as the {"type": "dossier"} WebSocket payload, rebuilt from
    storage. The verdicts table holds the score/tier/summary; the findings
    live in contradictions, so both have to be read to reproduce a
    ClaimDossier — returning the bare verdicts row would hand the Dossier
    screen an empty contradiction table, which is the centrepiece of it.
    """
    verdict_row = db.get_latest_verdict(claim_id)
    if not verdict_row:
        raise HTTPException(status_code=404, detail="no dossier yet for this claim")

    return {
        "claim_id": claim_id,
        "risk_score": verdict_row.get("risk_score"),
        "risk_tier": verdict_row.get("risk_tier"),
        "summary": verdict_row.get("summary"),
        "findings": db.get_contradictions(claim_id),
    }


@app.post("/claims/{claim_id}/analyze")
async def analyze_claim(claim_id: str, body: AnalyzeRequest):
    """
    Run the full pipeline over a finished transcript and return the dossier.

    The one-shot alternative to the live WebSocket: same stages 2-5, same
    output, one HTTP call. This is what a frontend should use unless it is
    genuinely streaming microphone audio — it removes binary framing, audio
    format negotiation and socket lifecycle from the integration entirely.

    Costs exactly one extraction call plus one judgment call per request, so
    it is also the cheapest way to exercise the whole pipeline while
    building.
    """
    transcript = body.transcript.strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="transcript is empty")

    session_id = await _db(db.start_intake_session, claim_id) or f"oneshot-{uuid.uuid4()}"
    await _db(db.log_audit_event, claim_id, "analyze_started", {"session_id": session_id})

    try:
        fields = await extract_fields(session_id, transcript)
    except Exception as exc:
        logger.exception("extraction failed for claim %s", claim_id)
        raise HTTPException(status_code=502, detail=f"field extraction failed: {exc}")

    for f in fields:
        await _db(db.save_extracted_field, f)

    warning = None
    try:
        evidence = await dispatch_lookups(fields)
        findings = await judge(claim_id, fields, evidence)
    except Exception as exc:
        # Partial result beats no result: the extracted fields are still
        # worth showing even if verification couldn't run.
        logger.exception("verification/judgment failed for claim %s", claim_id)
        findings, warning = [], f"verification/judgment failed: {exc}"

    dossier = score_dossier(claim_id, findings)

    for finding in findings:
        await _db(db.save_contradiction, finding)
    await _db(db.save_dossier, dossier)
    await _db(db.end_intake_session, session_id)
    await _db(db.log_audit_event, claim_id, "dossier_computed", {"risk_score": dossier.risk_score})

    return {
        **dossier.model_dump(mode="json"),
        "fields": [f.model_dump(mode="json") for f in fields],
        "warning": warning,
    }


@app.websocket("/ws/intake/{claim_id}")
async def intake_socket(websocket: WebSocket, claim_id: str):
    await websocket.accept()

    # A storage outage must not stop the call from being transcribed, so fall
    # back to a local id and keep going.
    session_id = await _db(db.start_intake_session, claim_id) or f"local-{uuid.uuid4()}"
    await _db(db.log_audit_event, claim_id, "intake_started", {"session_id": session_id})

    transcript_lines: list[str] = []
    fields_seen: dict[str, ExtractedField] = {}
    extraction_lock = asyncio.Lock()
    pending: set[asyncio.Task] = set()

    chars_at_last_extraction = 0
    last_extraction_at = 0.0
    extraction_calls = 0

    def _should_extract(cumulative: str) -> bool:
        """Throttle: enough new speech, enough elapsed time, under the cap."""
        if extraction_calls >= settings.extraction_max_calls:
            return False
        if len(cumulative) - chars_at_last_extraction < settings.extraction_min_new_chars:
            return False
        return (time.monotonic() - last_extraction_at) >= settings.extraction_min_interval_s

    async def _run_extraction(cumulative: str) -> bool:
        """Extract and merge. Returns True if any field value actually changed."""
        nonlocal chars_at_last_extraction, last_extraction_at, extraction_calls

        async with extraction_lock:
            extraction_calls += 1
            last_extraction_at = time.monotonic()
            chars_at_last_extraction = len(cumulative)
            new_fields = await extract_fields(session_id, cumulative)

        changed = False
        for f in new_fields:
            previous = fields_seen.get(f.field_name)
            fields_seen[f.field_name] = f  # latest value per field wins (handles corrections)
            if previous is None or previous.field_value != f.field_value:
                changed = True
                # Only persist real changes: each extraction re-reports every
                # field it can still support, so writing them all would pile
                # up duplicate rows for values that never moved.
                await _db(db.save_extracted_field, f)
        return changed

    async def _send(payload: dict) -> bool:
        try:
            await websocket.send_json(payload)
            return True
        except Exception:
            return False  # client navigated away or the socket is closing

    async def _send_fields() -> None:
        await _send({"type": "fields", "fields": [f.model_dump(mode="json") for f in fields_seen.values()]})

    async def _handle_turn(turn: TranscriptTurn) -> None:
        sent = await _send(
            {"type": "transcript", "speaker": turn.speaker, "text": turn.text, "is_final": turn.is_final}
        )
        if not sent or not turn.is_final:
            return

        transcript_lines.append(f"{turn.speaker.upper()}: {turn.text}")
        cumulative = "\n".join(transcript_lines)
        if not _should_extract(cumulative):
            return

        try:
            changed = await _run_extraction(cumulative)
        except Exception:
            logger.exception("field extraction failed")
            return

        if changed:
            await _send_fields()

    def on_turn(turn: TranscriptTurn) -> None:
        task = asyncio.create_task(_handle_turn(turn))
        # Hold a reference: a bare create_task can be garbage-collected
        # mid-flight, and its exceptions would go unreported.
        pending.add(task)
        task.add_done_callback(pending.discard)

    transcriber = LiveTranscriber(on_turn=on_turn)
    try:
        await transcriber.start()
    except Exception as exc:
        # Almost always a bad/missing SPEECHMATICS_API_KEY. Tell the frontend
        # instead of dropping the socket with no explanation.
        logger.exception("could not start transcription session")
        await _send({"type": "error", "stage": "listen", "detail": str(exc)})
        await _db(db.end_intake_session, session_id)
        await websocket.close()
        return

    try:
        while True:
            message = await websocket.receive()

            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await transcriber.push_audio(message["bytes"])
            elif message.get("text") is not None:
                payload = json.loads(message["text"])
                if payload.get("type") == "end_call":
                    break

    except WebSocketDisconnect:
        pass
    finally:
        try:
            # Waits for the server's end-of-transcript internally, so no
            # arbitrary sleep is needed here — see LiveTranscriber.stop().
            await transcriber.stop()
        except Exception:
            logger.exception("transcriber shutdown failed")
        if pending:
            # Extractions still in flight own fields the dossier needs.
            await asyncio.gather(*pending, return_exceptions=True)
        await _db(db.end_intake_session, session_id)
        await _db(db.log_audit_event, claim_id, "intake_ended", {"session_id": session_id})

    # One guaranteed pass over the complete transcript. The throttle above
    # may have skipped the tail, and this is the only extraction that is
    # certain to have seen the whole call — but skip it if the last throttled
    # pass already covered exactly this text, so it costs at most one call.
    cumulative = "\n".join(transcript_lines)
    if cumulative.strip() and len(cumulative) != chars_at_last_extraction:
        try:
            await _run_extraction(cumulative)
        except Exception:
            logger.exception("final field extraction failed")
    await _send_fields()

    # Stages 3 + 4 — run once, when the call ends
    fields = list(fields_seen.values())
    stage_error = None
    try:
        evidence = await dispatch_lookups(fields)
        findings = await judge(claim_id, fields, evidence)
    except Exception as exc:
        logger.exception("verification/judgment failed — returning an empty dossier")
        findings, stage_error = [], str(exc)

    dossier = score_dossier(claim_id, findings)

    for finding in findings:
        await _db(db.save_contradiction, finding)
    await _db(db.save_dossier, dossier)
    await _db(db.log_audit_event, claim_id, "dossier_computed", {"risk_score": dossier.risk_score})

    if stage_error:
        # Say so out loud rather than letting an empty findings list read as
        # "we checked and this claim is clean".
        await _send({"type": "error", "stage": "verification/judgment", "detail": stage_error})

    if not await _send({"type": "dossier", "dossier": dossier.model_dump(mode="json")}):
        logger.info("client gone; dossier saved — fetch via GET /claims/%s/dossier", claim_id)
