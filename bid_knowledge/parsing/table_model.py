from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

from bid_knowledge.utils.text_utils import clean_text


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.raw_rows: list[list[dict[str, Any]]] = []
        self._current_row: list[dict[str, Any]] | None = None
        self._current_cell: dict[str, Any] | None = None
        self._cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._current_row = []
            return
        if tag not in {"td", "th"} or self._current_row is None:
            return
        attr_map = {name.lower(): value for name, value in attrs}
        self._current_cell = {
            "rowspan": _positive_int(attr_map.get("rowspan"), 1),
            "colspan": _positive_int(attr_map.get("colspan"), 1),
            "is_header": tag == "th",
        }
        self._cell_text = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            self._current_cell["text"] = clean_text("".join(self._cell_text))
            self._current_row.append(self._current_cell)
            self._current_cell = None
            self._cell_text = []
            return
        if tag == "tr" and self._current_row is not None:
            if any(clean_text(cell.get("text") or "") for cell in self._current_row):
                self.raw_rows.append(self._current_row)
            self._current_row = None


def _positive_int(value: Any, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return default
    return result if result > 0 else default


def _normalize_bbox(bbox: list[float] | None) -> list[float] | None:
    if not bbox or len(bbox) < 4:
        return None
    return [float(value) for value in bbox[:4]]


def _empty_model(*, source: str, bbox: list[float] | None = None, raw_html: str = "") -> dict[str, Any]:
    return {
        "schema_version": "table_model_v1",
        "source": source,
        "row_count": 0,
        "col_count": 0,
        "rows": [],
        "cells": [],
        "merged_cells": [],
        "bbox": _normalize_bbox(bbox),
        "raw_html": raw_html,
        "preserves_spans": False,
    }


def build_table_model_from_rows(
    rows: list[list[Any]],
    *,
    source: str,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    normalized_rows = [[clean_text(cell) for cell in row] for row in rows if isinstance(row, list)]
    col_count = max((len(row) for row in normalized_rows), default=0)
    padded_rows = [row + [""] * (col_count - len(row)) for row in normalized_rows]
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(padded_rows):
        for col_index, text in enumerate(row):
            cells.append(
                {
                    "row": row_index,
                    "col": col_index,
                    "rowspan": 1,
                    "colspan": 1,
                    "text": text,
                    "is_header": row_index == 0,
                    "bbox": None,
                }
            )
    return {
        "schema_version": "table_model_v1",
        "source": source,
        "row_count": len(padded_rows),
        "col_count": col_count,
        "rows": padded_rows,
        "cells": cells,
        "merged_cells": [],
        "bbox": _normalize_bbox(bbox),
        "raw_html": "",
        "preserves_spans": False,
    }


def build_table_model_from_html(
    html: str,
    *,
    source: str = "pp_structure_html",
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    if "<table" not in str(html or "").lower():
        return _empty_model(source=source, bbox=bbox, raw_html=str(html or ""))

    parser = _HTMLTableParser()
    parser.feed(str(html or ""))
    if not parser.raw_rows:
        return _empty_model(source=source, bbox=bbox, raw_html=str(html or ""))

    occupied: set[tuple[int, int]] = set()
    cells: list[dict[str, Any]] = []
    row_count = 0
    col_count = 0
    for row_index, raw_row in enumerate(parser.raw_rows):
        col_index = 0
        for raw_cell in raw_row:
            while (row_index, col_index) in occupied:
                col_index += 1
            rowspan = _positive_int(raw_cell.get("rowspan"), 1)
            colspan = _positive_int(raw_cell.get("colspan"), 1)
            cell = {
                "row": row_index,
                "col": col_index,
                "rowspan": rowspan,
                "colspan": colspan,
                "text": clean_text(raw_cell.get("text") or ""),
                "is_header": bool(raw_cell.get("is_header")),
                "bbox": None,
            }
            cells.append(cell)
            for row_offset in range(rowspan):
                for col_offset in range(colspan):
                    occupied.add((row_index + row_offset, col_index + col_offset))
            row_count = max(row_count, row_index + rowspan)
            col_count = max(col_count, col_index + colspan)
            col_index += colspan

    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in cells:
        rows[int(cell["row"])][int(cell["col"])] = str(cell.get("text") or "")

    merged_cells = [
        {
            "row": cell["row"],
            "col": cell["col"],
            "rowspan": cell["rowspan"],
            "colspan": cell["colspan"],
        }
        for cell in cells
        if int(cell.get("rowspan") or 1) > 1 or int(cell.get("colspan") or 1) > 1
    ]
    return {
        "schema_version": "table_model_v1",
        "source": source,
        "row_count": row_count,
        "col_count": col_count,
        "rows": rows,
        "cells": cells,
        "merged_cells": merged_cells,
        "bbox": _normalize_bbox(bbox),
        "raw_html": str(html or ""),
        "preserves_spans": bool(merged_cells),
    }
