"""Streamlit UI for the Trip Planner AI Agent capstone."""

from __future__ import annotations

import json
import os

import streamlit as st

from src.agent import TripPlannerAgent
from src.config import (
    DEFAULT_MODEL,
    DEFAULT_USER_AGENT,
    INTEREST_OPTIONS,
    MODEL_OPTIONS,
    PACE_OPTIONS,
)
from src.feedback import feedback_summary, record_feedback
from src.geocoding import geocode_city
from src.maps import build_deck, itinerary_points
from src.persistence import load_app_state, save_app_state
from src.validation import BLOCKS, validate_user_inputs

st.set_page_config(
    page_title="Trip Planner AI Agent",
    page_icon="🧭",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _init_state() -> None:
    defaults = {
        "openai_key": "",
        "remember_key": True,
        "itinerary": None,
        "pois": {},
        "trace": [],
        "city_meta": None,
        "destination": "Santa Fe, NM",
        "days": 3,
        "pace": "moderate",
        "interests": ["food", "outdoors", "history"],
        "constraints": "",
        "status": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

    if "hydrated" not in st.session_state:
        saved = load_app_state()
        if saved.get("itinerary"):
            for field in (
                "destination",
                "days",
                "pace",
                "interests",
                "constraints",
                "itinerary",
                "pois",
                "trace",
                "city_meta",
            ):
                if saved.get(field) is not None:
                    st.session_state[field] = saved[field]
        st.session_state.hydrated = True


def _persist() -> None:
    save_app_state(
        {
            "destination": st.session_state.destination,
            "days": st.session_state.days,
            "pace": st.session_state.pace,
            "interests": st.session_state.interests,
            "constraints": st.session_state.constraints,
            "itinerary": st.session_state.itinerary,
            "pois": st.session_state.pois,
            "trace": st.session_state.trace,
            "city_meta": st.session_state.city_meta,
        }
    )


def _resolve_api_key() -> str:
    if st.session_state.openai_key:
        return st.session_state.openai_key.strip()
    if "OPENAI_API_KEY" in st.secrets:
        return str(st.secrets["OPENAI_API_KEY"])
    return os.environ.get("OPENAI_API_KEY", "").strip()


def _render_sidebar() -> dict:
    with st.sidebar:
        st.header("Setup")
        key = st.text_input(
            "OpenAI API key",
            type="password",
            value=st.session_state.openai_key,
            key="user_openai_key",
            help="Stored in session state only. Never committed to git.",
        )
        remember = st.checkbox("Remember for this session", value=st.session_state.remember_key)
        if remember:
            st.session_state.openai_key = key
        else:
            st.session_state.openai_key = ""
        st.session_state.remember_key = remember
        if st.button("Clear API key"):
            st.session_state.openai_key = ""
            st.rerun()

        st.divider()
        st.header("Trip")
        destination = st.text_input("Destination", value=st.session_state.destination)
        days = st.slider("Trip length (days)", min_value=1, max_value=10, value=int(st.session_state.days))
        pace = st.selectbox(
            "Pace",
            PACE_OPTIONS,
            index=PACE_OPTIONS.index(st.session_state.pace)
            if st.session_state.pace in PACE_OPTIONS
            else 1,
        )
        interests = st.multiselect(
            "Interests",
            INTEREST_OPTIONS,
            default=[i for i in st.session_state.interests if i in INTEREST_OPTIONS],
        )
        constraints = st.text_area(
            "Constraints",
            value=st.session_state.constraints,
            placeholder="Vegetarian, walkable only, avoid late nights...",
            height=80,
        )

        st.divider()
        st.header("Agent")
        model = st.selectbox("Model", MODEL_OPTIONS, index=MODEL_OPTIONS.index(DEFAULT_MODEL))
        fast_mode = st.toggle("Fast mode", value=True, help="One broad POI search and fewer agent steps.")
        enable_rag = st.toggle("Wikivoyage RAG", value=True)
        max_steps = st.slider("Max agent steps", min_value=3, max_value=12, value=5 if fast_mode else 10)
        user_agent = st.text_input("OSM User-Agent", value=DEFAULT_USER_AGENT)
        dark_map = st.toggle("Dark map", value=False)

        st.divider()
        summary = feedback_summary(destination)
        st.caption(
            f"Feedback so far: {summary['upvotes']} up / {summary['downvotes']} down "
            f"across {summary['unique_pois']} POIs"
        )
        if st.button("Reset saved itinerary"):
            st.session_state.itinerary = None
            st.session_state.pois = {}
            st.session_state.trace = []
            st.session_state.city_meta = None
            _persist()
            st.rerun()

    st.session_state.destination = destination
    st.session_state.days = days
    st.session_state.pace = pace
    st.session_state.interests = interests
    st.session_state.constraints = constraints
    return {
        "destination": destination,
        "days": days,
        "pace": pace,
        "interests": interests,
        "constraints": constraints,
        "model": model,
        "fast_mode": fast_mode,
        "enable_rag": enable_rag,
        "max_steps": max_steps,
        "user_agent": user_agent,
        "dark_map": dark_map,
    }


def _make_agent(cfg: dict) -> TripPlannerAgent:
    def on_event(event: dict) -> None:
        st.session_state.trace.append(event)
        st.session_state.status = event.get("message", "")

    return TripPlannerAgent(
        api_key=_resolve_api_key(),
        model=cfg["model"],
        user_agent=cfg["user_agent"],
        enable_rag=cfg["enable_rag"],
        max_steps=cfg["max_steps"],
        on_event=on_event,
    )


def _restore_agent_catalog(agent: TripPlannerAgent) -> None:
    agent.tool_state["pois"] = dict(st.session_state.pois or {})
    agent.tool_state["city_meta"] = st.session_state.city_meta


def generate_itinerary(cfg: dict) -> None:
    errors = validate_user_inputs(cfg["destination"], cfg["days"], cfg["pace"], cfg["interests"])
    if errors:
        for err in errors:
            st.error(err)
        return
    if not _resolve_api_key():
        st.error("Add an OpenAI API key in the sidebar (or set OPENAI_API_KEY).")
        return

    st.session_state.trace = []
    st.session_state.status = "Starting agent..."
    agent = _make_agent(cfg)
    with st.status("Planning your trip...", expanded=True) as status:
        try:
            status.write("Geocoding destination…")
            geo = geocode_city(cfg["destination"], user_agent=cfg["user_agent"])
            status.write(f"Found {geo['display_name']}")
            itin = agent.plan(
                destination=cfg["destination"],
                days=cfg["days"],
                pace=cfg["pace"],
                interests=cfg["interests"],
                constraints=cfg["constraints"],
                fast_mode=cfg["fast_mode"],
            )
            st.session_state.itinerary = itin
            st.session_state.pois = agent.tool_state["pois"]
            st.session_state.city_meta = agent.tool_state["city_meta"]
            st.session_state.trace = agent.trace
            _persist()
            status.update(label="Itinerary ready", state="complete")
        except Exception as exc:
            st.session_state.trace = agent.trace
            st.session_state.pois = agent.tool_state.get("pois") or {}
            status.update(label="Planning failed", state="error")
            st.error(str(exc))
            if getattr(exc, "args", None):
                with st.expander("Details"):
                    st.exception(exc)
            if agent.trace:
                with st.expander("Agent trace"):
                    render_trace(agent.trace)


def refine_itinerary(cfg: dict, request: str, target_day: int | None) -> None:
    if not st.session_state.itinerary:
        st.warning("Generate an itinerary first.")
        return
    if not request.strip():
        st.warning("Describe how you want to refine the plan.")
        return
    if not _resolve_api_key():
        st.error("Add an OpenAI API key in the sidebar.")
        return
    agent = _make_agent(cfg)
    _restore_agent_catalog(agent)
    try:
        refined = agent.refine(
            itinerary=st.session_state.itinerary,
            request=request.strip(),
            target_day=target_day,
            fast_mode=cfg["fast_mode"],
        )
        st.session_state.itinerary = refined
        st.session_state.pois = agent.tool_state["pois"]
        st.session_state.city_meta = agent.tool_state["city_meta"] or st.session_state.city_meta
        st.session_state.trace = (st.session_state.trace or []) + agent.trace
        _persist()
        st.success("Itinerary updated.")
    except Exception as exc:
        st.error(f"Refinement failed: {exc}")
        with st.expander("Details"):
            st.exception(exc)


def render_itinerary(itin: dict, destination: str, *, key_prefix: str = "plan") -> None:
    st.subheader(f"{itin.get('destination', destination)}")
    if itin.get("notes"):
        st.info(itin["notes"])

    for day in itin.get("days") or []:
        day_num = day.get("day")
        theme = day.get("theme") or ""
        st.markdown(f"### Day {day_num}{' — ' + theme if theme else ''}")
        cols = st.columns(3)
        for col, block in zip(cols, BLOCKS):
            with col:
                st.markdown(f"**{block.title()}**")
                items = day.get(block) or []
                if not items:
                    st.caption("No stops")
                    continue
                for idx, item in enumerate(items):
                    st.markdown(f"**{item.get('name', 'Untitled')}**")
                    st.caption(f"{item.get('category', '')} · `{item.get('poi_id', '')}`")
                    if item.get("why"):
                        st.write(item["why"])
                    if item.get("url"):
                        st.markdown(f"[Open]({item['url']})")
                    c1, c2 = st.columns(2)
                    poi_id = item.get("poi_id", "")
                    with c1:
                        if st.button("👍", key=f"{key_prefix}-up-{day_num}-{block}-{idx}-{poi_id}"):
                            record_feedback(destination, poi_id, "up")
                            st.toast(f"Upvoted {item.get('name')}")
                    with c2:
                        if st.button("👎", key=f"{key_prefix}-down-{day_num}-{block}-{idx}-{poi_id}"):
                            record_feedback(destination, poi_id, "down")
                            st.toast(f"Downvoted {item.get('name')}")

    sources = [s for s in (itin.get("sources") or []) if s]
    if sources:
        st.markdown("#### Sources")
        for src in sources:
            st.markdown(f"- {src}")

    st.download_button(
        "Download itinerary JSON",
        data=json.dumps(itin, indent=2, ensure_ascii=False),
        file_name="itinerary.json",
        mime="application/json",
        key=f"{key_prefix}-download-json",
    )


def render_map(itin: dict, dark: bool) -> None:
    days = [f"Day {d.get('day')}" for d in itin.get("days") or []]
    day_filter = st.selectbox("Map filter", ["All"] + days, key="map_day_filter")
    points = itinerary_points(itin, day_filter)
    if points.empty:
        st.caption("No mappable coordinates in this itinerary.")
        return
    deck = build_deck(points, dark=dark)
    if deck:
        st.pydeck_chart(deck, use_container_width=True)


def render_trace(trace: list[dict]) -> None:
    if not trace:
        st.caption("No agent steps yet.")
        return
    for event in trace:
        step = event.get("step", "?")
        phase = event.get("phase", "")
        seconds = event.get("seconds")
        suffix = f" ({seconds}s)" if seconds is not None else ""
        st.markdown(f"- **Step {step} · {phase}**{suffix} — {event.get('message', '')}")


def main() -> None:
    _init_state()
    cfg = _render_sidebar()

    st.title("🧭 Trip Planner AI Agent")
    st.caption(
        "Codecademy capstone — OpenAI Responses API, OpenStreetMap tools, "
        "optional Wikivoyage RAG, and PyDeck maps."
    )

    left, right = st.columns([1, 1])
    with left:
        generate = st.button("Generate itinerary", type="primary", use_container_width=True)
    with right:
        st.caption("Uses live Nominatim + Overpass data. Typical cost is a few cents per plan.")

    if generate:
        generate_itinerary(cfg)

    itin = st.session_state.itinerary
    if itin:
        tab_plan, tab_map, tab_refine, tab_trace = st.tabs(
            ["Itinerary", "Map", "Refine", "Agent trace"]
        )
        with tab_plan:
            render_itinerary(itin, cfg["destination"], key_prefix="plan")
        with tab_map:
            render_map(itin, dark=cfg["dark_map"])
        with tab_refine:
            request = st.text_input(
                "Refinement request",
                placeholder="Make it more outdoorsy / swap evening restaurants / less walking",
            )
            day_labels = ["Entire trip"] + [f"Day {d.get('day')}" for d in itin.get("days") or []]
            target = st.selectbox("Scope", day_labels)
            target_day = None if target == "Entire trip" else int(target.split()[-1])
            if st.button("Apply refinement"):
                refine_itinerary(cfg, request, target_day)
            st.caption("After a refinement, switch back to the Itinerary tab to review the updated plan.")
        with tab_trace:
            render_trace(st.session_state.trace or [])
    else:
        st.markdown(
            """
            **How it works**
            1. Enter a destination, trip length, pace, and interests.
            2. The agent geocodes the city, searches live OSM POIs, and optionally retrieves Wikivoyage context.
            3. It returns a day-by-day itinerary that is validated against real POI IDs.
            4. Vote on stops to boost or demote them in future searches.
            """
        )


if __name__ == "__main__":
    main()
