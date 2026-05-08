from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from bid_knowledge.schemas.models import ParsedTable
from bid_knowledge.utils.id_utils import make_stable_id
from bid_knowledge.utils.io_utils import write_json
from bid_knowledge.utils.text_utils import clean_text


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            self._current_row.append(clean_text("".join(self._current_cell)))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            if any(clean_text(cell) for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def _parse_html_table_rows(content: str) -> list[list[str]]:
    if "<table" not in content.lower():
        return []
    parser = _TableHTMLParser()
    parser.feed(content)
    return parser.rows


def _float_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list | tuple) or len(value) < 4:
        return None
    bbox: list[float] = []
    for item in value[:4]:
        try:
            bbox.append(float(item))
        except (TypeError, ValueError):
            return None
    return bbox


def _page_no(result: dict[str, Any], payload: dict[str, Any]) -> int:
    page_index = result.get("page_index", payload.get("page_index", 0))
    try:
        return int(payload.get("page_no") or int(page_index) + 1)
    except (TypeError, ValueError):
        return 1


def _bbox_overlap_ratio(bbox: list[float], other: list[float]) -> float:
    x0, y0, x1, y1 = bbox[:4]
    ox0, oy0, ox1, oy1 = other[:4]
    ix0 = max(x0, ox0)
    iy0 = max(y0, oy0)
    ix1 = min(x1, ox1)
    iy1 = min(y1, oy1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area = max((x1 - x0) * (y1 - y0), 1.0)
    other_area = max((ox1 - ox0) * (oy1 - oy0), 1.0)
    return intersection / min(area, other_area)


def _duplicates_existing(bbox: list[float], existing: list[ParsedTable]) -> bool:
    return any(table.bbox and _bbox_overlap_ratio(bbox, [float(value) for value in table.bbox[:4]]) >= 0.8 for table in existing)


def merge_pp_and_pdf_tables(pp_tables: list[ParsedTable], pdf_tables: list[ParsedTable]) -> list[ParsedTable]:
    merged = list(pp_tables)
    for table in pdf_tables:
        if table.bbox:
            pdf_bbox = [float(value) for value in table.bbox[:4]]
            overlapping_index = next(
                (
                    index
                    for index, existing in enumerate(merged)
                    if existing.bbox and _bbox_overlap_ratio(pdf_bbox, [float(value) for value in existing.bbox[:4]]) >= 0.8
                ),
                None,
            )
            if overlapping_index is not None:
                existing = merged[overlapping_index]
                if not existing.rows and table.rows:
                    merged[overlapping_index] = table
                continue
        merged.append(table)
    return sorted(merged, key=lambda item: (item.page_no, float((item.bbox or [0, 0, 0, 0])[1]) if item.bbox else 0.0))


def extract_pp_structure_tables(
    pp_structure_results: list[dict[str, Any]],
    *,
    out_path: str | Path | None = None,
) -> list[ParsedTable]:
    tables: list[ParsedTable] = []
    for result in pp_structure_results:
        payload = result.get("res") if isinstance(result.get("res"), dict) else result
        if not isinstance(payload, dict):
            continue
        page_no = _page_no(result, payload)

        for block_index, block in enumerate(payload.get("parsing_res_list") or [], start=1):
            if not isinstance(block, dict) or str(block.get("block_label") or "") != "table":
                continue
            bbox = _float_bbox(block.get("block_bbox") or block.get("bbox"))
            if not bbox:
                continue
            content = str(block.get("block_content") or "")
            tables.append(
                ParsedTable(
                    table_id=make_stable_id("pp-table", page_no, block_index, bbox, content[:120]),
                    page_no=page_no,
                    rows=_parse_html_table_rows(content),
                    bbox=bbox,
                    source_type="pp_structure_table",
                    table_content=content,
                    source_detail="parsing_res_list",
                    pp_block_id=block.get("block_id"),
                    pp_block_order=block.get("block_order"),
                )
            )

        layout_index = 0
        for box in (payload.get("layout_det_res") or {}).get("boxes") or []:
            if not isinstance(box, dict) or str(box.get("label") or "") != "table":
                continue
            bbox = _float_bbox(box.get("coordinate"))
            if not bbox or _duplicates_existing(bbox, tables):
                continue
            layout_index += 1
            tables.append(
                ParsedTable(
                    table_id=make_stable_id("pp-table-region", page_no, layout_index, bbox),
                    page_no=page_no,
                    rows=[],
                    bbox=bbox,
                    source_type="pp_structure_table",
                    table_content="",
                    source_detail="layout_det_res",
                    pp_score=box.get("score"),
                )
            )

    if out_path:
        write_json(out_path, tables)
    return tables
