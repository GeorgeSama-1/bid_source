from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from bid_knowledge.schemas.models import ParsedTable
from bid_knowledge.utils.io_utils import ensure_dir


TABLE_TO_JSON_PROMPT = """请识别图片中的表格并输出严格 JSON，不要输出解释、Markdown 或自然语言。
第一个字符必须是 {，最后一个字符必须是 }。
JSON schema:
{
  "row_count": 0,
  "col_count": 0,
  "cells": [
    {"row": 0, "col": 0, "text": "", "rowspan": 1, "colspan": 1}
  ],
  "merged_cells": []
}
row 和 col 从 0 开始。必须尽量保留原表格行列结构和合并单元格。"""


def _extract_response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        return "\n".join(str(item.get("text") or "") for item in content if isinstance(item, dict) and item.get("type") == "text")
    return str(content or "")


def _strip_json_fence(text: str) -> str:
    stripped = str(text or "").strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        return fenced.group(1).strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return stripped[start : end + 1]
    return stripped


def _table_model_from_rows(rows: list[list[Any]], *, source: str) -> dict[str, Any]:
    normalized_rows = [[str(cell or "").strip() for cell in row] for row in rows if isinstance(row, list)]
    row_count = len(normalized_rows)
    col_count = max((len(row) for row in normalized_rows), default=0)
    padded_rows = [row + [""] * (col_count - len(row)) for row in normalized_rows]
    cells: list[dict[str, Any]] = []
    for row_index, row in enumerate(padded_rows):
        for col_index, text in enumerate(row):
            cells.append(
                {
                    "row": row_index,
                    "col": col_index,
                    "text": text,
                    "rowspan": 1,
                    "colspan": 1,
                    "bbox": None,
                }
            )
    return {
        "schema_version": "table_model_v1",
        "source": source,
        "row_count": row_count,
        "col_count": col_count,
        "rows": padded_rows,
        "cells": cells,
        "merged_cells": [],
        "bbox": None,
        "raw_html": "",
        "preserves_spans": False,
    }


def _parse_table_model_text(text: str) -> dict[str, Any]:
    payload = json.loads(_strip_json_fence(text))
    if isinstance(payload, list):
        return _table_model_from_rows(payload, source="vlm_rows_json")
    if isinstance(payload, dict) and isinstance(payload.get("table_model"), dict):
        payload = payload["table_model"]
    if not isinstance(payload, dict):
        raise ValueError("VLM table response is not a JSON object.")
    cells = payload.get("cells")
    if not isinstance(cells, list):
        raise ValueError("VLM table response must contain cells list.")
    row_count = int(payload.get("row_count") or 0)
    col_count = int(payload.get("col_count") or 0)
    normalized_cells: list[dict[str, Any]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        normalized_cells.append(
            {
                "row": int(cell.get("row") or 0),
                "col": int(cell.get("col") or 0),
                "text": str(cell.get("text") or ""),
                "rowspan": max(1, int(cell.get("rowspan") or 1)),
                "colspan": max(1, int(cell.get("colspan") or 1)),
                "bbox": cell.get("bbox"),
            }
        )
    rows = [["" for _ in range(col_count)] for _ in range(row_count)]
    for cell in normalized_cells:
        row = int(cell["row"])
        col = int(cell["col"])
        if 0 <= row < row_count and 0 <= col < col_count:
            rows[row][col] = str(cell.get("text") or "")
    merged_cells = payload.get("merged_cells")
    if not isinstance(merged_cells, list):
        merged_cells = [
            {
                "row": cell["row"],
                "col": cell["col"],
                "rowspan": cell["rowspan"],
                "colspan": cell["colspan"],
            }
            for cell in normalized_cells
            if int(cell["rowspan"]) > 1 or int(cell["colspan"]) > 1
        ]
    return {
        "schema_version": "table_model_v1",
        "source": "paddleocr_vl",
        "row_count": row_count,
        "col_count": col_count,
        "rows": rows,
        "cells": normalized_cells,
        "merged_cells": merged_cells,
        "bbox": payload.get("bbox"),
        "raw_html": str(payload.get("raw_html") or payload.get("html") or ""),
        "preserves_spans": bool(merged_cells),
    }


def _image_to_data_uri(image_path: str | Path) -> str:
    raw = Path(image_path).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _render_table_crop(
    *,
    pdf_path: str | Path,
    table: ParsedTable,
    out_dir: str | Path,
    zoom: float = 2.0,
) -> Path:
    if not table.bbox or len(table.bbox) < 4:
        raise ValueError(f"table {table.table_id} has no bbox.")
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency-driven
        raise RuntimeError("需要安装 PyMuPDF 才能裁剪表格区域。") from exc

    target_dir = ensure_dir(out_dir)
    image_path = target_dir / f"{table.table_id}.png"
    doc = fitz.open(str(pdf_path))
    try:
        page = doc.load_page(int(table.page_no) - 1)
        page_width = float(page.rect.width)
        page_height = float(page.rect.height)
        bbox = [float(value) for value in table.bbox[:4]]
        source_width = getattr(table, "page_width", None)
        source_height = getattr(table, "page_height", None)
        try:
            source_width_value = float(source_width) if source_width else None
            source_height_value = float(source_height) if source_height else None
        except (TypeError, ValueError):
            source_width_value = None
            source_height_value = None
        if source_width_value and source_height_value:
            scale_x = page_width / source_width_value
            scale_y = page_height / source_height_value
            bbox = [bbox[0] * scale_x, bbox[1] * scale_y, bbox[2] * scale_x, bbox[3] * scale_y]
        clip = fitz.Rect(*bbox)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, alpha=False)
        pix.save(image_path)
    finally:
        doc.close()
    return image_path


