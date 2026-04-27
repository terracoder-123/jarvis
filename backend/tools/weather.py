"""Weather via Open-Meteo (no API key required)."""

import httpx


WEATHER_CODES = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Fog", 48: "Rime fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Dense drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow", 77: "Snow grains",
    80: "Light showers", 81: "Showers", 82: "Violent showers",
    85: "Snow showers", 86: "Heavy snow showers",
    95: "Thunderstorm", 96: "Thunderstorm with hail", 99: "Severe thunderstorm",
}


async def get_weather(location: str = ""):
    """Get current weather for a location (or user's IP if blank)."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=8) as client:
        # 1. Resolve coordinates
        if location:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            gd = geo.json()
            if not gd.get("results"):
                return {"error": f"Location '{location}' not found."}
            place = gd["results"][0]
            lat, lon = place["latitude"], place["longitude"]
            city_label = f"{place.get('name', location)}, {place.get('country', '')}"
        else:
            # Use IP-based geolocation
            ip = await client.get("https://ipapi.co/json/")
            ipd = ip.json()
            lat, lon = ipd.get("latitude"), ipd.get("longitude")
            city_label = f"{ipd.get('city', '')}, {ipd.get('country_name', '')}"

        if lat is None:
            return {"error": "Could not determine location."}

        # 2. Fetch weather
        w = await client.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m",
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
                "timezone": "auto",
            },
        )
        wd = w.json()
        c = wd.get("current", {})
        return {
            "location": city_label,
            "temperature_c": round(c.get("temperature_2m", 0)),
            "feels_like_c": round(c.get("apparent_temperature", 0)),
            "condition": WEATHER_CODES.get(c.get("weather_code", -1), "Unknown"),
            "humidity": c.get("relative_humidity_2m"),
            "wind_kmh": round(c.get("wind_speed_10m", 0)),
        }


DECLARATIONS = [
    {
        "name": "get_weather",
        "description": (
            "Get the current weather conditions. If no location is specified, uses the user's IP location. "
            "Use when the user asks about weather, temperature, forecast, or conditions."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "location": {
                    "type": "STRING",
                    "description": "City or location name. Leave empty to use user's current location.",
                }
            },
        },
    }
]
