from __future__ import annotations

from typing import Any

from bid_knowledge.schemas.models import PageMaterialItem, ParsedTable, PdfTextBlock


def _top_from_bbox(bbox: list[float] | None) -> float:
    if not bbox or len(bbox) < 2:
        return 0.0
    return float(bbox[1])


def _ocr_texts(pp_result: dict[str, Any]) -> list[str]:
    ocr = pp_result.get("overall_ocr_res") or {}
    if not isinstance(ocr, dict):
        return []
    return [str(text) for text in (ocr.get("rec_texts") or []) if str(text).strip()]


def _ocr_scores(pp_result: dict[str, Any]) -> list[float]:
    ocr = pp_result.get("overall_ocr_res") or {}
    if not isinstance(ocr, dict):
        return []
    scores: list[float] = []
    for score in ocr.get("rec_scores") or []:
        try:
            scores.append(float(score))
        except (TypeError, ValueError):
            continue
    return scores


def build_page_material_stream(
    *,
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
) -> list[PageMaterialItem]:
    items: list[PageMaterialItem] = []

    for block in blocks:
        items.append(
            PageMaterialItem(
                item_id=block.block_id,
                item_type="text",
                source_type=block.source_type,
                page_no=block.page_no,
                top_y=_top_from_bbox(block.bbox),
                bbox=[float(value) for value in block.bbox],
                text=block.text,
                payload={
                    "block_id": block.block_id,
                    "block_no": block.block_no,
                    "font_size": block.font_size,
                    "confidence": block.confidence,
                },
            )
        )

    for table in tables:
        items.append(
            PageMaterialItem(
                item_id=table.table_id,
                item_type="table",
                source_type=table.source_type,
                page_no=table.page_no,
                top_y=_top_from_bbox(table.bbox),
                bbox=[float(value) for value in (table.bbox or [])],
                text="",
                payload={
                    "table_id": table.table_id,
                    "rows": table.rows,
                },
            )
        )

    for image in images:
        rect = [float(value) for value in (image.get("rect") or [])]
        items.append(
            PageMaterialItem(
                item_id=str(image.get("image_id") or ""),
                item_type="image",
                source_type="pdf_embedded_image",
                page_no=int(image.get("page_no") or 0),
                top_y=_top_from_bbox(rect),
                bbox=rect,
                text="",
                payload=dict(image),
            )
        )

    items = sorted(items, key=lambda item: (item.page_no, item.top_y, item.item_type))
    for index, item in enumerate(items, start=1):
        item.reading_order = index
    return items


def build_pp_structure_page_material_items(pp_result: dict[str, Any], *, page_no: int) -> list[PageMaterialItem]:
    items: list[PageMaterialItem] = []
    ocr_texts = _ocr_texts(pp_result)
    ocr_scores = _ocr_scores(pp_result)
    ocr_text = "\n".join(ocr_texts)

    for index, block in enumerate(pp_result.get("parsing_res_list") or [], start=1):
        label = str(block.get("block_label") or "")
        if label not in {"doc_title", "paragraph_title", "text"}:
            continue
        bbox = [float(value) for value in (block.get("block_bbox") or [])]
        items.append(
            PageMaterialItem(
                item_id=f"pp-text-{page_no}-{index}",
                item_type="text",
                source_type="pp_structure_text",
                page_no=page_no,
                reading_order=int(block.get("block_order") or index),
                top_y=_top_from_bbox(bbox),
                bbox=bbox,
                text=str(block.get("block_content") or ""),
                payload={
                    "layout_label": label,
                    "block_id": block.get("block_id"),
                },
            )
        )

    image_index = 0
    table_index = 0
    fallback_text_index = 0
    has_parsed_text = any(item.item_type == "text" for item in items)
    for box in (pp_result.get("layout_det_res") or {}).get("boxes") or []:
        label = str(box.get("label") or "")
        if label == "image":
            image_index += 1
            bbox = [float(value) for value in (box.get("coordinate") or [])]
            items.append(
                PageMaterialItem(
                    item_id=f"pp-image-{page_no}-{image_index}",
                    item_type="image",
                    source_type="pp_structure_image_region",
                    page_no=page_no,
                    top_y=_top_from_bbox(bbox),
                    bbox=bbox,
                    text="",
                    payload={
                        "layout_label": "image",
                        "score": box.get("score"),
                    },
                )
            )
            continue

        if label == "table":
            table_index += 1
            bbox = [float(value) for value in (box.get("coordinate") or [])]
            items.append(
                PageMaterialItem(
                    item_id=f"pp-table-{page_no}-{table_index}",
                    item_type="table",
                    source_type="pp_structure_table_region",
                    page_no=page_no,
                    top_y=_top_from_bbox(bbox),
                    bbox=bbox,
                    text="",
                    payload={
                        "layout_label": "table",
                        "score": box.get("score"),
                    },
                )
            )
            continue

        if not has_parsed_text and label in {"doc_title", "paragraph_title", "text"}:
            fallback_text_index += 1
            bbox = [float(value) for value in (box.get("coordinate") or [])]
            items.append(
                PageMaterialItem(
                    item_id=f"pp-text-region-{page_no}-{fallback_text_index}",
                    item_type="text",
                    source_type="pp_structure_text_region",
                    page_no=page_no,
                    top_y=_top_from_bbox(bbox),
                    bbox=bbox,
                    text=ocr_text,
                    payload={
                        "layout_label": label,
                        "score": box.get("score"),
                        "ocr_texts": ocr_texts,
                        "ocr_scores": ocr_scores,
                    },
                )
            )

    items = sorted(items, key=lambda item: (item.page_no, item.top_y, item.item_type))
    for index, item in enumerate(items, start=1):
        item.reading_order = index
    return items


def build_combined_page_material_stream(
    *,
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
    pp_structure_results: list[dict[str, Any]] | None = None,
) -> list[PageMaterialItem]:
    items = build_page_material_stream(blocks=blocks, tables=tables, images=images)
    for result in pp_structure_results or []:
        payload = result.get("res") if isinstance(result, dict) and isinstance(result.get("res"), dict) else result
        page_index = int((result or {}).get("page_index") or payload.get("page_index") or 0)
        page_no = int(payload.get("page_no") or (page_index + 1))
        items.extend(build_pp_structure_page_material_items(payload, page_no=page_no))
    items = sorted(items, key=lambda item: (item.page_no, item.top_y, item.item_type, item.source_type))
    for index, item in enumerate(items, start=1):
        item.reading_order = index
    return items
