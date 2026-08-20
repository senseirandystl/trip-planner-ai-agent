"""Input checks and itinerary POI-id validation."""

from __future__ import annotations

import json
import re
from typing import Any

BLOCKS = ("morning", "afternoon", "evening")


def validate_user_inputs(
    destination: str,
    days: int,
    pace: str,
    interests: list[str],
) -> list[str]:
    errors: list[str] = []
    if not (destination or "").strip():
        errors.append("Enter a destination city.")
    if not isinstance(days, int) or days < 1 or days > 14:
        errors.append("Trip length must be between 1 and 14 days.")
    if pace not in {"relaxed", "moderate", "packed"}:
        errors.append("Choose a pace: relaxed, moderate, or packed.")
    if interests and not isinstance(interests, list):
        errors.append("Interests must be a list of strings.")
    return errors


def extract_json(raw: str) -> dict[str, Any]:
    """Pull the first JSON object from a model response."""
    if not raw or not str(raw).strip():
        raise ValueError("Model returned an empty response.")
    text = str(raw).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model output.")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse itinerary JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Parsed JSON is not an object.")
    return parsed


def itinerary_poi_ids(itin: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for day in itin.get("days") or []:
        for block in BLOCKS:
            for item in day.get(block) or []:
                if isinstance(item, dict) and item.get("poi_id"):
                    ids.append(str(item["poi_id"]))
    return ids


def validate_itinerary_poi_ids(itin: dict[str, Any], allowed_pois: dict[str, Any]) -> None:
    valid_ids = set(allowed_pois.keys())
    if not valid_ids:
        raise ValueError("No POIs were returned by tools — cannot validate itinerary.")
    for day in itin.get("days") or []:
        for block in BLOCKS:
            for item in day.get(block) or []:
                if not isinstance(item, dict):
                    raise ValueError(f"Invalid itinerary item in {block}: {item!r}")
                poi_id = item.get("poi_id")
                if poi_id not in valid_ids:
                    raise ValueError(f"Invalid poi_id: {poi_id}")


def other_days_unchanged(original: dict[str, Any], refined: dict[str, Any], target_day: int) -> None:
    orig_days = original.get("days") or []
    new_days = refined.get("days") or []
    if len(orig_days) != len(new_days):
        raise ValueError("Refined itinerary changed the number of days.")
    for idx, (before, after) in enumerate(zip(orig_days, new_days), start=1):
        if idx == target_day:
            continue
        if json.dumps(before, sort_keys=True) != json.dumps(after, sort_keys=True):
            raise ValueError(f"Day {idx} changed even though only day {target_day} should be modified.")


def enrich_itinerary(itin: dict[str, Any], allowed_pois: dict[str, Any]) -> dict[str, Any]:
    """Fill missing name/category/lat/lon from the POI catalog."""
    for day in itin.get("days") or []:
        for block in BLOCKS:
            items = day.get(block) or []
            for item in items:
                poi = allowed_pois.get(item.get("poi_id"), {})
                item.setdefault("name", poi.get("name", "Unknown"))
                item.setdefault("category", poi.get("category", "attraction"))
                item.setdefault("url", poi.get("url"))
                if poi.get("lat") is not None:
                    item["lat"] = poi["lat"]
                    item["lon"] = poi["lon"]
    return itin
