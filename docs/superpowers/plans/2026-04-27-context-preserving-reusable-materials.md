# Context-Preserving Reusable Materials Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve original text/table/image context inside each reusable child module while still enforcing Excel rule paths and storage-spec naming constraints.

**Architecture:** Add a unified material-item layer between page parsing and module packaging. Keep raw context metadata and business archive metadata side by side, then upgrade module output files so `ordered_material.json` becomes the canonical replay file for later reuse.

**Tech Stack:** Python, PyMuPDF, existing `bid_knowledge` packaging pipeline, JSON outputs, pytest.

---

## Chunk 1: Introduce Unified Material Item Metadata

### Task 1: Extend schemas for context-preserving item metadata

**Files:**
- Modify: `bid_knowledge/schemas/models.py`
- Test: `tests/` new schema-focused tests if needed

- [ ] **Step 1: Write a failing test for new material metadata fields**

Add a focused test that instantiates the target models with:
- `item_type`
- `source_type`
- `material_path`
- `nearest_heading`
- `rule_section_path`
- `reading_order`

Expected: current models either reject or cannot represent the full shape cleanly.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest <new-test-file> -v`
Expected: FAIL because fields or model structure are missing.

- [ ] **Step 3: Add minimal schema support**

Update models so they can represent:
- raw context metadata
- archive mapping metadata
- ordered replay item metadata

Keep the new schema additive and backward-compatible where practical.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest <new-test-file> -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/schemas/models.py <new-test-file>
git commit -m "feat: add context-preserving material item schema"
```

## Chunk 2: Build a Unified Material Item Layer

### Task 2: Normalize text/table/image items into one internal representation

**Files:**
- Modify: `bid_knowledge/parsing/module_packager.py`
- Possibly modify: `bid_knowledge/parsing/pdf_parser.py`
- Test: `tests/test_module_packager.py`

- [ ] **Step 1: Write a failing packaging test**

Create or extend a packaging test that expects one child material to produce ordered entries with:
- stable `item_id`
- explicit `item_type`
- `payload_ref`
- `nearest_heading`
- `rule_section_path`
- `reading_order` or equivalent ordering field

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_module_packager.py -v`
Expected: FAIL because current output is only partially structured.

- [ ] **Step 3: Implement a unified internal material-item builder**

Inside `module_packager.py`, add a small internal layer that converts:
- text blocks
- tables
- images

into one common structure before writing output files.

Keep existing extraction logic where possible; change only the packaging boundary.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_module_packager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/module_packager.py tests/test_module_packager.py
git commit -m "feat: unify material items before packaging"
```

## Chunk 3: Upgrade `ordered_material.json`

### Task 3: Make ordered material the canonical replay file

**Files:**
- Modify: `bid_knowledge/parsing/module_packager.py`
- Test: `tests/test_module_packager.py`

- [ ] **Step 1: Write a failing test for ordered replay output**

Expected output should include:
- `material_path`
- `material_types`
- `dominant_material_type`
- ordered `items`
- per-item `item_type`
- per-item `payload_ref`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_module_packager.py -v`
Expected: FAIL because `ordered_material.json` is still a lighter index.

- [ ] **Step 3: Upgrade ordered output writing**

Refactor the writer so `ordered_material.json` becomes the main replay surface for later reuse.

Requirements:
- preserve sequence
- preserve mixed media
- preserve archive mapping
- avoid duplicating large payloads inline when a file reference is enough

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_module_packager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/module_packager.py tests/test_module_packager.py
git commit -m "feat: upgrade ordered material replay structure"
```

## Chunk 4: Upgrade `material_meta.json` and `compound_instance_meta.json`

### Task 4: Separate raw context identity from archive identity

**Files:**
- Modify: `bid_knowledge/parsing/module_packager.py`
- Test: `tests/test_module_packager.py`

- [ ] **Step 1: Write failing tests for metadata layering**

Expect metadata files to contain:
- `rule_section_path`
- `rule_module_name`
- `material_types`
- `dominant_material_type`
- `title_mapping`
- `material_path`

And for compound instances:
- `instance_path`
- child `material_path`
- child `material_types`

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_module_packager.py -v`
Expected: FAIL because current metadata does not fully separate these layers.

- [ ] **Step 3: Implement metadata upgrades**

Update meta writers so:
- submodule metadata describes the material as a reusable package
- compound metadata describes the parent-child archive structure

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_module_packager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/module_packager.py tests/test_module_packager.py
git commit -m "feat: separate raw and archive metadata layers"
```

## Chunk 5: Preserve Rule Constraints Without Overwriting Raw Context

### Task 5: Add explicit title-mapping and rule-mapping fields

**Files:**
- Modify: `bid_knowledge/parsing/module_packager.py`
- Possibly modify: `bid_knowledge/matching/section_matcher.py`
- Possibly modify: `bid_knowledge/config/rule_loader.py`
- Test: `tests/test_module_packager.py`

- [ ] **Step 1: Write a failing test for title mapping**

Test should verify one material can carry:
- raw heading
- normalized heading
- Excel-driven archive path
- final material title

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_module_packager.py -v`
Expected: FAIL because the current structure collapses some of these names.

- [ ] **Step 3: Implement explicit title mapping**

Add a small helper that derives:
- `raw_context_title`
- `normalized_context_title`
- `material_title`
- `rule_section_path`

Do not overwrite raw values when archive values differ.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_module_packager.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/module_packager.py tests/test_module_packager.py
git commit -m "feat: preserve title mapping across raw and archive layers"
```

## Chunk 6: PP-StructureV3 Integration Point

### Task 6: Define a page-material stream that can accept PP-StructureV3 results

**Files:**
- Modify: `bid_knowledge/parsing/pdf_parser.py`
- Create or modify: new parsing adapter module if needed
- Test: new adapter test file

- [ ] **Step 1: Write a failing test for page material stream input**

The test should verify that page-level text/image/table items from a structure parser can be normalized into the same material-item layer used by packaging.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest <new-adapter-test-file> -v`
Expected: FAIL because there is not yet a common adapter boundary.

- [ ] **Step 3: Implement the adapter boundary**

Add a narrow integration layer so future PP-StructureV3 outputs can feed:
- text regions
- image regions
- table regions

into the same packaging path as existing PDF text and embedded-image extraction.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest <new-adapter-test-file> -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/pdf_parser.py <new-adapter-test-file> <new-adapter-module-if-any>
git commit -m "feat: add page material stream adapter boundary"
```

## Chunk 7: Regression Verification

### Task 7: Verify current history-run style outputs still package correctly

**Files:**
- Test only: existing packaging tests plus any fixture updates

- [ ] **Step 1: Run targeted packaging tests**

Run: `pytest tests/test_module_packager.py -v`
Expected: PASS

- [ ] **Step 2: Run related candidate extraction tests**

Run: `pytest tests/test_candidate_extractor.py -v`
Expected: PASS

- [ ] **Step 3: Run rule/plan tests that guard section path behavior**

Run: `pytest tests/test_processing_plan_builder.py tests/test_rule_loader.py tests/test_section_matcher.py -v`
Expected: PASS

- [ ] **Step 4: Spot-check one generated module output**

Re-run the pipeline or targeted packager flow on a representative section and confirm:
- `ordered_material.json` preserves item order and type
- `material_meta.json` preserves archive mapping
- `compound_instance_meta.json` preserves child relationships

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "test: verify context-preserving reusable material packaging"
```
