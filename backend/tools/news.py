"""News feeds — BBC, NYT, Al Jazeera, CNBC, TechCrunch, Ars Technica."""

import httpx
import xml.etree.ElementTree as ET
import asyncio
import re


WORLD_FEEDS = [
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/World.xml", "NYT"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera"),
    ("https://www.cnbc.com/id/100727362/device/rss/rss.html", "CNBC"),
]
FINANCE_FEEDS = [
    ("https://www.cnbc.com/id/10000664/device/rss/rss.html", "CNBC"),
    ("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch"),
    ("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NYT Business"),
]
TECH_FEEDS = [
    ("https://feeds.feedburner.com/TechCrunch", "TechCrunch"),
    ("https://www.wired.com/feed/rss", "Wired"),
    ("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica"),
]


async def _fetch_feed(client: httpx.AsyncClient, url: str, source: str, limit: int = 5):
    try:
        r = await client.get(url, timeout=6.0, headers={"User-Agent": "JARVIS/1.0"})
        if r.status_code != 200:
            return []
        root = ET.fromstring(r.content)
        items = []
        for item in root.findall(".//item")[:limit]:
            title = (item.findtext("title") or "").strip()
            desc = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            # find thumbnail
            thumb = ""
            enc = item.find("enclosure")
            if enc is not None and enc.get("url"):
                thumb = enc.get("url")
            if title:
                items.append({
                    "source": source,
                    "title": title,
                    "summary": desc[:220],
                    "link": link,
                    "published": pub,
                    "thumbnail": thumb,
                })
        return items
    except Exception:
        return []


async def _fetch_many(feeds, per_feed=5):
    async with httpx.AsyncClient(follow_redirects=True) as client:
        tasks = [_fetch_feed(client, url, src, per_feed) for url, src in feeds]
        results = await asyncio.gather(*tasks)
    return [a for batch in results for a in batch]


async def get_world_news():
    """Fetch global headlines from BBC, NYT, Al Jazeera, CNBC."""
    articles = await _fetch_many(WORLD_FEEDS)
    return {"articles": articles[:15], "count": len(articles)}


async def get_finance_news():
    """Fetch finance and market headlines."""
    articles = await _fetch_many(FINANCE_FEEDS)
    return {"articles": articles[:12], "count": len(articles)}


async def get_tech_news():
    """Fetch technology headlines from TechCrunch, Wired, Ars Technica."""
    articles = await _fetch_many(TECH_FEEDS)
    return {"articles": articles[:12], "count": len(articles)}


DECLARATIONS = [
    {
        "name": "get_world_news",
        "description": (
            "Fetches live global news headlines from BBC, NYT, Al Jazeera, and CNBC. "
            "Use when the user asks: 'what's happening', 'world news', 'brief me', "
            "'latest news', 'catch me up', 'any news today'."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_finance_news",
        "description": (
            "Fetches live finance and market headlines from CNBC, MarketWatch, NYT Business. "
            "Use when the user asks about: markets, finance, stocks, economy, trading."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
    {
        "name": "get_tech_news",
        "description": (
            "Fetches latest technology headlines from TechCrunch, Wired, Ars Technica. "
            "Use when the user asks about: tech news, AI, silicon valley, startups, gadgets."
        ),
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]
