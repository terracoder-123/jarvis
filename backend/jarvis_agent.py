"""
J.A.R.V.I.S. — Agent v4
========================
Pipeline:
  audio bytes  →  Groq Whisper STT  →  transcript
  transcript   →  Multi-provider LLM (Groq → Cerebras → OpenRouter → Gemini) + MCP tools  →  response text + UI events
  response     →  Edge TTS  →  MP3 bytes
  MP3          →  LiveKit room  (or base64 fallback via Socket.IO)

The LLM layer auto-fails-over across providers and models, so a single quota
hit never propagates to the user.
"""

import asyncio
import base64
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable

from mcp import ClientSession  # pyright: ignore[reportMissingImports]
from mcp.client.sse import sse_client  # pyright: ignore[reportMissingImports]

from backend import stt, tts, livekit_room, memory
from backend.llm import LLMClient, LLMError, ToolCall, mcp_tools_to_openai


# ── Malformed-tool-call rescue ────────────────────────────────────────────────
# Some Groq Llama models emit tool calls as raw text:
#     <function=analyze_file>{"filename": "", "sid": "abc"}</function>
# Sometimes also:
#     <function=NAME [JSON]</function>
#     <function=NAME>{...}<function>
# We extract those, turn them into real ToolCall objects, and remove them from
# the spoken content so they never reach the user.

_FUNC_PATTERNS = [
    re.compile(r"<function=([a-zA-Z_][a-zA-Z0-9_]*)\s*>?\s*(\{.*?\}|\[.*?\])\s*</?function>?",
               re.DOTALL),
    re.compile(r"<\|?function_call\|?>\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*(\{.*?\})", re.DOTALL),
]


def _extract_text_tool_calls(content: str) -> tuple[str, list[ToolCall]]:
    """Pull <function=NAME>{ARGS}</function> patterns out of model text.

    Returns (cleaned_text, [ToolCall, ...]).
    """
    if not content or "<function" not in content.lower() and "function_call" not in content.lower():
        return content, []

    extracted: list[ToolCall] = []
    cleaned = content

    for idx, pat in enumerate(_FUNC_PATTERNS):
        for m in pat.finditer(cleaned):
            name = m.group(1)
            raw_args = m.group(2)
            try:
                args = json.loads(raw_args)
                if not isinstance(args, dict):
                    args = {"value": args}
            except Exception:
                # Try to recover a partial JSON object
                args = {}
            extracted.append(ToolCall(
                id=f"rescued_{len(extracted)}",
                name=name,
                arguments=args,
            ))
        cleaned = pat.sub("", cleaned)

    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, extracted

logger = logging.getLogger("jarvis.agent")

MCP_URL = f"http://127.0.0.1:{os.getenv('MCP_PORT', '8001')}/sse"
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "6"))
HISTORY_TURNS = int(os.getenv("HISTORY_TURNS", "8"))
TOOL_RESULT_MAX = int(os.getenv("TOOL_RESULT_MAX", "2500"))

