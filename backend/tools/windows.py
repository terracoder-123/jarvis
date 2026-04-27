"""
Window-opening tools — UI command triggers.
These return a marker that the frontend intercepts to open HUD panels.
"""


async def open_world_map():
    """Open the full world map (world-monitor.com) on the HUD."""
    return {"ui_command": "open_window", "window": "world_map"}


async def open_globe_view():
    """Open a 3D rotating globe view on the HUD."""
    return {"ui_command": "open_window", "window": "globe"}


async def open_news_wire():
    """Open the live news wire feed (BBC, NYT, Al Jazeera, etc.)."""
    return {"ui_command": "open_window", "window": "news_wire"}


async def open_video_player(query: str):
    """Search YouTube for the query and open a video player window that auto-plays."""
    return {
        "ui_command": "open_window",
        "window": "video_player",
        "params": {"query": query},
    }


async def open_stocks_panel():
    """Open a live stocks/markets ticker panel."""
    return {"ui_command": "open_window", "window": "stocks"}


async def open_weather_panel():
    """Open the weather HUD panel."""
    return {"ui_command": "open_window", "window": "weather"}


async def close_all_windows():
    """Close all open HUD windows."""
    return {"ui_command": "close_all"}


DECLARATIONS = [
    {
        "name": "open_world_map",
        "description": (
            "Open the full interactive world map on the user's HUD. The map shows live events, "
            "news pins, and global activity. Use when the user says 'show me the world', "
            "'world map', 'what's happening globally', or wants a geographic overview."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_globe_view",
        "description": (
            "Open a 3D rotating globe view. Use when the user says 'show the globe', "
            "'3D earth', 'rotate the globe', or wants an aesthetic planetary view."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_news_wire",
        "description": (
            "Open the live news wire panel — streaming headlines from BBC, NYT, Al Jazeera, "
            "CNBC, TechCrunch. Use when the user asks: 'what's happening', 'brief me', "
            "'show news', 'headlines', 'latest news'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_video_player",
        "description": (
            "Search YouTube and open a pop-out video player that immediately auto-plays the top match. "
            "Use when the user says 'play X', 'watch X', 'show me videos about X', 'put on X'. "
            "Pass the video topic as the query parameter."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "What to search for and play (e.g. 'Iron Man suit up scenes', 'AC/DC Back in Black')",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "open_stocks_panel",
        "description": (
            "Open a live stocks/markets ticker panel showing major indices. "
            "Use when the user asks about markets, stocks, or financial data visually."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "open_weather_panel",
        "description": (
            "Open a weather HUD panel showing current conditions for the user's location. "
            "Use when the user asks about weather, temperature, forecast."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "close_all_windows",
        "description": (
            "Close all open HUD windows and return to the main standby view. "
            "Use when the user says 'close everything', 'clear the HUD', 'shut it all down', "
            "'dismiss windows'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]
