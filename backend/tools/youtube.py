"""YouTube search and inline player — via Piped (no API key required)."""

import httpx
import asyncio


PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi-libre.kavin.rocks",
    "https://api.piped.yt",
    "https://pipedapi.ducks.party",
]


async def youtube_search(query: str, limit: int = 8):
    """Search YouTube videos without needing an API key."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=6) as client:
        for base in PIPED_INSTANCES:
            try:
                r = await client.get(
                    f"{base}/search",
                    params={"q": query, "filter": "videos"},
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                items = data.get("items", [])
                results = []
                for it in items[:limit]:
                    url = it.get("url", "")
                    vid_id = url.replace("/watch?v=", "").split("&")[0] if url else ""
                    if not vid_id:
                        continue
                    results.append({
                        "video_id": vid_id,
                        "title": it.get("title", "Untitled"),
                        "channel": it.get("uploaderName") or it.get("uploader") or "Unknown",
                        "thumbnail": it.get("thumbnail") or it.get("thumbnailUrl") or "",
                        "duration_seconds": it.get("duration"),
                        "watch_url": f"https://www.youtube.com{url}" if url.startswith("/") else url,
                        "embed_url": f"https://www.youtube-nocookie.com/embed/{vid_id}?autoplay=1&rel=0",
                    })
                if results:
                    return {"query": query, "results": results, "count": len(results)}
            except Exception:
                continue
    return {"query": query, "results": [], "count": 0, "error": "All Piped instances unreachable"}


async def play_youtube(query: str):
    """Find the top-matching YouTube video and return its embed URL for inline playback."""
    res = await youtube_search(query, limit=1)
    if res.get("results"):
        top = res["results"][0]
        return {
            "playing": True,
            "video_id": top["video_id"],
            "title": top["title"],
            "channel": top["channel"],
            "embed_url": top["embed_url"],
            "thumbnail": top["thumbnail"],
        }
    return {"playing": False, "error": "No video found for that query."}


DECLARATIONS = [
    {
        "name": "youtube_search",
        "description": (
            "Search YouTube for videos and return a list of results with thumbnails. "
            "Use when the user asks to: find videos, search YouTube, show videos, "
            "look up videos. Returns up to 8 videos the user can click to play inline."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "YouTube search query."},
                "limit": {"type": "INTEGER", "description": "Max results, default 8."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "play_youtube",
        "description": (
            "Find and immediately play the top YouTube video matching a query inline. "
            "Use when the user says: 'play X', 'watch X', 'put on X', or names a specific video."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Video to play."},
            },
            "required": ["query"],
        },
    },
]