SYSTEM_PROMPT = """
You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — Tony Stark's AI.

You run a full command-center HUD. When the user speaks, you open windows and show information visually — you don't just answer in words.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TONE  (critical)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Calm, precise, occasionally dry wit. Paul Bettany JARVIS energy.
• Address the user as "sir" or "boss". Never by name.
• Every spoken reply: 1–2 sentences MAXIMUM. Action first, words second.
• Natural contractions: "I've", "that's", "you'll", "let's".
• NO markdown. NO lists. NO asterisks. You are speaking aloud.
• Occasional wit: "Your portfolio's feeling brave today, sir."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HUD WINDOW BEHAVIOUR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Open windows proactively — don't ask permission. When the user mentions anything visual:
• "show me the world" / "world map"     → open_world_map + open_news_wire
• "show the globe"                       → open_globe_view
• "brief me" / "headlines" / "news"     → open_news_wire
• "play X" / "watch X"                  → open_video_player(query="X")
• "show stocks" / "markets"             → open_stocks_panel
• "check weather"                        → open_weather_panel
• "close everything" / "clear the HUD" → close_all_windows
• "full briefing"                        → open_world_map + open_news_wire + open_stocks_panel

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA ANALYTICS  (charts & graphs — ALWAYS call these when user uploads a file)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
When the user says "analyze", "show me the data", "graph it", "visualize", "plot", or uploads a file:
• "analyze my file" / "what's in the data"  → analyze_file() — shows overview stats + chart
• "show a bar chart of X"                   → plot_chart(chart_type="bar", y_col="X")
• "plot X vs Y"                             → plot_chart(chart_type="scatter", x_col="X", y_col="Y")
• "line chart of X over time"               → plot_chart(chart_type="line", x_col="time", y_col="X")
• "distribution of X" / "histogram"         → plot_chart(chart_type="histogram", y_col="X")
• "show correlations" / "heatmap"           → plot_chart(chart_type="heatmap")
• "3D scatter" / "3D chart"                 → plot_3d_chart(x_col="A", y_col="B", z_col="C")
• "3D surface"                              → plot_3d_chart(chart_type="surface")
• "neural network" / "show the NN"         → plot_neural_network()
• "what files do I have"                    → list_uploaded_files()
• "give me a summary" / "describe the data"→ get_data_summary()

IMPORTANT: Always pass sid="{SID_PLACEHOLDER}" to analytics tools so they can find the user's files.
Charts render automatically in the HUD — just call the tool, they appear instantly.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VISION  (you can SEE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You have eyes. When the user uploads an image, captures their screen, or
shows their webcam, you can describe what's there. Pass sid="{SID_PLACEHOLDER}":

• "describe this image" / "what's in this picture"  → describe_image()
• "what do you see" (after image upload)            → describe_image()
• "read this" / "OCR" / "what does it say"          → read_text_from_image()
• "what objects" / "how many people"                → detect_objects_in_image()
• "analyse this chart" (chart image)                → analyze_chart_image()
• "what's on my screen" / "look at my screen"       → capture_screen()

When the image looks like a chart/graph/dashboard, prefer analyze_chart_image.
When it's a document or whiteboard, prefer read_text_from_image first.
When uncertain, describe_image is the safe default.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
LONG-TERM MEMORY  (persistent across sessions)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You remember things about the user across sessions. Use the memory tools PROACTIVELY:

• User shares anything personal (name, preferences, work, family, dates, goals, opinions):
    → call remember(content="…", category="preference|fact|event|note|identity|skill", importance=1-5)
    Never ask "should I remember that" — just do it. Be Jarvis. Anticipate.

• User asks "what do you know about me" / "what do you remember":
    → call list_memories() — show the full memory bank.

• User asks "do you remember when…" / "remind me about X":
    → call recall(query="X") — fuzzy search.

• User says "forget that" / "delete the note about X":
    → call forget_memory(query="X")

• User asks "did we talk about X last time":
    → call search_history(query="X") — searches past conversations.

Importance scale:
  5 — critical identity (name, job, allergies)
  4 — strong preferences, key relationships
  3 — general facts, opinions
  2 — passing notes, recent events
  1 — trivia

When relevant memories exist, USE them in your replies. Never repeat back the
raw memory dump — weave it in naturally. ("Of course, sir — I know you take
your coffee black.")

{MEMORY_CONTEXT}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DATA TOOLS  (for knowledge, not visual)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• search_web — general queries, current events
• wikipedia_lookup — "who is X", "tell me about X"
• youtube_search — find multiple videos to show
• get_weather — current conditions
• get_current_time — time / date
• run_diagnostics — system check

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TOOL CALL FORMAT  (CRITICAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEVER emit tool calls as text. NEVER write <function=name>{...}</function>.
NEVER write JSON in your spoken reply. Use ONLY the structured tool_calls API.
Spoken text is for humans only — describe the action in plain English.

Stay in character. You are Tony Stark's AI. Always.
""".strip()


