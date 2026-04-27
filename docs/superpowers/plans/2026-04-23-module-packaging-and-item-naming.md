# Module Packaging And Item Naming Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add nearest-heading naming for table/image artifacts and export module-based directories with per-item JSON/files alongside existing global outputs.

**Architecture:** Keep current parse/match/candidate outputs intact for debugging, then add a packaging layer that consumes parsed blocks/tables/images plus section/rule context to emit `modules/<module_name>/...` artifacts. Reuse a shared heading-detection helper so tables and images use the same naming/context rules.

**Tech Stack:** Python, Typer CLI, PyMuPDF, pdfplumber, pydantic, pytest.

---

## Files To Modify / Create

- Modify: `bid_knowledge/parsing/pdf_parser.py`
- Modify: `bid_knowledge/parsing/table_extractor.py`
- Modify: `bid_knowledge/cli.py`
- Modify: `bid_knowledge/schemas/models.py`
- Modify: `tests/test_attachment_asset_exporter.py`
- Create: `bid_knowledge/utils/heading_utils.py`
- Create: `bid_knowledge/parsing/module_packager.py`
- Create: `tests/test_module_packager.py`

## Chunk 1: Shared Heading Rules
- [ ] Add a shared heading utility that recognizes multi-level titles like `3.8.1.2`, `（5）`, `（5.1）`, `附：...`.
- [ ] Add tests for heading recognition and title sanitization behavior through packager-facing tests.

## Chunk 2: Table/Image Metadata
- [ ] Extend parsed image metadata with rect/bbox so nearest-title resolution can work for images.
- [ ] Extend table metadata with title/context fields populated later by packaging.
- [ ] Write failing tests covering nearest-title naming for one table and multiple images under one heading.

## Chunk 3: Module Packager
- [ ] Create module packager that groups artifacts by rule module name.
- [ ] Export `module_meta.json`, `tables.json`, `table_items/*.json`, `images.json`, `image_items/*.json` and extracted image files.
- [ ] Keep global outputs unchanged.
- [ ] Add tests that assert module directory layout and expected per-item filenames.

## Chunk 4: CLI / Pipeline Wiring
- [ ] Add a CLI command to package module artifacts.
- [ ] Call it from `pipeline` after candidate extraction.
- [ ] Update docs references where needed.

## Chunk 5: Verification
- [ ] Run targeted tests for new packager and naming logic.
- [ ] Run full test suite.
- [ ] Run packaging on current `outputs/demo_run` inputs and verify sample module outputs.
