"""
Central config. Every external service the 5-stage pipeline touches
reads its credentials from here, nowhere else — so swapping a stubbed
client for a real one later never means hunting through the codebase.
"""
import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Stage 1 — Listen
    speechmatics_api_key: str = os.getenv("SPEECHMATICS_API_KEY", "")
    speechmatics_rt_url: str = os.getenv("SPEECHMATICS_RT_URL", "wss://eu.rt.speechmatics.com/v2")

    # Stages 2 + 4 — Understand and Judge, both on AI/ML API.
    # The hackathon grants one provider key, either AI/ML API or Featherless.
    # This build uses AI/ML API for both LLM stages; there is no Featherless
    # dependency anywhere in the codebase.
    aiml_api_key: str = os.getenv("AIML_API_KEY", "")
    aiml_api_base: str = os.getenv("AIML_API_BASE", "https://api.aimlapi.com/v1")
    # Extraction model. MUST be a non-reasoning model: reasoning tokens count
    # against max_tokens, so a thinking model spends the whole budget on
    # hidden reasoning, returns content=None with finish_reason="length", and
    # extraction silently yields zero fields. Measured on this key:
    # kimi-k2.6 -> 90s+ timeout, no output. deepseek/deepseek-chat -> 2.9s,
    # clean JSON. DeepSeek-V3 is also open-weight, which keeps the brief's
    # compliance argument intact for the judge stage.
    aiml_kimi_model: str = os.getenv("AIML_KIMI_MODEL", "deepseek/deepseek-chat")
    # Judgment defaults to the same model as extraction: it's the one model id
    # you'll have already confirmed works against your key. Point it at any
    # open-weight model in the AI/ML catalog to strengthen the compliance
    # argument — see app/judgment/judge_client.py.
    aiml_judge_model: str = os.getenv("AIML_JUDGE_MODEL", "") or aiml_kimi_model

    # Stage 3 — Go look
    brightdata_api_key: str = os.getenv("BRIGHTDATA_API_KEY", "")
    brightdata_api_base: str = os.getenv("BRIGHTDATA_API_BASE", "https://api.brightdata.com")
    # Default ON: the four lookups in bright_data_client.py are still TODOs,
    # so having a key doesn't mean there's an implementation to call. Flip to
    # false only once those are written — see that module's docstring.
    brightdata_use_stub: bool = os.getenv("BRIGHTDATA_USE_STUB", "true").lower() != "false"

    # Storage
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")

    # --- Credit control -------------------------------------------------
    # Hackathon credits are a fixed budget, and Stage 2 is the only thing in
    # this pipeline that fires repeatedly during a call. Re-extracting on
    # every final turn costs O(turns) calls over an ever-growing transcript,
    # so a 4-minute call can burn 40+ requests. These throttle it to a
    # handful per call without changing what the frontend sees: extraction
    # runs only when enough NEW speech has arrived AND enough time has
    # passed, plus exactly one guaranteed pass over the full transcript when
    # the call ends. Lower the interval for a live demo, raise it while
    # iterating on other stages.
    extraction_min_new_chars: int = int(os.getenv("EXTRACTION_MIN_NEW_CHARS", "180"))
    extraction_min_interval_s: float = float(os.getenv("EXTRACTION_MIN_INTERVAL_S", "8"))
    extraction_max_calls: int = int(os.getenv("EXTRACTION_MAX_CALLS", "12"))  # hard per-session cap

    def missing_for_stage(self) -> dict[str, list[str]]:
        """Quick self-check so a half-configured .env fails loud, not silent."""
        gaps: dict[str, list[str]] = {}
        if not self.speechmatics_api_key:
            gaps["listen"] = ["SPEECHMATICS_API_KEY"]
        if not self.aiml_api_key:
            # One key powers both LLM stages, so it gaps both.
            gaps["understand"] = ["AIML_API_KEY"]
            gaps["judge"] = ["AIML_API_KEY"]
        if not self.brightdata_api_key and not self.brightdata_use_stub:
            gaps["go_look"] = ["BRIGHTDATA_API_KEY"]
        if not self.supabase_url or not self.supabase_service_key:
            gaps["storage"] = ["SUPABASE_URL", "SUPABASE_SERVICE_KEY"]
        return gaps


settings = Settings()