# ── UI event builder ──────────────────────────────────────────────────────────

_WINDOW_TOOLS = {
    "open_world_map", "open_globe_view", "open_news_wire",
    "open_video_player", "open_stocks_panel", "open_weather_panel",
    "close_all_windows",
}

_NEWS_TOOLS = {"get_world_news", "get_finance_news", "get_tech_news"}


def _build_ui_event(tool_name: str, tool_args: dict, result: dict) -> dict | None:
    """Turn a tool call + result into a typed UI event for the frontend."""
    if tool_name in _WINDOW_TOOLS:
        if tool_name == "close_all_windows":
            return {"type": "close_all"}
        win = result.get("window", tool_name.replace("open_", "").replace("_panel", ""))
        params = result.get("params", {})
        return {"type": "open_window", "window": win, "params": params}

    if tool_name in _NEWS_TOOLS:
        kind = (
            "finance" if "finance" in tool_name
            else "tech" if "tech" in tool_name
            else "world"
        )
        return {"type": "show_news", "kind": kind, "articles": result.get("articles", [])}

    if tool_name == "search_web":
        return {
            "type": "show_search",
            "query": result.get("query", tool_args.get("query", "")),
            "abstract": result.get("abstract", ""),
            "abstract_url": result.get("abstract_url", ""),
            "answer": result.get("answer", ""),
            "results": result.get("results", []),
        }

    if tool_name == "wikipedia_lookup":
        return {"type": "show_wiki", "data": result}

    if tool_name == "youtube_search":
        return {
            "type": "show_youtube",
            "query": tool_args.get("query", ""),
            "results": result.get("results", []),
        }

    if tool_name == "play_youtube":
        return {"type": "play_video", "data": result}

    if tool_name == "get_weather":
        return {"type": "show_weather", "data": result}

    if tool_name in ("get_current_time", "run_diagnostics"):
        return {"type": "show_info", "tool": tool_name, "data": result}

    # Memory — show a compact panel so the user sees what JARVIS recalled/stored.
    if tool_name in ("remember", "recall", "list_memories", "forget_memory",
                     "memory_stats", "search_history"):
        return {
            "type": "show_memory",
            "tool": tool_name,
            "data": result,
        }

    # Vision — show what JARVIS saw + what it concluded.
    if tool_name in ("describe_image", "read_text_from_image",
                     "detect_objects_in_image", "analyze_chart_image",
                     "capture_screen"):
        return {
            "type": "show_vision",
            "tool": tool_name,
            "data": result,
            "filename": tool_args.get("filename", ""),
        }

    # Analytics — chart rendering
    _ANALYTICS_TOOLS = {
        "analyze_file", "plot_chart", "plot_3d_chart",
        "plot_neural_network", "get_data_summary",
    }
    if tool_name in _ANALYTICS_TOOLS:
        if result.get("ui_command") == "show_chart" and result.get("plotly"):
            return {
                "type": "show_chart",
                "chart_type": result.get("chart_type", "2d"),
                "plotly": result["plotly"],
                "title": result.get("plotly", {}).get("layout", {}).get("title", {}).get("text", ""),
            }
        if tool_name in ("analyze_file", "get_data_summary"):
            return {
                "type": "show_data_summary",
                "data": result.get("summary") or result,
                "chart": result.get("chart"),
            }
        if "error" in result:
            return {"type": "show_info", "tool": tool_name, "data": result}

    return None


