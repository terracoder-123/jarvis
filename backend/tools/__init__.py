"""JARVIS tool registry — v2."""
from backend.tools import news, web, wiki, weather, youtube, system, windows


def get_tool_declarations():
    """Returns Gemini function declarations for all JARVIS tools."""
    return [
        *windows.DECLARATIONS,   # window-opening commands (priority for voice)
        *news.DECLARATIONS,
        *web.DECLARATIONS,
        *wiki.DECLARATIONS,
        *weather.DECLARATIONS,
        *youtube.DECLARATIONS,
        *system.DECLARATIONS,
    ]


async def call_tool(name: str, args: dict) -> dict:
    """Routes a tool call to the right module."""
    handlers = {
        # windows (UI commands)
        "open_world_map":      windows.open_world_map,
        "open_globe_view":     windows.open_globe_view,
        "open_news_wire":      windows.open_news_wire,
        "open_video_player":   windows.open_video_player,
        "open_stocks_panel":   windows.open_stocks_panel,
        "open_weather_panel":  windows.open_weather_panel,
        "close_all_windows":   windows.close_all_windows,
        # data
        "get_world_news":      news.get_world_news,
        "get_finance_news":    news.get_finance_news,
        "get_tech_news":       news.get_tech_news,
        "search_web":          web.search_web,
        "wikipedia_lookup":    wiki.wikipedia_lookup,
        "get_weather":         weather.get_weather,
        "youtube_search":      youtube.youtube_search,
        "play_youtube":        youtube.play_youtube,
        "get_current_time":    system.get_current_time,
        "run_diagnostics":     system.run_diagnostics,
    }
    fn = handlers.get(name)
    if not fn:
        return {"error": f"Unknown tool: {name}"}
    try:
        return await fn(**args) if args else await fn()
    except Exception as e:
        return {"error": str(e)}
