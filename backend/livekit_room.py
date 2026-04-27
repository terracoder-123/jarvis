"""LiveKit room integration — publishes TTS audio and generates browser tokens.

Falls back gracefully when LIVEKIT_* env vars are not set.
"""

import os
import asyncio
import logging
from io import BytesIO

logger = logging.getLogger("jarvis.livekit")

LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")


def is_configured() -> bool:
    return bool(LIVEKIT_URL and LIVEKIT_API_KEY and LIVEKIT_API_SECRET)


def make_agent_token(room_name: str) -> str:
    """JWT for the JARVIS backend identity (publish-only)."""
    from livekit import api
    return (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity("jarvis-agent")
        .with_name("J.A.R.V.I.S.")
        .with_grants(api.VideoGrants(room_join=True, room=room_name, can_publish=True))
        .to_jwt()
    )


def make_user_token(room_name: str, user_id: str) -> str:
    """JWT for the browser user (subscribe-only)."""
    from livekit import api
    return (
        api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET)
        .with_identity(f"user-{user_id}")
        .with_name("Commander")
        .with_grants(api.VideoGrants(
            room_join=True,
            room=room_name,
            can_subscribe=True,
            can_publish=False,
        ))
        .to_jwt()
    )


async def publish_mp3_to_room(mp3_bytes: bytes, room_name: str) -> None:
    """Decode MP3 to PCM and stream audio frames into a LiveKit room."""
    try:
        from livekit import rtc
    except ImportError:
        logger.warning("livekit SDK not installed — skipping LiveKit publish")
        return

    try:
        from pydub import AudioSegment
        seg = (
            AudioSegment.from_file(BytesIO(mp3_bytes), format="mp3")
            .set_frame_rate(48000)
            .set_channels(1)
            .set_sample_width(2)
        )
        pcm_data: bytes = seg.raw_data
        sample_rate = 48000
    except Exception as exc:
        logger.error(f"MP3 decode failed: {exc}")
        return

    token = make_agent_token(room_name)
    room = rtc.Room()

    try:
        await room.connect(LIVEKIT_URL, token)

        source = rtc.AudioSource(sample_rate=sample_rate, num_channels=1)
        track = rtc.LocalAudioTrack.create_audio_track("jarvis-voice", source)
        await room.local_participant.publish_track(track, rtc.TrackPublishOptions())

        # 20 ms frames
        samples_per_frame = sample_rate // 50   # 960 samples @ 48 kHz
        bytes_per_frame = samples_per_frame * 2  # 16-bit = 2 bytes

        for offset in range(0, len(pcm_data), bytes_per_frame):
            chunk = pcm_data[offset : offset + bytes_per_frame]
            if len(chunk) < bytes_per_frame:
                chunk = chunk + b"\x00" * (bytes_per_frame - len(chunk))
            frame = rtc.AudioFrame(
                data=chunk,
                sample_rate=sample_rate,
                num_channels=1,
                samples_per_channel=samples_per_frame,
            )
            await source.capture_frame(frame)
            await asyncio.sleep(0.018)  # slightly under 20 ms to avoid stutter

    except Exception as exc:
        logger.error(f"LiveKit publish error: {exc}")
    finally:
        try:
            await room.disconnect()
        except Exception:
            pass