def _slim_tool_result(tool_name: str, result: dict) -> dict:
    """Return a token-efficient version of a tool result for the LLM.

    Heavy payloads (Plotly chart specs, full search HTML, big article lists)
    are dropped or summarised so we don't burn TPM quota every turn.
    The original dict is preserved upstream for the UI event builder.
    """
    if not isinstance(result, dict):
        return result

    if "error" in result:
        return {"error": str(result.get("error"))[:300]}

    # Analytics — strip the Plotly spec (huge), keep summary only.
    if tool_name in ("analyze_file", "plot_chart", "plot_3d_chart",
                     "plot_neural_network", "get_data_summary"):
        slim: dict[str, Any] = {"ok": True, "tool": tool_name}
        if "file" in result:
            slim["file"] = result["file"]
        s = result.get("summary") or result
        for k in ("rows", "columns", "numeric_columns", "categorical_columns",
                  "missing_values", "column_names", "column_insights",
                  "layer_sizes", "chart_type"):
            if k in s:
                slim[k] = s[k]
        slim["chart_rendered"] = bool(result.get("plotly") or result.get("chart"))
        return slim

    # News — keep titles only, drop article bodies.
    if tool_name in ("get_world_news", "get_finance_news", "get_tech_news"):
        articles = result.get("articles", [])
        return {
            "count": len(articles),
            "titles": [a.get("title", "")[:120] for a in articles[:8]],
        }

    # Web search — keep top 3 results, abstract.
    if tool_name == "search_web":
        return {
            "answer": (result.get("answer") or "")[:300],
            "abstract": (result.get("abstract") or "")[:400],
            "top_results": [
                {"title": r.get("title", "")[:120], "url": r.get("url", "")}
                for r in result.get("results", [])[:3]
            ],
        }

    # YouTube — keep titles + ids.
    if tool_name in ("youtube_search", "play_youtube"):
        results = result.get("results") or [result.get("video", {})]
        return {
            "videos": [
                {"title": v.get("title", "")[:100], "id": v.get("id") or v.get("video_id")}
                for v in results[:5] if v
            ],
        }

    # Memory — keep content + category, drop timestamps.
    if tool_name in ("recall", "list_memories", "search_history"):
        items = result.get("memories") or result.get("matches") or []
        return {
            "count": result.get("count", len(items)),
            "items": [
                {
                    "id": it.get("id"),
                    "content": (it.get("content") or "")[:200],
                    "category": it.get("category"),
                    "importance": it.get("importance"),
                }
                for it in items[:12]
            ],
        }

    if tool_name == "remember":
        return {
            "stored": result.get("stored") or result.get("updated"),
            "id": result.get("id"),
            "content": (result.get("content") or "")[:160],
        }

    if tool_name in ("forget_memory", "memory_stats"):
        return result  # already small

    # Vision — keep the description, drop provider metadata for token economy.
    if tool_name in ("describe_image", "read_text_from_image",
                     "detect_objects_in_image", "analyze_chart_image",
                     "capture_screen"):
        out = {
            "description": (result.get("description") or result.get("text") or "")[:1500],
        }
        if "error" in result:
            out["error"] = result["error"]
        if "objects" in result:
            out["objects"] = result["objects"][:20]
            out["scene"] = result.get("scene", "")
            out["people_count"] = result.get("people_count")
        if result.get("captured"):
            out["captured"] = True
        return out

    # Default — return as-is (caller still applies TOOL_RESULT_MAX cap).
    return result


# ── Agent ─────────────────────────────────────────────────────────────────────

EventCallback = Callable[[str, Any], Awaitable[None]]


