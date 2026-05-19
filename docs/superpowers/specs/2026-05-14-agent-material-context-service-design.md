# Agent Material Context Service Design

## Goal

Provide a stable service interface for other agents to retrieve reusable bid material by directory path or similar title, without exposing the parser's internal `modules`, `table_items`, `image_items`, or debug JSON structure.

## Scope

The first version serves already parsed pipeline outputs under `outputs/<run>/modules`. It does not upload PDFs, start parsing jobs, or manage long-running pipeline execution. Those can be added later after the material context contract is stable.

## Architecture

The existing parser continues to generate internal material folders. A new Agent Material Context layer reads those folders and builds a clean in-memory index of materials:

- `material_id`: stable run-local identifier derived from the material path.
- `section_path`: original section path from `material_meta.json` or `ordered_material.json`.
- `title`: material title.
- `content_markdown`: ready-to-use content from `material.md`.
- `source_pages`: pages gathered from ordered material items.
- `evidence`: simplified item references for text, table, image, and submaterial content.

The service resolves agent requests in this order:

1. Exact section path or module path.
2. Normalized path, ignoring spacing and punctuation differences.
3. Exact normalized leaf title.
4. Fuzzy title matching.
5. Ambiguous candidates if multiple close matches exist.

## API

Add `POST /api/runs/{run_name}/materials/context`.

Request:

```json
{
  "section_path": "技术文件 / 技术偏差表",
  "title": "技术偏差表",
  "top_k": 5
}
```

Successful response:

```json
{
  "status": "matched",
  "match_type": "exact_path",
  "selected": {
    "material_id": "技术文件/技术偏差表",
    "section_path": "技术文件 / 技术偏差表",
    "title": "技术偏差表",
    "score": 1.0
  },
  "content_markdown": "...",
  "source_pages": [1],
  "evidence": []
}
```

Ambiguous response:

```json
{
  "status": "ambiguous",
  "match_type": "fuzzy",
  "candidates": []
}
```

Not found response:

```json
{
  "status": "not_found",
  "match_type": "not_found",
  "candidates": []
}
```

## Error Handling

Missing runs still return `404`. Missing or unmatched material queries return a normal `not_found` payload so an agent can continue gracefully. Ambiguous matches do not return content, preventing accidental use of the wrong section.

## MCP Interface

Expose the same material context resolver as a stdio MCP server for OpenCode and other coding agents. The MCP server lives at `python -m bid_knowledge.service.mcp_server` and uses `BID_MATERIAL_OUTPUTS_DIR` to find parsed outputs.

Tools:

- `get_bid_material_context(run_name, section_path="", title="", top_k=5)`: returns matched Markdown context, ambiguous candidates, not found, or error payloads.
- `get_bid_project_material_context(project_id, section_path="", title="", top_k=5)`: routes across all runs configured for a bid project, such as business and technical files.
- `list_bid_materials(run_name, limit=200)`: lists material ids, titles, section paths, and source pages for one parsed run.

The MCP layer does not start PDF parsing. It only serves already generated output folders.

## Project-Level Routing

When a writing agent works on a complete bid, it should use a `project_id` instead of manually selecting a `run_name`. Projects are configured in `configs/material_projects.json`:

```json
{
  "gansu_2026_272608": {
    "runs": {
      "商务文件": "pdf_toc_run_business_v8",
      "技术文件": "pdf_toc_run_tech_v9"
    }
  }
}
```

The project resolver uses the first section path segment, such as `技术文件`, to choose the preferred run. If no file type is available, it searches all configured runs and returns the best match or ambiguous candidates.

## Testing

Add unit tests around the index and resolver:

- exact path match
- normalized path match
- leaf title match
- fuzzy title match
- ambiguous fuzzy match
- response includes markdown, source pages, and simplified evidence

Add API tests through FastAPI's test client once the endpoint is wired.
