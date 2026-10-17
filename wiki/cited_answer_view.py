"""POST /api/answer/ — WIKI-131. Permission filter runs before excerpt extraction."""
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from wiki.cited_answer import (
    CITED_ANSWER_RELEVANCE_FLOOR,
    CITED_ANSWER_SCAN_CAP,
    DEFAULT_MAX_CITATIONS,
    compose_cited_answer,
)
from wiki.section_edit import list_markdown_sections
from wiki.views import visible_pages_qs

# Documented next to the handler (WIKI-131). Default is 0.5.
RELEVANCE_FLOOR = CITED_ANSWER_RELEVANCE_FLOOR


class CitedAnswerView(APIView):
    """Extractive cited answer. No LLM. Anonymous callers get no verification fields."""

    permission_classes = [AllowAny]

    def post(self, request):
        question = str(request.data.get("question") or "").strip()
        if len(question) < 2:
            return Response({"detail": "question is required"}, status=400)
        if len(question) > 500:
            return Response({"detail": "question too large"}, status=400)
        space_id = request.data.get("space_id") or request.data.get("space")
        try:
            max_citations = int(request.data.get("max_citations") or DEFAULT_MAX_CITATIONS)
        except (TypeError, ValueError):
            return Response({"detail": "max_citations must be an integer"}, status=400)

        pages = visible_pages_qs(request).filter(status="published")
        if space_id:
            pages = pages.filter(space_id=space_id)
        # Bound the scan. Section ranking is in-process and deterministic.
        # CITED_ANSWER_SCAN_CAP: v1 scans at most this many published pages
        # after the permission filter. Named so the bound is not an inline magic number.
        pages = pages.order_by("id")[:CITED_ANSWER_SCAN_CAP]

        passages = []
        for page in pages.only("id", "title", "content_text", "version"):
            # verified_at is not on Page until Slice A. Do not touch a deferred
            # field here; verification metadata stays omitted until that column exists.
            sections = list_markdown_sections(page.content_text or "")
            if not sections:
                sections_payload = [{
                    "text": page.content_text or "",
                    "section_hash": "",
                }]
            else:
                sections_payload = [
                    {"text": section.content, "section_hash": section.section_hash}
                    for section in sections
                ]
            for section in sections_payload:
                passages.append({
                    "page_id": page.id,
                    "version": page.version,
                    "section_hash": section["section_hash"],
                    "title": page.title,
                    "text": section["text"],
                    "verified": False,
                    "verified_at": None,
                })
        include_verification = bool(getattr(request.user, "is_authenticated", False))
        payload = compose_cited_answer(
            question,
            passages,
            max_citations=max_citations,
            include_verification=include_verification,
        )
        return Response(payload)
