"""HTTP helpers with retries, exponential backoff, and OSM-compliant headers."""

from __future__ import annotations

import time
from typing import Any

import requests

from .config import DEFAULT_USER_AGENT, HTTP_RETRIES, HTTP_TIMEOUT


def osm_headers(user_agent: str | None = None) -> dict[str, str]:
    ua = user_agent or DEFAULT_USER_AGENT
    return {
        "User-Agent": ua,
        "Accept": "application/json",
        "Accept-Language": "en",
    }


def request_json(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    data: Any = None,
    headers: dict[str, str] | None = None,
    timeout: int = HTTP_TIMEOUT,
    retries: int = HTTP_RETRIES,
    min_interval: float = 0.0,
) -> Any:
    """GET/POST JSON with 429/5xx backoff. Raises the last exception on failure."""
    if min_interval:
        time.sleep(min_interval)

    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.request(
                method,
                url,
                params=params,
                data=data,
                headers=headers or osm_headers(),
                timeout=timeout,
            )
            if response.status_code == 429:
                time.sleep(2**attempt)
                last_error = requests.HTTPError("429 Too Many Requests")
                continue
            if response.status_code >= 500:
                time.sleep(2**attempt)
                last_error = requests.HTTPError(f"{response.status_code} server error")
                continue
            response.raise_for_status()
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise ValueError(f"Non-JSON response from {url}: {response.text[:200]}") from exc
        except (requests.Timeout, requests.ConnectionError) as exc:
            last_error = exc
            time.sleep(2**attempt)
        except requests.HTTPError as exc:
            last_error = exc
            if getattr(exc.response, "status_code", 0) in {400, 401, 403, 404}:
                raise
            time.sleep(2**attempt)
    raise last_error or RuntimeError(f"Request to {url} failed after {retries} attempts")
