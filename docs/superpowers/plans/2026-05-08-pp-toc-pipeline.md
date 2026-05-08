# PP TOC Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a new PP-Structure-first TOC pipeline that avoids mixing PDF text extraction, pdfplumber tables, and PP layout output in `material.md`.

**Architecture:** Keep the existing `pdf-toc-pipeline` unchanged. Add a focused `pp_toc_packager` module that converts PP-Structure results into one ordered stream of `text/table/image` elements, scopes that stream by PDF TOC leaf candidates, and writes `material.md` plus asset folders. Tables are linked as JSON in the first version; images are cropped from PDF page regions when a PDF is available.

**Tech Stack:** Python, Typer CLI, PyMuPDF/fitz for image cropping, existing `run_pp_structure`, `parse_pdf`, `build_toc_leaf_candidates`, `write_json`.

---

## Chunk 1: PP-Structure Stream Packager

**Files:**
- Create: `bid_knowledge/parsing/pp_toc_packager.py`
- Test: `tests/test_pp_toc_packager.py`

- [ ] Write tests for extracting ordered PP text/table/image items while ignoring header/footer/page numbers.
- [ ] Write tests for packaging a TOC leaf folder with text, table JSON link, and image metadata.
- [ ] Implement minimal stream extraction and leaf material writing.
- [ ] Run `pytest tests/test_pp_toc_packager.py -q`.

## Chunk 2: CLI Command

**Files:**
- Modify: `bid_knowledge/cli.py`
- Test: `tests/test_pp_toc_packager.py`

- [ ] Add `pp-toc-pipeline` command that runs `parse_pdf` for TOC/page count, runs PP-Structure, builds TOC leaf candidates, and calls the new packager.
- [ ] Write a small command-level helper test if practical; otherwise verify via `py_compile`.
- [ ] Run relevant tests and compile checks.

## Chunk 3: Verification

**Files:**
- Existing tests only.

- [ ] Run `pytest tests/test_pp_toc_packager.py tests/test_toc_leaf_builder.py -q`.
- [ ] Run `python3 -m py_compile bid_knowledge/cli.py bid_knowledge/parsing/pp_toc_packager.py`.
- [ ] Report the server command:
  `CUDA_VISIBLE_DEVICES=6 python -m bid_knowledge.cli pp-toc-pipeline --pdf "2、商务文件.pdf" --out-dir outputs/pp_toc_run_v1 --pp-structure-device gpu --progress true`.
