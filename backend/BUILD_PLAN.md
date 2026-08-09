# Adjudicate — Build & Submission Plan

Reference doc for the rest of hackathon day. Check items off as you go.

## Where things stand right now

- **Frontend**: 3 screens live on Native.builder (Queue, Live Intake, Verdict), Supabase connected, currently running on seeded demo data.
- **Backend**: `adjudicate-backend/` — built, dependency-installed, imports clean, dispatcher/scoring logic tested against your actual demo claim (hail / 2019 Corolla / Al Noor Auto Works).
- **Credits**: AI/ML API confirmed (~$19). Featherless unavailable (coupon exclusivity — you claimed AI/ML API). Stage 4 (Judge) is pre-configured to run through AI/ML API using DeepSeek-V3 instead — no code change needed, just the env vars below.
- **Eligibility**: verified against the hackathon's actual rules text + precedent submissions using the same partner-tool stack. Still worth a Discord confirmation in parallel — send that now if you haven't.

## Credentials checklist (fill into `.env`)

- [ ] `SPEECHMATICS_API_KEY`
- [ ] `AIML_API_KEY`
- [ ] `BRIGHTDATA_API_KEY` (promo code `aiaccess50` on the hackathon page if not yet claimed)
- [ ] `AIML_JUDGE_MODEL` = `deepseek/deepseek-chat`
- [ ] `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` (get from Burhan)
- [ ] `BRIGHTDATA_USE_STUB` = `true` (flip to `false` only in Phase 5)

> **The `FEATHERLESS_*` vars are gone.** Featherless was removed from the
> codebase entirely — there is no code left that reads them, so setting them
> does nothing and the Judge stage would silently stay on the default model.
> Stage 4 now runs on `AIML_API_KEY` with whatever `AIML_JUDGE_MODEL` says.
> Leave `AIML_JUDGE_MODEL` blank to reuse the extraction model.

## Phase 1 — Deploy the backend (blocks everything else, do first)

1. ~~Push to GitHub~~ — done, commit `83612eb` on `IlyasKhan11/Ai-Factory-Hackathon-Adjudicate`.
2. Connect the repo to Railway (fastest for this), or Render/Fly.
3. **Set Root Directory to `backend`** in the service settings. The app is in
   a subfolder; without this the build won't find `requirements.txt`.
4. Set every env var above in the host's dashboard.
5. Hit `https://<your-app>/health` — confirm `"status": "ok"` with an empty `missing` object.
6. Note the host — you'll need `wss://<host>/ws/intake/{claim_id}` in Phase 3.

A `Dockerfile`, `Procfile` and `.dockerignore` are in `backend/`. The
Dockerfile binds `0.0.0.0:$PORT`, which the host requires — binding
localhost is the usual cause of "deployed fine, nothing responds".

*(~15 min)*

## Phase 2 — Prove Stage 1+2 work before touching the frontend

1. Get a short (~15s) two-person test clip. Record yourself + anyone nearby, or convert any existing clip:
   `ffmpeg -i any_audio.mp3 -ar 16000 -ac 1 -c:a pcm_s16le test.wav`
2. Locally: `cp .env.example .env` (fill real keys), `pip install -r requirements.txt`.
3. `python test_speechmatics_live.py test.wav`
4. Confirm `[FINAL]` lines appear with two different speaker labels.

*(~10 min — do not skip; this is the highest-risk piece and cheapest to debug in isolation)*

## Phase 3 — Wire the Live Intake screen

1. Resolve with Burhan: does the Queue screen create the `claims` row, or does clicking "Start call" create one fresh? This determines whether the backend needs a create-if-missing patch — tell me if it does, quick fix.
2. Integrate `frontend-wiring-reference.js` into the real Live Intake component (via the Native.builder agent, or by hand-editing the synced React code if you have repo access).
3. Set `WS_BASE` to your deployed `wss://` URL from Phase 1.
4. Test: click mic, speak as both adjuster and caller, confirm transcript + fields populate live on screen.

*(~30-45 min, the most involved phase)*

## Phase 4 — Verify the Supabase schema

1. Fill `SUPABASE_URL` + `SUPABASE_SERVICE_KEY` into `.env`, then run
   `python check_schema.py`. It reports every missing table and column
   against what the code actually writes. Read-only, takes seconds.
2. If the project is empty, run `schema.sql` in the Supabase SQL editor
   first — it creates all six tables and seeds a demo claim id.
3. If column names differ, tell me the real ones — the fix is renaming dict
   keys in `supabase_client.py`, no call sites move.

Until this is done the pipeline still runs and the WebSocket dossier still
arrives — writes fail soft. What's broken without it is
`GET /claims/{id}/dossier`, which the Verdict screen needs after navigation.

## Phase 5 — Wire one real Bright Data lookup

1. Implement `check_weather()` in `bright_data_client.py` — simplest, and matches your already-tested demo claim exactly.
2. **Set `BRIGHTDATA_USE_STUB=false`.** Without this the stub still returns
   and your new implementation never runs — the flag gates all four lookups,
   not just the unwritten ones.
3. Leave the other three stubbed. Each lookup is isolated in the dispatcher,
   so the three unwritten ones degrade to `CANNOT_DETERMINE` individually
   while your real weather verdict comes through intact. Verified by
   simulation — a partial implementation is a supported state, not a
   half-broken one.
4. This is fine — the brief itself treats `CANNOT_DETERMINE` as a legitimate,
   expected outcome, not a gap to hide. One real `CONTRADICTED` row next to
   three honest cannot-determines is a stronger demo than four fabricated
   findings.

## Phase 6 — Full end-to-end test

1. Run the demo script (hail, 2019 Corolla, Shahrah-e-Faisal, Al Noor Auto Works) through the live Intake screen for real.
2. Confirm it reaches the Verdict/Dossier screen with at least one real, non-stub finding.
3. Confirm the Queue screen shows the claim with the correct risk tier.

**This is your minimum bar for a valid, working submission. Everything past this point strengthens the entry but isn't required.**

## Phase 7 — Submission materials (start now, don't wait on Phase 6)

- [ ] Demo video, ≤3 minutes, showing one complete end-to-end workflow
- [ ] Problem description + target user (insurance claims adjusters / SIU teams)
- [ ] "How native.builder was used" writeup — say the word and I'll draft this
- [ ] List of external APIs/tools: Speechmatics, AI/ML API (Kimi K2.6 + DeepSeek-V3), Bright Data, Supabase
- [ ] Native.builder project URL, confirmed publicly accessible

## Phase 8 — Submit

- Don't wait for every stage to be polished — a working submission with one real finding beats a more complete one submitted late.
- Confirm your exact deadline time on your personal lablab.ai dashboard before you cut it close.

---

**If you get stuck on anything above, come back with what broke — error message, screenshot, whatever you've got — and I'll debug it directly rather than you troubleshooting solo.**
