"""
Worldometer Scraper — Live Global Data
Fetches population, births, deaths, and economic stats in real-time.
"""

import requests
from bs4 import BeautifulSoup
import logging
from typing import Dict, Any

logger = logging.getLogger("jarvis.scraper")

URLS = {
    "population": "https://www.worldometers.info/world-population/",
    "covid": "https://www.worldometers.info/coronavirus/",
    "economy": "https://www.worldometers.info/gdp/",
}

def fetch_world_population() -> Dict[str, Any]:
    """Fetch live world population stats from Worldometer."""
    try:
        res = requests.get(URLS["population"], timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"
        })
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # Main counter
        counters = soup.find_all("div", class_="maincounter-number")
        
        data = {
            "population": None,
            "births_today": None,
            "deaths_today": None,
            "net_growth": None,
        }

        if len(counters) > 0:
            data["population"] = counters[0].text.strip()
        
        # Try to get births/deaths/growth
        try:
            items = soup.find_all("div", class_="divisor")
            if len(items) > 1:
                data["births_today"] = items[0].text.strip() if items[0].text else None
            if len(items) > 2:
                data["deaths_today"] = items[1].text.strip() if items[1].text else None
            if len(items) > 3:
                data["net_growth"] = items[2].text.strip() if items[2].text else None
        except Exception as e:
            logger.debug(f"Could not parse births/deaths: {e}")

        return data

    except requests.exceptions.Timeout:
        return {"error": "Request timeout"}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {str(e)}"}
    except Exception as e:
        return {"error": f"Parse error: {str(e)}"}


def fetch_world_covid() -> Dict[str, Any]:
    """Fetch COVID-19 stats."""
    try:
        res = requests.get(URLS["covid"], timeout=10, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/91.0"
        })
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        counters = soup.find_all("div", class_="maincounter-number")
        
        data = {
            "total_cases": counters[0].text.strip() if len(counters) > 0 else None,
            "total_deaths": counters[1].text.strip() if len(counters) > 1 else None,
            "total_recovered": counters[2].text.strip() if len(counters) > 2 else None,
        }

        return data

    except Exception as e:
        return {"error": f"COVID fetch failed: {str(e)}"}


def fetch_all_world_data() -> Dict[str, Any]:
    """Fetch all world data."""
    return {
        "population": fetch_world_population(),
        "covid": fetch_world_covid(),
        "timestamp": __import__("time").time(),
    }
