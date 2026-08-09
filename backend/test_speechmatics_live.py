"""
Stage 1 in isolation — stream a .wav through Speechmatics and print turns.

This is the highest-risk piece of the pipeline and the cheapest to debug
alone, before any frontend or WebSocket is involved. If this prints [FINAL]
lines with two speaker labels, Stage 1 works and everything downstream is
just plumbing.

    python test_speechmatics_live.py test.wav

The file must be 16kHz mono 16-bit PCM — the same format the browser sends.
Convert anything else with:

    ffmpeg -i any_audio.mp3 -ar 16000 -ac 1 -c:a pcm_s16le test.wav

Costs Speechmatics minutes, not AI/ML credits. A 15s clip is enough.
"""
import asyncio
import sys
import wave

from app.config import settings
from app.models import TranscriptTurn
from app.speechmatics_client import LiveTranscriber

# Matches AUDIO_FORMAT in speechmatics_client.py.
EXPECTED_RATE = 16000
EXPECTED_CHANNELS = 1
EXPECTED_SAMPLE_WIDTH = 2  # bytes, i.e. 16-bit

CHUNK_FRAMES = 4096


def read_wav(path: str) -> bytes:
    with wave.open(path, "rb") as wav:
        rate, channels, width = wav.getframerate(), wav.getnchannels(), wav.getsampwidth()
        problems = []
        if rate != EXPECTED_RATE:
            problems.append(f"sample rate is {rate}, needs {EXPECTED_RATE}")
        if channels != EXPECTED_CHANNELS:
            problems.append(f"{channels} channels, needs mono")
        if width != EXPECTED_SAMPLE_WIDTH:
            problems.append(f"{width * 8}-bit, needs 16-bit")
        if problems:
            print("Wrong audio format: " + "; ".join(problems))
            print(f"\nFix with:\n  ffmpeg -i {path} -ar 16000 -ac 1 -c:a pcm_s16le fixed.wav")
            sys.exit(1)

        frames = wav.readframes(wav.getnframes())
        print(f"Loaded {path}: {len(frames)} bytes, {wav.getnframes() / rate:.1f}s\n")
        return frames


async def run(path: str) -> int:
    if not settings.speechmatics_api_key:
        print("SPEECHMATICS_API_KEY is not set in .env")
        return 2

    audio = read_wav(path)
    turns: list[TranscriptTurn] = []

    def on_turn(turn: TranscriptTurn) -> None:
        tag = "FINAL" if turn.is_final else "partial"
        print(f"[{tag:7}] {turn.speaker:9} | {turn.text}")
        if turn.is_final:
            turns.append(turn)

    transcriber = LiveTranscriber(on_turn=on_turn)
    await transcriber.start()

    # Feed it at roughly real time. Dumping the whole file at once can trip
    # server-side rate limits and isn't what the browser does anyway.
    bytes_per_chunk = CHUNK_FRAMES * EXPECTED_SAMPLE_WIDTH
    seconds_per_chunk = CHUNK_FRAMES / EXPECTED_RATE
    for offset in range(0, len(audio), bytes_per_chunk):
        await transcriber.push_audio(audio[offset : offset + bytes_per_chunk])
        await asyncio.sleep(seconds_per_chunk)

    await transcriber.stop()

    print(f"\n{len(turns)} final turn(s).")
    speakers = {t.speaker for t in turns}
    print(f"Speakers detected: {', '.join(sorted(speakers)) or 'none'}")

    if not turns:
        print("\nNo final transcripts. Check the API key, the region in "
              "SPEECHMATICS_RT_URL, and that the clip actually has speech.")
        return 1
    if len(speakers) < 2:
        print("\nOnly one speaker — fine if the clip is one person. For the demo "
              "you want two, so adjuster/caller mapping gets exercised.")

    print("\nStage 1 works. The transcript above is what the frontend will render.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    sys.exit(asyncio.run(run(sys.argv[1])))
