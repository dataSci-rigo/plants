import logging
import os
import httpx

logger = logging.getLogger(__name__)

_BASE = "https://perenual.com/api"


def _key() -> str | None:
    return os.getenv("PERENUAL_API_KEY")


async def search_species(name: str) -> int | None:
    """Return the Perenual species_id for the first search hit, or None."""
    key = _key()
    if not key:
        return None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_BASE}/species-list",
                params={"key": key, "q": name, "page": 1},
            )
            r.raise_for_status()
            data = r.json().get("data", [])
            if data:
                return data[0].get("id")
    except Exception as e:
        logger.warning("Perenual search failed for %r: %s", name, e)
    return None


async def get_species_details(species_id: int) -> dict:
    """Return relevant care fields from a Perenual species detail response."""
    key = _key()
    if not key:
        return {}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{_BASE}/species/details/{species_id}",
                params={"key": key},
            )
            r.raise_for_status()
            d = r.json()
            return {
                "scientific_name": d.get("scientific_name", []),
                "care_level":      d.get("care_level"),
                "growth_rate":     d.get("growth_rate"),
                "maintenance":     d.get("maintenance"),
                "pruning_month":   d.get("pruning_month") or [],
                "dimension":       d.get("dimension"),
            }
    except Exception as e:
        logger.warning("Perenual details failed for id=%s: %s", species_id, e)
    return {}