def _call_vlm_table_model(
    *,
    image_path: str | Path,
    endpoint: str,
    model: str,
    api_key: str | None = None,
    request_timeout: int = 180,
    max_tokens: int = 4096,
) -> tuple[dict[str, Any], dict[str, Any]]:
    import requests

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a table recognition engine. Return strict JSON only."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TABLE_TO_JSON_PROMPT},
                    {"type": "image_url", "image_url": {"url": _image_to_data_uri(image_path)}},
                ],
            },
        ],
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    response = requests.post(endpoint, headers=headers, json=payload, timeout=request_timeout)
    response.raise_for_status()
    raw_response = response.json()
    table_model = _parse_table_model_text(_extract_response_text(raw_response))
    return table_model, raw_response


def enhance_tables_with_vlm(
    *,
    pdf_path: str | Path,
    tables: list[ParsedTable],
    out_dir: str | Path,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    request_timeout: int = 180,
    max_tokens: int = 4096,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[ParsedTable]:
    endpoint = endpoint or os.getenv("VLM_TABLE_ENDPOINT")
    model = model or os.getenv("VLM_TABLE_MODEL")
    api_key = api_key or os.getenv("VLM_TABLE_API_KEY")
    if not endpoint or not model:
        return tables

    crop_dir = ensure_dir(Path(out_dir) / "table_crops")
    enhanced: list[ParsedTable] = []
    total = len(tables)
    for index, table in enumerate(tables, start=1):
        try:
            existing_image_path = getattr(table, "table_image_path", "")
            if existing_image_path and Path(existing_image_path).exists():
                image_path = Path(existing_image_path)
            else:
                image_path = _render_table_crop(pdf_path=pdf_path, table=table, out_dir=crop_dir, zoom=2.0)
            table_model, raw_response = _call_vlm_table_model(
                image_path=image_path,
                endpoint=endpoint,
                model=model,
                api_key=api_key,
                request_timeout=request_timeout,
                max_tokens=max_tokens,
            )
            data = table.model_dump()
            data.update(
                {
                    "rows": table_model.get("rows") or table.rows,
                    "table_model": table_model,
                    "vlm_table_model": table_model,
                    "vlm_raw_response": raw_response,
                    "vlm_error": None,
                    "table_model_source": "paddleocr_vl",
                    "table_image_path": str(image_path),
                }
            )
            enhanced.append(ParsedTable(**data))
        except Exception as exc:
            data = table.model_dump()
            data.update({"vlm_error": str(exc), "table_model_source": data.get("table_model_source") or data.get("source_type")})
            enhanced.append(ParsedTable(**data))
        if progress_callback:
            progress_callback(index, total)
    return enhanced