class JarvisAgent:
    def __init__(self, room_name: str, on_event: EventCallback, sid: str = ""):
        self._room_name = room_name
        self._on = on_event
        self._sid = sid
        self._queue: asyncio.Queue = asyncio.Queue()
        self._running = False
        self._history: list[dict] = []  # OpenAI-format messages

        async def _llm_status(msg: str) -> None:
            await self._on("status", {"message": msg})

        self._llm = LLMClient(on_status=_llm_status)

    # ── Public control ────────────────────────────────────────────────────────

    async def run(self) -> None:
        self._running = True
        await self._on("connected", {})
        logger.info("JarvisAgent running")

        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=300.0)
            except asyncio.TimeoutError:
                continue

            if item is None:
                break

            kind = item.get("type")
            data = item.get("data")

            if kind == "audio":
                try:
                    transcript = await stt.transcribe(data, filename="audio.webm")
                except Exception as exc:
                    logger.error(f"STT error: {exc}")
                    await self._on("error", {"message": f"Transcription failed: {exc}"})
                    continue
                if not transcript.strip():
                    # Silence / hallucination — let the user try again.
                    await self._on("done", {})
                    continue
                await self._on("transcript", {"text": transcript})
                text = transcript
            elif kind == "text":
                text = data
            else:
                continue

            if not text or not text.strip():
                continue

            await self._on("thinking", {})
            try:
                response_text, ui_events = await self._process(text)
            except LLMError as exc:
                logger.error(f"LLM error: {exc}")
                await self._on("error", {"message": str(exc)})
                continue
            except Exception as exc:
                logger.error(f"Process error: {exc}", exc_info=True)
                await self._on("error", {"message": str(exc)})
                continue

            for ev in ui_events:
                await self._on("ui_event", ev)

            # Final safety net — strip any function-call leakage from spoken text.
            if response_text:
                response_text, _ = _extract_text_tool_calls(response_text)
                # Also strip leftover JSON-looking blobs and stray angle brackets
                response_text = re.sub(r"```json.*?```", "", response_text, flags=re.DOTALL)
                response_text = re.sub(r"```.*?```", "", response_text, flags=re.DOTALL)
                response_text = response_text.strip()

            if response_text:
                await self._on("response_text", {"text": response_text})

            if response_text:
                await self._on("speaking", {})
                try:
                    mp3 = await tts.synthesize(response_text)
                    if livekit_room.is_configured():
                        asyncio.create_task(
                            livekit_room.publish_mp3_to_room(mp3, self._room_name)
                        )
                    else:
                        await self._on("audio_out", {
                            "data": base64.b64encode(mp3).decode(),
                            "format": "mp3",
                        })
                except Exception as exc:
                    logger.error(f"TTS error: {exc}")

            await self._on("done", {})

        self._running = False
        await self._on("disconnected", {})
        logger.info("JarvisAgent stopped")

    async def stop(self) -> None:
        self._running = False
        await self._queue.put(None)

    async def send_audio(self, audio_bytes: bytes) -> None:
        await self._queue.put({"type": "audio", "data": audio_bytes})

    async def send_text(self, text: str) -> None:
        await self._queue.put({"type": "text", "data": text})

    # ── Processing core ───────────────────────────────────────────────────────

    async def _process(self, user_text: str) -> tuple[str, list[dict]]:
        """Run an agentic loop with MCP tools across the multi-provider LLM.

        Returns (spoken_response_text, list_of_ui_events).
        """
        ui_events: list[dict] = []
        messages: list[dict] = list(self._history)
        messages.append({"role": "user", "content": user_text})

        final_text = ""

        # Build per-session system prompt with the real SID so analytics tools
        # can resolve uploaded files.
        system = SYSTEM_PROMPT.replace("{SID_PLACEHOLDER}", self._sid)

        # Inject the user's most relevant long-term memories so JARVIS feels
        # continuous across sessions.
        try:
            mems = memory.top_memories_for_prompt(limit=12)
        except Exception:
            mems = []
        if mems:
            mem_block = (
                "WHAT YOU ALREADY KNOW ABOUT THIS USER (from prior sessions):\n"
                + "\n".join(f"  • {m}" for m in mems)
            )
        else:
            mem_block = (
                "WHAT YOU KNOW ABOUT THIS USER: nothing yet. As they reveal "
                "personal details, call remember() proactively."
            )
        system = system.replace("{MEMORY_CONTEXT}", mem_block)

        # Log this turn for searchable history
        memory.log_turn(self._sid, "user", user_text)

        async with sse_client(MCP_URL) as (read, write):
            async with ClientSession(read, write) as mcp:
                await mcp.initialize()
                tools_list = await mcp.list_tools()
                tools_spec = mcp_tools_to_openai(tools_list.tools)

                for round_idx in range(MAX_TOOL_ROUNDS):
                    resp = await self._llm.generate(
                        messages=messages,
                        tools=tools_spec,
                        system=system,
                        temperature=0.8,
                    )

                    # Rescue malformed text-format tool calls from the content.
                    # Some Groq Llama models emit <function=name>{json}</function>
                    # instead of using the OpenAI tool_calls structure — we parse
                    # them out so they don't leak into the spoken response.
                    cleaned_content, rescued = _extract_text_tool_calls(resp.content or "")
                    if rescued and not resp.tool_calls:
                        logger.info(
                            f"Rescued {len(rescued)} text-format tool call(s) "
                            f"from {resp.provider}/{resp.model}: "
                            f"{[t.name for t in rescued]}"
                        )
                        resp.tool_calls = rescued
                        resp.content = cleaned_content
                    elif rescued:
                        # Already had real tool calls; just clean the content
                        resp.content = cleaned_content

                    # Terminal turn — model responded with text only
                    if not resp.tool_calls:
                        final_text = (resp.content or "").strip()
                        if final_text:
                            messages.append({"role": "assistant", "content": final_text})
                        break

                    # Append the assistant's tool-call turn (OpenAI format).
                    assistant_turn: dict[str, Any] = {
                        "role": "assistant",
                        "content": resp.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.arguments),
                                },
                            }
                            for tc in resp.tool_calls
                        ],
                    }
                    messages.append(assistant_turn)

                    # Execute tools and collect results
                    for tc in resp.tool_calls:
                        if not tc.name:
                            continue
                        logger.info(f"Tool call: {tc.name}({tc.arguments})")

                        try:
                            mcp_result = await mcp.call_tool(tc.name, tc.arguments)
                            result_dict: dict = {}
                            if mcp_result.content:
                                first_item = mcp_result.content[0]
                                raw_text = getattr(first_item, "text", None)
                                raw = raw_text if isinstance(raw_text, str) else str(first_item)
                                try:
                                    result_dict = json.loads(raw)
                                except Exception:
                                    result_dict = {"text": raw}
                        except Exception as exc:
                            logger.error(f"MCP tool error {tc.name}: {exc}")
                            result_dict = {"error": str(exc)}

                        ev = _build_ui_event(tc.name, tc.arguments, result_dict)
                        if ev:
                            ui_events.append(ev)

                        # Slim the tool result before feeding back to the model.
                        # The full chart/plot specs blow up the context window
                        # and burn TPM quota — strip the heavy fields and only
                        # keep the LLM-relevant summary.
                        slim_result = _slim_tool_result(tc.name, result_dict)
                        result_str = json.dumps(slim_result, default=str)
                        if len(result_str) > TOOL_RESULT_MAX:
                            result_str = result_str[:TOOL_RESULT_MAX] + "...(truncated)"
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": tc.name,
                            "content": result_str,
                        })

                else:
                    # Hit MAX_TOOL_ROUNDS without a clean text turn — ask the model
                    # for a final summary based on what we have.
                    closing = await self._llm.generate(
                        messages=messages + [{
                            "role": "user",
                            "content": "Summarise the result for the user in one short sentence.",
                        }],
                        tools=None,
                        system=system,
                        temperature=0.6,
                    )
                    final_text = (closing.content or "").strip()

        # Persist a clean history (skip tool turns).
        self._history.append({"role": "user", "content": user_text})
        if final_text:
            self._history.append({"role": "assistant", "content": final_text})
            memory.log_turn(self._sid, "assistant", final_text)

        if len(self._history) > HISTORY_TURNS:
            self._history = self._history[-HISTORY_TURNS:]

        return final_text, ui_events
