"""Shared configuration, OSM interest mappings, and default model options."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
APP_STATE_PATH = DATA_DIR / "app_state.json"
FEEDBACK_PATH = DATA_DIR / "feedback.jsonl"

DEFAULT_USER_AGENT = os.environ.get(
    "TRIP_PLANNER_USER_AGENT",
    "trip-planner-capstone/1.0 (randalljames34@pm.me)",
)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
WIKIVOYAGE_API = "https://en.wikivoyage.org/w/api.php"

NOMINATIM_MIN_INTERVAL = 1.1  # seconds — Nominatim usage policy
HTTP_TIMEOUT = 25
HTTP_RETRIES = 3

DEFAULT_MODEL = "gpt-4.1-mini"
MODEL_OPTIONS = [
    "gpt-4.1-mini",
    "gpt-4.1",
    "gpt-4o-mini",
    "gpt-4o",
]

PACE_OPTIONS = ["relaxed", "moderate", "packed"]
INTEREST_OPTIONS = [
    "museums",
    "food",
    "outdoors",
    "history",
    "nightlife",
    "shopping",
    "architecture",
    "family",
    "art",
    "nature",
]

# User-facing interest labels -> OSM tag filters (key, regex value).
INTEREST_TO_TAGS: dict[str, list[tuple[str, str]]] = {
    "museums": [("tourism", "museum|gallery")],
    "art": [("tourism", "museum|gallery|artwork"), ("amenity", "arts_centre")],
    "food": [("amenity", "restaurant|cafe|fast_food|food_court|bakery")],
    "outdoors": [
        ("leisure", "park|nature_reserve|garden"),
        ("natural", "peak|beach|wood|water"),
        ("tourism", "viewpoint"),
    ],
    "nature": [
        ("leisure", "park|nature_reserve|garden"),
        ("natural", "peak|beach|wood|water|hot_spring"),
    ],
    "history": [
        ("historic", ".*"),
        ("tourism", "museum|attraction"),
        ("amenity", "place_of_worship"),
    ],
    "nightlife": [("amenity", "bar|pub|nightclub|biergarten")],
    "shopping": [("shop", "mall|department_store|gift|clothes|marketplace"), ("amenity", "marketplace")],
    "architecture": [
        ("historic", "monument|castle|church|cathedral|building"),
        ("tourism", "attraction"),
        ("building", "cathedral|church|castle"),
    ],
    "family": [
        ("tourism", "zoo|theme_park|aquarium"),
        ("leisure", "park|playground|water_park"),
        ("amenity", "ice_cream"),
    ],
}

# Fallback tags used when no interests are selected.
DEFAULT_TAGS: list[tuple[str, str]] = [
    ("tourism", "attraction|museum|gallery|viewpoint"),
    ("amenity", "restaurant|cafe"),
    ("leisure", "park"),
    ("historic", "monument|castle"),
]

CATEGORY_FROM_TAGS = {
    "museum": "museum",
    "gallery": "art",
    "artwork": "art",
    "arts_centre": "art",
    "restaurant": "food",
    "cafe": "food",
    "fast_food": "food",
    "food_court": "food",
    "bakery": "food",
    "ice_cream": "food",
    "park": "outdoors",
    "nature_reserve": "outdoors",
    "garden": "outdoors",
    "peak": "outdoors",
    "beach": "outdoors",
    "wood": "outdoors",
    "water": "outdoors",
    "viewpoint": "outdoors",
    "hot_spring": "outdoors",
    "bar": "nightlife",
    "pub": "nightlife",
    "nightclub": "nightlife",
    "biergarten": "nightlife",
    "mall": "shopping",
    "department_store": "shopping",
    "gift": "shopping",
    "clothes": "shopping",
    "marketplace": "shopping",
    "monument": "history",
    "castle": "history",
    "church": "history",
    "cathedral": "history",
    "place_of_worship": "history",
    "attraction": "attraction",
    "zoo": "family",
    "theme_park": "family",
    "aquarium": "family",
    "playground": "family",
    "water_park": "family",
}

UPVOTE_BOOST = 0.25
DOWNVOTE_BOOST = -0.35
