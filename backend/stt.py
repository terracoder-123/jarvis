"""
Speech-to-Text via Groq Whisper API (free tier).

Defaults to `whisper-large-v3` — the most accurate openly available model — and
biases recognition toward the JARVIS command vocabulary so quiet speech and
mic noise don't collapse into nonsense.

Sign up: https://console.groq.com/keys (no credit card required).
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from groq import AsyncGroq  # pyright: ignore[reportMissingImports]

logger = logging.getLogger("jarvis.stt")

_client: Optional[AsyncGroq] = None

# `whisper-large-v3` is more accurate than `-turbo`. Override via env if you
# want the faster turbo variant or one of the distilled models.
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3")
STT_FALLBACK_MODEL = os.getenv("STT_FALLBACK_MODEL", "whisper-large-v3-turbo")
STT_LANGUAGE = os.getenv("STT_LANGUAGE", "en")

# Drop blobs smaller than this — almost certainly silence / button-tap noise.
MIN_AUDIO_BYTES = int(os.getenv("STT_MIN_BYTES", "1500"))

# Anchor recognition with names + commands likely to appear. This dramatically
# reduces mishears like "JARVIS" → "service" or "show the globe" → "showed
# the glove". Whisper uses the prompt to bias next-token probabilities.
STT_PROMPT = os.getenv(
    "STT_PROMPT",
    (
        "JARVIS, sir, boss, Tony Stark, Stark Industries. "
        "Show me the world map. Show the globe. Open the news wire. "
        "Brief me. Headlines. Play, watch, put on. Search the web. "
        "Wikipedia. Who is, what is, tell me about. "
        "Stocks, markets, finance, portfolio. Weather, temperature, forecast. "
        "Run diagnostics. Close everything. Clear the HUD. Full briefing."
    ),
)

# Common Whisper hallucinations on near-silence — drop these so the agent
# doesn't fire a tool call from background noise.
_HALLUCINATIONS = {
    "", ".", "...", "thank you.", "thanks.", "thanks for watching.",
    "thanks for watching!", "you", "yeah.", "bye.", "hmm.", "uh.",
    "okay.", "ok.", "thank you", "subtitles by the amara.org community",
    "music", "[music]", "(music)", "[music playing]",
}


def _get_client() -> AsyncGroq:
    global _client
    if _client is None:
        _client = AsyncGroq(api_key=os.getenv("GROQ_API_KEY", ""))
    return _client


def _is_hallucination(text: str) -> bool:
    return text.strip().lower() in _HALLUCINATIONS


async def _transcribe_with(model: str, audio_bytes: bytes, filename: str) -> str:
    client = _get_client()
    transcription = await client.audio.transcriptions.create(
        file=(filename, audio_bytes),
        model=model,
        language=STT_LANGUAGE,
        prompt=STT_PROMPT,
        response_format="text",
        temperature=0.0,
    )
    raw = transcription if isinstance(transcription, str) else getattr(transcription, "text", "")
    return (raw or "").strip()


async def transcribe(audio_bytes: bytes, filename: str = "audio.webm") -> str:
    """Transcribe audio bytes to text using Groq Whisper.

    Accepts: webm, mp3, mp4, m4a, mpeg, mpga, wav, flac.
    Returns the transcribed text, or an empty string for silence /
    hallucinations so the agent can quietly ignore non-speech.
    """
    if not audio_bytes or len(audio_bytes) < MIN_AUDIO_BYTES:
        logger.debug(f"STT skip: {len(audio_bytes)} bytes (< {MIN_AUDIO_BYTES})")
        return ""

    last_exc: Optional[Exception] = None
    for model in dict.fromkeys([STT_MODEL, STT_FALLBACK_MODEL]):
        try:
            text = await _transcribe_with(model, audio_bytes, filename)
        except Exception as exc:
            logger.warning(f"STT model {model} failed: {exc}")
            last_exc = exc
            continue

        if _is_hallucination(text):
            logger.info(f"STT discarded hallucination: {text!r}")
            return ""
        return text

    if last_exc:
        raise RuntimeError(f"STT failed across all models: {last_exc}")
    return ""
