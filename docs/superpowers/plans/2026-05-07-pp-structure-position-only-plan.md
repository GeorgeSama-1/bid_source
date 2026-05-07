# PP-Structure Position Only Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure PP-Structure is used only for locating text/table/image regions and never creates financial compound folders or markdown正文.

**Architecture:** Keep the package structure driven by Excel/PDF-native section matching and candidate metadata. PP-Structure items remain in `ordered_material.json` for positioning, but are excluded from compound instance/child title discovery and material markdown text rendering.

**Tech Stack:** Python, pytest, existing `bid_knowledge.parsing.module_packager` packaging pipeline.

---

### Task 1: Lock PP-Structure Out Of Financial Folder Creation

**Files:**
- Modify: `tests/test_module_packager.py`
- Modify: `bid_knowledge/parsing/module_packager.py`

- [ ] **Step 1: Replace the PP-created financial instance regression test**

Change the test that currently expects PP-Structure titles to create `2022 年度财务审计报告` folders so it instead asserts those folders are not created when Excel/PDF/candidate structure does not provide them.

- [ ] **Step 2: Run the targeted test and verify it fails**

Run:

```bash
pytest tests/test_module_packager.py::test_package_module_artifacts_ignores_pp_structure_titles_for_financial_instance_headings
```

Expected: FAIL until production code stops using PP-Structure text as compound title blocks.

- [ ] **Step 3: Remove PP-Structure text from compound title discovery**

Delete `_structure_blocks_from_page_material_items` and remove `page_material_items` from `_package_compound_materials`. Instance detection should use only `path_instances` and PDF-native `scoped_blocks`.

- [ ] **Step 4: Run the targeted test and verify it passes**

Run the same single test. Expected: PASS.

### Task 2: Verify OCR/PP Text Still Does Not Enter Markdown

**Files:**
- Modify only if needed: `bid_knowledge/parsing/module_packager.py`
- Test: `tests/test_module_packager.py`

- [ ] **Step 1: Run existing OCR markdown tests**

Run:

```bash
pytest tests/test_module_packager.py::test_package_module_artifacts_keeps_pp_ocr_text_out_of_material_markdown tests/test_module_packager.py::test_package_module_artifacts_deduplicates_pdf_and_pp_structure_text_in_markdown
```

Expected: PASS.

- [ ] **Step 2: Keep markdown filtering if tests pass**

Do not remove `_is_ocr_derived_material_text`; this is still the desired behavior.

### Task 3: Regression Suite

**Files:**
- No additional edits expected.

- [ ] **Step 1: Run related regression tests**

Run:

```bash
pytest tests/test_material_stream.py tests/test_module_packager.py tests/test_section_matcher.py
```

Expected: all tests pass.

- [ ] **Step 2: Review git diff**

Confirm only `module_packager.py`, `tests/test_module_packager.py`, and this plan changed.
