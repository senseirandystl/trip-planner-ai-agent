"""OpenAI Responses API agent with strict function calling."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from openai import OpenAI

from .config import DEFAULT_MODEL, DEFAULT_USER_AGENT
from .pois import search_pois
from .rag import retrieve_guides
from .validation import (
    enrich_itinerary,
    extract_json,
    other_days_unchanged,
    validate_itinerary_poi_ids,
)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "name": "search_pois",
        "description": (
            "Geocode a city and retrieve live OpenStreetMap points of interest. "
            "Call this at least once before writing an itinerary. Use interests "
            "such as museums, food, outdoors, history, nightlife, shopping, "
            "architecture, family, art, or nature."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City or place to search, e.g. 'Santa Fe, NM'.",
                },
                "query": {
                    "type": ["string", "null"],
                    "description": "Optional free-text focus such as 'tapas' or 'hiking trails'.",
                },
                "interests": {
                    "type": ["array", "null"],
                    "items": {"type": "string"},
                    "description": "Interest categories to map onto OSM tags.",
                },
                "limit": {
                    "type": ["integer", "null"],
                    "description": "Maximum POIs to return (10-40).",
                },
            },
            "required": ["city", "query", "interests", "limit"],
            "additionalProperties": False,
        },
    },
    {
        "type": "function",
        "name": "retrieve_guides",
        "description": (
            "Retrieve relevant Wikivoyage travel-guide chunks for a destination. "
            "Use this for local context, neighborhoods, and practical tips."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {
                "destination": {
                    "type": "string",
                    "description": "Destination name matching the trip city.",
                },
                "query": {
                    "type": "string",
                    "description": "What to look up, e.g. 'walkable neighborhoods and food'.",
                },
                "top_k": {
                    "type": ["integer", "null"],
                    "description": "Number of chunks to return (2-6).",
                },
            },
            "required": ["destination", "query", "top_k"],
            "additionalProperties": False,
        },
    },
]


def _tool_result_summary(name: str, result: dict[str, Any]) -> str:
    if name == "search_pois":
        return f"{result.get('count', 0)} POIs near {result.get('city')}"
    if name == "retrieve_guides":
        chunks = result.get("chunks") or []
        article = result.get("article") or result.get("error") or "no article"
        return f"{len(chunks)} guide chunks ({article})"
    return "ok"


class TripPlannerAgent:
    def __init__(
        self,
        api_key: str,
        *,
        model: str = DEFAULT_MODEL,
        user_agent: str = DEFAULT_USER_AGENT,
        enable_rag: bool = True,
        max_steps: int = 8,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.user_agent = user_agent
        self.enable_rag = enable_rag
        self.max_steps = max_steps
        self.on_event = on_event or (lambda _event: None)
        self.tool_state: dict[str, Any] = {
            "pois": {},
            "chunks": [],
            "city_meta": None,
        }
        self.trace: list[dict[str, Any]] = []

    def _emit(self, event: dict[str, Any]) -> None:
        self.trace.append(event)
        self.on_event(event)

    def _tools(self) -> list[dict[str, Any]]:
        if self.enable_rag:
            return TOOL_SCHEMAS
        return [tool for tool in TOOL_SCHEMAS if tool["name"] != "retrieve_guides"]

    def _execute_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "search_pois":
            limit = arguments.get("limit") or 30
            result = search_pois(
                city=arguments["city"],
                query=arguments.get("query"),
                interests=arguments.get("interests"),
                limit=int(limit),
                user_agent=self.user_agent,
            )
            for poi in result.get("pois") or []:
                self.tool_state["pois"][poi["poi_id"]] = poi
            self.tool_state["city_meta"] = {
                "city": result.get("city"),
                "lat": result.get("lat"),
                "lon": result.get("lon"),
                "bbox": result.get("bbox"),
            }
            return result
        if name == "retrieve_guides":
            if not self.enable_rag:
                return {"error": "RAG disabled", "chunks": []}
            result = retrieve_guides(
                destination=arguments["destination"],
                query=arguments.get("query") or arguments["destination"],
                top_k=int(arguments.get("top_k") or 4),
                user_agent=self.user_agent,
            )
            self.tool_state["chunks"].extend(result.get("chunks") or [])
            return result
        return {"error": f"Unknown tool: {name}"}

    def _system_instructions(self, fast_mode: bool) -> str:
        tool_policy = (
            "Call search_pois ONCE with broad criteria (limit around 40)."
            if fast_mode
            else "Call search_pois 2-3 times with complementary queries (limit around 30)."
        )
        rag_policy = (
            "You may call retrieve_guides once for local context."
            if self.enable_rag
            else "Do not call retrieve_guides."
        )
        return f"""You are a production trip-planning agent.

