import os
import logging
from datetime import datetime, timezone
import aiohttp
from db import cache_weather, get_cached_weather

logger = logging.getLogger(__name__)

# forecast gives 3-hour intervals for 5 days; we pick today's daytime high
_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


async def fetch_weather() -> dict | None:
    cached = await get_cached_weather()
    if cached:
        return cached

    api_key = os.getenv("OPENWEATHER_API_KEY")
    city = os.getenv("WEATHER_CITY", "San Francisco")

    if not api_key:
        logger.warning("OPENWEATHER_API_KEY not set — skipping weather")
        return None

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _FORECAST_URL,
                params={"q": city, "appid": api_key, "units": "metric", "cnt": 8},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error("Weather API error %s: %s", resp.status, data)
                    return None

                items = data.get("list", [])
                if not items:
                    return None

                # Find today's daytime high (forecast items between 10:00–20:00 local)
                # We use UTC date of first item as "today" since VM is UTC
                today_str = datetime.fromtimestamp(items[0]["dt"], tz=timezone.utc).strftime("%Y-%m-%d")
                daytime = [
                    item for item in items
                    if datetime.fromtimestamp(item["dt"], tz=timezone.utc).strftime("%Y-%m-%d") == today_str
                    and 10 <= datetime.fromtimestamp(item["dt"], tz=timezone.utc).hour <= 20
                ]

                # Fall back to all today's items if no daytime slots in the 8-item window
                if not daytime:
                    daytime = [
                        item for item in items
                        if datetime.fromtimestamp(item["dt"], tz=timezone.utc).strftime("%Y-%m-%d") == today_str
                    ] or items[:4]

                temp_c = max(item["main"]["temp_max"] for item in daytime)
                humidity = round(sum(item["main"]["humidity"] for item in daytime) / len(daytime))
                # Use description from the hottest slot
                hottest = max(daytime, key=lambda x: x["main"]["temp_max"])
                description = hottest["weather"][0]["description"]

                weather = {"temp_c": temp_c, "humidity": humidity, "description": description}
                await cache_weather(**weather)
                logger.info("Weather fetched: %.1f°C (daily high), %d%% humidity, %s", temp_c, humidity, description)
                return weather

    except Exception as e:
        logger.error("Failed to fetch weather: %s", e)
        return None


def water_adjustment(temp_c: float) -> tuple[float, str]:
    """Return (multiplier, reason) based on today's predicted high temperature."""
    if temp_c >= 38:
        return 1.75, f"extreme heat ({temp_c:.0f}°C high)"
    if temp_c >= 35:
        return 1.5, f"very hot ({temp_c:.0f}°C high)"
    if temp_c >= 28:
        return 1.25, f"hot ({temp_c:.0f}°C high)"
    if temp_c >= 22:
        return 1.0, f"warm ({temp_c:.0f}°C high)"
    if temp_c >= 15:
        return 0.85, f"mild ({temp_c:.0f}°C high)"
    return 0.7, f"cool ({temp_c:.0f}°C high)"
