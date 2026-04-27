"""
J.A.R.V.I.S. — Unified LLM layer with multi-provider auto-failover.

All providers expose the OpenAI Chat Completions interface, so we use a single
HTTP path for everything. Order is configurable via LLM_PROVIDERS:

    groq        — Llama 3.3 70B Versatile (primary, fast, free)
    cerebras    — Llama 3.3 70B (very fast, free)
    openrouter  — :free models (free tier)
    gemini      — Google's OpenAI-compatible endpoint (last resort)

For each provider we walk a list of models. If a model 429s, errors out, or
isn't found, we fall through to the next model, then the next provider — so a
quota hit never becomes a user-facing failure.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

import httpx

logger = logging.getLogger("jarvis.llm")

DEFAULT_TIMEOUT = float(os.getenv("LLM_TIMEOUT", "45"))


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    provider: str = ""
    model: str = ""


class LLMError(RuntimeError):
    """Raised when an individual provider/model call fails."""


# ── Provider catalogue ────────────────────────────────────────────────────────

@dataclass
class ProviderConfig:
    name: str
    base_url: str
    api_key_env: str
    default_models: list[str]
    extra_headers: dict[str, str] = field(default_factory=dict)


def _env_models(env_name: str, fallback: list[str]) -> list[str]:
    """Read a comma-separated model list from env, or use the defaults.

    Env value REPLACES the defaults so that an explicit override is honoured
    exactly. Cross-provider failover still rescues a bad list.
    """
    raw = os.getenv(env_name, "")
    if not raw.strip():
        return list(fallback)
    return [m.strip() for m in raw.split(",") if m.strip()]


PROVIDERS: dict[str, ProviderConfig] = {
    "groq": ProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
        default_models=_env_models(
            "GROQ_MODELS",
            [
                # gpt-oss-120b leads — much higher daily quota and stable tool calling
                "openai/gpt-oss-120b",
                "openai/gpt-oss-20b",
                "llama-3.3-70b-versatile",
                "llama-3.1-8b-instant",
            ],
        ),
    ),
    "cerebras": ProviderConfig(
        name="cerebras",
        base_url="https://api.cerebras.ai/v1",
        api_key_env="CEREBRAS_API_KEY",
        default_models=_env_models(
            "CEREBRAS_MODELS",
            ["llama-3.3-70b", "llama3.1-8b", "qwen-3-32b"],
        ),
    ),
    "openrouter": ProviderConfig(
        name="openrouter",
        base_url="https://openrouter.ai/api/v1",
        api_key_env="OPENROUTER_API_KEY",
        default_models=_env_models(
            "OPENROUTER_MODELS",
            [
                "meta-llama/llama-3.3-70b-instruct:free",
                "mistralai/mistral-small-3.1-24b-instruct:free",
                "google/gemma-3-27b-it:free",
            ],
        ),
        extra_headers={
            "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "https://jarvis.local"),
            "X-Title": os.getenv("OPENROUTER_TITLE", "J.A.R.V.I.S."),
        },
    ),
    "gemini": ProviderConfig(
        name="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        api_key_env="GEMINI_API_KEY",
        default_models=_env_models(
            "GEMINI_MODELS_LIST",
            [
                # gemini-1.5-flash is decommissioned on the OpenAI shim — keep
                # only models that still resolve.
                os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                "gemini-2.5-flash-lite",
                "gemini-2.0-flash",
            ],
        ),
    ),
}


def enabled_providers() -> list[ProviderConfig]:
    """Return providers in priority order that have an API key configured."""
    order = [
        p.strip().lower()
        for p in os.getenv("LLM_PROVIDERS", "groq,cerebras,openrouter,gemini").split(",")
        if p.strip()
    ]
    out: list[ProviderConfig] = []
    for name in order:
        cfg = PROVIDERS.get(name)
        if cfg and os.getenv(cfg.api_key_env, "").strip():
            out.append(cfg)
    return out


# ── HTTP call ─────────────────────────────────────────────────────────────────

_RETRYABLE_KEYWORDS = (
    "429", "quota", "resource_exhausted", "rate limit", "rate_limit",
    "timeout", "timed out", "503", "502", "504", "500",
    "not found", "model_not_found", "unsupported", "decommissioned",
    "tool_use_failed", "internal_server_error", "overloaded",
    "context_length", "max_tokens",
)


def _is_retryable(msg: str) -> bool:
    msg_l = msg.lower()
    return any(s in msg_l for s in _RETRYABLE_KEYWORDS)


# ── Per-model cooldown registry ──────────────────────────────────────────────
# When a provider returns 429 with a "try again in Xs" hint, we record an
# epoch-time at which that model becomes eligible again. Models still in
# cooldown are skipped without burning an HTTP round-trip.

import time as _time

_MODEL_COOLDOWN: dict[str, float] = {}  # key: "provider/model"  →  unix-ts ready_at


def _cooldown_key(provider: str, model: str) -> str:
    return f"{provider}/{model}"


def _is_in_cooldown(provider: str, model: str) -> tuple[bool, float]:
    ready = _MODEL_COOLDOWN.get(_cooldown_key(provider, model), 0.0)
    now = _time.time()
    return (ready > now, max(0.0, ready - now))


def _set_cooldown(provider: str, model: str, seconds: float) -> None:
    _MODEL_COOLDOWN[_cooldown_key(provider, model)] = _time.time() + max(1.0, seconds)


def _parse_cooldown_seconds(error_msg: str) -> float:
    """Extract Groq/Gemini-style 'try again in 9.42s' or '52m30s' hints."""
    import re as _re
    msg = error_msg.lower()

    # "tokens per day (TPD)" → assume locked until tomorrow (worst case 1 day)
    if "tokens per day" in msg or "tpd" in msg or "requests per day" in msg or "rpd" in msg:
        # Use the explicit "try again in Xm Ys" if present (Groq gives this)
        m = _re.search(r"try again in\s+([0-9hms\.\s]+)", msg)
        if m:
            return _parse_duration(m.group(1))
        return 3600.0  # 1h default for daily caps

    m = _re.search(r"try again in\s+([0-9hms\.\s]+)", msg)
    if m:
        return _parse_duration(m.group(1))

    # Generic 429 — short cooldown
    if "429" in msg or "rate limit" in msg or "rate_limit" in msg:
        return 30.0
    return 0.0


def _parse_duration(s: str) -> float:
    """Parse '9.42s', '51m45s', '1h2m3s' → seconds."""
    import re as _re
    s = s.strip()
    total = 0.0
    for val, unit in _re.findall(r"([0-9]*\.?[0-9]+)\s*(h|m|s)?", s):
        try:
            v = float(val)
        except ValueError:
            continue
        if unit == "h":
            total += v * 3600
        elif unit == "m":
            total += v * 60
        else:
            total += v
    return total or 30.0


def _normalise_messages(messages: list[dict]) -> list[dict]:
    """Ensure messages are clean OpenAI-format dicts."""
    out: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            continue
        clean = {"role": role}
        if "content" in m and m["content"] is not None:
            clean["content"] = m["content"]
        else:
            clean["content"] = ""
        if role == "assistant" and m.get("tool_calls"):
            clean["tool_calls"] = m["tool_calls"]
            # OpenAI requires content=null when tool_calls present, but most
            # providers accept empty string too. Use None for max compat.
            if not clean["content"]:
                clean["content"] = None  # type: ignore[assignment]
        if role == "tool":
            clean["tool_call_id"] = m.get("tool_call_id") or ""
            if m.get("name"):
                clean["name"] = m["name"]
        out.append(clean)
    return out


async def _call_openai_compatible(
    cfg: ProviderConfig,
    model: str,
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    system: Optional[str] = None,
    temperature: float = 0.8,
    timeout: float = DEFAULT_TIMEOUT,
) -> LLMResponse:
    """Call any OpenAI Chat Completions–compatible endpoint."""
    api_key = os.getenv(cfg.api_key_env, "").strip()
    if not api_key:
        raise LLMError(f"{cfg.name}: API key missing")

    msgs = _normalise_messages(messages)
    if system and (not msgs or msgs[0].get("role") != "system"):
        msgs = [{"role": "system", "content": system}] + msgs

    payload: dict[str, Any] = {
        "model": model,
        "messages": msgs,
        "temperature": temperature,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        **cfg.extra_headers,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as http:
            resp = await http.post(
                f"{cfg.base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        raise LLMError(f"{cfg.name}/{model}: timeout") from exc
    except httpx.HTTPError as exc:
        raise LLMError(f"{cfg.name}/{model}: network error — {exc}") from exc

    if resp.status_code >= 400:
        snippet = resp.text[:300].replace("\n", " ")
        raise LLMError(f"{cfg.name}/{model}: HTTP {resp.status_code} — {snippet}")

    try:
        data = resp.json()
    except Exception as exc:
        raise LLMError(f"{cfg.name}/{model}: bad JSON — {exc}")

    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}

    content = msg.get("content") or ""
    if not isinstance(content, str):
        # Some providers return list-of-parts; flatten.
        try:
            content = "".join(
                p.get("text", "") for p in content if isinstance(p, dict)
            )
        except Exception:
            content = str(content)

    raw_calls = msg.get("tool_calls") or []
    parsed: list[ToolCall] = []
    for i, tc in enumerate(raw_calls):
        fn = tc.get("function") or {}
        try:
            args_raw = fn.get("arguments") or "{}"
            args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
        except Exception:
            args = {}
        parsed.append(
            ToolCall(
                id=tc.get("id") or f"call_{i}",
                name=fn.get("name") or "",
                arguments=args,
            )
        )

    return LLMResponse(
        content=content,
        tool_calls=parsed,
        provider=cfg.name,
        model=model,
    )


# ── Public client with auto-failover ──────────────────────────────────────────

StatusCallback = Callable[[str], Awaitable[None]]


class LLMClient:
    """Multi-provider LLM with automatic failover.

    Walks (provider × model) combinations in priority order until one returns a
    successful response. Auth errors skip the rest of that provider; everything
    else is retryable and falls through to the next model/provider.
    """

    def __init__(self, on_status: Optional[StatusCallback] = None):
        self._on_status = on_status

    async def _notify(self, message: str) -> None:
        if not self._on_status:
            return
        try:
            await self._on_status(message)
        except Exception:
            pass

    async def generate(
        self,
        messages: list[dict],
        tools: Optional[list[dict]] = None,
        system: Optional[str] = None,
        temperature: float = 0.8,
    ) -> LLMResponse:
        providers = enabled_providers()
        if not providers:
            raise LLMError(
                "No LLM provider configured. Set GROQ_API_KEY (or "
                "CEREBRAS_API_KEY / OPENROUTER_API_KEY / GEMINI_API_KEY)."
            )

        last_err: Optional[str] = None
        attempts = 0
        skipped: list[str] = []

        for cfg in providers:
            for model in cfg.default_models:
                # Skip models still cooling down from a recent 429.
                in_cd, secs_left = _is_in_cooldown(cfg.name, model)
                if in_cd:
                    skipped.append(f"{cfg.name}/{model} (cooldown {secs_left:.0f}s)")
                    continue

                attempts += 1
                try:
                    if attempts > 1:
                        logger.info(f"LLM trying {cfg.name}/{model}")
                    return await _call_openai_compatible(
                        cfg=cfg,
                        model=model,
                        messages=messages,
                        tools=tools,
                        system=system,
                        temperature=temperature,
                    )
                except LLMError as exc:
                    msg = str(exc)
                    last_err = msg
                    logger.warning(msg)
                    if "API key missing" in msg:
                        break  # skip to next provider

                    # Park rate-limited models so we don't keep hammering them.
                    cd_secs = _parse_cooldown_seconds(msg)
                    if cd_secs > 0:
                        _set_cooldown(cfg.name, model, cd_secs)
                        logger.info(
                            f"  ↳ cooling down {cfg.name}/{model} for {cd_secs:.0f}s"
                        )

                    if not _is_retryable(msg):
                        await self._notify(f"{cfg.name} failed; falling back…")
                        continue
                    await self._notify("Switching to backup model…")

        # If everyone was skipped due to cooldown, try the one with the
        # shortest remaining cooldown anyway (better than failing).
        if attempts == 0 and _MODEL_COOLDOWN:
            soonest = min(_MODEL_COOLDOWN.items(), key=lambda kv: kv[1])
            key = soonest[0]
            for cfg in providers:
                for model in cfg.default_models:
                    if _cooldown_key(cfg.name, model) == key:
                        logger.info(f"All models in cooldown; forcing {key}")
                        try:
                            return await _call_openai_compatible(
                                cfg=cfg, model=model,
                                messages=messages, tools=tools,
                                system=system, temperature=temperature,
                            )
                        except LLMError as exc:
                            last_err = str(exc)

        raise LLMError(
            f"All LLM providers failed. Last error: {last_err}. "
            f"Skipped (cooldown): {', '.join(skipped) or 'none'}"
        )


# ── Tool conversion ───────────────────────────────────────────────────────────

def _clean_schema(schema: dict) -> dict:
    """Ensure JSON schema is valid for OpenAI tool spec.

    Some providers (esp. Gemini's OpenAI shim) reject unexpected keys, so we
    keep only the OpenAPI-subset Whisper, Groq, etc. all accept.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    out: dict[str, Any] = {}
    t = schema.get("type", "object")
    out["type"] = t

    if "description" in schema:
        out["description"] = schema["description"]

    if "enum" in schema:
        out["enum"] = schema["enum"]

    if t == "object":
        props = schema.get("properties") or {}
        out["properties"] = {k: _clean_schema(v) for k, v in props.items()}
        req = schema.get("required") or []
        if req:
            out["required"] = list(req)
    elif t == "array" and "items" in schema:
        out["items"] = _clean_schema(schema["items"])

    return out


def mcp_tools_to_openai(mcp_tools) -> list[dict]:
    """Convert a list of MCP Tool objects to OpenAI-compatible tool specs."""
    out: list[dict] = []
    for tool in mcp_tools:
        schema = tool.inputSchema if tool.inputSchema else {"type": "object", "properties": {}}
        cleaned = _clean_schema(schema)
        if cleaned.get("type") == "object" and "properties" not in cleaned:
            cleaned["properties"] = {}
        out.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": (tool.description or "")[:1024],
                    "parameters": cleaned,
                },
            }
        )
    return out


# ── Convenience text-only helpers ─────────────────────────────────────────────

async def generate_text(
    prompt: str,
    system: str = "",
    temperature: float = 0.7,
) -> str:
    """One-shot text completion across the failover chain."""
    client = LLMClient()
    resp = await client.generate(
        messages=[{"role": "user", "content": prompt}],
        tools=None,
        system=system or None,
        temperature=temperature,
    )
    return (resp.content or "").strip()
