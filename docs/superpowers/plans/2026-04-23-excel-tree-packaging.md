# Excel Tree Packaging Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Precreate the full business Excel history tree under the four top-level modules, while continuing to name extracted files by nearest PDF titles.

**Architecture:** Keep matching and extraction unchanged. Extend packaging inputs so the packager receives the planned history section paths from the processing plan, prebuilds every directory in that tree with `section_meta.json`, and then places matched candidate artifacts into the corresponding folders.

**Tech Stack:** Python, Typer, Pydantic, pytest

---

## Chunk 1: Test the expected tree behavior
### Task 1: Add failing tests for prebuilt empty directories
- [ ] Add tests that pass planned history section paths without candidates and assert empty directories plus `section_meta.json` exist.
- [ ] Run the targeted tests and confirm failure.

## Chunk 2: Implement tree precreation
### Task 2: Extend packager inputs and directory creation
- [ ] Update the packager to accept planned history section paths.
- [ ] Precreate every Excel-tree directory with `section_meta.json`, even with zero matched candidates.
- [ ] Keep top-level module directories fixed and keep file naming based on nearest PDF headings.
- [ ] Run targeted tests and make them pass.

## Chunk 3: Wire CLI and pipeline
### Task 3: Pass planned history section paths from the processing plan
- [ ] Update `package-materials` and `pipeline` to pass the history section tree into packaging.
- [ ] Re-run targeted and full tests.
- [ ] Rebuild `outputs/history_run` and verify the four-module tree.
