# Bid Knowledge MVP Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a configuration-driven pre-ingestion parsing and retrieval-validation MVP for historical bid documents without introducing a database.

**Architecture:** The system is a modular Python package centered on JSON/JSONL/CSV intermediates. Excel rules and manual JSON config produce a processing plan, then PDF parsing, optional OCR, table extraction, section reconstruction, section matching, candidate extraction, chunk building, and retrieval evaluation execute as separate debuggable stages.

**Tech Stack:** Python, Typer, Pydantic, pandas/openpyxl, PyMuPDF, pdfplumber, rapidfuzz, rank_bm25, optional sentence-transformers/faiss-cpu, requests.

---

## Chunk 1: Foundations

### Task 1: Project scaffold and package boundaries

**Files:**
- Create: `bid_knowledge/`
- Create: `configs/manual_config.example.json`
- Create: `data/.gitkeep`
- Create: `outputs/.gitkeep`
- Create: `requirements.txt`
- Create: `README.md`

- [ ] Step 1: Create the package and output directory structure.
- [ ] Step 2: Add dependency declarations and placeholder package files.
- [ ] Step 3: Add example manual config and repository keep files.

### Task 2: Test-first coverage for core business rules

**Files:**
- Create: `tests/test_rule_loader.py`
- Create: `tests/test_normalizer.py`
- Create: `tests/test_strategy_router.py`

- [ ] Step 1: Write failing tests for rule loading bool normalization, section path building, and missing column tolerance.
- [ ] Step 2: Write failing tests for title normalization and numbering stripping.
- [ ] Step 3: Write failing tests for strategy routing and heuristic content typing.
- [ ] Step 4: Run pytest to confirm failures.

## Chunk 2: Core models and config pipeline

### Task 3: Shared schemas and utility helpers

**Files:**
- Create: `bid_knowledge/schemas/models.py`
- Create: `bid_knowledge/utils/io_utils.py`
- Create: `bid_knowledge/utils/text_utils.py`
- Create: `bid_knowledge/utils/id_utils.py`
- Create: `bid_knowledge/utils/logging_utils.py`

- [ ] Step 1: Define the Pydantic models used across the pipeline.
- [ ] Step 2: Add JSON/JSONL/CSV helpers, path helpers, id generation, and logger setup.

### Task 4: Rule loading and processing plan generation

**Files:**
- Create: `bid_knowledge/config/rule_loader.py`
- Create: `bid_knowledge/config/manual_config_loader.py`
- Create: `bid_knowledge/config/processing_plan_builder.py`

- [ ] Step 1: Implement tolerant Excel column mapping and rule serialization.
- [ ] Step 2: Implement manual config loading with defaults.
- [ ] Step 3: Implement config-driven processing plan assembly and strategy defaults.

## Chunk 3: Parsing and matching pipeline

### Task 5: PDF parsing, OCR, tables, and section reconstruction

**Files:**
- Create: `bid_knowledge/parsing/pdf_parser.py`
- Create: `bid_knowledge/parsing/table_extractor.py`
- Create: `bid_knowledge/parsing/ocr_client.py`
- Create: `bid_knowledge/parsing/ocr_merger.py`
- Create: `bid_knowledge/parsing/section_builder.py`

- [ ] Step 1: Implement PDF metadata, TOC, text block, and image extraction.
- [ ] Step 2: Implement targeted table extraction and OCR client wrapper.
- [ ] Step 3: Implement OCR merge behavior without overwriting native PDF text.
- [ ] Step 4: Implement simple but debuggable section reconstruction.

### Task 6: Section normalization and matching

**Files:**
- Create: `bid_knowledge/matching/normalizer.py`
- Create: `bid_knowledge/matching/section_matcher.py`

- [ ] Step 1: Implement robust title normalization for Chinese bid headings.
- [ ] Step 2: Implement exact, normalized, contains, fuzzy, and keyword matching.

## Chunk 4: Candidate and retrieval pipeline

### Task 7: Strategy routing, candidate extraction, and chunk building

**Files:**
- Create: `bid_knowledge/extraction/strategy_router.py`
- Create: `bid_knowledge/extraction/candidate_extractor.py`
- Create: `bid_knowledge/extraction/chunk_builder.py`

- [ ] Step 1: Implement process strategy routing with reasons.
- [ ] Step 2: Implement candidate extraction paths for structured fields, attachments, reusable text, and project-specific materials.
- [ ] Step 3: Implement chunk generation with traceable metadata.

### Task 8: Retrieval and evaluation

**Files:**
- Create: `bid_knowledge/retrieval/bm25_retriever.py`
- Create: `bid_knowledge/retrieval/vector_retriever.py`
- Create: `bid_knowledge/retrieval/retrieval_eval.py`

- [ ] Step 1: Implement BM25 retrieval.
- [ ] Step 2: Implement optional vector retrieval with graceful dependency fallback.
- [ ] Step 3: Implement retrieval evaluation against JSON query definitions.

## Chunk 5: CLI and verification

### Task 9: CLI commands and pipeline orchestration

**Files:**
- Create: `bid_knowledge/cli.py`
- Modify: `README.md`

- [ ] Step 1: Add Typer commands for each pipeline stage.
- [ ] Step 2: Add a one-command pipeline that preserves intermediate files and conditionally runs OCR.
- [ ] Step 3: Document how to execute the full flow.

### Task 10: Verification

**Files:**
- Verify: `tests/`

- [ ] Step 1: Run `pytest` and confirm green tests.
- [ ] Step 2: Run a light CLI smoke check such as `python -m bid_knowledge.cli --help`.
- [ ] Step 3: Report the exact verification status and any remaining gaps.
