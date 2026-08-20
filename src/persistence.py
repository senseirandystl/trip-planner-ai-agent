"""Session/itinerary persistence to data/app_state.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .config import APP_STATE_PATH, DATA_DIR


def ensure_data_dir() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR


def load_app_state(path: Path | None = None) -> dict[str, Any]:
    ensure_data_dir()
    target = path or APP_STATE_PATH
    if not target.exists():
        return {}
    try:
        return json.loads(target.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_app_state(state: dict[str, Any], path: Path | None = None) -> None:
    ensure_data_dir()
    target = path or APP_STATE_PATH
    payload = {
        "destination": state.get("destination"),
        "days": state.get("days"),
        "pace": state.get("pace"),
        "interests": state.get("interests"),
        "constraints": state.get("constraints"),
        "itinerary": state.get("itinerary"),
        "pois": state.get("pois"),
        "trace": state.get("trace"),
        "city_meta": state.get("city_meta"),
    }
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
