# CLAUDE.md - Shizuha Wiki

## Overview

**Shizuha Wiki** is the team documentation and knowledge management service (similar to Confluence).

| Setting | Value |
|---------|-------|
| Backend Port | 8013 |
| Frontend Port | 5176 |
| Database | shizuha_wiki |
| Redis DB | 5 |
| URL Path | `/wiki/` |

## Access

| URL | Description |
|-----|-------------|
| `/wiki/` | Documentation UI |
| `/wiki/api/` | REST API |
| `/wiki/admin/` | Django Admin |

## API Endpoints

### Spaces
```
GET/POST   /wiki/api/spaces/              # List/create spaces
GET/PATCH  /wiki/api/spaces/{id}/         # Space details
GET        /wiki/api/spaces/{id}/pages/   # Pages in space
```

### Pages
```
GET/POST   /wiki/api/pages/               # List/create pages
GET/PATCH  /wiki/api/pages/{id}/          # Page details
GET        /wiki/api/pages/{id}/children/ # Child pages
GET        /wiki/api/pages/{id}/history/  # Version history
POST       /wiki/api/pages/{id}/restore/  # Restore version
```

`POST /wiki/api/pages/` accepts an optional `template_id`. When present, omit
`content_json` and `content_text`: the server copies both canonical fields from
the visible template through the normal page authorization/version transaction.
Org-wide/global templates apply to writable spaces in the same org; a
space-scoped template applies only to its owning space.

### Templates
```
GET/POST    /wiki/api/templates/           # List/create templates
GET         /wiki/api/templates/{uuid}/    # Visible template detail
PATCH/DELETE /wiki/api/templates/{uuid}/   # Explicit X-Organization-ID required
```

`GET /templates/?space=<uuid>` is a list-availability filter only. It never
changes UUID identity at the detail route. Space-bound templates follow space
visibility/membership; org-wide/global templates are scoped to their org.

### Search
```
GET /wiki/api/search/?q=<query>           # Full-text search
```

## Key Models

- **Space** - Organized container for documentation (like Confluence spaces)
- **Page** - Rich text document with hierarchy
- **Label** - Cross-space categorization tags
- **PageVersion** - Version history for pages

## Features

- Hierarchical page organization
- Rich text editing (TipTap/ProseMirror)
- Full-text search (PostgreSQL FTS with GIN indexes)
- Version history and restore
- Labels for cross-space organization
- Page templates

## Commands

All development commands run from the `compose/` directory using the master docker-compose.yaml:

```bash
# Start service with frontend
cd compose && docker compose up -d shizuha-wiki shizuha-wiki-frontend

# Run migrations
cd compose && docker compose exec shizuha-wiki python manage.py migrate

# Run tests
cd compose && docker compose exec shizuha-wiki python manage.py test

# View logs
cd compose && docker compose logs -f shizuha-wiki

```

## Project Structure

```
shizuha-wiki/
├── wikimanager/          # Django project settings
├── wiki/                 # Main app
│   ├── models.py         # Space, Page, Label, PageVersion
│   ├── views.py          # DRF ViewSets
│   ├── serializers.py    # DRF serializers
│   └── search.py         # Full-text search
└── frontend/             # React UI with TipTap editor
```

Also reference [../CLAUDE.md](../CLAUDE.md) for platform-wide rules.
