"""Wikipedia knowledge lookup."""

import httpx


async def wikipedia_lookup(query: str):
    """Look up a topic on Wikipedia and return summary + image."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
        # Try direct summary first
        r = await client.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{query.replace(' ', '_')}",
            headers={"User-Agent": "JARVIS/1.0"},
        )
        if r.status_code == 200:
            data = r.json()
        else:
            # Fallback: opensearch to find best match, then fetch that
            s = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "opensearch",
                    "search": query,
                    "limit": 1,
                    "namespace": 0,
                    "format": "json",
                },
                headers={"User-Agent": "JARVIS/1.0"},
            )
            sd = s.json()
            if sd and len(sd) > 1 and sd[1]:
                best = sd[1][0]
                r2 = await client.get(
                    f"https://en.wikipedia.org/api/rest_v1/page/summary/{best.replace(' ', '_')}",
                    headers={"User-Agent": "JARVIS/1.0"},
                )
                if r2.status_code == 200:
                    data = r2.json()
                else:
                    return {"query": query, "found": False}
            else:
                return {"query": query, "found": False}

        return {
            "query": query,
            "found": True,
            "title": data.get("title", ""),
            "extract": data.get("extract", ""),
            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
            "thumbnail": data.get("thumbnail", {}).get("source", ""),
            "description": data.get("description", ""),
        }


DECLARATIONS = [
    {
        "name": "wikipedia_lookup",
        "description": (
            "Look up a person, place, thing, or concept on Wikipedia. Returns a summary, "
            "image, and link. Use when the user asks 'who is X', 'what is X', 'tell me about X'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "The topic to look up on Wikipedia.",
                }
            },
            "required": ["query"],
        },
    }
]
