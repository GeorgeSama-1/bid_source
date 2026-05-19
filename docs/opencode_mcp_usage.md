# OpenCode MCP Usage

This MCP server is intended to run on the server that stores parsed bid outputs.

## Server Deployment

Install dependencies on the server:

```bash
python3 -m pip install -r requirements.txt
```

Make sure `BID_MATERIAL_OUTPUTS_DIR` points to the server-side parsed output directory:

```bash
export BID_MATERIAL_OUTPUTS_DIR="/path/to/bid_source/outputs"
export BID_MATERIAL_PROJECTS_CONFIG="/path/to/bid_source/configs/material_projects.json"
python3 -m bid_knowledge.service.mcp_server
```

## OpenCode Configuration

If OpenCode runs on the same server, configure `opencode.json` like this:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "bid_material": {
      "type": "local",
      "command": ["python3", "-m", "bid_knowledge.service.mcp_server"],
      "enabled": true,
      "environment": {
        "BID_MATERIAL_OUTPUTS_DIR": "/path/to/bid_source/outputs",
        "BID_MATERIAL_PROJECTS_CONFIG": "/path/to/bid_source/configs/material_projects.json"
      }
    }
  }
}
```

If OpenCode runs on another machine, deploy this MCP through the server-side runtime used by your OpenCode environment, or expose it through your team's remote MCP gateway. Keep the MCP process close to the parsed `outputs` directory so tool calls do not need to transfer internal files.

Available tools:

- `get_bid_material_context`: retrieve ready-to-use Markdown by `run_name`, `section_path`, and optional `title`.
- `get_bid_project_material_context`: retrieve ready-to-use Markdown by `project_id`, routing across business and technical runs.
- `list_bid_materials`: list indexed materials for a parsed run.

Recommended agent instruction:

```text
When writing a bid section and a directory path or section title is available, call get_bid_project_material_context first.
Use section_path before title. If the tool returns matched, use content_markdown as the main reference.
If it returns ambiguous, ask the user to choose from candidates instead of guessing.
```

Example tool arguments:

```json
{
  "project_id": "gansu_2026_272608",
  "section_path": "技术文件 / 技术偏差表",
  "title": "技术偏差表",
  "top_k": 5
}
```

Project config example:

```json
{
  "gansu_2026_272608": {
    "name": "国网甘肃电力2026年新增第一次物资公开招标采购",
    "runs": {
      "商务文件": "pdf_toc_run_business_v8",
      "技术文件": "pdf_toc_run_tech_v9"
    }
  }
}
```
