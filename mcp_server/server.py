"""JARVIS MCP Tool Server — FastMCP with SSE transport.

Run standalone:
    python -m mcp_server.server

Listens on http://127.0.0.1:MCP_PORT/sse  (default port 8001)
All backend tool logic is imported directly — no duplication.
"""

import sys
import os
from pathlib import Path

# Ensure project root is on path so `backend.tools` imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastmcp import FastMCP  # pyright: ignore[reportMissingImports]
from backend.tools import news, web, wiki, weather, youtube, system, windows, analytics, vision
from backend import data_store, memory

mcp = FastMCP(
    "JARVIS Tools",
    instructions=(
        "You are the tool layer for J.A.R.V.I.S. — Tony Stark's AI assistant. "
        "Execute tools accurately and return clean structured data."
    ),
)

# ── News ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_world_news() -> dict:
    """Fetch live global headlines from BBC, NYT, Al Jazeera, CNBC.
    Use when the user asks about world news, what's happening, or wants a briefing."""
    return await news.get_world_news()


@mcp.tool()
async def get_finance_news() -> dict:
    """Fetch finance and market headlines from CNBC, MarketWatch, NYT Business.
    Use for markets, stocks, economy, or trading questions."""
    return await news.get_finance_news()


@mcp.tool()
async def get_tech_news() -> dict:
    """Fetch technology headlines from TechCrunch, Wired, Ars Technica.
    Use for tech news, AI, startups, or gadget questions."""
    return await news.get_tech_news()

# ── Web search ────────────────────────────────────────────────────────────────

@mcp.tool()
async def search_web(query: str) -> dict:
    """Search the web via DuckDuckGo for any query.
    Use for general knowledge, current events, or anything news/wiki/weather don't cover."""
    return await web.search_web(query)

# ── Wikipedia ─────────────────────────────────────────────────────────────────

@mcp.tool()
async def wikipedia_lookup(query: str) -> dict:
    """Look up a person, place, thing, or concept on Wikipedia.
    Use when the user asks 'who is X', 'what is X', 'tell me about X'."""
    return await wiki.wikipedia_lookup(query)

# ── Weather ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_weather(location: str = "") -> dict:
    """Get current weather conditions for a location.
    Leave location empty to use the user's IP-based location.
    Use when the user asks about weather, temperature, or forecast."""
    return await weather.get_weather(location)

# ── YouTube ───────────────────────────────────────────────────────────────────

@mcp.tool()
async def youtube_search(query: str, limit: int = 8) -> dict:
    """Search YouTube for videos matching a query. Returns up to `limit` results.
    Use when the user asks to find videos or search YouTube."""
    return await youtube.youtube_search(query, limit)


@mcp.tool()
async def play_youtube(query: str) -> dict:
    """Find and return the top YouTube video matching a query for immediate playback.
    Use when the user says 'play X', 'watch X', or 'put on X'."""
    return await youtube.play_youtube(query)

# ── System ────────────────────────────────────────────────────────────────────

@mcp.tool()
async def get_current_time() -> dict:
    """Get the current local date and time.
    Use when the user asks 'what time is it' or 'what's the date'."""
    return await system.get_current_time()


@mcp.tool()
async def run_diagnostics() -> dict:
    """Run system diagnostics — OS, CPU, disk usage.
    Use when the user asks for a system check or diagnostics."""
    return await system.run_diagnostics()

# ── HUD window commands ───────────────────────────────────────────────────────

@mcp.tool()
async def open_world_map() -> dict:
    """Open the interactive world map on the HUD.
    Use when the user says 'show me the world', 'world map', or wants a geographic overview."""
    return await windows.open_world_map()


@mcp.tool()
async def open_globe_view() -> dict:
    """Open a 3D rotating globe view on the HUD.
    Use when the user says 'show the globe', '3D earth', or wants a planetary view."""
    return await windows.open_globe_view()


@mcp.tool()
async def open_news_wire() -> dict:
    """Open the live news wire panel on the HUD.
    Use when the user says 'show news', 'brief me', 'headlines', or 'what's happening'."""
    return await windows.open_news_wire()


@mcp.tool()
async def open_video_player(query: str) -> dict:
    """Search YouTube and open an auto-playing video player on the HUD.
    Use when the user says 'play X', 'watch X', or 'show me videos about X'."""
    return await windows.open_video_player(query)


@mcp.tool()
async def open_stocks_panel() -> dict:
    """Open a live stocks and markets panel on the HUD.
    Use when the user asks about markets, stocks, or financial data visually."""
    return await windows.open_stocks_panel()


