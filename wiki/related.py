"""Related-page ranking for WIKI-13.

Combines three cheap, explainable signals:
- shared labels
- PageLink graph adjacency (1-hop and 2-hop)
- title/content term similarity
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Iterable

from django.db.models import Q, QuerySet

from .models import Page, PageLink

_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{2,}")
_STOP = {
    'the', 'and', 'for', 'with', 'from', 'that', 'this', 'are', 'was', 'were',
    'page', 'wiki', 'doc', 'docs', 'how', 'what', 'why', 'when', 'where', 'into',
}


def _terms(*parts: str) -> set[str]:
    words: set[str] = set()
    for part in parts:
        for word in _WORD_RE.findall(part or ''):
            w = word.lower()
            if w not in _STOP:
                words.add(w)
    return words


def _label_ids(page: Page) -> set[str]:
    return {str(v) for v in page.labels.values_list('id', flat=True)}


def _graph_sets(page: Page) -> tuple[set[str], set[str]]:
    """Return (one-hop, two-hop) related page ids as strings."""
    outgoing = set(PageLink.objects.filter(source_page=page).values_list('target_page_id', flat=True))
    incoming = set(PageLink.objects.filter(target_page=page).values_list('source_page_id', flat=True))
    one_hop = {str(v) for v in outgoing | incoming}

    raw_two = set(PageLink.objects.filter(
        Q(source_page_id__in=outgoing | incoming) | Q(target_page_id__in=outgoing | incoming)
    ).values_list('source_page_id', 'target_page_id'))
    two_hop: set[str] = set()
    for source_id, target_id in raw_two:
        if source_id != page.id:
            two_hop.add(str(source_id))
        if target_id != page.id:
            two_hop.add(str(target_id))
    two_hop.difference_update(one_hop)
    return one_hop, two_hop


def related_pages_for(page: Page, visible_pages: QuerySet[Page] | None = None, limit: int = 6) -> list[dict]:
    """Rank related pages visible to the caller.

    Returns dictionaries with `page`, `score`, and `reasons` so callers can serialize
    the page and show why it was suggested.
    """
    limit = max(1, min(int(limit or 6), 20))
    if visible_pages is None:
        visible_pages = Page.objects.all()
    candidates = list(
        visible_pages
        .exclude(id=page.id)
        .filter(space__organization_id=page.space.organization_id, status='published')
        .select_related('space')
        .prefetch_related('labels')[:500]
    )

    source_labels = _label_ids(page)
    source_terms = _terms(page.title, page.content_text)
    one_hop, two_hop = _graph_sets(page)

    ranked: list[dict] = []
    for candidate in candidates:
        score = 0.0
        reasons: list[str] = []

        shared_labels = source_labels & _label_ids(candidate)
        if shared_labels:
            score += 4.0 + len(shared_labels)
            reasons.append('shared_labels')

        cid = str(candidate.id)
        if cid in one_hop:
            score += 6.0
            reasons.append('linked')
        elif cid in two_hop:
            score += 2.0
            reasons.append('nearby_link')

        cand_terms = _terms(candidate.title, candidate.content_text)
        if source_terms and cand_terms:
            overlap = source_terms & cand_terms
            if overlap:
                similarity = len(overlap) / max(len(source_terms | cand_terms), 1)
                score += 1.0 + (6.0 * similarity)
                reasons.append('similar_content')

        if score > 0:
            ranked.append({'page': candidate, 'score': round(score, 3), 'reasons': reasons})

    ranked.sort(key=lambda item: (-item['score'], item['page'].title.lower()))
    return ranked[:limit]
