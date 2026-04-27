"""
AI Summary Layer
================
Converts raw world data into natural-language insights via the unified
multi-provider LLM cascade (Groq → Cerebras → OpenRouter → Gemini).

These functions are async — call sites in server.py already run in an async
context. A failed provider just falls through; if every provider is down we
return a graceful placeholder rather than raising.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from backend.llm import generate_text, LLMError

logger = logging.getLogger("jarvis.ai")


def configure_gemini(_api_key: str) -> None:
    """Kept for backward-compat with existing imports — the LLM layer reads
    keys from the environment directly, so this is a no-op now.
    """
    return None


async def _safe_generate(prompt: str, system: str = "") -> str:
    try:
        return await generate_text(prompt, system=system, temperature=0.7)
    except LLMError as exc:
        logger.warning(f"AI summary unavailable: {exc}")
        return ""
    except Exception as exc:
        logger.error(f"AI summary error: {exc}")
        return ""


async def summarize_world_population(data: Dict[str, Any]) -> str:
    """Generate a JARVIS-style briefing of world population data."""
    if not data or "population" not in data:
        return "Unable to fetch population data."

    pop_data = data.get("population", {}) or {}
    if "error" in pop_data:
        return f"Data unavailable: {pop_data['error']}"

    prompt = f"""
Based on this live world data, give a SHORT (1-2 sentence) compelling summary
suitable for a voice interface. Make it feel like JARVIS briefing Iron Man.

Data:
- Current World Population: {pop_data.get('population', 'N/A')}
- Births Today: {pop_data.get('births_today', 'N/A')}
- Deaths Today: {pop_data.get('deaths_today', 'N/A')}

Summary (voice-friendly, dramatic but accurate):
""".strip()

    text = await _safe_generate(prompt)
    return text or "Population data online; figures are climbing on schedule, sir."


async def summarize_covid_data(data: Dict[str, Any]) -> str:
    """One-line COVID briefing."""
    if not data or "covid" not in data:
        return "Unable to fetch COVID data."

    covid_data = data.get("covid", {}) or {}
    if "error" in covid_data:
        return f"Data unavailable: {covid_data['error']}"

    prompt = f"""
Give a BRIEF (1 sentence) COVID-19 briefing based on this data:
- Total Cases: {covid_data.get('total_cases', 'N/A')}
- Deaths: {covid_data.get('total_deaths', 'N/A')}
- Recovered: {covid_data.get('total_recovered', 'N/A')}

Keep it factual and concise for voice delivery.
""".strip()

    text = await _safe_generate(prompt)
    return text or "COVID figures retrieved, sir."


async def analyze_world_metrics(data: Dict[str, Any]) -> str:
    """Deeper analysis of world metrics."""
    prompt = f"""
Analyze this live world data and provide 2-3 key insights for a CEO briefing:

{str(data)[:4000]}

Keep it professional, data-driven, and actionable.
""".strip()

    text = await _safe_generate(prompt)
    return text or "Analysis temporarily unavailable, sir."