Rules:
- {tool_policy}
- {rag_policy}
- Only recommend places returned by search_pois. Never invent poi_id values.
- Use each selected POI at most once in the itinerary.
- Cluster nearby stops in the same day-block when coordinates allow.
- Respect pace: relaxed = 1-2 stops per block, moderate = 2-3, packed = 3-4.
- Honor constraints (budget, mobility, dietary, must-see / avoid).
- After tools have returned enough data, respond with ONLY a JSON object (no markdown):
{{
  "destination": string,
  "days": [
    {{
      "day": 1,
      "theme": string,
      "morning": [{{"poi_id": "osm_...", "name": string, "category": string, "why": string}}],
      "afternoon": [...],
      "evening": [...]
    }}
  ],
  "notes": string,
  "sources": [string]
}}
- `why` should be one concise sentence tying the stop to the traveler's interests.
- `sources` may include Wikivoyage URLs when RAG was used.
"""

    def _run_loop(self, user_prompt: str, fast_mode: bool) -> str:
        tools = self._tools()
        input_items: list[dict[str, Any]] = [
            {"role": "developer", "content": self._system_instructions(fast_mode)},
            {"role": "user", "content": user_prompt},
        ]

        for step in range(1, self.max_steps + 1):
            started = time.time()
            self._emit({"step": step, "phase": "model", "message": f"Calling {self.model}"})
            response = self.client.responses.create(
                model=self.model,
                tools=tools,
                input=input_items,
                temperature=0.4,
            )
            elapsed = round(time.time() - started, 2)
            output_items = list(getattr(response, "output", None) or [])
            function_calls = [item for item in output_items if getattr(item, "type", None) == "function_call"]

            if not function_calls:
                text = getattr(response, "output_text", None) or ""
                if not text:
                    parts = []
                    for item in output_items:
                        for content in getattr(item, "content", None) or []:
                            if getattr(content, "type", "") in {"output_text", "text"}:
                                parts.append(getattr(content, "text", ""))
                    text = "\n".join(parts)
                self._emit(
                    {
                        "step": step,
                        "phase": "final",
                        "message": "Model returned itinerary JSON",
                        "seconds": elapsed,
                    }
                )
                return text

            for item in output_items:
                serialized = item.model_dump() if hasattr(item, "model_dump") else item
                input_items.append(serialized)

            for call in function_calls:
                name = getattr(call, "name", "")
                raw_args = getattr(call, "arguments", "{}")
                call_id = getattr(call, "call_id", "")
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
                except json.JSONDecodeError:
                    args = {}
                self._emit(
                    {
                        "step": step,
                        "phase": "tool",
                        "message": f"{name}({json.dumps(args)[:180]})",
                        "seconds": elapsed,
                    }
                )
                t0 = time.time()
                try:
                    result = self._execute_tool(name, args)
                    ok = True
                except Exception as exc:
                    result = {"error": str(exc)}
                    ok = False
                duration = round(time.time() - t0, 2)
                self._emit(
                    {
                        "step": step,
                        "phase": "tool_result",
                        "message": _tool_result_summary(name, result) if ok else f"{name} failed: {result.get('error')}",
                        "seconds": duration,
                        "ok": ok,
                    }
                )
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": json.dumps(result, ensure_ascii=False)[:12000],
                    }
                )

        raise TimeoutError(
            f"Agent exceeded max_steps={self.max_steps} without producing a final itinerary."
        )

    def plan(
        self,
        *,
        destination: str,
        days: int,
        pace: str,
        interests: list[str],
        constraints: str = "",
        fast_mode: bool = True,
    ) -> dict[str, Any]:
        self._emit({"step": 0, "phase": "prefetch", "message": f"Searching POIs in {destination}"})
        try:
            seeded = self._execute_tool(
                "search_pois",
                {
                    "city": destination,
                    "query": None,
                    "interests": interests or None,
                    "limit": 40 if fast_mode else 30,
                },
            )
            self._emit(
                {
                    "step": 0,
                    "phase": "prefetch_result",
                    "message": _tool_result_summary("search_pois", seeded),
                    "ok": True,
                }
            )
        except Exception as exc:
            self._emit({"step": 0, "phase": "prefetch_result", "message": str(exc), "ok": False})
            raise

        if not self.tool_state["pois"]:
            raise RuntimeError(
                f"No mapped places were found for {destination}. "
                "Try a more specific city name or different interests."
            )

        catalog = [
            {
                "poi_id": poi["poi_id"],
                "name": poi["name"],
                "category": poi.get("category"),
                "lat": poi.get("lat"),
                "lon": poi.get("lon"),
            }
            for poi in list(self.tool_state["pois"].values())[:40]
        ]
        prompt = (
            f"Plan a {days}-day {pace}-pace trip to {destination}.\n"
            f"Interests: {', '.join(interests) or 'general sightseeing'}.\n"
            f"Constraints: {constraints or 'none'}.\n"
            "These POIs were already retrieved. Use only these poi_id values unless you call search_pois again:\n"
            f"{json.dumps(catalog, ensure_ascii=False)}\n"
            "You may call tools for extra coverage, then return the itinerary JSON."
        )
        raw = self._run_loop(prompt, fast_mode=fast_mode)
        return self._finalize(raw)

    def refine(
        self,
        *,
        itinerary: dict[str, Any],
        request: str,
        target_day: int | None = None,
        fast_mode: bool = True,
    ) -> dict[str, Any]:
        catalog = [
            {
                "poi_id": poi["poi_id"],
                "name": poi["name"],
                "category": poi.get("category"),
            }
            for poi in self.tool_state["pois"].values()
        ]
        if target_day:
            prompt = (
                f"Goal: ONLY modify day {target_day}. All other days must remain EXACTLY unchanged.\n"
                f"Compare JSON structures to verify compliance.\n"
                f"Existing itinerary: {json.dumps(itinerary, ensure_ascii=False)}\n"
                f"Available POIs: {json.dumps(catalog, ensure_ascii=False)}\n"
                f"Request: {request}\n"
                "Use tools if you need additional POIs, then return the full updated itinerary JSON."
            )
        else:
            prompt = (
                "Refine the existing itinerary. Keep the same number of days. "
                "Only use poi_id values from tools / the available POI list.\n"
                f"Existing itinerary: {json.dumps(itinerary, ensure_ascii=False)}\n"
                f"Available POIs: {json.dumps(catalog, ensure_ascii=False)}\n"
                f"Request: {request}\n"
                "Return the full updated itinerary JSON."
            )
        raw = self._run_loop(prompt, fast_mode=fast_mode)
        refined = self._finalize(raw)
        if target_day:
            other_days_unchanged(itinerary, refined, target_day)
        return refined

    def _finalize(self, raw: str) -> dict[str, Any]:
        itin = extract_json(raw)
        validate_itinerary_poi_ids(itin, self.tool_state["pois"])
        enrich_itinerary(itin, self.tool_state["pois"])
        return itin
