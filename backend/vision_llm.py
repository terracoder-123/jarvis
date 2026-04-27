"""
JARVIS Vision — multi-modal LLM calls with image input.

Uses the same multi-provider failover as the text LLM, but only attempts
vision-capable models. All providers expose vision via the OpenAI-compatible
chat-completions API: image_url with a data: or http: URL.

Free vision models:
  groq      — meta-llama/llama-4-scout-17b-16e-instruct (vision-capable)
              llama-3.2-90b-vision-preview (legacy fallback)
  gemini    — gemini-2.5-flash, gemini-2.0-flash (multi-modal native)
  openrouter— meta-llama/llama-3.2-11b-vision-instruct:free
              google/gemini-2.0-flash-exp:free
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger("jarvis.vision")

DEFAULT_TIMEOUT = float(os.getenv("VISION_TIMEOUT", "60"))

# (provider_name, env_var_for_key, base_url, [models...], extra_headers)
_VISION_PROVIDERS = [
    (
        "groq",
        "GROQ_API_KEY",
        "https://api.groq.com/openai/v1",
        [
            "meta-llama/llama-4-scout-17b-16e-instruct",
            "meta-llama/llama-4-maverick-17b-128e-instruct",
            "llama-3.2-90b-vision-preview",
            "llama-3.2-11b-vision-preview",
        ],
        {},
    ),
    (
        "gemini",
        "GEMINI_API_KEY",
        "https://generativelanguage.googleapis.com/v1beta/openai",
        [
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
        ],
        {},
    ),
    (
        "openrouter",
        "OPENROUTER_API_KEY",
        "https://openrouter.ai/api/v1",
        [
            "meta-llama/llama-3.2-11b-vision-instruct:free",
            "google/gemini-2.0-flash-exp:free",
            "qwen/qwen2.5-vl-72b-instruct:free",
        ],
        {
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://jarvis.local"),
            "X-Title": os.getenv("OPENROUTER_TITLE", "J.A.R.V.I.S."),
        },
    ),
]


def _file_to_data_url(image_path: str) -> str:
    p = Path(image_path)
    if not p.exists():
        raise FileNotFoundError(image_path)
    mime, _ = mimetypes.guess_type(p.name)
    if not mime or not mime.startswith("image/"):
        mime = "image/jpeg"
    raw = p.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _bytes_to_data_url(data: bytes, mime: str = "image/jpeg") -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


async def analyze(
    image: str,
    prompt: str = "Describe this image in detail.",
    max_tokens: int = 800,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict:
    """
    Send an image + prompt to a vision LLM, with provider/model failover.

    `image` may be:
      * a filesystem path
      * a data: URL (already base64-encoded)
      * an http(s):// URL
    """
    if image.startswith(("data:", "http://", "https://")):
        image_url = image
    else:
        image_url = _file_to_data_url(image)

    last_err: str = ""

    for prov_name, env_key, base_url, models, headers in _VISION_PROVIDERS:
        api_key = os.getenv(env_key, "").strip()
        if not api_key:
            continue

        for model in models:
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "temperature": 0.4,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    }
                ],
            }
            req_headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                **headers,
            }
            try:
                async with httpx.AsyncClient(timeout=timeout) as http:
                    resp = await http.post(
                        f"{base_url}/chat/completions",
                        json=payload,
                        headers=req_headers,
                    )
            except httpx.TimeoutException:
                last_err = f"{prov_name}/{model}: timeout"
                logger.warning(last_err)
                continue
            except httpx.HTTPError as exc:
                last_err = f"{prov_name}/{model}: network error {exc}"
                logger.warning(last_err)
                continue

            if resp.status_code >= 400:
                snippet = resp.text[:280].replace("\n", " ")
                last_err = f"{prov_name}/{model}: HTTP {resp.status_code} — {snippet}"
                logger.warning(last_err)
                continue

            try:
                data = resp.json()
            except Exception:
                last_err = f"{prov_name}/{model}: bad JSON"
                continue

            choice = (data.get("choices") or [{}])[0]
            msg = choice.get("message") or {}
            content = msg.get("content") or ""
            if isinstance(content, list):
                content = "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )

            if content:
                return {
                    "provider": prov_name,
                    "model": model,
                    "description": content.strip(),
                }

    return {
        "error": "All vision providers failed",
        "last_error": last_err,
    }
