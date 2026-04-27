"""Web search via DuckDuckGo Instant Answers (no API key required)."""

import httpx


async def search_web(query: str):
    """Search the web using DuckDuckGo."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
            r = await client.get(
                "https://api.duckduckgo.com/",
                params={
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                },
                headers={"User-Agent": "JARVIS/1.0"},
            )
            data = r.json()
            return {
                "query": query,
                "abstract": data.get("AbstractText", ""),
                "abstract_source": data.get("AbstractSource", ""),
                "abstract_url": data.get("AbstractURL", ""),
                "answer": data.get("Answer", ""),
                "results": [
                    {
                        "title": (t.get("Text", "") or "").split(" - ")[0] or "Result",
                        "snippet": t.get("Text", ""),
                        "url": t.get("FirstURL", ""),
                    }
                    for t in (data.get("RelatedTopics", []) or [])
                    if t.get("FirstURL")
                ][:8],
            }
    except Exception as e:
        return {"query": query, "error": str(e), "results": []}


DECLARATIONS = [
    {
        "name": "search_web",
        "description": (
            "Search the web for any query using DuckDuckGo. "
            "Use when the user asks to: search, google, look up, find information, "
            "or when general knowledge is needed that news/wiki/weather don't cover. "
            "Returns instant answers, summaries, and related results."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "The search query."}
            },
            "required": ["query"],
        },
    }
]