@mcp.tool()
async def open_weather_panel() -> dict:
    """Open the weather HUD panel showing current conditions.
    Use when the user asks about weather or temperature visually."""
    return await windows.open_weather_panel()


@mcp.tool()
async def close_all_windows() -> dict:
    """Close all open HUD windows and return to standby.
    Use when the user says 'close everything', 'clear the HUD', or 'shut it all down'."""
    return await windows.close_all_windows()


# ── Data Analytics ───────────────────────────────────────────────────────────

# The MCP server needs to know which session's files to use.
# We use a thread-local/global SID that the JARVIS agent sets before each call.
# For simplicity we expose a module-level variable the agent injects into.
_current_sid: str = ""


def _resolve_file(filename: str, sid: str) -> str:
    """Return the absolute path for a file, or raise if not found.

    Resolution order:
      1. exact (sid, filename) — works when SID is passed
      2. most-recent file in this SID's folder
      3. most-recent file in ANY session folder (fallback when LLM forgets sid=)
    """
    if filename:
        path = data_store.get_path(sid, filename)
        if path:
            return path
    # try "most recent" for this SID
    result = data_store.get_any_path(sid)
    if result:
        return result[1]
    # last resort — most recent across all sessions on disk
    if not sid:
        result = data_store.get_any_path("")
        if result:
            return result[1]
    # try without SID even if one was given but yielded nothing
    result = data_store.get_any_path("")
    if result:
        return result[1]
    raise FileNotFoundError(
        "No uploaded file found. Ask the user to upload a file first."
    )


@mcp.tool()
async def list_uploaded_files(sid: str = "") -> dict:
    """List all files the user has uploaded in this session.
    Use when the user asks 'what files do I have' or before analyzing."""
    target_sid = sid or _current_sid
    files = data_store.list_files(target_sid)
    return {"files": files, "count": len(files)}


