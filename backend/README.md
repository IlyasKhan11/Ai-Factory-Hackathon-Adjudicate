# Adjudicate Backend

FastAPI service implementing the 5-stage pipeline from the team brief:
**Listen** (Speechmatics) → **Understand** (AI/ML API, Kimi K2.6) → **Go look**
(Bright Data) → **Judge** (AI/ML API) → **Dossier** (scored + saved to Supabase).

Both LLM stages run on **one AI/ML API key** — the hackathon grants either
AI/ML API or Featherless, not both. All shared LLM plumbing lives in
`app/llm.py`, which is also where per-call token usage is logged.

## Status

| Stage | File | Status |
|---|---|---|
| 1. Listen | `app/speechmatics_client.py` | Built on `speechmatics-rt` (current SDK), verified against its actual API surface |
| 2. Understand | `app/kimi_client.py` | Built, ready — same pattern as the OLS pipeline's `kimi_client.py` |
| 3. Go look | `app/verification/` | Dispatcher logic done; Bright Data calls stubbed behind `BRIGHTDATA_USE_STUB` |
| 4. Judge | `app/judgment/judge_client.py` | Built, ready — runs on AI/ML API (same key as Stage 2), no Featherless dependency |
| Storage | `app/supabase_client.py` | Built against inferred column names — **verify against Burhan's real schema**. Writes are best-effort: a wrong column loses the row, not the demo |

## Credit budget

Stage 2 is the only paid call that repeats during a call, and it was firing
once per final transcript turn over an ever-growing transcript — roughly 40
calls for a 4-minute call. It's now throttled to a handful per session via
`EXTRACTION_MIN_NEW_CHARS` / `EXTRACTION_MIN_INTERVAL_S` /
`EXTRACTION_MAX_CALLS`, plus exactly one guaranteed pass over the full
transcript when the call ends. Stages 3 and 4 run once per call.

To develop for free: leave `BRIGHTDATA_USE_STUB=true` and raise
`EXTRACTION_MIN_INTERVAL_S`. `dispatch_lookups()` + `score_dossier()` +
`parse_json_object()` are all exercisable with no network at all.

**Frontend audio format**: the browser must send raw 16kHz mono 16-bit
signed PCM binary frames over the WebSocket (`AudioFormat` in
`speechmatics_client.py`) — not WebM/Opus from `MediaRecorder`. See the
frontend wiring notes for the matching Web Audio API capture code.

Full pipeline runs end-to-end today with stubbed evidence — verified with
`dispatch_lookups()` + `score_dossier()` against the exact demo claim
(hail / Corolla / Al Noor Auto Works) from the mockup.

## Setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real keys
uvicorn app.main:app --reload
```

`GET /health` reports which stages are missing credentials — check this first.

## What's left

1. **Bright Data**: fill in the four `TODO`s in `app/verification/bright_data_client.py`
   (weather, business registry, market value, news), then set
   `BRIGHTDATA_USE_STUB=false`. Everything upstream and downstream already
   works against these — swap the stub body, not the function signature.
2. **Supabase**: set `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` in `.env`, then
   run `python check_schema.py` — it reports every missing table and column
   against what the code actually writes, read-only. If the project is empty,
   run `schema.sql` in the SQL editor first. Writes fail soft until then:
   the pipeline runs and the WebSocket dossier arrives, but nothing persists
   and `GET /claims/{id}/dossier` 404s.
3. **Deployment**: native.builder hosts the frontend only — this needs
   somewhere else to run for the live demo link (Railway/Render/Fly all
   work fine for a FastAPI + WebSocket app).
4. **Frontend wiring**: Live Intake screen needs to open
   `wss://<backend-host>/ws/intake/{claim_id}`, stream mic audio as binary
   frames, and render incoming `{"type": "transcript", ...}` and
   `{"type": "fields", ...}` messages. Dossier screen fetches
   `GET /claims/{claim_id}/dossier`.
