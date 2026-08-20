"""Overpass POI search tool used by the agent."""

from __future__ import annotations

from typing import Any

from .config import (
    CATEGORY_FROM_TAGS,
    DEFAULT_TAGS,
    INTEREST_TO_TAGS,
    NOMINATIM_MIN_INTERVAL,
    NOMINATIM_URL,
    OVERPASS_URLS,
)
from .feedback import feedback_boost_map
from .geocoding import city_key, geocode_city
from .http_client import osm_headers, request_json


def tags_for_interests(interests: list[str] | None) -> list[tuple[str, str]]:
    if not interests:
        return list(DEFAULT_TAGS)
    tags: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for interest in interests:
        key = interest.strip().lower()
        for pair in INTEREST_TO_TAGS.get(key, []):
            if pair not in seen:
                tags.append(pair)
                seen.add(pair)
    return tags or list(DEFAULT_TAGS)


def _category_for_tags(tags: dict[str, str]) -> str:
    for value in tags.values():
        if value in CATEGORY_FROM_TAGS:
            return CATEGORY_FROM_TAGS[value]
    if tags.get("tourism"):
        return tags["tourism"]
    if tags.get("amenity"):
        return tags["amenity"]
    if tags.get("leisure"):
        return tags["leisure"]
    if tags.get("historic"):
        return "history"
    return "attraction"


def _poi_id(element: dict[str, Any]) -> str:
    return f"osm_{element.get('type', 'node')}_{element.get('id')}"


def _coords(element: dict[str, Any]) -> tuple[float | None, float | None]:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None, None


def build_overpass_query(
    lat: float,
    lon: float,
    tags: list[tuple[str, str]],
    *,
    radius_m: int = 8000,
    limit: int = 40,
) -> str:
    clauses: list[str] = []
    for key, value in tags:
        regex = value if value != ".*" else "."
        for osm_type in ("node", "way"):
            clauses.append(
                f'  {osm_type}["{key}"~"{regex}",i](around:{radius_m},{lat},{lon});'
            )
    body = "\n".join(clauses)
    return (
        f"[out:json][timeout:25];\n"
        f"(\n{body}\n);\n"
        f"out center {max(1, min(limit * 3, 120))};\n"
    )


def _parse_elements(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pois: list[dict[str, Any]] = []
    seen: set[str] = set()
    for element in elements:
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        lat, lon = _coords(element)
        if lat is None or lon is None:
            continue
        poi_id = _poi_id(element)
        if poi_id in seen:
            continue
        seen.add(poi_id)
        website = tags.get("website") or tags.get("contact:website")
        osm_type = element.get("type", "node")
        osm_id = element.get("id")
        url = website or f"https://www.openstreetmap.org/{osm_type}/{osm_id}"
        importance = float(tags.get("wikidata") is not None) + float(bool(website))
        pois.append(
            {
                "poi_id": poi_id,
                "name": name,
                "category": _category_for_tags(tags),
                "lat": lat,
                "lon": lon,
                "url": url,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "_base_score": importance,
            }
        )
    return pois


def _nominatim_fallback(
    city: str,
    interests: list[str],
    *,
    query: str | None,
    limit: int,
    user_agent: str | None,
) -> list[dict[str, Any]]:
    """Search Nominatim when Overpass is down or empty."""
    terms = list(interests or [])
    if query:
        terms.append(query)
    if not terms:
        terms = ["attraction", "restaurant", "museum", "park"]
    seen: set[str] = set()
    pois: list[dict[str, Any]] = []
    for term in terms[:4]:
        try:
            results = request_json(
                "GET",
                NOMINATIM_URL,
                params={
                    "q": f"{term} in {city}",
                    "format": "json",
                    "limit": min(15, max(limit, 10)),
                    "addressdetails": 0,
                },
                headers=osm_headers(user_agent),
                min_interval=NOMINATIM_MIN_INTERVAL,
            )
        except Exception:
            continue
        for hit in results or []:
            name = hit.get("name") or (hit.get("display_name") or "").split(",")[0]
            if not name or "lat" not in hit:
                continue
            osm_type = hit.get("osm_type", "node")
            osm_id = hit.get("osm_id")
            poi_id = f"osm_{osm_type}_{osm_id}"
            if poi_id in seen:
                continue
            seen.add(poi_id)
            kind = hit.get("type") or hit.get("class") or "attraction"
            pois.append(
                {
                    "poi_id": poi_id,
                    "name": name,
                    "category": CATEGORY_FROM_TAGS.get(kind, kind),
                    "lat": float(hit["lat"]),
                    "lon": float(hit["lon"]),
                    "url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
                    "osm_type": osm_type,
                    "osm_id": osm_id,
                    "_base_score": float(hit.get("importance") or 0),
                    "_score": float(hit.get("importance") or 0),
                }
            )
    return pois


def search_pois(
    city: str,
    query: str | None = None,
    interests: list[str] | None = None,
    limit: int = 30,
    radius_m: int = 8000,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Geocode a city and return ranked POIs for the requested interests."""
    geo = geocode_city(city, user_agent=user_agent)
    interest_list = list(interests or [])
    if query:
        lowered = query.lower()
        for option in INTEREST_TO_TAGS:
            if option in lowered and option not in interest_list:
                interest_list.append(option)

    tags = tags_for_interests(interest_list)
    overpass_ql = build_overpass_query(
        geo["lat"], geo["lon"], tags, radius_m=radius_m, limit=limit
    )
    elements: list[dict[str, Any]] = []
    overpass_error: str | None = None
    for endpoint in OVERPASS_URLS:
        try:
            payload = request_json(
                "POST",
                endpoint,
                data={"data": overpass_ql},
                headers=osm_headers(user_agent),
                timeout=35,
                retries=2,
            )
            elements = payload.get("elements") if isinstance(payload, dict) else []
            if elements:
                overpass_error = None
                break
            overpass_error = f"{endpoint} returned no elements"
        except Exception as exc:
            overpass_error = f"{endpoint}: {exc}"
            continue
    pois = _parse_elements(elements or [])
    if not pois:
        pois = _nominatim_fallback(
            city,
            interest_list,
            query=query,
            limit=limit,
            user_agent=user_agent,
        )
    if not pois and overpass_error:
        raise RuntimeError(
            "OpenStreetMap POI search failed. Overpass instances were busy or blocked "
            f"({overpass_error}). Wait a moment and try again."
        )

    boosts = feedback_boost_map(city)
    for poi in pois:
        poi["_score"] = poi.get("_base_score", 0.0) + boosts.get(poi["poi_id"], 0.0)
        if query and query.lower() in poi["name"].lower():
            poi["_score"] += 0.5

    pois.sort(key=lambda p: p["_score"], reverse=True)
    trimmed = pois[: max(1, min(int(limit), 60))]

    return {
        "city": geo["display_name"],
        "city_key": city_key(city),
        "lat": geo["lat"],
        "lon": geo["lon"],
        "bbox": geo.get("bbox"),
        "query": query,
        "interests": interest_list,
        "count": len(trimmed),
        "pois": [
            {
                "poi_id": p["poi_id"],
                "name": p["name"],
                "category": p["category"],
                "lat": p["lat"],
                "lon": p["lon"],
                "url": p["url"],
                "score": round(float(p["_score"]), 3),
            }
            for p in trimmed
        ],
    }
