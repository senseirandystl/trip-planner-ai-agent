"""Nominatim geocoding with rate limiting."""

from __future__ import annotations

from typing import Any

from .config import NOMINATIM_MIN_INTERVAL, NOMINATIM_URL
from .http_client import osm_headers, request_json


def geocode_city(city: str, user_agent: str | None = None) -> dict[str, Any]:
    """Resolve a city/place name to lat, lon, display name, and bounding box.

    Returns a dict with keys: city, lat, lon, display_name, bbox, osm_id.
    Raises ValueError if nothing is found.
    """
    query = (city or "").strip()
    if not query:
        raise ValueError("Destination is required.")

    results = request_json(
        "GET",
        NOMINATIM_URL,
        params={
            "q": query,
            "format": "json",
            "limit": 1,
            "addressdetails": 1,
        },
        headers=osm_headers(user_agent),
        min_interval=NOMINATIM_MIN_INTERVAL,
    )
    if not results:
        raise ValueError(
            f"Could not geocode '{query}'. Try a more specific place name "
            "(e.g. 'Santa Fe, NM' or 'Kyoto, Japan')."
        )

    hit = results[0]
    lat = float(hit["lat"])
    lon = float(hit["lon"])
    bbox_raw = hit.get("boundingbox") or []
    bbox = None
    if len(bbox_raw) == 4:
        south, north, west, east = (float(x) for x in bbox_raw)
        bbox = {"south": south, "north": north, "west": west, "east": east}

    return {
        "city": query,
        "lat": lat,
        "lon": lon,
        "display_name": hit.get("display_name", query),
        "bbox": bbox,
        "osm_id": hit.get("osm_id"),
        "osm_type": hit.get("osm_type"),
        "importance": hit.get("importance"),
    }


def city_key(city: str) -> str:
    return " ".join(city.lower().strip().split())
