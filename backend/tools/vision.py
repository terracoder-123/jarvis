"""
JARVIS Vision Tools — wrappers around the multi-provider vision LLM.

Exposes:
  describe_image    — full description / Q&A about an image
  read_text         — OCR / extract text from an image
  detect_objects    — list visible objects with rough positions
  capture_screen    — server-side screenshot, then describe it
  analyze_chart     — focused on charts/graphs/diagrams
"""

from __future__ import annotations

import base64
import io
import logging
from pathlib import Path
from typing import Optional

from backend import vision_llm

logger = logging.getLogger("jarvis.vision_tools")


async def describe_image(image_path: str, question: str = "") -> dict:
    """Describe an image, or answer a specific question about it."""
    prompt = question.strip() or (
        "You are JARVIS, Tony Stark's AI. Describe what you see in this image "
        "in 2-3 calm, precise sentences. Note key objects, colours, mood, and "
        "anything unusual. Speak as JARVIS would — concise, dry wit if fitting."
    )
    return await vision_llm.analyze(image_path, prompt=prompt, max_tokens=500)


async def read_text(image_path: str) -> dict:
    """Extract all readable text from an image (OCR)."""
    prompt = (
        "Extract ALL text visible in this image. Preserve the original layout "
        "as best you can. Return only the extracted text, nothing else. "
        "If no text is present, respond with: NO_TEXT_FOUND."
    )
    result = await vision_llm.analyze(image_path, prompt=prompt, max_tokens=2000)
    if "description" in result:
        text = result["description"]
        result["text"] = text
        result["empty"] = "NO_TEXT_FOUND" in text.upper()
    return result


async def detect_objects(image_path: str) -> dict:
    """Identify visible objects + a brief scene summary."""
    prompt = (
        "List the main objects, people, and elements visible in this image. "
        "Format as a JSON object with keys: 'scene' (one-sentence summary), "
        "'objects' (array of strings), 'people_count' (integer), "
        "'dominant_colours' (array of 3-5 colour names). Return ONLY the JSON."
    )
    result = await vision_llm.analyze(image_path, prompt=prompt, max_tokens=600)
    if "description" in result:
        # Try to parse the JSON the model returned
        import json
        import re
        raw = result["description"]
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                parsed = json.loads(m.group(0))
                result.update(parsed)
            except Exception:
                pass
    return result


async def analyze_chart(image_path: str) -> dict:
    """Focused analysis of charts, graphs, dashboards, diagrams."""
    prompt = (
        "This image contains a chart, graph, or data visualisation. "
        "Identify: 1) the chart type, 2) the variables shown, 3) the key "
        "insight or trend, 4) any notable outliers. Be precise and concise. "
        "If no chart is present, say so."
    )
    return await vision_llm.analyze(image_path, prompt=prompt, max_tokens=700)


async def capture_screen(monitor: int = 1, question: str = "") -> dict:
    """
    Take a server-side screenshot of the user's primary monitor and analyse it.
    Requires `mss` (added to requirements). Falls back to error if unavailable
    or if running headless.
    """
    try:
        import mss  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError:
        return {
            "error": "Screenshot dependencies missing. Install with: pip install mss pillow"
        }

    try:
        with mss.mss() as sct:
            mon_idx = max(1, min(monitor, len(sct.monitors) - 1))
            mon = sct.monitors[mon_idx]
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")

            # Downscale to keep payload small (vision models prefer ≤ 1280px)
            max_w = 1280
            if img.width > max_w:
                ratio = max_w / img.width
                img = img.resize(
                    (max_w, int(img.height * ratio)), Image.Resampling.LANCZOS
                )

            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=82)
            data_url = (
                "data:image/jpeg;base64,"
                + base64.b64encode(buf.getvalue()).decode()
            )
    except Exception as exc:
        return {"error": f"screen capture failed: {exc}"}

    prompt = question.strip() or (
        "You are JARVIS. The user just captured their screen. Tell them what "
        "they're looking at — what application or website appears active, "
        "what the user seems to be doing, and any notable on-screen elements. "
        "Two or three calm sentences."
    )
    result = await vision_llm.analyze(data_url, prompt=prompt, max_tokens=500)
    result["captured"] = True
    result["monitor"] = mon_idx
    return result
