"""Text-to-Speech via Microsoft edge-tts (completely free, no API key).

Uses the public Edge browser TTS endpoint via the `edge-tts` Python package.
Returns MP3 bytes — drop-in compatible with the LiveKit publisher.
"""

import edge_tts

# British male — closest to Paul Bettany's JARVIS voice.
# Other good options:
#   en-GB-ThomasNeural   — British male, refined
#   en-US-GuyNeural      — American male, deep
#   en-US-DavisNeural    — American male, conversational
#   en-US-BrandonNeural  — American male, warm
VOICE = "en-GB-RyanNeural"
RATE = "+0%"        # speed, e.g. "+10%" / "-15%"
PITCH = "+0Hz"      # pitch, e.g. "-2Hz" deeper / "+2Hz" higher


async def synthesize(text: str) -> bytes:
    """Convert text to speech. Returns MP3 bytes."""
    communicate = edge_tts.Communicate(text, VOICE, rate=RATE, pitch=PITCH)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)
