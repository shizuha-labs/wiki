#!/usr/bin/env python3
"""
Shizuha Wiki MCP Server.

Team documentation tools for AI agents.

Tools (44):
  Spaces:
  - wiki_list_spaces: List wiki spaces
  - wiki_create_space: Create new space
  - wiki_get_space: Get space details
  - wiki_update_space: Update space metadata
  - wiki_delete_space: Delete a space
  - wiki_archive_space: Archive a space
  - wiki_unarchive_space: Unarchive a space
  - wiki_get_space_members: List space members
  - wiki_add_space_member: Add member to space
  - wiki_update_space_member: Update member role
  - wiki_remove_space_member: Remove member from space
  - wiki_get_space_tree: Get space page tree
  - wiki_watch_space: Toggle watch on space
  - wiki_get_space_permissions: Get space permissions

  Pages:
  - wiki_list_pages: List pages with filters
  - wiki_create_page: Create new page
  - wiki_create_page_from_template: Instantiate a page from a template
  - wiki_get_page: Get page content
  - wiki_update_page: Update page content
  - wiki_verify_page: Mark a page verified (editor-or-admin)
  - wiki_get_page_sections: List page sections and section hashes
  - wiki_update_page_section: Update one page section by heading/anchor
  - wiki_delete_page: Delete a page
  - wiki_list_page_versions: View page history
  - wiki_restore_page_version: Restore previous version
  - wiki_get_page_comments: List comments on a page
  - wiki_add_page_comment: Add comment to page
  - wiki_watch_page: Toggle watch on page
  - wiki_get_page_children: Get child pages
  - wiki_get_page_backlinks: Get pages linking to this page
  - wiki_move_page: Move page to different parent/space
  - wiki_reorder_pages: Reorder pages within parent

  Labels:
  - wiki_list_labels: List labels
  - wiki_create_label: Create new label
  - wiki_get_label: Get label details
  - wiki_update_label: Update a label
  - wiki_delete_label: Delete a label

  Templates:
  - wiki_list_templates: List page templates
  - wiki_create_template: Create page template
  - wiki_get_template: Get template details
  - wiki_update_template: Update a template
  - wiki_delete_template: Delete a template

  Attachments:
  - wiki_list_attachments: List attachments
  - wiki_upload_attachment: Upload attachment to page
  - wiki_get_attachment: Get attachment metadata
  - wiki_delete_attachment: Delete attachment
  - wiki_download_attachment: Get attachment download URL

  Comments:
  - wiki_list_comments: List comments
  - wiki_get_comment: Get comment details
  - wiki_update_comment: Update a comment
  - wiki_delete_comment: Delete a comment
  - wiki_resolve_comment: Resolve a comment
  - wiki_unresolve_comment: Unresolve a comment

  Search:
  - wiki_search_pages: Search wiki content
"""

import argparse
import base64
import hashlib
import json
import os
import re
import sys
from typing import Optional

from mcp.server.fastmcp import FastMCP
from mcp.types import BlobResourceContents, CallToolResult, EmbeddedResource, TextContent

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from base import ShizuhaMCPBase, run_mcp_server


def parse_args():
    """Parse command-line arguments for CLI argument compatibility."""
    parser = argparse.ArgumentParser(description="Shizuha Wiki MCP Server")
    parser.add_argument(
        "--jwt-token",
        help="JWT token for authentication (overrides SHIZUHA_WIKI_JWT_TOKEN env var)",
    )
    parser.add_argument(
        "--api-url",
        help="Wiki API URL (overrides SHIZUHA_WIKI_URL env var)",
    )
    args, _ = parser.parse_known_args()
    return args


# Parse CLI args (for callers that don't pass env vars to MCP subprocesses)
_args = parse_args()

# Configuration priority: CLI args > environment > defaults
WIKI_API_URL = (
    _args.api_url
    or os.environ.get("SHIZUHA_WIKI_URL")
    or os.environ.get("WIKI_API_URL")
)
WIKI_JWT_TOKEN = (
    _args.jwt_token
    or os.environ.get("SHIZUHA_WIKI_JWT_TOKEN")
    or os.environ.get("WIKI_JWT_TOKEN")
    or ""
)

# Stateless JSON responses are the MCP SDK's production-scalability mode.
# Keeping the default SSE response mode here made every fleet connection hold
# substantially more transport state; with dozens of agents the two Wiki pods
# repeatedly hit their memory limit and returned 502s (2026-07-16).
mcp = FastMCP("shizuha-wiki", stateless_http=True, json_response=True)

# Advertise OAuth 2.0 discovery metadata so MCP clients can discover the auth server.
from base import _register_oauth_discovery_routes as _reg_oauth_routes
_reg_oauth_routes(mcp, "wiki")
base = ShizuhaMCPBase("wiki", 8013, api_url=WIKI_API_URL, jwt_token=WIKI_JWT_TOKEN)


# ---------------------------------------------------------------------------
# Markdown-to-TipTap helpers
# ---------------------------------------------------------------------------

# WIKI-99 component-2(a): markdown image syntax → TipTap image node.
# `![alt](src)` or `![alt](src "title")`. The frontend render path
# (renderSafeImageTag/resolveSafeMediaSrc) is the render-time authority; this
# conversion mirrors its src rules so unsafe sources never become image nodes
# (they stay ordinary text/links instead).
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)\s]+)(?:\s+"([^"]*)")?\)')


def _safe_image_src(src: str) -> bool:
    """Mirror the frontend resolveSafeMediaSrc allow-list for image srcs.

    Allows http(s) URLs and same-origin /wiki/... paths (attachment view URLs).
    Rejects protocol-relative (//), embedded backslash/NUL tricks, and every
    other scheme (javascript:, data:, vbscript:, ...).
    """
    value = (src or '').strip()
    if not value or value.startswith('//') or '\\' in value or '\0' in value:
        return False
    if value.startswith('/wiki/'):
        return True
    if value.startswith('http://') or value.startswith('https://'):
        return True
    return False


def _image_node(src: str, alt: str = '', title: str = '') -> dict:
    attrs = {'src': src}
    if alt:
        attrs['alt'] = alt
    if title:
        attrs['title'] = title
    return {"type": "image", "attrs": attrs}


def _split_image_segments(text: str) -> list:
    """Split text into ('text', str) and ('image', node) segments.

    Image matches with a safe src become image nodes; unsafe or malformed
    matches stay in the text stream (the link parser handles them as before).
    """
    segments = []
    pos = 0
    for m in _IMAGE_RE.finditer(text):
        if not _safe_image_src(m.group(2)):
            continue
        if m.start() > pos:
            segments.append(('text', text[pos:m.start()]))
        segments.append(('image', _image_node(m.group(2), m.group(1) or '', m.group(3) or '')))
        pos = m.end()
    if pos < len(text):
        segments.append(('text', text[pos:]))
    if not segments and text:
        segments.append(('text', text))
    # Whitespace at segment edges is insignificant once the image becomes its
    # own block node — strip so paragraphs don't carry dangling spaces.
    return [(kind, payload.strip() if kind == 'text' else payload) for kind, payload in segments]


def _parse_inline(text: str) -> list:
    """Parse inline markdown (bold, italic, code, links) into TipTap text nodes."""
    if not text:
        return []

    nodes = []
    # Pattern matches: **bold**, *italic*, `code`, [text](url)
    pattern = re.compile(
        r'(\*\*(.+?)\*\*)'        # bold
        r'|(\*(.+?)\*)'           # italic
        r'|(`(.+?)`)'             # inline code
        r'|(\[([^\]]+)\]\(([^)]+)\))'  # link
    )

    pos = 0
    for m in pattern.finditer(text):
        # Add plain text before this match
        if m.start() > pos:
            plain = text[pos:m.start()]
            if plain:
                nodes.append({"type": "text", "text": plain})

        if m.group(2) is not None:  # bold
            nodes.append({"type": "text", "text": m.group(2), "marks": [{"type": "bold"}]})
        elif m.group(4) is not None:  # italic
            nodes.append({"type": "text", "text": m.group(4), "marks": [{"type": "italic"}]})
        elif m.group(6) is not None:  # code
            nodes.append({"type": "text", "text": m.group(6), "marks": [{"type": "code"}]})
        elif m.group(8) is not None:  # link
            nodes.append({
                "type": "text",
                "text": m.group(8),
                "marks": [{"type": "link", "attrs": {"href": m.group(9)}}],
            })

        pos = m.end()

    # Remaining text after last match
    if pos < len(text):
        remaining = text[pos:]
        if remaining:
            nodes.append({"type": "text", "text": remaining})

    # If nothing matched, return the whole text as a single node
    if not nodes and text:
        nodes.append({"type": "text", "text": text})

    return nodes


