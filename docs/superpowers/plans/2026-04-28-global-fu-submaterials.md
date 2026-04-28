# Global `附：` Submaterials Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global packaging rule so any `附：xxx` / `附:xxx` block becomes a reusable child submaterial while preserving parent-section context and `text/table/image` order.

**Architecture:** Extend the existing heading and module packaging flow rather than inventing a separate attachment pipeline. Detect `附：` anchors as child-package boundaries inside any matched parent section, write explicit child package artifacts, and add parent-level references so downstream reuse can restore either the full section or an individual attachment package.

**Tech Stack:** Python, Pydantic models, existing packaging utilities, pytest

---

## File Map

- Modify: `bid_knowledge/parsing/module_packager.py`
  - Add generic `附：` submaterial grouping for any matched section.
  - Write child package manifests and parent references.
- Modify: `bid_knowledge/schemas/models.py`
  - Extend package item/reference schemas for child package references if needed.
- Modify: `bid_knowledge/utils/heading_utils.py`
  - Keep `附：` normalization rules explicit and reusable.
- Modify: `docs/reusable_material_storage_spec.md`
  - Clarify that `附：` is a global submaterial rule, not an authorization-only convention.
- Test: `tests/test_module_packager.py`
  - Add end-to-end packaging regression coverage.
- Test: `tests/test_material_models.py`
  - Add schema coverage for child package references if schema changes.

## Chunk 1: Lock the Behavior with Tests

### Task 1: Add a generic `附：` child-package packaging test

**Files:**
- Modify: `tests/test_module_packager.py`

- [ ] **Step 1: Write the failing test**

Add a test where:

- parent section is not `法定代表人授权委托书`
- blocks contain `附：履约证明材料`
- child items include at least one text item and one image item
- expected output includes a child package named `履约证明材料`
- expected parent output includes a submaterial reference

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_module_packager.py::test_package_module_artifacts_creates_global_fu_submaterial -v`
Expected: FAIL because the current packager does not create a generic child submaterial package.

- [ ] **Step 3: Add a duplicate-title test**

Add a second test covering two `附：营业执照副本` anchors under one parent and assert stable suffixing for directories/payload refs.

- [ ] **Step 4: Run both tests**

Run: `pytest tests/test_module_packager.py -k "global_fu_submaterial or duplicate_fu_titles" -v`
Expected: FAIL

- [ ] **Step 5: Commit**

```bash
git add tests/test_module_packager.py
git commit -m "test: cover global fu attachment submaterials"
```

## Chunk 2: Extend Schemas and Heading Semantics

### Task 2: Add explicit child-package reference support

**Files:**
- Modify: `bid_knowledge/schemas/models.py`
- Test: `tests/test_material_models.py`

- [ ] **Step 1: Write the failing schema test**

Add a test that instantiates an ordered material item/reference with:

```python
MaterialItemRef(
    order=3,
    item_type="submaterial",
    payload_ref="submaterials/履约证明材料/ordered_material.json",
    nearest_heading="附：履约证明材料",
    material_path="商务文件 / 模块 / 履约证明材料",
)
```

- [ ] **Step 2: Run test to verify it fails or is unsupported**

Run: `pytest tests/test_material_models.py::test_material_item_ref_supports_submaterial_type -v`
Expected: FAIL or schema mismatch.

- [ ] **Step 3: Update schema minimally**

Allow the existing reference model to represent child package refs cleanly without broadening unrelated responsibilities.

- [ ] **Step 4: Re-run schema tests**

Run: `pytest tests/test_material_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/schemas/models.py tests/test_material_models.py
git commit -m "feat: model child package references"
```

### Task 3: Make `附：` title normalization reusable and explicit

**Files:**
- Modify: `bid_knowledge/utils/heading_utils.py`

- [ ] **Step 1: Add or tighten helper behavior**

Ensure there is one obvious helper path for:

- identifying `附：` headings
- removing only the prefix
- preserving the remainder exactly enough for display naming

- [ ] **Step 2: Run focused regression tests**

Run: `pytest tests/test_module_packager.py -k "fu or authorization" -v`
Expected: existing attachment-related tests remain green.

- [ ] **Step 3: Commit**

```bash
git add bid_knowledge/utils/heading_utils.py
git commit -m "refactor: centralize fu heading normalization"
```

## Chunk 3: Implement Generic Child Package Writing

### Task 4: Detect `附：` spans inside any parent package

**Files:**
- Modify: `bid_knowledge/parsing/module_packager.py`

- [ ] **Step 1: Identify current parent-section packaging path**

Trace where the packager currently:

- groups blocks/images/tables by candidate section
- resolves nearest headings
- writes `ordered_material.json` and `material_meta.json`

- [ ] **Step 2: Add failing assertions locally if useful**

Use the new tests as the boundary: no behavior beyond what's needed for generic child packages.

- [ ] **Step 3: Implement span detection**

Inside a matched parent section:

- treat `附：` headings as child anchors
- collect items until the next sibling heading or end of section
- preserve original item order

- [ ] **Step 4: Re-run focused packaging tests**

Run: `pytest tests/test_module_packager.py -k "global_fu_submaterial or duplicate_fu_titles or authorization" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/module_packager.py
git commit -m "feat: package global fu attachment submaterials"
```

### Task 5: Write parent references and child package artifacts

**Files:**
- Modify: `bid_knowledge/parsing/module_packager.py`

- [ ] **Step 1: Write child package outputs**

For each child anchor, write:

- child `ordered_material.json`
- child `material_meta.json`
- child item payloads already supported by the packager

- [ ] **Step 2: Write parent reference items**

Append or inject a `submaterial` reference item into the parent ordered package with:

- `payload_ref`
- `nearest_heading`
- `material_path`

- [ ] **Step 3: Preserve existing output compatibility**

Do not remove currently expected text/table/image payload files unless the tests demand it.

- [ ] **Step 4: Run the full relevant packager suite**

Run: `pytest tests/test_module_packager.py tests/test_material_models.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bid_knowledge/parsing/module_packager.py
git commit -m "feat: reference child submaterials from parent packages"
```

## Chunk 4: Document the Rule and Verify End-to-End

### Task 6: Update storage documentation

**Files:**
- Modify: `docs/reusable_material_storage_spec.md`

- [ ] **Step 1: Add a short normative section**

Document that `附：xxx` is a global submaterial rule and that child package names drop the prefix.

- [ ] **Step 2: Add an example path**

Include an example under a non-authorization parent section to show the rule is generic.

- [ ] **Step 3: Commit**

```bash
git add docs/reusable_material_storage_spec.md
git commit -m "docs: define global fu submaterial packaging rule"
```

### Task 7: Run verification before completion

**Files:**
- No file changes required

- [ ] **Step 1: Run targeted tests**

Run:

```bash
pytest tests/test_material_models.py tests/test_module_packager.py -q
```

Expected: PASS

- [ ] **Step 2: Run adjacent regression tests**

Run:

```bash
pytest tests/test_candidate_extractor.py tests/test_section_matcher.py -q
```

Expected: PASS

- [ ] **Step 3: Compile touched modules**

Run:

```bash
python -m py_compile \
  bid_knowledge/schemas/models.py \
  bid_knowledge/utils/heading_utils.py \
  bid_knowledge/parsing/module_packager.py
```

Expected: no output

- [ ] **Step 4: Commit final verification-only changes if any**

```bash
git status
```

- [ ] **Step 5: Prepare execution handoff**

Confirm the implementation is ready for the next coding pass.

Plan complete and saved to `docs/superpowers/plans/2026-04-28-global-fu-submaterials.md`. Ready to execute?
