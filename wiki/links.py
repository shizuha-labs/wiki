"""
WIKI-11: cross-link insertion + resolution/validation.

On save we resolve every internal link a page contains — `[[target]]`
wikilinks (in content_text and content_json text) and page-referencing
hrefs/ids in the TipTap content_json — sync the PageLink backlink index
(WIKI-10), and return the list of unresolvable ("dangling") targets so the
caller can surface them as a NON-blocking save warning.
"""
import re

from django.utils.text import slugify

# [[Target]] or [[Target|display alias]] — target excludes [ ] |
WIKILINK_RE = re.compile(r'\[\[\s*([^\[\]|]+?)\s*(?:\|[^\[\]]*)?\]\]')
_UUID_RE = re.compile(
    r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I
)
# Canonical internal page path: /spaces/<key>/pages/<slug> (optionally /wiki-prefixed).
# Precise on purpose — a broad "/...page..." heuristic would flag unrelated
# relative paths like /users/foo (WIKI-11 review P3).
_INTERNAL_PATH_RE = re.compile(r'(?:/wiki)?/spaces/[^/]+/pages/([^/?#]+)')


def _walk(node):
    """Yield every dict node in a TipTap content_json tree."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _collect_text_and_hrefs(content_json):
    """Return (list of text strings, list of href/id strings) from TipTap JSON."""
    texts, hrefs = [], []
    for n in _walk(content_json or {}):
        if n.get('type') == 'text' and isinstance(n.get('text'), str):
            texts.append(n['text'])
        for mark in (n.get('marks') or []):
            if isinstance(mark, dict) and mark.get('type') == 'link':
                href = (mark.get('attrs') or {}).get('href')
                if isinstance(href, str):
                    hrefs.append(href)
        attrs = n.get('attrs') or {}
        if n.get('type') in ('pageLink', 'wikiLink', 'mention'):
            for key in ('href', 'pageId', 'page_id', 'id', 'target'):
                val = attrs.get(key)
                if isinstance(val, str):
                    hrefs.append(val)
    return texts, hrefs


def extract_link_targets(page):
    """De-duped list of raw internal-link targets in `page`.

    Sources: `[[...]]` wikilinks (content_text + content_json text) and
    internal page references in content_json hrefs/ids (a UUID, or an internal
    relative `/wiki/.../<slug>` path). External URLs (http/https/mailto) are
    ignored — they are not internal links and never count as dangling.
    """
    texts, hrefs = _collect_text_and_hrefs(page.content_json)
    blob = (page.content_text or '') + '\n' + '\n'.join(texts)

    targets = []
    for raw in WIKILINK_RE.findall(blob):
        t = raw.strip()
        if t:
            targets.append(t)

    for href in hrefs:
        um = _UUID_RE.search(href)
        if um:
            targets.append(um.group(0))
            continue
        pm = _INTERNAL_PATH_RE.search(href)
        if pm:
            targets.append(pm.group(1))  # the page slug
        # else: external/non-page URL — not an internal link, skip

    seen, out = set(), []
    for t in targets:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out


def resolve_target(space, raw):
    """Resolve a raw target to a Page, or None.

    Order: by id (UUID, cross-space) → by slug (within space) → by
    case-insensitive title (within space).
    """
    from .models import Page

    raw = (raw or '').strip()
    if not raw:
        return None

    um = _UUID_RE.search(raw)
    if um:
        p = Page.objects.filter(id=um.group(0)).first()
        if p:
            return p

    p = Page.objects.filter(space=space, slug=slugify(raw)).first()
    if p:
        return p
    p = Page.objects.filter(space=space, slug=raw).first()
    if p:
        return p
    return Page.objects.filter(space=space, title__iexact=raw).first()


def sync_page_links(page):
    """Resolve all internal links in `page`, sync the PageLink backlink index
    (replace this page's outgoing links), and return the sorted-by-appearance
    list of UNRESOLVED (dangling) target strings.
    """
    from .models import PageLink

    resolved_ids = set()
    dangling = []
    for raw in extract_link_targets(page):
        target = resolve_target(page.space, raw)
        if target is None:
            dangling.append(raw)
        elif target.pk != page.pk:  # ignore self-links
            resolved_ids.add(target.pk)

    # Replace this page's outgoing links with the freshly-resolved set.
    PageLink.objects.filter(source_page=page).exclude(
        target_page_id__in=resolved_ids
    ).delete()
    existing = set(
        PageLink.objects.filter(source_page=page).values_list(
            'target_page_id', flat=True
        )
    )
    to_create = [
        PageLink(source_page=page, target_page_id=tid)
        for tid in resolved_ids
        if tid not in existing
    ]
    if to_create:
        PageLink.objects.bulk_create(to_create, ignore_conflicts=True)

    seen, out = set(), []
    for d in dangling:
        if d.lower() not in seen:
            seen.add(d.lower())
            out.append(d)
    return out


def format_page_link(page, alias=None):
    """Insert helper (WIKI-11): a correctly-formatted wikilink to `page`.

    Uses the page slug (stable + resolvable); pass `alias` for a display label.
    """
    base = page.slug or page.title
    return f'[[{base}|{alias}]]' if alias else f'[[{base}]]'
