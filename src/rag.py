"""Optional Wikivoyage RAG: fetch guides, chunk, TF-IDF retrieve."""

from __future__ import annotations

import html
import re
from functools import lru_cache
from typing import Any

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .config import WIKIVOYAGE_API
from .http_client import osm_headers, request_json

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_html(raw: str) -> str:
    text = html.unescape(raw or "")
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text)
    return text.strip()


def _chunk_text(text: str, target: int = 900, overlap: int = 80) -> list[str]:
    """Split on paragraph/sentence boundaries near the target size."""
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n{2,}|(?<=\.)\s+(?=[A-Z])", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs:
        if not buf:
            buf = para
            continue
        if len(buf) + 1 + len(para) <= target:
            buf = f"{buf} {para}"
        else:
            chunks.append(buf)
            tail = buf[-overlap:] if overlap and len(buf) > overlap else ""
            buf = f"{tail} {para}".strip()
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) > 80]


def search_wikivoyage_title(destination: str, user_agent: str | None = None) -> str | None:
    data = request_json(
        "GET",
        WIKIVOYAGE_API,
        params={
            "action": "query",
            "list": "search",
            "srsearch": destination,
            "srlimit": 5,
            "format": "json",
            "origin": "*",
        },
        headers=osm_headers(user_agent),
    )
    hits = (((data or {}).get("query") or {}).get("search")) or []
    if not hits:
        return None
    return hits[0].get("title")


def fetch_wikivoyage_extract(title: str, user_agent: str | None = None) -> str:
    data = request_json(
        "GET",
        WIKIVOYAGE_API,
        params={
            "action": "query",
            "prop": "extracts",
            "explaintext": 1,
            "exsectionformat": "plain",
            "titles": title,
            "format": "json",
            "redirects": 1,
            "origin": "*",
        },
        headers=osm_headers(user_agent),
    )
    pages = (((data or {}).get("query") or {}).get("pages")) or {}
    extracts = [page.get("extract", "") for page in pages.values() if page.get("extract")]
    return _clean_html("\n\n".join(extracts))


@lru_cache(maxsize=32)
def _index_destination(destination: str, user_agent: str) -> dict[str, Any] | None:
    title = search_wikivoyage_title(destination, user_agent=user_agent)
    if not title:
        return None
    text = fetch_wikivoyage_extract(title, user_agent=user_agent)
    chunks = _chunk_text(text)
    if not chunks:
        return None
    vectorizer = TfidfVectorizer(stop_words="english", max_features=8000, ngram_range=(1, 2))
    matrix = vectorizer.fit_transform(chunks)
    return {
        "title": title,
        "source": f"https://en.wikivoyage.org/wiki/{title.replace(' ', '_')}",
        "chunks": chunks,
        "vectorizer": vectorizer,
        "matrix": matrix,
    }


def retrieve_guides(
    destination: str,
    query: str,
    top_k: int = 4,
    user_agent: str | None = None,
) -> dict[str, Any]:
    """Return top-k Wikivoyage chunks for a destination + query."""
    dest = (destination or "").strip()
    q = (query or destination or "").strip()
    if not dest:
        raise ValueError("destination is required for retrieve_guides")

    try:
        index = _index_destination(dest, user_agent or "")
    except Exception as exc:  # noqa: BLE001 — RAG is optional
        return {
            "destination": dest,
            "query": q,
            "error": f"Wikivoyage unavailable: {exc}",
            "chunks": [],
        }

    if not index:
        return {
            "destination": dest,
            "query": q,
            "error": "No Wikivoyage article found for this destination.",
            "chunks": [],
        }

    query_vec = index["vectorizer"].transform([q])
    scores = cosine_similarity(query_vec, index["matrix"]).ravel()
    ranked = sorted(enumerate(scores), key=lambda item: item[1], reverse=True)[: max(1, min(top_k, 8))]

    chunks = []
    for rank, (idx, score) in enumerate(ranked, start=1):
        chunks.append(
            {
                "chunk_id": f"wv_{index['title'].replace(' ', '_')}_{idx}",
                "source": index["source"],
                "title": index["title"],
                "text": index["chunks"][idx],
                "score": round(float(score), 4),
                "rank": rank,
            }
        )
    return {
        "destination": dest,
        "query": q,
        "article": index["title"],
        "source": index["source"],
        "chunks": chunks,
    }
