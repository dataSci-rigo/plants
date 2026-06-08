import os
import logging
import aiohttp
from db import cache_weather, get_cached_weather

logger = logging.getLogger(__name__)
OPENWEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"


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
                OPENWEATHER_URL,
                params={"q": city, "appid": api_key, "units": "metric"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                data = await resp.json()
                if resp.status != 200:
                    logger.error(f"Weather API error {resp.status}: {data}")
                    return None
                weather = {
                    "temp_c": data["main"]["temp"],
                    "humidity": data["main"]["humidity"],
                    "description": data["weather"][0]["description"],
                }
                await cache_weather(**weather)
                return weather
    except Exception as e:
        logger.error(f"Failed to fetch weather: {e}")
        return None


def water_adjustment(temp_c: float) -> tuple[float, str]:
    """Return (multiplier, human-readable reason) based on temperature."""
    if temp_c >= 35:
        return 1.5, f"very hot ({temp_c:.0f}°C)"
    if temp_c >= 28:
        return 1.25, f"hot ({temp_c:.0f}°C)"
    if temp_c >= 22:
        return 1.0, f"warm ({temp_c:.0f}°C)"
    if temp_c >= 15:
        return 0.85, f"mild ({temp_c:.0f}°C)"
    return 0.7, f"cool ({temp_c:.0f}°C)"