def _text_to_tiptap_json(text: str) -> dict:
    """
    Convert plain text or markdown to TipTap-compatible JSON.

    Supports: headings, bold, italic, code, links, bullet/ordered lists,
    code blocks, blockquotes, horizontal rules, and paragraph breaks.
    """
    if not text or not text.strip():
        return {"type": "doc", "content": [{"type": "paragraph"}]}

    lines = text.split("\n")
    doc_content = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        code_match = re.match(r'^```(\w*)', line)
        if code_match:
            lang = code_match.group(1) or None
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing ```
            node = {"type": "codeBlock", "content": [{"type": "text", "text": "\n".join(code_lines)}]}
            if lang:
                node["attrs"] = {"language": lang}
            doc_content.append(node)
            continue

        # Horizontal rule
        if re.match(r'^(---+|\*\*\*+|___+)\s*$', line.strip()):
            doc_content.append({"type": "horizontalRule"})
            i += 1
            continue

        # Heading
        heading_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            content = _parse_inline(heading_match.group(2))
            doc_content.append({
                "type": "heading",
                "attrs": {"level": level},
                "content": content,
            })
            i += 1
            continue

        # Markdown table (lines starting with |)
        if re.match(r'^\|(.+\|)\s*$', line):
            table_lines = []
            while i < len(lines) and re.match(r'^\|(.+\|)\s*$', lines[i]):
                table_lines.append(lines[i])
                i += 1
            if len(table_lines) >= 2:
                rows = []
                for row_idx, tl in enumerate(table_lines):
                    cells = [c.strip() for c in tl.strip('|').split('|')]
                    # Skip separator row (|---|---|)
                    if all(re.match(r'^[\-:\s]+$', c) for c in cells):
                        continue
                    is_header = (row_idx == 0)
                    cell_type = "tableHeader" if is_header else "tableCell"
                    row_content = []
                    for cell in cells:
                        inline = _parse_inline(cell)
                        row_content.append({
                            "type": cell_type,
                            "content": [{"type": "paragraph", "content": inline}] if inline else [{"type": "paragraph"}],
                        })
                    rows.append({"type": "tableRow", "content": row_content})
                if rows:
                    doc_content.append({"type": "table", "content": rows})
            continue

        # Blockquote (collect consecutive > lines)
        if line.startswith("> ") or line == ">":
            quote_lines = []
            while i < len(lines) and (lines[i].startswith("> ") or lines[i] == ">"):
                quote_lines.append(lines[i][2:] if lines[i].startswith("> ") else "")
                i += 1
            quote_text = "\n".join(quote_lines)
            paragraphs = [p.strip() for p in quote_text.split("\n\n") if p.strip()]
            if not paragraphs:
                paragraphs = [quote_text]
            quote_content = []
            for para in paragraphs:
                inline = _parse_inline(para.replace("\n", " "))
                if inline:
                    quote_content.append({"type": "paragraph", "content": inline})
                else:
                    quote_content.append({"type": "paragraph"})
            doc_content.append({"type": "blockquote", "content": quote_content})
            continue

        # Bullet list (collect consecutive - or * items)
        bullet_match = re.match(r'^[\-\*]\s+(.+)$', line)
        if bullet_match:
            items = []
            while i < len(lines) and re.match(r'^[\-\*]\s+(.+)$', lines[i]):
                item_match = re.match(r'^[\-\*]\s+(.+)$', lines[i])
                inline = _parse_inline(item_match.group(1))
                items.append({
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": inline}],
                })
                i += 1
            doc_content.append({"type": "bulletList", "content": items})
            continue

        # Ordered list (collect consecutive numbered items)
        ordered_match = re.match(r'^\d+\.\s+(.+)$', line)
        if ordered_match:
            items = []
            while i < len(lines) and re.match(r'^\d+\.\s+(.+)$', lines[i]):
                item_match = re.match(r'^\d+\.\s+(.+)$', lines[i])
                inline = _parse_inline(item_match.group(1))
                items.append({
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": inline}],
                })
                i += 1
            doc_content.append({"type": "orderedList", "content": items})
            continue

        # Empty line = skip (paragraph break)
        if not line.strip():
            i += 1
            continue

        # Standalone image line (WIKI-99): `![alt](src)` on its own line is a
        # block-level image node, not a paragraph.
        standalone = re.match(r'^\s*(!\[[^\]]*\]\([^)]+\))\s*$', line)
        if standalone:
            segments = _split_image_segments(standalone.group(1))
            for kind, payload in segments:
                if kind == 'image':
                    doc_content.append(payload)
                elif payload.strip():
                    inline = _parse_inline(payload)
                    doc_content.append({"type": "paragraph", "content": inline or [{"type": "text", "text": payload}]})
            i += 1
            continue

        # Regular paragraph (collect consecutive non-empty, non-special lines)
        para_lines = []
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i])
            i += 1
        para_text = " ".join(para_lines)
        # WIKI-99: inline images split the paragraph — TipTap's image node is
        # block-level, so `text ![img](src) more` becomes paragraph / image /
        # paragraph instead of a literal `![img](src)` text run.
        segments = _split_image_segments(para_text)
        if any(kind == 'image' for kind, _ in segments):
            for kind, payload in segments:
                if kind == 'image':
                    doc_content.append(payload)
                elif payload.strip():
                    inline = _parse_inline(payload)
                    doc_content.append({"type": "paragraph", "content": inline or [{"type": "text", "text": payload}]})
        else:
            inline = _parse_inline(para_text)
            if inline:
                doc_content.append({"type": "paragraph", "content": inline})
            else:
                doc_content.append({"type": "paragraph"})

    if not doc_content:
        doc_content = [{"type": "paragraph"}]

    return {"type": "doc", "content": doc_content}


def _is_block_start(line: str) -> bool:
    """Check if a line starts a block-level element."""
    if re.match(r'^#{1,6}\s+', line):
        return True
    if re.match(r'^```', line):
        return True
    if re.match(r'^(---+|\*\*\*+|___+)\s*$', line.strip()):
        return True
    if line.startswith("> ") or line == ">":
        return True
    if re.match(r'^[\-\*]\s+', line):
        return True
    if re.match(r'^\d+\.\s+', line):
        return True
    if re.match(r'^\|(.+\|)\s*$', line):
        return True
    # WIKI-99: a standalone image line is its own block — don't let paragraph
    # collection absorb it.
    if re.match(r'^\s*!\[[^\]]*\]\([^)]+\)\s*$', line):
        return True
    return False


# ===========================================================================
# Identity (org context discovery)
# ===========================================================================

@mcp.tool(name="wiki_get_my_identity")
def wiki_get_my_identity() -> str:
    """
    Get your own identity and the orgs you belong to.

    Use this BEFORE calling any write tool that requires `organization_id`.
    Returns your `organization_memberships` as `{org_id: role}` so you can
    pick the right org for the action you're about to take. Read tools
    aggregate across all your orgs by default — only writes need an
    explicit `organization_id`.
    """
    identity = base.get_identity()
    if "error" in identity:
        return base.format_error(identity)

    memberships = identity.get("organization_memberships") or {}
    output = "# Your Identity\n\n"
    output += f"**User ID**: {identity.get('user_id')}\n"
    output += f"**Username**: {identity.get('username')}\n"
    output += f"**Email**: {identity.get('email')}\n"
    output += f"**Is Agent**: {identity.get('is_agent', False)}\n\n"
    if memberships:
        output += "## Organization Memberships\n\n"
        output += "| Org ID | Role |\n|--------|------|\n"
        for org_id in sorted(memberships):
            output += f"| {org_id} | {memberships[org_id]} |\n"
        output += (
            "\nWrite tools (create/update/delete) require `organization_id` — "
            "pick one from the list above based on context. "
            "Read tools aggregate across all of these by default; pass "
            "`organization_id` to narrow to one.\n"
        )
    else:
        output += (
            "## No organization memberships\n\n"
            "You don't belong to any orgs. You can still read public spaces, "
            "but you cannot create/edit content until you're added to an org.\n"
        )
    return output


# ===========================================================================
# Spaces
# ===========================================================================

