"""WIKI-131 — extractive cited answers. No LLM in this path.

Relevance floor is a named deployment constant. A passage must meet or exceed
it before any sentence is returned as an answer. Below the floor the endpoint
refuses and still returns the best citations it already retrieved.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

# Default relevance floor (WIKI-131). Fraction of question terms that must
# appear in a section before that section may supply an extractive answer.
# Recorded in the PR: 0.5. Tunable per deployment by replacing this constant.
CITED_ANSWER_RELEVANCE_FLOOR = 0.5
# Published pages scanned after the permission filter. v1 bound, not a floor.
CITED_ANSWER_SCAN_CAP = 80

EXCERPT_MAX_CHARS = 400
ANSWER_MAX_CHARS = 500
DEFAULT_MAX_CITATIONS = 5
MAX_CITATIONS_CAP = 8

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")


def question_terms(question: str) -> list[str]:
    seen = []
    for token in _TOKEN_RE.findall((question or "").lower()):
        if token not in seen:
            seen.append(token)
    return seen


def section_rank(terms: list[str], text: str) -> float:
    """Deterministic overlap rank in [0, 1]. Empty question ranks 0."""
    if not terms:
        return 0.0
    hay = set(_TOKEN_RE.findall((text or "").lower()))
    return sum(1 for term in terms if term in hay) / len(terms)


def extractive_sentences(terms: list[str], text: str) -> str:
    """Best matching sentences, deterministic, bounded."""
    scored = []
    for sentence in _SENTENCE_RE.findall(text or ""):
        cleaned = " ".join(sentence.split())
        if not cleaned:
            continue
        scored.append((section_rank(terms, cleaned), cleaned))
    scored.sort(key=lambda item: (-item[0], item[1]))
    parts = []
    total = 0
    for rank, sentence in scored:
        if rank <= 0:
            break
        if parts and total + 1 + len(sentence) > ANSWER_MAX_CHARS:
            break
        parts.append(sentence)
        total += len(sentence) + 1
        if len(parts) == 2:
            break
    return " ".join(parts)[:ANSWER_MAX_CHARS]


def excerpt_of(text: str) -> str:
    flat = " ".join((text or "").split())
    if len(flat) <= EXCERPT_MAX_CHARS:
        return flat
    return flat[: EXCERPT_MAX_CHARS - 1] + "…"


def compose_cited_answer(question: str, passages: list[dict], *, max_citations: int = DEFAULT_MAX_CITATIONS, include_verification: bool = False):
    """Compose an extractive answer or a refuse-with-citations payload.

    ``passages`` must already be permission-filtered. Each passage needs
    page_id, version, section_hash, title, text, and optional verified/verified_at.
    """
    terms = question_terms(question)
    limit = max(1, min(int(max_citations or DEFAULT_MAX_CITATIONS), MAX_CITATIONS_CAP))
    ranked = []
    for passage in passages:
        text = passage.get("text") or ""
        rank = section_rank(terms, f"{passage.get('title') or ''} {text}")
        ranked.append((rank, str(passage.get("page_id") or ""), passage))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    citations = []
    for rank, _page_id, passage in ranked[:limit]:
        citation = {
            "page_id": str(passage.get("page_id") or ""),
            "version": int(passage.get("version") or 0),
            "section_hash": str(passage.get("section_hash") or ""),
            "title": str(passage.get("title") or ""),
            "excerpt": excerpt_of(passage.get("text") or ""),
            "rank": round(rank, 4),
        }
        if include_verification:
            citation["verified"] = bool(passage.get("verified"))
            citation["verified_at"] = passage.get("verified_at")
        citations.append(citation)
    generated_at = datetime.now(timezone.utc).isoformat()
    best = ranked[0][0] if ranked else 0.0
    if best < CITED_ANSWER_RELEVANCE_FLOOR or not citations:
        return {
            "answer": None,
            "refusal": "no_passage_clears_floor",
            "citations": citations,
            "generated_at": generated_at,
            "relevance_floor": CITED_ANSWER_RELEVANCE_FLOOR,
        }
    winner = ranked[0][2]
    return {
        "answer": extractive_sentences(terms, winner.get("text") or ""),
        "citations": citations,
        "generated_at": generated_at,
        "relevance_floor": CITED_ANSWER_RELEVANCE_FLOOR,
    }