@mcp.tool()
async def analyze_file(filename: str = "", sid: str = "") -> dict:
    """
    Analyze an uploaded data file (CSV, Excel, JSON, Parquet).
    Returns summary statistics, correlations, and an overview chart.
    Use when the user says 'analyze my data', 'show me the stats', or 'what's in the file'.
    Leave filename empty to use the most recently uploaded file.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_file(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await analytics.analyze_file(path)


@mcp.tool()
async def plot_chart(
    chart_type: str = "auto",
    x_col: str = "",
    y_col: str = "",
    color_col: str = "",
    title: str = "",
    filename: str = "",
    sid: str = "",
) -> dict:
    """
    Generate a Plotly 2D chart from an uploaded data file.
    chart_type: auto | bar | line | scatter | histogram | pie | box | heatmap
    x_col / y_col: column names to use (leave empty for auto-select).
    Use when the user asks to 'plot', 'chart', 'graph', 'visualize', or 'show a bar chart of X'.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_file(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await analytics.plot_chart(path, chart_type, x_col, y_col, color_col, title)


@mcp.tool()
async def plot_3d_chart(
    x_col: str = "",
    y_col: str = "",
    z_col: str = "",
    color_col: str = "",
    chart_type: str = "scatter3d",
    title: str = "",
    filename: str = "",
    sid: str = "",
) -> dict:
    """
    Generate an interactive 3D Plotly chart from an uploaded data file.
    chart_type: scatter3d | surface | line3d
    Use when the user asks for a '3D chart', '3D scatter', '3D surface', or 'three dimensional graph'.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_file(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await analytics.plot_3d(path, x_col, y_col, z_col, color_col, chart_type, title)


@mcp.tool()
async def plot_neural_network(
    layer_sizes: str = "",
    filename: str = "",
    title: str = "",
    sid: str = "",
) -> dict:
    """
    Render an interactive 3D neural network graph.
    layer_sizes: comma-separated node counts per layer, e.g. '4,8,8,3'.
    Leave empty to infer from the uploaded file's column structure.
    Use when the user asks for a 'neural network graph', 'NN visualization', or 'show the architecture'.
    """
    target_sid = sid or _current_sid
    sizes: list[int] | None = None
    if layer_sizes.strip():
        try:
            sizes = [int(x.strip()) for x in layer_sizes.split(",") if x.strip()]
        except ValueError:
            pass
    path = ""
    if filename or target_sid:
        try:
            path = _resolve_file(filename, target_sid)
        except FileNotFoundError:
            pass
    return await analytics.plot_neural_network(path, sizes, title)


@mcp.tool()
async def get_data_summary(filename: str = "", sid: str = "") -> dict:
    """
    Get a concise spoken-friendly summary of an uploaded data file.
    Returns row count, column info, and key statistics.
    Use when the user asks 'what's in the data', 'give me a quick summary', or 'describe the file'.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_file(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await analytics.get_data_summary(path)


# ── Vision ────────────────────────────────────────────────────────────────────

def _resolve_image(filename: str, sid: str) -> str:
    """Resolve an image filename via data_store. Same fallback chain as analytics."""
    if filename:
        path = data_store.get_path(sid, filename)
        if path:
            return path
    result = data_store.get_any_path(sid) or data_store.get_any_path("")
    if result:
        return result[1]
    raise FileNotFoundError(
        "No image found. Upload one to the drop zone, or use capture_screen / capture_webcam."
    )


@mcp.tool()
async def describe_image(
    question: str = "",
    filename: str = "",
    sid: str = "",
) -> dict:
    """
    Look at an uploaded image and describe what's in it (or answer a specific
    question about it). Use when the user says: 'what's in this image',
    'describe this picture', 'look at this', 'what do you see'.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_image(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await vision.describe_image(path, question)


@mcp.tool()
async def read_text_from_image(filename: str = "", sid: str = "") -> dict:
    """
    Extract all readable text from an image (OCR). Use when the user says:
    'read this', 'what does this say', 'extract the text', 'OCR this'.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_image(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await vision.read_text(path)


@mcp.tool()
async def detect_objects_in_image(filename: str = "", sid: str = "") -> dict:
    """
    Identify visible objects, count people, and list dominant colours.
    Use when the user asks: 'what objects do you see', 'how many people',
    'identify everything in the picture'.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_image(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await vision.detect_objects(path)


@mcp.tool()
async def analyze_chart_image(filename: str = "", sid: str = "") -> dict:
    """
    Analyse a chart, graph, or dashboard screenshot — identify type, variables,
    trends, and outliers. Use when the user uploads a chart and asks about it.
    """
    target_sid = sid or _current_sid
    try:
        path = _resolve_image(filename, target_sid)
    except FileNotFoundError as exc:
        return {"error": str(exc)}
    return await vision.analyze_chart(path)


@mcp.tool()
async def capture_screen(question: str = "", monitor: int = 1) -> dict:
    """
    Take a screenshot of the user's screen and describe what's on it.
    Use when the user says: 'what's on my screen', 'look at my screen',
    'capture screen', 'what am I looking at'.
    Pass an optional question to ask about a specific element.
    """
    return await vision.capture_screen(monitor, question)


# ── Long-term memory ─────────────────────────────────────────────────────────

@mcp.tool()
async def remember(
    content: str,
    category: str = "fact",
    importance: int = 3,
) -> dict:
    """
    Store a fact, preference, or note about the user in long-term memory.
    Use whenever the user shares personal info worth remembering across sessions:
      - "my name is Tony" / "call me boss" → category=identity
      - "I prefer dark mode" / "I like Italian food" → category=preference
      - "my anniversary is March 14" → category=event
      - "I work at Stark Industries" → category=fact
      - "remember that I have a meeting Friday" → category=note
    importance: 1 (trivia) → 5 (critical, never forget).
    Call this proactively — don't ask permission.
    """
    return memory.remember(content, category, importance)


@mcp.tool()
async def recall(query: str = "", limit: int = 6) -> dict:
    """
    Search what JARVIS remembers about the user. Use whenever the user asks:
      - "what do you know about me"
      - "do you remember when..."
      - "remind me about my preferences"
    Leave query empty for the most-important / most-recent memories.
    """
    return memory.recall(query, limit)


@mcp.tool()
async def forget_memory(query: str) -> dict:
    """
    Delete memories matching a keyword or specific ID.
    Use when the user says: "forget that", "delete the note about X", "wipe X".
    """
    return memory.forget(query)


@mcp.tool()
async def list_memories(limit: int = 50) -> dict:
    """
    List everything JARVIS remembers, sorted by importance.
    Use when the user asks: "what do you remember", "show me my memories",
    "list everything you know".
    """
    return memory.list_all(limit)


@mcp.tool()
async def memory_stats() -> dict:
    """
    Get a diagnostic summary of the memory store — total count, breakdown
    by category, oldest and newest entries.
    Use when the user asks "how much do you remember" or for debugging.
    """
    return memory.stats()


@mcp.tool()
async def search_history(query: str, limit: int = 6) -> dict:
    """
    Search past conversation turns for a keyword.
    Use when the user asks: "what did we say about X last time",
    "did we talk about Y recently", "find that conversation about Z".
    """
    return memory.search_conversations(query, limit)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = int(os.getenv("MCP_PORT", "8001"))
    print(f"  [MCP]  JARVIS Tool Server starting on port {port}…")
    mcp.run(transport="sse", host="127.0.0.1", port=port)