@mcp.tool(name="wiki_list_spaces")
def list_spaces(
    visibility: Optional[str] = None,
    organization_id: Optional[int] = None,
) -> str:
    """
    List wiki spaces the user has access to.

    Args:
        visibility: Filter by visibility (public, private, restricted)
        organization_id: Optional org scope. Omit to aggregate across every
            org you belong to (each space's organization_id is in the result
            so you can tell them apart). Set when you want spaces from a
            single org only. Use `wiki_get_my_identity` to discover your orgs.
    """
    params = {}
    if visibility:
        params["visibility"] = visibility

    result = base.api_request("GET", "/spaces/", params=params, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    spaces = (result if isinstance(result, list) else result.get("results", []))
    if not spaces:
        return "No spaces found."

    output = f"# Wiki Spaces ({len(spaces)})\n\n"
    for space in spaces:
        output += f"## {space.get('name')} [{space.get('key')}]\n"
        output += f"**ID**: {space.get('id')}\n"
        output += f"**Org**: {space.get('organization_id', 'N/A')}\n"
        output += f"**Type**: {space.get('space_type', 'N/A')}\n"
        output += f"**Visibility**: {space.get('visibility', 'N/A')}\n"
        if space.get('description'):
            output += f"**Description**: {space['description'][:100]}...\n"
        output += "\n"

    return output


@mcp.tool(name="wiki_create_space")
def create_space(
    name: str,
    key: str,
    organization_id: int,
    space_type: str = "documentation",
    visibility: str = "private",
    description: str = "",
) -> str:
    """
    Create a new wiki space.

    Args:
        name: Space name
        key: Short key (e.g., 'ENG')
        organization_id: Organization ID
        space_type: Type (documentation, knowledge_base, project, team, personal)
        visibility: Access level (public, private, restricted)
        description: Space description
    """
    data = {
        "name": name,
        "key": key.upper(),
        "space_type": space_type,
        "visibility": visibility,
        "description": description,
    }

    result = base.api_request("POST", "/spaces/", data=data, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    space = result
    return (
        f"Space created!\n\n"
        f"**Name**: {space.get('name')}\n"
        f"**Key**: {space.get('key')}\n"
        f"**ID**: {space.get('id')}\n"
        f"**Org**: {space.get('organization_id', organization_id)}\n"
    )


@mcp.tool(name="wiki_get_space")
def get_space(space_key: str) -> str:
    """
    Get detailed information about a wiki space.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("GET", f"/spaces/{space_key}/")
    if "error" in result:
        return base.format_error(result)

    space = result
    output = f"# {space.get('name')} [{space.get('key')}]\n\n"
    output += f"**ID**: {space.get('id')}\n"
    output += f"**Type**: {space.get('space_type')}\n"
    output += f"**Visibility**: {space.get('visibility')}\n"
    output += f"**Owner ID**: {space.get('owner_id')}\n"
    output += f"**Homepage ID**: {space.get('homepage_id', 'None')}\n"
    output += f"**Archived**: {space.get('is_archived', False)}\n"
    if space.get('description'):
        output += f"\n## Description\n{space['description']}\n"

    return output


@mcp.tool(name="wiki_update_space")
def update_space(
    space_key: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    visibility: Optional[str] = None,
    homepage_id: Optional[str] = None,
) -> str:
    """
    Update a wiki space's metadata.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
        name: New space name
        description: New description
        visibility: New visibility (public, private, restricted)
        homepage_id: Set homepage page ID
    """
    data = {}
    if name:
        data["name"] = name
    if description is not None:
        data["description"] = description
    if visibility:
        data["visibility"] = visibility
    if homepage_id:
        data["homepage_id"] = homepage_id

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/spaces/{space_key}/", data=data)
    if "error" in result:
        return base.format_error(result)

    space = result
    return (
        f"Space updated!\n\n"
        f"**Name**: {space.get('name')}\n"
        f"**Key**: {space.get('key')}\n"
    )


@mcp.tool(name="wiki_delete_space")
def delete_space(space_key: str) -> str:
    """
    Delete a wiki space and all its pages.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("DELETE", f"/spaces/{space_key}/")
    if "error" in result:
        return base.format_error(result)

    return f"Space '{space_key}' deleted."


@mcp.tool(name="wiki_archive_space")
def archive_space(space_key: str) -> str:
    """
    Archive a wiki space. Archived spaces are read-only.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("POST", f"/spaces/{space_key}/archive/")
    if "error" in result:
        return base.format_error(result)

    return f"Space '{space_key}' archived."


@mcp.tool(name="wiki_unarchive_space")
def unarchive_space(space_key: str) -> str:
    """
    Unarchive a wiki space, making it editable again.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("POST", f"/spaces/{space_key}/unarchive/")
    if "error" in result:
        return base.format_error(result)

    return f"Space '{space_key}' unarchived."


@mcp.tool(name="wiki_get_space_members")
def get_space_members(space_key: str) -> str:
    """
    List members of a wiki space and their roles.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("GET", f"/spaces/{space_key}/members/")
    if "error" in result:
        return base.format_error(result)

    members = (result if isinstance(result, list) else result.get("results", []))
    if not members:
        return "No members found."

    output = f"# Space Members ({len(members)})\n\n"
    for member in members:
        output += f"- **{member.get('email', member.get('user_email', member.get('user_id')))}**\n"
        output += f"  Role: {member.get('role', 'N/A')}\n"
        output += f"  Added: {member.get('created_at', 'N/A')}\n"

    return output


@mcp.tool(name="wiki_add_space_member")
def add_space_member(
    space_key: str,
    user_id: str,
    role: str = "viewer",
) -> str:
    """
    Add a member to a wiki space.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
        user_id: User ID to add
        role: Member role (viewer, editor, admin)
    """
    data = {
        "user_id": user_id,
        "role": role,
    }

    result = base.api_request("POST", f"/spaces/{space_key}/members/", data=data)
    if "error" in result:
        return base.format_error(result)

    return f"Member added to space with role '{role}'."


@mcp.tool(name="wiki_update_space_member")
def update_space_member(
    space_key: str,
    user_id: str,
    role: str,
) -> str:
    """
    Update a member's role in a wiki space.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
        user_id: User ID to update
        role: New role (viewer, editor, admin)
    """
    data = {
        "user_id": user_id,
        "role": role,
    }

    result = base.api_request("PATCH", f"/spaces/{space_key}/members/", data=data)
    if "error" in result:
        return base.format_error(result)

    return f"Member role updated to '{role}'."


@mcp.tool(name="wiki_remove_space_member")
def remove_space_member(space_key: str, user_id: str) -> str:
    """
    Remove a member from a wiki space.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
        user_id: User ID to remove
    """
    result = base.api_request("DELETE", f"/spaces/{space_key}/members/", data={"user_id": user_id})
    if "error" in result:
        return base.format_error(result)

    return f"Member removed from space."


@mcp.tool(name="wiki_get_space_tree")
def get_space_tree(space_key: str, max_depth: int = 5) -> str:
    """
    Get the full page tree hierarchy for a space.

    Returns pages organized in their parent-child tree structure.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
        max_depth: Maximum depth to traverse (default 5, max 10)
    """
    # Validate max_depth
    try:
        max_depth = min(max(1, int(max_depth)), 10)
    except (ValueError, TypeError):
        max_depth = 5

    params = {"max_depth": max_depth}
    result = base.api_request("GET", f"/spaces/{space_key}/tree/", params=params)

    # Check for errors
    if isinstance(result, dict) and "error" in result:
        return base.format_error(result)

    # Handle different response formats
    tree = result if isinstance(result, list) else result.get("results", [])

    if not tree:
        return f"Space '{space_key}' has no pages (or you don't have access)."

    output = f"# Page Tree for '{space_key}' ({max_depth} levels)\n\n"

    def format_tree_node(node, indent=0):
        prefix = "  " * indent
        out = f"{prefix}- **{node.get('title', 'Untitled')}**\n"
        out += f"{prefix}  ID: {node.get('id')}\n"
        children = node.get('children', [])
        if children:
            for child in children:
                out += format_tree_node(child, indent + 1)
        return out

    for node in tree:
        output += format_tree_node(node)

    return output


@mcp.tool(name="wiki_watch_space")
def watch_space(space_key: str) -> str:
    """
    Toggle watch on a space to receive notifications on changes.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("POST", f"/spaces/{space_key}/watch/")
    if "error" in result:
        return base.format_error(result)

    is_watching = result.get("is_watching", result.get("watching", True))
    return f"Space {'watched' if is_watching else 'unwatched'}."


@mcp.tool(name="wiki_get_space_permissions")
def get_space_permissions(space_key: str) -> str:
    """
    Get the effective permissions for a space.

    Args:
        space_key: Space key (e.g., 'ENG') or UUID
    """
    result = base.api_request("GET", f"/spaces/{space_key}/permissions/")
    if "error" in result:
        return base.format_error(result)

    perms = result
    output = f"# Space Permissions\n\n"
    if isinstance(perms, dict):
        for key, value in perms.items():
            output += f"**{key}**: {value}\n"
    elif isinstance(perms, list):
        for perm in perms:
            output += f"- **{perm.get('role', perm.get('name', 'N/A'))}**: {perm.get('permissions', perm)}\n"
    else:
        output += json.dumps(perms, indent=2)

    return output


# ===========================================================================
# Pages
# ===========================================================================

@mcp.tool(name="wiki_list_pages")
def list_pages(
    space_id: Optional[str] = None,
    space_key: Optional[str] = None,
    parent_id: Optional[str] = None,
    status: str = "published",
    limit: int = 20,
    organization_id: Optional[int] = None,
) -> str:
    """
    List wiki pages.

    Args:
        space_id: Filter by space ID (UUID)
        space_key: Filter by space key (e.g., 'ENG', 'OPS') — alternative to space_id
        parent_id: Filter by parent page ID
        status: Filter by status (draft, published, archived)
        limit: Maximum pages to return
        organization_id: Optional org scope. Omit to aggregate pages across
            every org you belong to. Each page result includes an
            `organization_id` so you can tell which org it belongs to.
    """
    params = {"status": status, "page_size": limit}
    if space_id:
        params["space"] = space_id
    if space_key:
        params["space_key"] = space_key
    if parent_id:
        params["parent"] = parent_id

    result = base.api_request("GET", "/pages/", params=params, organization_id=organization_id)

    # Check for errors
    if isinstance(result, dict) and "error" in result:
        return base.format_error(result)

    # Handle different response formats
    pages = result if isinstance(result, list) else result.get("results", [])

    if not pages:
        return "No pages found."

    total = result.get("count") if isinstance(result, dict) else len(pages)
    count_label = f"{len(pages)} of {total}" if total and total > len(pages) else f"{len(pages)}"
    output = f"# Wiki Pages ({count_label})\n\n"
    if total and total > len(pages):
        output += f"_Showing first {len(pages)} of {total}. Narrow with space_key/parent_id/status, or raise `limit`._\n\n"
    for page in pages:
        output += f"- **{page.get('title')}**\n"
        output += f"  ID: {page.get('id')}\n"
        output += f"  Slug: {page.get('slug')}\n"
        output += f"  Org: {page.get('organization_id', 'N/A')}\n"
        output += f"  Space: {page.get('space_key') or page.get('space')}\n"
        output += f"  Version: {page.get('version', 1)}\n"
        output += f"  Views: {page.get('view_count', 0)}\n"

    return output


@mcp.tool(name="wiki_create_page")
def create_page(
    space_id: str,
    title: str,
    content: str,
    parent_id: Optional[str] = None,
    status: str = "published",
    organization_id: Optional[int] = None,
) -> str:
    """
    Create a new wiki page inside a space.

    The page automatically inherits the space's org — you don't normally need
    to pass `organization_id`. Pass it only if you want to assert which org
    you expect (the server will refuse if you pass the wrong one).

    Args:
        space_id: Space ID to create page in (this also determines the org)
        title: Page title
        content: Page content (plain text or markdown)
        parent_id: Parent page ID for hierarchy
        status: Page status (draft, published)
        organization_id: OPTIONAL — assert the space's org. Usually omit;
            the page goes into whichever org owns the space.
    """
    data = {
        "space": space_id,
        "title": title,
        "content_text": content,
        "content_json": _text_to_tiptap_json(content),
        "status": status,
    }
    if parent_id:
        data["parent"] = parent_id

    result = base.api_request("POST", "/pages/", data=data, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    page = result
    return (
        f"Page created!\n\n"
        f"**Title**: {page.get('title')}\n"
        f"**ID**: {page.get('id')}\n"
        f"**Slug**: {page.get('slug')}\n"
        f"**Org**: {page.get('organization_id', organization_id)}\n"
        f"**Version**: {page.get('version', 1)}\n"
    )


@mcp.tool(name="wiki_create_page_from_template")
def create_page_from_template(
    template_id: str,
    space_id: str,
    title: str,
    parent_id: Optional[str] = None,
    status: str = "published",
    organization_id: Optional[int] = None,
) -> str:
    """Create a page by copying the canonical content of a template.

    Org-wide/global templates may be used in any writable space in the same
    organization. A space-scoped template may be used only in that space. The
    backend performs the copy through the normal page-create authorization,
    versioning, and link-index transaction.

    Args:
        template_id: Template UUID to instantiate.
        space_id: Writable target space UUID.
        title: Title for the new page.
        parent_id: Optional parent page UUID in the target space.
        status: Page status (draft or published).
        organization_id: Optional assertion for the target space's org.
    """
    data = {
        "template_id": template_id,
        "space": space_id,
        "title": title,
        "status": status,
    }
    if parent_id:
        data["parent"] = parent_id

    result = base.api_request("POST", "/pages/", data=data, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    return (
        f"Page created from template!\n\n"
        f"**Title**: {result.get('title')}\n"
        f"**ID**: {result.get('id')}\n"
        f"**Slug**: {result.get('slug')}\n"
        f"**Template**: {template_id}\n"
        f"**Org**: {result.get('organization_id', organization_id)}\n"
        f"**Version**: {result.get('version', 1)}\n"
    )


@mcp.tool(name="wiki_get_page")
def get_page(page_id: str) -> str:
    """
    Get a wiki page with full content.

    Args:
        page_id: Page ID (UUID) — a partial/prefix ID is resolved to the unique
            full UUID when unambiguous (WIKI-69); an ambiguous prefix returns a
            typed error listing the candidates instead of a bare 404.
    """
    result = base.api_request("GET", f"/pages/{page_id}/")
    if "error" in result:
        # WIKI-69: a bare 404 on a partial ID is a dead-end for cross-link
        # navigation. Resolve the prefix to the unique full UUID (or return an
        # actionable disambiguation) before giving up.
        resolved = _resolve_partial_page_id(page_id)
        if resolved is not None:
            result = base.api_request("GET", f"/pages/{resolved}/")
        elif resolved is False:
            return base.format_error({
                "error": "ambiguous prefix",
                "detail": f"Page ID prefix {page_id!r} matches multiple pages — be more specific.",
                "status_code": 409,
            })
        else:
            return base.format_error({
                "error": "not found",
                "detail": (
                    f"No page found for ID {page_id!r}. If this is a partial ID, "
                    "no page matches that prefix — check the full ID or search "
                    "the wiki (wiki_search_pages) instead."
                ),
                "status_code": 404,
            })

    if "error" in result:
        return base.format_error(result)

    page = result
    output = f"# {page.get('title')}\n\n"
    output += f"**ID**: {page.get('id')}\n"
    output += f"**Space**: {page.get('space_name', page.get('space'))}\n"
    output += f"**Status**: {page.get('status')}\n"
    output += f"**Version**: {page.get('version', 1)}\n"
    output += f"**Views**: {page.get('view_count', 0)}\n"

    if page.get('breadcrumbs'):
        crumbs = " > ".join([b.get('title', '') for b in page['breadcrumbs']])
        output += f"**Path**: {crumbs}\n"

    labels = page.get('labels', [])
    if labels:
        label_names = [l.get('name', str(l)) for l in labels]
        output += f"**Labels**: {', '.join(label_names)}\n"

    output += f"\n---\n\n"

    # Content - prefer plain text, fallback to JSON
    if page.get('content_text'):
        output += page['content_text']
    elif page.get('content_json'):
        output += f"```json\n{json.dumps(page['content_json'], indent=2)}\n```"
    else:
        output += "(No content)"

    return output


def _resolve_partial_page_id(page_id: str) -> Optional[str]:
    """Resolve a partial page ID prefix to the unique full UUID.

    Returns the full UUID when exactly one page matches the prefix; False when
    multiple pages match (ambiguous); None when no page matches.

    WIKI-85: resolution is a SINGLE server-side query (`/pages/?prefix=`) that
    filters on the UUID prefix in the backend, instead of walking every
    paginated /pages/ page in Python (1400+ pages at 20/page) — which exceeded
    the 30s MCP request timeout on every lookup.
    """
    if not page_id or len(page_id) < 4:
        return None
    prefix = page_id.lower()
    matches: list[str] = []
    try:
        result = base.api_request(
            "GET", "/pages/",
            params={"prefix": prefix, "page_size": 500},
        )
        if isinstance(result, dict) and "error" in result:
            return None
        pages = result if isinstance(result, list) else result.get("results", [])
        for p in pages:
            pid = str(p.get("id", "")).lower()
            if pid.startswith(prefix):
                matches.append(pid)
                # More than one match is ambiguous — short-circuit.
                if len(matches) > 1:
                    return False
    except Exception:
        return None
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        return False
    return None


@mcp.tool(name="wiki_update_page")
def update_page(
    page_id: str,
    title: Optional[str] = None,
    content: Optional[str] = None,
    status: Optional[str] = None,
    expected_version: Optional[int] = None,
) -> str:
    """
    Update a wiki page.

    Args:
        page_id: Page ID to update
        title: New title
        content: New content
        status: New status (draft, published, archived)
        expected_version: WIKI-7 optimistic concurrency — the page `version` you
            read before editing. When given, the save is REJECTED (409 conflict)
            if the page advanced since (someone else edited it), instead of
            silently overwriting their changes. Strongly recommended for any
            co-edited page: read the page, pass its `version` here; on conflict,
            re-pull + re-apply. Omit only for a deliberate unconditional save.
    """
    data = {}
    if title:
        data["title"] = title
    if content:
        data["content_text"] = content
        data["content_json"] = _text_to_tiptap_json(content)
    if status:
        data["status"] = status
    if expected_version is not None:
        data["expected_version"] = expected_version

    if not data or (len(data) == 1 and "expected_version" in data):
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/pages/{page_id}/", data=data)
    if "error" in result:
        # WIKI-7: surface the version conflict actionably so the caller re-pulls.
        err = result.get("error")
        if isinstance(err, dict) and err.get("error") == "version_conflict":
            return (
                f"⚠️ VERSION CONFLICT — NOT saved (WIKI-7 optimistic concurrency).\n"
                f"{err.get('detail')}\n"
                f"Re-pull the page (wiki_get_page), re-apply your changes onto the current "
                f"content, then update again with expected_version={err.get('current_version')}."
            )
        return base.format_error(result)

    page = result
    return (
        f"Page updated!\n\n"
        f"**Title**: {page.get('title')}\n"
        f"**Version**: {page.get('version')}\n"
    )



@mcp.tool(name="wiki_verify_page")
def verify_page(page_id: str, owner: Optional[int] = None) -> str:
    """
    Mark a wiki page as verified (WIKI-125): attest you reviewed the page and
    its content is correct as of now. Requires editor-or-admin on the page's
    space. Verification auto-clears on the next content change (same
    transaction as the write), so re-verify after meaningful edits.

    Args:
        page_id: Page ID (UUID)
        owner: Optional accountable user id (Shizuha ID integer) for
            re-verification. Defaults to you on the first verify; preserved on
            re-verify unless explicitly passed.
    """
    data = {}
    if owner is not None:
        if not isinstance(owner, int):
            return "⚠️ owner must be a Shizuha user id (integer) — resolve one via wiki_get_my_identity or the identity API first."
        data["owner"] = owner
    result = base.api_request("PATCH", f"/pages/{page_id}/verify/", data=data)
    if "error" in result:
        detail = result.get("detail")
        conflict = detail if isinstance(detail, dict) and detail.get("error") == "verify_conflict" else None
        if result.get("error") == "verify_conflict":
            conflict = result
        if conflict:
            return (
                "⚠️ VERIFY CONFLICT — not applied. The page content changed while "
                f"verifying (current version {conflict.get('current_version')}). "
                "Re-read the page and retry so you attest the content you actually saw."
            )
        return base.format_error(result)

    import datetime
    verified_at = result.get("verified_at")
    if isinstance(verified_at, str) and "T" in verified_at:
        try:
            verified_at = datetime.datetime.fromisoformat(verified_at.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M UTC")
        except ValueError:
            pass
    return (
        "# Page Verified\n\n"
        f"**Page**: {result.get('page_id')} (version {result.get('version')})\n"
        f"**Verified at**: {verified_at}\n"
        f"**Verified by**: user {result.get('verified_by_id')}\n"
        f"**Verify owner** (accountable for re-verification): user {result.get('verify_owner_id')}\n\n"
        "Verification auto-clears on the next content change; re-verify after meaningful edits."
    )


@mcp.tool(name="wiki_get_page_sections")

def get_page_sections(page_id: str) -> str:
    """
    List Markdown heading sections for a page, including WIKI-8 section hashes.

    Use this before wiki_update_page_section: read the target section's
    section_hash, then pass it as base_section_hash so stale same-section edits
    reject without blocking concurrent edits to other sections.

    Args:
        page_id: Page ID (UUID)
    """
    result = base.api_request("GET", f"/pages/{page_id}/sections/")
    if "error" in result:
        return base.format_error(result)

    output = f"Page sections (version {result.get('version')})\n\n"
    sections = result.get("sections", [])
    if not sections:
        return output + "No Markdown heading sections found. Add headings before using section-scoped edits."
    for section in sections:
        output += (
            f"- H{section.get('level')} {section.get('heading')} "
            f"(anchor: {section.get('anchor')}, lines {section.get('start_line')}-{section.get('end_line')})\n"
            f"  hash: `{section.get('section_hash')}`\n"
        )
    return output


@mcp.tool(name="wiki_update_page_section")
def update_page_section(
    page_id: str,
    heading_or_anchor: str,
    base_section_hash: str,
    content: str,
    change_message: Optional[str] = None,
) -> str:
    """
    Update exactly one Markdown heading section of a wiki page (WIKI-8).

    The server re-reads the current page, finds the heading/anchor, verifies
    base_section_hash against only that section, then splices just that block.
    Concurrent edits to different sections can both land; stale edits to this
    same section return a SECTION CONFLICT and are not saved.

    Args:
        page_id: Page ID (UUID)
        heading_or_anchor: Heading title, slug anchor, or explicit {#anchor}
        base_section_hash: section_hash from wiki_get_page_sections
        content: Replacement section body. If it starts with a Markdown heading,
            it replaces the whole section; otherwise the existing heading line is
            preserved and only the body is replaced.
        change_message: Optional history message
    """
    data = {
        "heading_or_anchor": heading_or_anchor,
        "base_section_hash": base_section_hash,
        "content": content,
    }
    if change_message:
        data["change_message"] = change_message
    result = base.api_request("POST", f"/pages/{page_id}/sections/", data=data)
    if "error" in result:
        detail = result.get("detail")
        if isinstance(detail, dict) and detail.get("error") == "section_conflict":
            return (
                "⚠️ SECTION CONFLICT — NOT saved (WIKI-8 section concurrency).\n"
                f"{detail.get('detail')}\n"
                f"Current section_hash: `{detail.get('current_section_hash')}`; "
                f"page version: {detail.get('current_version')}. Re-pull only this section, "
                "re-apply your body, and retry with the current hash."
            )
        return base.format_error(result)

    section = result.get("section", {})
    return (
        "Page section updated!\n\n"
        f"**Title**: {result.get('title')}\n"
        f"**Version**: {result.get('version')}\n"
        f"**Section**: {section.get('heading')} (anchor: {section.get('anchor')})\n"
        f"**New section_hash**: `{section.get('section_hash')}`\n"
    )


@mcp.tool(name="wiki_delete_page")
def delete_page(page_id: str) -> str:
    """
    Delete a wiki page.

    Args:
        page_id: Page ID (UUID)
    """
    result = base.api_request("DELETE", f"/pages/{page_id}/")
    if "error" in result:
        return base.format_error(result)

    return f"Page deleted."


@mcp.tool(name="wiki_list_page_versions")
def list_page_versions(page_id: str) -> str:
    """
    List version history for a page.

    Args:
        page_id: Page ID
    """
    result = base.api_request("GET", f"/pages/{page_id}/versions/")
    if "error" in result:
        return base.format_error(result)

    versions = (result if isinstance(result, list) else result.get("results", []))
    if not versions:
        return "No versions found."

    output = f"# Page Version History ({len(versions)})\n\n"
    for v in versions:
        output += f"- **Version {v.get('version_number')}**\n"
        output += f"  Created: {v.get('created_at')}\n"
        output += f"  By: {v.get('created_by_email', v.get('created_by_id'))}\n"
        if v.get('change_message'):
            output += f"  Message: {v['change_message']}\n"

    return output


@mcp.tool(name="wiki_restore_page_version")
def restore_page_version(page_id: str, version_number: int) -> str:
    """
    Restore a page to a previous version.

    Args:
        page_id: Page ID
        version_number: Version number to restore
    """
    result = base.api_request("POST", f"/pages/{page_id}/restore_version/", data={"version": version_number})
    if "error" in result:
        return base.format_error(result)

    return f"Page restored to version {version_number}."


@mcp.tool(name="wiki_get_page_comments")
def get_page_comments(page_id: str) -> str:
    """
    List all comments on a wiki page.

    Args:
        page_id: Page ID (UUID)
    """
    result = base.api_request("GET", f"/pages/{page_id}/comments/", as_user=base.has_user_context)
    if "error" in result:
        return base.format_error(result)

    comments = (result if isinstance(result, list) else result.get("results", []))
    if not comments:
        return "No comments on this page."

    output = f"# Page Comments ({len(comments)})\n\n"
    for c in comments:
        resolved = " [RESOLVED]" if c.get('is_resolved') else ""
        output += f"- **{c.get('author_email', c.get('author_id', c.get('created_by_id', 'Unknown')))}**{resolved}\n"
        output += f"  ID: {c.get('id')}\n"
        output += f"  {c.get('content', '')[:200]}\n"
        output += f"  Created: {c.get('created_at')}\n"
        if c.get('parent'):
            output += f"  Reply to: {c['parent']}\n"

    return output


@mcp.tool(name="wiki_add_page_comment")
def add_page_comment(page_id: str, content: str, parent_id: Optional[str] = None) -> str:
    """
    Add a comment to a wiki page.

    Args:
        page_id: Page ID
        content: Comment content
        parent_id: Parent comment ID for threading
    """
    data = {"page": page_id, "content": content}
    if parent_id:
        data["parent"] = parent_id

    # WIKI-53: comments are user-owned content. Delegate to the authenticated
    # user (when a delegation token is present) so the creator is persisted as
    # the author and can edit/delete their own comment — not the agent identity.
    result = base.api_request(
        "POST", f"/pages/{page_id}/comments/", data=data,
        as_user=base.has_user_context,
    )
    if "error" in result:
        return base.format_error(result)

    comment = result
    return (
        f"Comment added!\n\n"
        f"**ID**: {comment.get('id')}\n"
        f"**Created**: {comment.get('created_at')}\n"
    )


@mcp.tool(name="wiki_watch_page")
def watch_page(page_id: str) -> str:
    """
    Toggle watch on a page to receive notifications on changes.

    Args:
        page_id: Page ID (UUID)
    """
    result = base.api_request("POST", f"/pages/{page_id}/watch/")
    if "error" in result:
        return base.format_error(result)

    is_watching = result.get("is_watching", result.get("watching", True))
    return f"Page {'watched' if is_watching else 'unwatched'}."


@mcp.tool(name="wiki_get_page_children")
def get_page_children(page_id: str) -> str:
    """
    Get the direct child pages of a page.

    Args:
        page_id: Page ID (UUID)
    """
    result = base.api_request("GET", f"/pages/{page_id}/children/")
    if "error" in result:
        return base.format_error(result)

    children = (result if isinstance(result, list) else result.get("results", []))
    if not children:
        return "No child pages."

    output = f"# Child Pages ({len(children)})\n\n"
    for page in children:
        output += f"- **{page.get('title')}**\n"
        output += f"  ID: {page.get('id')}\n"
        output += f"  Status: {page.get('status')}\n"

    return output


@mcp.tool(name="wiki_get_page_backlinks")
def get_page_backlinks(page_id: str) -> str:
    """
    Get pages that link to this page (backlinks / incoming links).

    Args:
        page_id: Page ID (UUID)
    """
    result = base.api_request("GET", f"/pages/{page_id}/backlinks/")
    if "error" in result:
        return base.format_error(result)

    backlinks = (result if isinstance(result, list) else result.get("results", []))
    if not backlinks:
        return "No backlinks found."

    output = f"# Backlinks ({len(backlinks)})\n\n"
    for page in backlinks:
        output += f"- **{page.get('title')}**\n"
        output += f"  ID: {page.get('id')}\n"
        output += f"  Space: {page.get('space_name', page.get('space', 'N/A'))}\n"

    return output


@mcp.tool(name="wiki_move_page")
def move_page(
    page_id: str,
    target_space_id: Optional[str] = None,
    target_parent_id: Optional[str] = None,
    position: Optional[int] = None,
) -> str:
    """
    Move a page to a different parent or space.

    Args:
        page_id: Page ID to move
        target_space_id: Target space ID (for cross-space moves)
        target_parent_id: Target parent page ID (None for root level)
        position: Position among siblings (0-based)
    """
    data = {}
    if target_space_id:
        data["space"] = target_space_id
    if target_parent_id is not None:
        data["parent"] = target_parent_id
    if position is not None:
        data["position"] = position

    if not data:
        return "Error: Provide target_space_id, target_parent_id, or position."

    result = base.api_request("POST", f"/pages/{page_id}/move/", data=data)
    if "error" in result:
        return base.format_error(result)

    if target_space_id and str(result.get("space")) != str(target_space_id):
        return (
            "Error: move endpoint returned success but did not persist the "
            f"destination space (expected {target_space_id}, got {result.get('space')})."
        )

    destination = f" to space {result.get('space')}" if target_space_id else ""
    return f"Page moved successfully{destination}."


@mcp.tool(name="wiki_reorder_pages")
def reorder_pages(page_ids: str, parent_id: Optional[str] = None) -> str:
    """
    Reorder pages within a parent. Provide page IDs in desired order.

    Args:
        page_ids: Comma-separated page IDs in desired order
        parent_id: Parent page ID (None for root-level pages)
    """
    ids = [pid.strip() for pid in page_ids.split(",") if pid.strip()]
    if not ids:
        return "Error: Provide at least one page ID."

    data = {"page_ids": ids}
    if parent_id:
        data["parent"] = parent_id

    result = base.api_request("POST", "/pages/reorder/", data=data)
    if "error" in result:
        return base.format_error(result)

    return f"Pages reordered ({len(ids)} pages)."


# ===========================================================================
# Labels
# ===========================================================================

@mcp.tool(name="wiki_list_labels")
def list_labels(organization_id: Optional[int] = None) -> str:
    """
    List all wiki labels (tags for categorizing pages).

    Args:
        organization_id: Optional org scope. Omit to aggregate across orgs.
    """
    result = base.api_request("GET", "/labels/", organization_id=organization_id)
    # /labels/ has pagination disabled — returns a plain list. Other endpoints
    # return dicts. Branch carefully so `"error" in result` doesn't get
    # interpreted as list-membership.
    if isinstance(result, dict) and "error" in result:
        return base.format_error(result)

    if isinstance(result, list):
        labels = result
    else:
        labels = result.get("results", [])
    if not labels:
        return "No labels found."

    output = f"# Labels ({len(labels)})\n\n"
    for label in labels:
        output += f"- **{label.get('name')}**\n"
        output += f"  ID: {label.get('id')}\n"
        output += f"  Org: {label.get('organization_id', 'N/A')}\n"
        if label.get('color'):
            output += f"  Color: {label['color']}\n"
        if label.get('page_count') is not None:
            output += f"  Pages: {label['page_count']}\n"

    return output


@mcp.tool(name="wiki_create_label")
def create_label(
    name: str,
    organization_id: int,
    color: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Create a new label for categorizing pages. Required: organization_id.

    Args:
        name: Label name
        organization_id: REQUIRED — the org this label belongs to.
        color: Label color (hex code, e.g., '#FF5733')
        description: Label description
    """
    data = {"name": name}
    if color:
        data["color"] = color
    if description:
        data["description"] = description

    result = base.api_request("POST", "/labels/", data=data, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    label = result
    return (
        f"Label created!\n\n"
        f"**Name**: {label.get('name')}\n"
        f"**ID**: {label.get('id')}\n"
        f"**Org**: {label.get('organization_id', organization_id)}\n"
    )


@mcp.tool(name="wiki_get_label")
def get_label(label_id: str) -> str:
    """
    Get details of a specific label.

    Args:
        label_id: Label ID (UUID)
    """
    result = base.api_request("GET", f"/labels/{label_id}/")
    if "error" in result:
        return base.format_error(result)

    label = result
    output = f"# Label: {label.get('name')}\n\n"
    output += f"**ID**: {label.get('id')}\n"
    if label.get('color'):
        output += f"**Color**: {label['color']}\n"
    if label.get('description'):
        output += f"**Description**: {label['description']}\n"
    if label.get('page_count') is not None:
        output += f"**Pages**: {label['page_count']}\n"

    return output


@mcp.tool(name="wiki_update_label")
def update_label(
    label_id: str,
    name: Optional[str] = None,
    color: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Update a label.

    Args:
        label_id: Label ID (UUID)
        name: New label name
        color: New color (hex code)
        description: New description
    """
    data = {}
    if name:
        data["name"] = name
    if color:
        data["color"] = color
    if description is not None:
        data["description"] = description

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request("PATCH", f"/labels/{label_id}/", data=data)
    if "error" in result:
        return base.format_error(result)

    label = result
    return (
        f"Label updated!\n\n"
        f"**Name**: {label.get('name')}\n"
        f"**ID**: {label.get('id')}\n"
    )


@mcp.tool(name="wiki_delete_label")
def delete_label(label_id: str) -> str:
    """
    Delete a label.

    Args:
        label_id: Label ID (UUID)
    """
    result = base.api_request("DELETE", f"/labels/{label_id}/")
    if "error" in result:
        return base.format_error(result)

    return f"Label deleted."


# ===========================================================================
# Templates
# ===========================================================================

@mcp.tool(name="wiki_list_templates")
def list_templates(
    space_id: Optional[str] = None,
    organization_id: Optional[int] = None,
) -> str:
    """
    List available page templates.

    Args:
        space_id: Filter templates by space ID
        organization_id: Optional org scope. Omit to aggregate across orgs.
    """
    params = {}
    if space_id:
        params["space"] = space_id

    result = base.api_request("GET", "/templates/", params=params, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    templates = (result if isinstance(result, list) else result.get("results", []))
    if not templates:
        return "No templates found."

    output = f"# Templates ({len(templates)})\n\n"
    for tmpl in templates:
        output += f"- **{tmpl.get('name')}**\n"
        output += f"  ID: {tmpl.get('id')}\n"
        if tmpl.get('description'):
            output += f"  Description: {tmpl['description'][:100]}\n"
        if tmpl.get('space_name'):
            output += f"  Space: {tmpl['space_name']}\n"

    return output


@mcp.tool(name="wiki_create_template")
def create_template(
    name: str,
    content: str,
    organization_id: int,
    space_id: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Create a new page template. Required: organization_id.

    Args:
        name: Template name
        content: Template content (plain text or markdown)
        organization_id: REQUIRED — the org this template belongs to.
        space_id: Space to associate template with
        description: Template description
    """
    data = {
        "name": name,
        "content_text": content,
        "content_json": _text_to_tiptap_json(content),
    }
    if space_id:
        data["space"] = space_id
    if description:
        data["description"] = description

    result = base.api_request("POST", "/templates/", data=data, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    tmpl = result
    return (
        f"Template created!\n\n"
        f"**Name**: {tmpl.get('name')}\n"
        f"**ID**: {tmpl.get('id')}\n"
        f"**Org**: {tmpl.get('organization_id', organization_id)}\n"
    )


@mcp.tool(name="wiki_get_template")
def get_template(template_id: str, organization_id: Optional[int] = None) -> str:
    """
    Get a template's content and details.

    Args:
        template_id: Template ID (UUID)
        organization_id: Optional org scope for this read.
    """
    result = base.api_request(
        "GET", f"/templates/{template_id}/", organization_id=organization_id
    )
    if "error" in result:
        return base.format_error(result)

    tmpl = result
    output = f"# Template: {tmpl.get('name')}\n\n"
    output += f"**ID**: {tmpl.get('id')}\n"
    if tmpl.get('description'):
        output += f"**Description**: {tmpl['description']}\n"
    if tmpl.get('space_name'):
        output += f"**Space**: {tmpl['space_name']}\n"

    output += f"\n---\n\n"

    if tmpl.get('content_text'):
        output += tmpl['content_text']
    elif tmpl.get('content_json'):
        output += f"```json\n{json.dumps(tmpl['content_json'], indent=2)}\n```"
    else:
        output += "(No content)"

    return output


@mcp.tool(name="wiki_update_template")
def update_template(
    template_id: str,
    organization_id: int,
    name: Optional[str] = None,
    content: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """
    Update a page template.

    Args:
        template_id: Template ID (UUID)
        organization_id: REQUIRED — the template's organization.
        name: New template name
        content: New template content
        description: New description
    """
    data = {}
    if name:
        data["name"] = name
    if content:
        data["content_text"] = content
        data["content_json"] = _text_to_tiptap_json(content)
    if description is not None:
        data["description"] = description

    if not data:
        return "Error: No fields provided to update."

    result = base.api_request(
        "PATCH",
        f"/templates/{template_id}/",
        data=data,
        organization_id=organization_id,
    )
    if "error" in result:
        return base.format_error(result)

    tmpl = result
    return (
        f"Template updated!\n\n"
        f"**Name**: {tmpl.get('name')}\n"
        f"**ID**: {tmpl.get('id')}\n"
    )


@mcp.tool(name="wiki_delete_template")
def delete_template(template_id: str, organization_id: int) -> str:
    """
    Delete a page template.

    Args:
        template_id: Template ID (UUID)
        organization_id: REQUIRED — the template's organization.
    """
    result = base.api_request(
        "DELETE", f"/templates/{template_id}/", organization_id=organization_id
    )
    if "error" in result:
        return base.format_error(result)

    return f"Template deleted."


# ===========================================================================
# Attachments
# ===========================================================================

@mcp.tool(name="wiki_list_attachments")
def list_attachments(
    page_id: Optional[str] = None,
    limit: int = 20,
    organization_id: Optional[int] = None,
) -> str:
    """
    List attachments, optionally filtered by page.

    Args:
        page_id: Filter by page ID
        limit: Maximum attachments to return
        organization_id: Optional org scope. Omit to aggregate across orgs.
    """
    params = {"page_size": limit}
    if page_id:
        # WIKI-52: use page_id, NOT page — DRF pagination owns the 'page' query
        # param, so sending a page UUID as 'page' yields 404 "Invalid page."
        params["page_id"] = page_id

    result = base.api_request("GET", "/attachments/", params=params, organization_id=organization_id)
    if "error" in result:
        return base.format_error(result)

    attachments = (result if isinstance(result, list) else result.get("results", []))
    if not attachments:
        return "No attachments found."

    output = f"# Attachments ({len(attachments)})\n\n"
    for att in attachments:
        output += f"- **{att.get('filename', att.get('name', 'Unnamed'))}**\n"
        output += f"  ID: {att.get('id')}\n"
        output += f"  Size: {att.get('file_size', 'N/A')} bytes\n"
        output += f"  SHA-256: {att.get('sha256') or 'N/A'}\n"
        output += f"  MIME: {att.get('mime_type', att.get('content_type', 'N/A'))}\n"
        if att.get('page_id') or att.get('page'):
            output += f"  Page: {att.get('page_id', att.get('page'))}\n"
        output += f"  Uploaded: {att.get('created_at', 'N/A')}\n"

    return output


@mcp.tool(name="wiki_upload_attachment")
def upload_attachment(
    page_id: str,
    filename: str,
    content_base64: str,
    content_type: Optional[str] = None,
) -> str:
    """
    Upload an attachment to a wiki page.

    The file content must be provided as a base64-encoded string.

    Args:
        page_id: Page ID to attach to
        filename: Filename for the attachment
        content_base64: Base64-encoded file content
        content_type: MIME type (auto-detected if omitted)
    """
    import base64 as b64

    try:
        file_bytes = b64.b64decode(content_base64)
    except Exception as e:
        return f"Error: Invalid base64 content - {e}"

    files = {"file": (filename, file_bytes, content_type or "application/octet-stream")}
    data = {"page": page_id}

    result = base.api_request("POST", "/attachments/", data=data, files=files)
    if "error" in result:
        return base.format_error(result)

    att = result
    return (
        f"Attachment uploaded!\n\n"
        f"**Filename**: {att.get('filename', att.get('name'))}\n"
        f"**ID**: {att.get('id')}\n"
        f"**Size**: {att.get('file_size', 'N/A')} bytes\n"
        f"**SHA-256**: {att.get('sha256') or 'N/A'}\n"
    )


@mcp.tool(name="wiki_get_attachment")
def get_attachment(attachment_id: str) -> str:
    """
    Get metadata for an attachment.

    Args:
        attachment_id: Attachment ID (UUID)
    """
    result = base.api_request("GET", f"/attachments/{attachment_id}/")
    if "error" in result:
        return base.format_error(result)

    att = result
    output = f"# Attachment: {att.get('filename', att.get('name', 'Unnamed'))}\n\n"
    output += f"**ID**: {att.get('id')}\n"
    output += f"**Size**: {att.get('file_size', 'N/A')} bytes\n"
    output += f"**SHA-256**: {att.get('sha256') or 'N/A'}\n"
    output += f"**Integrity**: {att.get('integrity_state') or 'N/A'}\n"
    output += f"**MIME**: {att.get('mime_type', att.get('content_type', 'N/A'))}\n"
    if att.get('page_id') or att.get('page'):
        output += f"**Page**: {att.get('page_id', att.get('page'))}\n"
    output += f"**Uploaded**: {att.get('created_at', 'N/A')}\n"
    if att.get('uploaded_by_email') or att.get('uploaded_by'):
        output += f"**Uploaded by**: {att.get('uploaded_by_email', att.get('uploaded_by'))}\n"

    return output


@mcp.tool(name="wiki_delete_attachment")
def delete_attachment(attachment_id: str) -> str:
    """
    Delete an attachment.

    Args:
        attachment_id: Attachment ID (UUID)
    """
    result = base.api_request("DELETE", f"/attachments/{attachment_id}/")
    if "error" in result:
        return base.format_error(result)

    return f"Attachment deleted."


def _attachment_download_error(message: str) -> CallToolResult:
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=message)],
    )


@mcp.tool(name="wiki_download_attachment", structured_output=False)
def download_attachment(
    attachment_id: str,
    offset_bytes: int = 0,
    length_bytes: Optional[int] = None,
) -> CallToolResult:
    """
    Download attachment bytes as an embedded binary MCP resource.

    Args:
        attachment_id: Attachment ID (UUID)
        offset_bytes: Optional zero-based byte offset for a ranged download
        length_bytes: Optional number of bytes to return (maximum 16 MiB)

    Files up to 16 MiB can be returned in one call. Larger files require an
    explicit bounded range. Partial ranges carry the authoritative full-object
    digest but become normative evidence only after complete reassembly/hash.
    """
    max_bytes = 16 * 1024 * 1024
    if offset_bytes < 0:
        return _attachment_download_error("offset_bytes must be non-negative.")
    if length_bytes is not None and not 1 <= length_bytes <= max_bytes:
        return _attachment_download_error(
            f"length_bytes must be between 1 and {max_bytes}."
        )

    metadata = base.api_request("GET", f"/attachments/{attachment_id}/")
    if "error" in metadata:
        return _attachment_download_error(base.format_error(metadata))

    file_size = metadata.get("file_size")
    sha256 = str(metadata.get("sha256") or "").lower()
    integrity_state = str(metadata.get("integrity_state") or "")
    metadata_mime = str(
        metadata.get("mime_type") or metadata.get("content_type") or ""
    ).split(";", 1)[0].strip().lower()
    metadata_version = str(metadata.get("storage_version_id") or "") or None
    if isinstance(file_size, bool) or not isinstance(file_size, int) or file_size < 0:
        return _attachment_download_error(
            "Attachment metadata is missing a valid canonical file_size; refusing download."
        )
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        return _attachment_download_error(
            "Attachment metadata is missing an authoritative SHA-256; refusing download."
        )
    if not integrity_state:
        return _attachment_download_error(
            "Attachment metadata is missing integrity state; refusing download."
        )
    if file_size > max_bytes and length_bytes is None:
        return _attachment_download_error(
            "Attachment exceeds the 16 MiB MCP response limit. Retry with "
            f"offset_bytes and length_bytes <= {max_bytes}."
        )
    if offset_bytes > file_size or (offset_bytes == file_size and file_size > 0):
        return _attachment_download_error(
            f"offset_bytes must be smaller than the attachment size ({file_size})."
        )

    is_range = bool(offset_bytes or length_bytes is not None)
    extra_headers = {}
    if is_range:
        requested_length = length_bytes or max_bytes
        end = offset_bytes + requested_length - 1
        extra_headers["Range"] = f"bytes={offset_bytes}-{end}"

    result = base.api_binary_request(
        "GET",
        f"/attachments/{attachment_id}/download/",
        extra_headers=extra_headers,
        max_bytes=max_bytes,
    )
    if "error" in result:
        detail = result.get("detail") or {}
        if result.get("error") == "file_too_large_for_mcp":
            message = (
                "Attachment exceeds the 16 MiB MCP response limit. Retry with "
                f"offset_bytes and length_bytes <= {max_bytes}. Details: "
                f"{json.dumps(detail, sort_keys=True)}"
            )
        else:
            message = base.format_error(result)
        return _attachment_download_error(message)

    content = result["content"]
    status_code = result["status_code"]
    headers = {key.lower(): value for key, value in result["headers"].items()}
    content_range = headers.get("content-range")
    response_mime = headers.get("content-type", "").split(";", 1)[0].strip().lower()
    response_sha256 = str(headers.get("x-wiki-checksum-sha256") or "").lower()
    response_integrity = str(headers.get("x-wiki-integrity") or "")
    response_version = headers.get("x-wiki-storage-version")

    if response_sha256 != sha256:
        return _attachment_download_error(
            "Attachment metadata and download checksum disagree; bytes were not returned."
        )
    if metadata_mime and response_mime and metadata_mime != response_mime:
        return _attachment_download_error(
            "Attachment metadata and download MIME type disagree; bytes were not returned."
        )
    if metadata_version and response_version != metadata_version:
        return _attachment_download_error(
            "Attachment metadata and storage version disagree; bytes were not returned."
        )

    if is_range:
        if status_code != 206 or not content_range:
            return _attachment_download_error(
                "Attachment server did not honor the bounded Range request."
            )
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
        if not match:
            return _attachment_download_error(
                "Attachment server returned an invalid Content-Range."
            )
        start, end, total = map(int, match.groups())
        expected_end = min(
            offset_bytes + (length_bytes or max_bytes) - 1,
            file_size - 1,
        )
        if (
            start != offset_bytes
            or end != expected_end
            or total != file_size
            or len(content) != end - start + 1
            or response_integrity != "partial-range"
        ):
            return _attachment_download_error(
                "Attachment metadata and ranged response disagree; bytes were not returned."
            )
    else:
        if status_code != 200 or content_range:
            return _attachment_download_error(
                "Attachment server returned an unexpected partial response."
            )
        actual_sha256 = hashlib.sha256(content).hexdigest()
        if (
            len(content) != file_size
            or actual_sha256 != sha256
            or response_integrity != integrity_state
        ):
            return _attachment_download_error(
                "Attachment metadata and returned bytes disagree; bytes were not returned."
            )

    mime_type = response_mime or metadata_mime or "application/octet-stream"
    uri = f"wiki://attachments/{attachment_id}"
    if content_range:
        uri += f"?range={content_range.replace(' ', '%20')}"
    structured = {
        "attachment_id": attachment_id,
        "returned_bytes": len(content),
        "content_range": content_range,
        "mime_type": mime_type,
        "integrity": response_integrity,
        "full_object_size": file_size,
        "checksum_sha256": sha256,
        "storage_version_id": response_version or metadata_version,
    }
    summary = "\n".join(
        [
            "Attachment downloaded as an embedded binary resource.",
            f"Attachment ID: {attachment_id}",
            f"Returned bytes: {len(content)}",
            f"Full object bytes: {file_size}",
            f"Content type: {mime_type}",
            f"Content range: {content_range or 'full attachment'}",
            f"Integrity: {response_integrity}",
            f"SHA-256: {sha256}",
        ]
    )
    return CallToolResult(
        content=[
            TextContent(type="text", text=summary),
            EmbeddedResource(
                type="resource",
                resource=BlobResourceContents(
                    uri=uri,
                    mimeType=mime_type,
                    blob=base64.b64encode(content).decode("ascii"),
                ),
            ),
        ],
        structuredContent=structured,
    )


# ===========================================================================
# Comments (standalone CRUD)
# ===========================================================================

@mcp.tool(name="wiki_list_comments")
def list_comments(
    page_id: Optional[str] = None,
    is_resolved: Optional[bool] = None,
    limit: int = 20,
    organization_id: Optional[int] = None,
) -> str:
    """
    List comments across all pages, or filtered by page.

    Args:
        page_id: Filter by page ID
        is_resolved: Filter by resolved status
        limit: Maximum comments to return
        organization_id: Optional org scope. Omit to aggregate across orgs.
    """
    params = {"page_size": limit}
    if page_id:
        # WIKI-52: use page_id, NOT page — DRF pagination owns the 'page' query
        # param, so sending a page UUID as 'page' yields 404 "Invalid page."
        params["page_id"] = page_id
    if is_resolved is not None:
        params["is_resolved"] = is_resolved

    result = base.api_request("GET", "/comments/", params=params, organization_id=organization_id, as_user=base.has_user_context)
    if "error" in result:
        return base.format_error(result)

    comments = (result if isinstance(result, list) else result.get("results", []))
    if not comments:
        return "No comments found."

    output = f"# Comments ({len(comments)})\n\n"
    for c in comments:
        resolved = " [RESOLVED]" if c.get('is_resolved') else ""
        output += f"- **{c.get('author_email', c.get('author_id', c.get('created_by_id', 'Unknown')))}**{resolved}\n"
        output += f"  ID: {c.get('id')}\n"
        output += f"  {c.get('content', '')[:200]}\n"
        output += f"  Page: {c.get('page_title', c.get('page', 'N/A'))}\n"
        output += f"  Created: {c.get('created_at')}\n"

    return output


@mcp.tool(name="wiki_get_comment")
def get_comment(comment_id: str) -> str:
    """
    Get details of a specific comment.

    Args:
        comment_id: Comment ID (UUID)
    """
    result = base.api_request("GET", f"/comments/{comment_id}/", as_user=base.has_user_context)
    if "error" in result:
        return base.format_error(result)

    c = result
    resolved = " [RESOLVED]" if c.get('is_resolved') else ""
    output = f"# Comment{resolved}\n\n"
    output += f"**ID**: {c.get('id')}\n"
    output += f"**Author**: {c.get('author_email', c.get('author_id', c.get('created_by_id', 'Unknown')))}\n"
    output += f"**Page**: {c.get('page_title', c.get('page', 'N/A'))}\n"
    output += f"**Created**: {c.get('created_at')}\n"
    if c.get('parent'):
        output += f"**Reply to**: {c['parent']}\n"
    output += f"\n---\n\n{c.get('content', '(No content)')}\n"

    return output


@mcp.tool(name="wiki_update_comment")
def update_comment(comment_id: str, content: str) -> str:
    """
    Update a comment's content.

    Args:
        comment_id: Comment ID (UUID)
        content: New comment content
    """
    result = base.api_request(
        "PATCH", f"/comments/{comment_id}/", data={"content": content},
        as_user=base.has_user_context,
    )
    if "error" in result:
        return base.format_error(result)

    return f"Comment updated."


@mcp.tool(name="wiki_delete_comment")
def delete_comment(comment_id: str) -> str:
    """
    Delete a comment.

    Args:
        comment_id: Comment ID (UUID)
    """
    result = base.api_request("DELETE", f"/comments/{comment_id}/", as_user=base.has_user_context)
    if "error" in result:
        return base.format_error(result)

    return f"Comment deleted."


@mcp.tool(name="wiki_resolve_comment")
def resolve_comment(comment_id: str) -> str:
    """
    Mark a comment as resolved.

    Args:
        comment_id: Comment ID (UUID)
    """
    result = base.api_request("POST", f"/comments/{comment_id}/resolve/", as_user=base.has_user_context)
    if "error" in result:
        return base.format_error(result)

    return f"Comment resolved."


@mcp.tool(name="wiki_unresolve_comment")
def unresolve_comment(comment_id: str) -> str:
    """
    Mark a resolved comment as unresolved.

    Args:
        comment_id: Comment ID (UUID)
    """
    result = base.api_request("POST", f"/comments/{comment_id}/unresolve/", as_user=base.has_user_context)
    if "error" in result:
        return base.format_error(result)

    return f"Comment unresolved."


# ===========================================================================
# Search
# ===========================================================================

@mcp.tool(name="wiki_search_pages")
def search_pages(
    query: str,
    space_id: Optional[str] = None,
    limit: int = 20,
    organization_id: Optional[int] = None,
) -> str:
    """
    Search wiki pages by content.

    Args:
        query: Search query
        space_id: Limit search to specific space
        limit: Maximum results
        organization_id: Optional org scope. Omit to search across every
            org you belong to.
    """
    # Use the dedicated search endpoint (expects ?q=)
    params = {"q": query}
    if space_id:
        params["space"] = space_id

    result = base.api_request("GET", "/search/", params=params, organization_id=organization_id)

    # Handle error responses (api_request returns dict on error)
    if isinstance(result, dict) and "error" in result:
        return base.format_error(result)

    # Search endpoint returns a plain list, not paginated
    results = result if isinstance(result, list) else result.get("results", [])
    if not results:
        return f"No pages found matching '{query}'."

    output = f"# Search Results for '{query}' ({len(results)})\n\n"
    for page in results:
        output += f"- **{page.get('title')}**\n"
        output += f"  ID: {page.get('id')}\n"
        if page.get('excerpt'):
            output += f"  ...{page['excerpt']}...\n"
        if page.get('space_name'):
            output += f"  Space: {page['space_name']}\n"

    return output


@mcp.tool(name="wiki_ask")
def wiki_ask(
    question: str,
    space_id: Optional[str] = None,
    max_citations: int = 5,
    organization_id: Optional[int] = None,
) -> str:
    """Ask the wiki a question and receive an extractive cited answer.

    No LLM call. If no passage clears the relevance floor, the payload is a
    refusal with the best citations, not a guess.

    Args:
        question: The question to answer from wiki sections.
        space_id: Optional space UUID. No cross-space fan-out when set.
        max_citations: Citation cap (default 5).
        organization_id: Optional org scope. Uses the caller's existing read path.
    """
    body = {"question": question, "max_citations": max_citations}
    if space_id:
        body["space_id"] = space_id
    result = base.api_request("POST", "/answer/", data=body, organization_id=organization_id)
    if isinstance(result, dict) and result.get("error"):
        return base.format_error(result)
    if not isinstance(result, dict):
        return base.format_error({"error": "malformed answer payload"})
    if result.get("refusal"):
        return (
            f"Refusal: {result['refusal']}\n"
            f"Citations: {len(result.get('citations') or [])}\n"
            f"{result}"
        )
    return (
        f"{result.get('answer') or ''}\n\n"
        f"Citations: {len(result.get('citations') or [])}\n"
        f"{result.get('citations')}"
    )


# ===========================================================================
# Main entry point
# ===========================================================================

def main():
    """Run the MCP server."""
    run_mcp_server(mcp, base)


if __name__ == "__main__":
    main()
