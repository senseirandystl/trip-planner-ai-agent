"""PyDeck layers for itinerary visualization."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pydeck as pdk

from .validation import BLOCKS

DAY_COLORS = [
    [37, 99, 235],
    [16, 185, 129],
    [245, 158, 11],
    [239, 68, 68],
    [139, 92, 246],
    [6, 182, 212],
    [236, 72, 153],
]


def itinerary_points(itin: dict[str, Any], day_filter: str = "All") -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for day in itin.get("days") or []:
        day_num = int(day.get("day", 0))
        if day_filter != "All" and f"Day {day_num}" != day_filter:
            continue
        for block in BLOCKS:
            for item in day.get(block) or []:
                if item.get("lat") is None or item.get("lon") is None:
                    continue
                color = DAY_COLORS[(day_num - 1) % len(DAY_COLORS)]
                rows.append(
                    {
                        "name": item.get("name", ""),
                        "category": item.get("category", ""),
                        "why": item.get("why", ""),
                        "day": day_num,
                        "block": block,
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                        "color": color,
                    }
                )
    return pd.DataFrame(rows)


def path_data(points: pd.DataFrame) -> list[dict[str, Any]]:
    if points.empty:
        return []
    ordered = points.sort_values(["day", "block"], kind="stable")
    paths: list[dict[str, Any]] = []
    for day, group in ordered.groupby("day"):
        coords = group[["lon", "lat"]].values.tolist()
        if len(coords) < 2:
            continue
        color = DAY_COLORS[(int(day) - 1) % len(DAY_COLORS)]
        paths.append({"path": coords, "day": int(day), "color": color})
    return paths


def zoom_for_spread(points: pd.DataFrame) -> float:
    if points.empty:
        return 11.0
    lat_span = float(points["lat"].max() - points["lat"].min())
    lon_span = float(points["lon"].max() - points["lon"].min())
    span = max(lat_span, lon_span)
    if span < 0.01:
        return 14.0
    if span < 0.03:
        return 13.0
    if span < 0.08:
        return 12.0
    if span < 0.2:
        return 11.0
    if span < 0.5:
        return 10.0
    return 9.0


def build_deck(points: pd.DataFrame, dark: bool = False) -> pdk.Deck | None:
    if points.empty:
        return None
    paths = path_data(points)
    scatter = pdk.Layer(
        "ScatterplotLayer",
        data=points,
        get_position="[lon, lat]",
        get_fill_color="color",
        get_radius=35,
        radius_min_pixels=4,
        radius_max_pixels=12,
        pickable=True,
        opacity=0.85,
    )
    path_layer = pdk.Layer(
        "PathLayer",
        data=paths,
        get_path="path",
        get_color="color",
        width_min_pixels=2,
        get_width=4,
        opacity=0.6,
    )
    view = pdk.ViewState(
        latitude=float(points["lat"].mean()),
        longitude=float(points["lon"].mean()),
        zoom=zoom_for_spread(points),
        pitch=35,
    )
    tooltip = {
        "html": "<b>{name}</b><br/>Day {day} · {block}<br/>{category}<br/>{why}",
        "style": {"backgroundColor": "#111827", "color": "white", "fontSize": "12px"},
    }
    return pdk.Deck(
        layers=[path_layer, scatter],
        initial_view_state=view,
        tooltip=tooltip,
        map_style="dark" if dark else "light",
    )
