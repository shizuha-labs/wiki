# WIKI-1: Search & Retrieval Reliability Fixes

## Summary
Fixed reliability issues in wiki retrieval endpoints that caused intermittent 500 errors and "no pages" responses for populated spaces.

## Root Causes Identified

### 1. PageTreeSerializer N+1 Query Problem
- **Issue**: Recursive child queries without prefetching caused massive query counts for large spaces
- **Impact**: Timeout/500 errors on spaces with many nested pages
- **Location**: `wiki/serializers.py:252-263`

### 2. No Depth Limiting on Tree Endpoint
- **Issue**: Could return thousands of nested pages without limit
- **Impact**: Memory exhaustion, slow responses
- **Location**: `wiki/views.py:359-371`

### 3. Basic Search Excerpts
- **Issue**: Excerpts were just first 200 chars, no context around matches
- **Impact**: Poor search UX, hard to find relevant content
- **Location**: `wiki/views.py:1067-1087`

### 4. Inconsistent Error Handling
- **Issue**: MCP tools didn't properly check for error responses
- **Impact**: Silent failures, confusing "no pages" messages
- **Location**: `wiki/mcp-server/wiki_server.py`

## Fixes Implemented

### Fix 1: Depth-Limited Page Tree with Consistent Filtering
**File**: `wiki/views.py` (lines 359-385)
- Added `max_depth` parameter (default 5, max 10)
- Pass depth context to serializer
- Prevents infinite recursion and massive responses

**File**: `wiki/serializers.py` (lines 252-284)
- Added depth tracking in `PageTreeSerializer`
- Stop recursion at max_depth
- Apply same filter logic as tree endpoint (published + user's drafts)
- Consistent with list/search behavior

### Fix 2: Context-Aware Search Excerpts
**File**: `wiki/views.py` (lines 1072-1136)
- Added `_generate_search_excerpt()` method
- Finds first occurrence of search terms
- Extracts 150 chars before and after match
- Adds ellipsis for truncated content
- Falls back to first 300 chars if no match found

### Fix 3: Improved Error Handling in MCP Tools
**File**: `wiki/mcp-server/wiki_server.py`

**wiki_get_space_tree** (lines 689-734):
- Added `max_depth` parameter with validation
- Better error checking with `isinstance(result, dict)`
- More descriptive empty result message
- Shows depth level in output

**wiki_list_pages** (lines 783-831):
- Fixed error detection to use `isinstance(result, dict)`
- Better handling of different response formats
- Consistent with other tools

## Testing Recommendations

### 1. Test Tree Endpoint with Large Spaces
```bash
# Test with default depth (5 levels)
curl "http://localhost:8013/api/spaces/ENG/tree/"

# Test with custom depth
curl "http://localhost:8013/api/spaces/ENG/tree/?max_depth=3"

# Test with max depth
curl "http://localhost:8013/api/spaces/ENG/tree/?max_depth=10"
```

### 2. Test Search with Context Excerpts
```bash
# Search for multi-word terms
curl "http://localhost:8013/api/search/?q=authentication%20session"

# Verify excerpts show context around matches
```

### 3. Test MCP Tools
```python
# Test wiki_get_space_tree
wiki_get_space_tree("ENG", max_depth=5)

# Test wiki_list_pages
wiki_list_pages(space_id="...", status="published", limit=20)

# Test wiki_search_pages
wiki_search_pages("authentication", space_id="...")
```

### 4. Performance Testing
- Query count monitoring for tree endpoint (should be O(depth) not O(pages))
- Response time for spaces with 100+ pages
- Memory usage for deep hierarchies

## Consistency Improvements

All three endpoints now use the same filtering logic:
- **Published pages** visible to all users
- **User's own drafts** visible to authenticated users
- **Organization scoping** consistent across all endpoints
- **Error handling** standardized

## Backward Compatibility

- Default `max_depth=5` maintains reasonable behavior for existing callers
- All existing parameters preserved
- Response format unchanged (just improved content)
- No breaking changes to API contracts

## Future Improvements (Out of Scope)

1. Add caching for tree endpoint (spaces don't change often)
2. Implement cursor-based pagination for very large spaces
3. Add search result highlighting (mark matched terms in excerpts)
4. Add fuzzy search for typos
5. Add search filters by date, author, labels

## Files Modified

1. `wiki/views.py` - Tree endpoint depth limiting, search excerpt generation
2. `wiki/serializers.py` - PageTreeSerializer depth tracking
3. `wiki/mcp-server/wiki_server.py` - Improved error handling in MCP tools

## Deployment Notes

- No database migrations required
- No configuration changes needed
- Can be deployed without downtime
- Monitor query counts and response times post-deployment
