"""
Stage 1 — Listen (Speechmatics)

Built on speechmatics-rt (the current SDK — the older speechmatics-python
package used in an earlier draft of this file is deprecated and warns on
import). This version is simpler and lower-risk than the first draft: no
thread/queue adapter, no file-like object shim. send_audio() is natively
async, so main.py can just `await transcriber.push_audio(chunk)` directly
from the WebSocket receive loop.

  browser mic --(binary WS frames)--> FastAPI --> push_audio()
    --> AsyncClient.send_audio() --> Speechmatics RT API
  Speechmatics RT API --(partial/final transcript messages)--> registered
    handlers --> on_turn callback --> FastAPI --> frontend

AUDIO_FORMAT below (16kHz mono, 16-bit signed PCM, no container) must
match exactly what the frontend's mic capture sends — see the frontend
wiring notes for the matching Web Audio API code.
"""
import asyncio
import logging
from typing import Callable, Optional

from speechmatics.rt import AsyncClient, ServerMessageType, TranscriptionConfig, AudioFormat, AudioEncoding

from app.config import settings
from app.models import TranscriptTurn

logger = logging.getLogger("adjudicate")

AUDIO_FORMAT = AudioFormat(encoding=AudioEncoding.PCM_S16LE, sample_rate=16000)

# How long to wait for the server's end-of-transcript during teardown.
STOP_TIMEOUT_S = 10.0


class LiveTranscriber:
    """
    One instance per intake session (one phone call).

    Speaker mapping is a deliberate demo simplification: the first raw
    speaker id Speechmatics reports gets mapped to "adjuster" (they speak
    first per the call script — "Thanks for holding, Mr Ahmed..."), the
    next distinct id to "caller". Fine for a two-party FNOL call; would
    need real role metadata for anything beyond a demo.
    """

    def __init__(self, on_turn: Callable[[TranscriptTurn], None]):
        self.on_turn = on_turn
        self._speaker_role_map: dict[str, str] = {}
        self._client = AsyncClient(
            api_key=settings.speechmatics_api_key,
            url=settings.speechmatics_rt_url,
        )
        self._client.on(ServerMessageType.ADD_PARTIAL_TRANSCRIPT, self._handle_partial)
        self._client.on(ServerMessageType.ADD_TRANSCRIPT, self._handle_final)

    def _map_speaker(self, raw_speaker: Optional[str]) -> str:
        if raw_speaker is None:
            return "unknown"
        if raw_speaker not in self._speaker_role_map:
            if len(self._speaker_role_map) == 0:
                self._speaker_role_map[raw_speaker] = "adjuster"
            elif len(self._speaker_role_map) == 1:
                self._speaker_role_map[raw_speaker] = "caller"
            else:
                self._speaker_role_map[raw_speaker] = raw_speaker  # 3rd+ speaker: leave raw id
        return self._speaker_role_map[raw_speaker]

    def _extract_turn(self, message: dict, is_final: bool) -> Optional[TranscriptTurn]:
        results = message.get("results", [])
        if not results:
            return None
        words, raw_speaker = [], None
        start_time = results[0].get("start_time", 0.0)
        end_time = results[-1].get("end_time", start_time)
        for r in results:
            alts = r.get("alternatives") or []
            if not alts:
                continue
            words.append(alts[0].get("content", ""))
            raw_speaker = raw_speaker or alts[0].get("speaker")
        if not words:
            return None
        text = " ".join(words).replace(" .", ".").replace(" ,", ",").replace(" ?", "?")
        return TranscriptTurn(
            speaker=self._map_speaker(raw_speaker),
            text=text,
            start_time=start_time,
            end_time=end_time,
            is_final=is_final,
        )

    def _handle_partial(self, message: dict) -> None:
        turn = self._extract_turn(message, is_final=False)
        if turn:
            self.on_turn(turn)

    def _handle_final(self, message: dict) -> None:
        turn = self._extract_turn(message, is_final=True)
        if turn:
            self.on_turn(turn)

    async def start(self) -> None:
        await self._client.start_session(
            transcription_config=TranscriptionConfig(
                language="en",
                diarization="speaker",
                enable_partials=True,
                max_delay=2,
            ),
            audio_format=AUDIO_FORMAT,
        )

    async def push_audio(self, chunk: bytes) -> None:
        await self._client.send_audio(chunk)

    async def stop(self) -> None:
        """
        Graceful teardown: stop_session() sends end-of-stream and waits for
        the server's end-of-transcript before closing, so the last utterance
        still arrives. close() alone does NOT wait — its own docstring warns
        about exactly that, and in this demo the final turn is where the
        damage amount and repair shop are stated.

        Bounded, because that wait depends on the server replying: if it
        doesn't, fall back to the abrupt close rather than hanging the
        WebSocket handler and never producing a dossier.
        """
        try:
            await asyncio.wait_for(self._client.stop_session(), timeout=STOP_TIMEOUT_S)
        except Exception:
            logger.warning("graceful stop_session failed or timed out — closing abruptly", exc_info=True)
            try:
                await self._client.close()
            except Exception:
                logger.exception("transcriber close failed")
