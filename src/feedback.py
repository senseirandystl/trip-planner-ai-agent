"""JSONL feedback store and per-city POI boost scores."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import DOWNVOTE_BOOST, FEEDBACK_PATH, UPVOTE_BOOST
from .geocoding import city_key


def ensure_feedback_file(path: Path | None = None) -> Path:
    target = path or FEEDBACK_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.touch()
    return target


def record_feedback(
    city: str,
    poi_id: str,
    vote: str,
    *,
    path: Path | None = None,
) -> dict[str, Any]:
    if vote not in {"up", "down"}:
        raise ValueError("vote must be 'up' or 'down'")
    event = {
        "ts": time.time(),
        "city_key": city_key(city),
        "poi_id": poi_id,
        "vote": vote,
    }
    target = ensure_feedback_file(path)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event) + "\n")
    return event


def load_feedback_events(path: Path | None = None) -> list[dict[str, Any]]:
    target = ensure_feedback_file(path)
    events: list[dict[str, Any]] = []
    with target.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def feedback_boost_map(city: str, path: Path | None = None) -> dict[str, float]:
    """Net boost per POI for a city: +0.25 upvote, -0.35 downvote."""
    key = city_key(city)
    boosts: dict[str, float] = {}
    for event in load_feedback_events(path):
        if event.get("city_key") != key:
            continue
        poi_id = event.get("poi_id")
        vote = event.get("vote")
        if not poi_id:
            continue
        delta = UPVOTE_BOOST if vote == "up" else DOWNVOTE_BOOST if vote == "down" else 0.0
        boosts[poi_id] = boosts.get(poi_id, 0.0) + delta
    return boosts


def feedback_summary(city: str | None = None, path: Path | None = None) -> dict[str, Any]:
    events = load_feedback_events(path)
    if city:
        events = [e for e in events if e.get("city_key") == city_key(city)]
    ups = sum(1 for e in events if e.get("vote") == "up")
    downs = sum(1 for e in events if e.get("vote") == "down")
    return {
        "total": len(events),
        "upvotes": ups,
        "downvotes": downs,
        "unique_pois": len({e.get("poi_id") for e in events if e.get("poi_id")}),
    }
