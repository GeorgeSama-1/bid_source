# Agent Material Context Service Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an Agent-facing material context API that resolves a requested section path or similar title to ready-to-use Markdown from an existing parsed output run.

**Architecture:** Add a focused `agent_material_context` service module that reads generated material folders and exposes clean material records, match candidates, and context responses. Wire it into the existing FastAPI service without changing the parser output format.

**Tech Stack:** Python, FastAPI, Pydantic-compatible dict payloads, pytest.

---

## Chunk 1: Material Index And Resolver

### Task 1: Add the material context resolver

**Files:**
- Create: `bid_knowledge/service/agent_material_context.py`
- Test: `tests/test_agent_material_context.py`

- [x] **Step 1: Write failing tests**

Create tests for exact path, normalized path, title, fuzzy, and ambiguous resolution using a temporary `outputs/history_run/modules` tree with `material.md`, `material_meta.json`, and `ordered_material.json`.

- [x] **Step 2: Run tests to verify failure**

Run: `pytest tests/test_agent_material_context.py -q`

Expected: import or assertion failures because the module does not exist yet.

- [x] **Step 3: Implement minimal resolver**

Implement:

- `AgentMaterialContextService`
- `MaterialRecord`
- path/title normalization helpers
- `build_index(run_name)`
- `get_context(run_name, section_path=None, title=None, top_k=5)`

- [x] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_agent_material_context.py -q`

Expected: all new resolver tests pass.

## Chunk 2: FastAPI Endpoint

### Task 2: Wire resolver into service API

**Files:**
- Modify: `bid_knowledge/service/app.py`
- Test: `tests/test_result_browser.py`

- [x] **Step 1: Write failing API test**

Add a FastAPI `TestClient` test for `POST /api/runs/{run_name}/materials/context`.

- [x] **Step 2: Run API test to verify failure**

Run: `pytest tests/test_result_browser.py -q`

Expected: endpoint missing or response mismatch.

- [x] **Step 3: Add endpoint**

Instantiate `AgentMaterialContextService(BASE_DIR / "outputs")` and add the POST endpoint. Translate missing runs to `404`; return `matched`, `ambiguous`, or `not_found` payloads directly.

- [x] **Step 4: Run API tests**

Run: `pytest tests/test_result_browser.py tests/test_agent_material_context.py -q`

Expected: service tests pass.

## Chunk 3: Full Verification

### Task 3: Add MCP wrapper for OpenCode

**Files:**
- Create: `bid_knowledge/service/mcp_server.py`
- Modify: `requirements.txt`
- Test: `tests/test_mcp_server.py`

- [x] **Step 1: Add pure MCP handler tests**

Run: `pytest tests/test_mcp_server.py -q`

Expected: tests cover material context lookup and material listing without requiring the MCP SDK at import time.

- [x] **Step 2: Implement MCP server entrypoint**

Create `python -m bid_knowledge.service.mcp_server` with tools `get_bid_material_context` and `list_bid_materials`.

- [x] **Step 3: Add MCP dependency**

Add `mcp>=1.2.0` to `requirements.txt`.

- [x] **Step 4: Run MCP and service tests**

Run: `pytest tests/test_mcp_server.py tests/test_agent_material_context.py tests/test_result_browser.py -q`

Expected: all tests pass.

### Task 4: Verify repository behavior

**Files:**
- No additional files expected.

- [x] **Step 1: Run full tests**

Run: `pytest -q`

Expected: all tests pass.

- [x] **Step 2: Review diff**

Run: `git diff --stat && git diff -- bid_knowledge/service/agent_material_context.py bid_knowledge/service/app.py tests/test_agent_material_context.py tests/test_result_browser.py`

Expected: diff is scoped to the Agent material context service and tests.

- [ ] **Step 3: Commit when requested**

Run only after explicit user request:

```bash
git add bid_knowledge/service/agent_material_context.py bid_knowledge/service/app.py tests/test_agent_material_context.py tests/test_result_browser.py docs/superpowers/specs/2026-05-14-agent-material-context-service-design.md docs/superpowers/plans/2026-05-14-agent-material-context-service.md
git commit -m "feat: add agent material context service"
```
