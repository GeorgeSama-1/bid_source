from __future__ import annotations

from typing import Any

from bid_knowledge.schemas.models import ReusableCandidate
from bid_knowledge.utils.id_utils import make_stable_id


def _clean_toc_title(title: str) -> str:
    return " ".join(str(title or "").strip().split())


def _toc_path_prefix(path_root: str) -> list[str]:
    return [part.strip() for part in str(path_root or "PDF").split(" / ") if part.strip()] or ["PDF"]


def _toc_leaf_indexes(toc: list[dict[str, Any]]) -> set[int]:
    leaf_indexes: set[int] = set()
    for index, item in enumerate(toc):
        level = int(item.get("level") or 1)
        next_level = int(toc[index + 1].get("level") or 1) if index + 1 < len(toc) else 0
        if index + 1 == len(toc) or next_level <= level:
            leaf_indexes.add(index)
    return leaf_indexes


def build_toc_leaf_candidates(
    *,
    toc: list[dict[str, Any]],
    page_count: int,
    path_root: str = "PDF",
    company_id: str = "pdf",
    document_id: str = "pdf_document",
) -> list[ReusableCandidate]:
    root_parts = _toc_path_prefix(path_root)
    stack: list[str] = []
    leaf_indexes = _toc_leaf_indexes(toc)
    candidates: list[ReusableCandidate] = []

    for index, item in enumerate(toc):
        level = max(1, int(item.get("level") or 1))
        title = _clean_toc_title(str(item.get("title") or ""))
        if not title:
            continue
        while len(stack) >= level:
            stack.pop()
        stack.append(title)
        if index not in leaf_indexes:
            continue

        next_page = int(toc[index + 1].get("page") or page_count + 1) if index + 1 < len(toc) else page_count + 1
        page_start = max(1, int(item.get("page") or 1))
        page_end = max(page_start, min(page_count, next_page - 1))
        section_parts = [*root_parts, *stack]
        parent_title = stack[-2] if len(stack) >= 2 else ""
        section_path = " / ".join(section_parts)
        candidates.append(
            ReusableCandidate(
                candidate_id=make_stable_id("toc-leaf", index, section_path, page_start, page_end),
                company_id=company_id,
                document_id=document_id,
                rule_id=make_stable_id("toc-rule", section_path),
                section_path=section_path,
                from_history_bid=True,
                has_standard_template=True,
                title=title,
                content="",
                candidate_type="pdf_toc_leaf",
                reuse_method="PDF目录叶子章节",
                reuse_level="document",
                enter_long_term_library=True,
                source_file="",
                source_page=page_start,
                source_page_end=page_end,
                source_container_title=parent_title,
            )
        )

    return candidates


def toc_leaf_section_paths(candidates: list[ReusableCandidate]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for candidate in candidates:
        if candidate.section_path in seen:
            continue
        seen.add(candidate.section_path)
        paths.append(candidate.section_path)
    return paths


def top_level_modules_from_toc_candidates(candidates: list[ReusableCandidate]) -> list[str]:
    modules: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        parts = [part.strip() for part in candidate.section_path.split(" / ") if part.strip()]
        if len(parts) < 2:
            continue
        module = parts[1]
        if module in seen:
            continue
        seen.add(module)
        modules.append(module)
    return modules
