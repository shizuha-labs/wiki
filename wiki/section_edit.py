"""Section-scoped wiki edit helpers (WIKI-8).

The wiki stores canonical agent-authored content as Markdown/plain text in
``Page.content_text``. These helpers identify Markdown heading sections
(deteministically by title, explicit ``{#anchor}``, or slug anchor), hash the
exact section text, and splice only the requested section.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable

from django.utils.text import slugify


_HEADING_RE = re.compile(r'^(?P<marks>#{1,6})\s+(?P<title>.*?)(?:\s+\{#(?P<anchor>[A-Za-z0-9_-]+)\}\s*)?$')
# CommonMark fenced-code opener/closer: up to 3 leading spaces, 3+ fence chars,
# optional info string. A closing fence must be the same char and at least as
# long as the opening one (WIKI-51).
_FENCE_RE = re.compile(r'^(?P<indent>[ ]{0,3})(?P<fence>(?P<char>[`~]){3,})(?P<rest>.*)$')


class _FenceTracker:
    """Tracks fenced-code state while scanning for headings (WIKI-51).

    A line inside a fenced code block that begins with ``#`` (a Python/shell
    comment) must NOT be indexed as a Markdown heading. Handles both fence
    chars, >3-char fences, info strings, <=3-space indentation, nested fences
    (different char), and unterminated fences at EOF (stays in-fence).
    """

    def __init__(self) -> None:
        self._char: str | None = None
        self._length = 0

    def in_fence(self) -> bool:
        return self._char is not None

    def update(self, line: str) -> None:
        """Advance fence state from one raw line (no trailing newline)."""
        match = _FENCE_RE.match(line)
        if self._char is None:
            if match:
                self._char = match.group('char')
                self._length = len(match.group('fence'))
            return
        if match and match.group('char') == self._char and len(match.group('fence')) >= self._length:
            # Closing fence: same char, at least as long as the opener.
            self._char = None
            self._length = 0


def _iter_heading_matches(text: str):
    """Yield ``(line_no, start_offset, heading_match)`` for lines outside fences.

    Converges the heading scan on one fence-aware path so every consumer
    (sections, anchors, section-boundary resolution, TipTap conversion) sees the
    same document structure (WIKI-51).
    """
    fence = _FenceTracker()
    for line_no, line, start, _end in _iter_line_offsets(text or ''):
        raw = line.rstrip('\r\n')
        fence.update(raw)
        if fence.in_fence():
            continue
        match = _HEADING_RE.match(raw)
        if match:
            yield line_no, start, match


@dataclass(frozen=True)
class MarkdownSection:
    heading: str
    anchor: str
    level: int
    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    content: str

    @property
    def section_hash(self) -> str:
        return hash_section(self.content)


def hash_section(content: str) -> str:
    """Stable SHA-256 hash of the exact section bytes the caller read."""
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def _iter_line_offsets(text: str) -> Iterable[tuple[int, str, int, int]]:
    offset = 0
    for line_no, line in enumerate(text.splitlines(keepends=True), start=1):
        start = offset
        offset += len(line)
        yield line_no, line, start, offset
    if text == '':
        return
    if not text.endswith(('\n', '\r')):
        return


def _heading_title(raw_title: str) -> str:
    return re.sub(r'\s+', ' ', (raw_title or '').strip())


def list_markdown_sections(text: str) -> list[MarkdownSection]:
    """Return all Markdown heading sections in document order.

    A section starts at a heading and ends immediately before the next heading
    of the same or a higher level. Nested subheadings remain inside their
    parent section. Headings inside fenced code blocks are ignored (WIKI-51).
    """
    lines = list(_iter_line_offsets(text or ''))
    headings = []
    for line_no, start, match in _iter_heading_matches(text or ''):
        title = _heading_title(match.group('title'))
        explicit_anchor = match.group('anchor') or ''
        headings.append({
            'idx': len(headings),
            'line_no': line_no,
            'start': start,
            'level': len(match.group('marks')),
            'heading': title,
            'anchor': explicit_anchor or slugify(title),
        })

    sections: list[MarkdownSection] = []
    for pos, heading in enumerate(headings):
        end_offset = len(text or '')
        end_line = lines[-1][0] if lines else heading['line_no']
        for later in headings[pos + 1:]:
            if later['level'] <= heading['level']:
                end_offset = later['start']
                end_line = later['line_no'] - 1
                break
        content = (text or '')[heading['start']:end_offset]
        sections.append(MarkdownSection(
            heading=heading['heading'],
            anchor=heading['anchor'],
            level=heading['level'],
            start_line=heading['line_no'],
            end_line=end_line,
            start_offset=heading['start'],
            end_offset=end_offset,
            content=content,
        ))
    return sections


def find_section(text: str, heading_or_anchor: str) -> MarkdownSection:
    query = (heading_or_anchor or '').strip()
    if not query:
        raise ValueError('heading_or_anchor is required')
    normalized_query = query.lstrip('#').strip().lower()
    anchor_query = slugify(normalized_query)
    matches = []
    for section in list_markdown_sections(text):
        heading_key = section.heading.lower()
        section_anchor = section.anchor.lower()
        if normalized_query == heading_key or normalized_query == section_anchor or anchor_query == section_anchor:
            matches.append(section)
    if not matches:
        raise LookupError(f'section {query!r} not found')
    if len(matches) > 1:
        raise ValueError(f'section {query!r} is ambiguous; use an explicit unique anchor')
    return matches[0]


def _replacement_text(original: MarkdownSection, new_content: str) -> str:
    content = (new_content or '').strip('\n')
    if _HEADING_RE.match(content.splitlines()[0] if content.splitlines() else ''):
        replacement = content
    else:
        first_line = original.content.splitlines()[0] if original.content.splitlines() else f"{'#' * original.level} {original.heading}"
        replacement = first_line.rstrip('\r\n')
        if content:
            replacement += '\n' + content
    # Preserve a newline before the next section/body when the original had one.
    if original.content.endswith('\n'):
        replacement += '\n'
    return replacement


def splice_section(text: str, section: MarkdownSection, new_content: str) -> str:
    replacement = _replacement_text(section, new_content)
    return (text or '')[:section.start_offset] + replacement + (text or '')[section.end_offset:]


def text_to_tiptap_json(text: str) -> dict:
    """Small server-side Markdown/plaintext to TipTap converter for section edits.

    MCP full-page updates already send richer JSON. Section edits need a safe
    server-side fallback so ``content_json`` stays broadly renderable after the
    server splices ``content_text``.
    """
    blocks = []
    paragraph: list[str] = []
    fence = _FenceTracker()

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            blocks.append({
                'type': 'paragraph',
                'content': [{'type': 'text', 'text': '\n'.join(paragraph)}],
            })
            paragraph = []

    for line_no, line, _start, _end in _iter_line_offsets(text or ''):
        raw = line.rstrip('\r\n')
        fence.update(raw)
        if fence.in_fence():
            # Fenced code content is literal — never a heading (WIKI-51).
            paragraph.append(line.rstrip('\r\n'))
            continue
        match = _HEADING_RE.match(raw)
        if match:
            flush_paragraph()
            title = _heading_title(match.group('title'))
            blocks.append({
                'type': 'heading',
                'attrs': {'level': len(match.group('marks'))},
                'content': [{'type': 'text', 'text': title}],
            })
        elif line.strip() == '':
            flush_paragraph()
        else:
            paragraph.append(line)
    flush_paragraph()
    return {'type': 'doc', 'content': blocks or [{'type': 'paragraph'}]}
