from __future__ import annotations

import re
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

from bid_knowledge.matching.normalizer import normalize_section_title
from bid_knowledge.parsing.attachment_asset_exporter import sanitize_asset_name
from bid_knowledge.parsing.review_index_parser import align_business_review_index_entries, build_precise_folder_ranges, parse_business_review_index
from bid_knowledge.schemas.models import (
    CompoundInstanceMeta,
    MaterialItemRef,
    MaterialMeta,
    OrderedMaterialPackage,
    PageMaterialItem,
    ParsedTable,
    PdfTextBlock,
    ReusableCandidate,
    TitleMapping,
)
from bid_knowledge.utils.heading_utils import (
    attachment_heading_title,
    build_heading_candidates,
    find_nearest_heading,
    is_attachment_heading,
    sanitize_display_title,
)
from bid_knowledge.utils.id_utils import make_stable_id
from bid_knowledge.utils.io_utils import ensure_dir, write_json


DEFAULT_COMPOUND_MATERIAL_RULES = [
    {
        "excel_anchor_path": "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表",
        "instance_title_patterns": [r"20\d{2}.*(?:会计|财务|审计).*(?:报表|报告)"],
        "auto_detect_children": True,
        "store_unlisted_children": True,
        "child_title_exclude_patterns": [r"商务投标文件", r"国网.*公司", r"^\d+$"],
        "child_title_rename_map": {},
    }
]


def _history_candidates(candidates: list[ReusableCandidate]) -> list[ReusableCandidate]:
    return [candidate for candidate in candidates if candidate.from_history_bid]


def _section_parts(section_path: str) -> list[str]:
    parts = [part.strip() for part in str(section_path or "").split(" / ") if part.strip()]
    return parts[1:] if len(parts) > 1 else parts


def _page_numbers(candidate: ReusableCandidate) -> list[int]:
    start = candidate.source_page
    end = candidate.source_page_end or start
    if not start:
        return []
    return list(range(int(start), int(end or start) + 1))


def _sanitize_item_title(title: str, suffix: str) -> str:
    base = sanitize_asset_name(title).strip()
    base = re.sub(r"\s+", " ", base).strip()
    return f"{base}_{suffix}" if base else suffix


def _item_filename(title: str, extension: str) -> str:
    base = sanitize_asset_name(title).strip()
    base = re.sub(r"\s+", " ", base).strip() or "未命名材料"
    if len(base) <= 80:
        return f"{base}.{extension}"
    shortened = base[:48].rstrip(" _")
    digest = make_stable_id("item", base)[-8:]
    return f"{shortened}_{digest}.{extension}"


def _text_item_base_title(folder_title: str) -> str:
    title = re.sub(r"^\s*\d+(?:\.\d+)*[、.．]\s*", "", folder_title or "").strip()
    title = re.sub(r"^\s*[（(]?\d+(?:\.\d+)*[）)]?[、.．]?\s*", "", title).strip()
    return sanitize_asset_name(title).strip() or sanitize_asset_name(folder_title).strip() or "未命名文字材料"


def _block_top_y(block: PdfTextBlock) -> float | None:
    return float(block.bbox[1]) if block.bbox and len(block.bbox) >= 2 else None


def _block_bottom_y(block: PdfTextBlock) -> float | None:
    return float(block.bbox[3]) if block.bbox and len(block.bbox) >= 4 else None


def _text_signature(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _looks_like_page_margin_text(text: str, bbox: list[float] | None) -> bool:
    signature = _text_signature(text)
    if not signature:
        return False
    top = float(bbox[1]) if bbox and len(bbox) >= 2 else 0.0
    bottom = float(bbox[3]) if bbox and len(bbox) >= 4 else top
    if "商务投标文件" in signature and top <= 120:
        return True
    if re.fullmatch(r"\d+", signature) and (top <= 80 or bottom >= 760):
        return True
    return top <= 70 or bottom >= 760


def _decorative_text_signatures(blocks: list[PdfTextBlock]) -> set[str]:
    pages_by_signature: dict[str, set[int]] = defaultdict(set)
    for block in blocks:
        signature = _text_signature(block.text)
        if not signature or not _looks_like_page_margin_text(block.text, block.bbox):
            continue
        pages_by_signature[signature].add(block.page_no)
    return {signature for signature, pages in pages_by_signature.items() if len(pages) >= 2 or "商务投标文件" in signature}


def _is_decorative_text_block(block: PdfTextBlock, signatures: set[str]) -> bool:
    signature = _text_signature(block.text)
    return bool(signature and signature in signatures and _looks_like_page_margin_text(block.text, block.bbox))


def _is_decorative_page_material_text(item: dict[str, Any], signatures: set[str]) -> bool:
    if str(item.get("item_type") or item.get("type") or "") != "text":
        return False
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    layout_label = str(payload.get("layout_label") or "")
    if layout_label in {"header", "header_image", "footer", "footer_image", "number", "footnote"}:
        return True
    text = str(item.get("text") or "")
    bbox = item.get("bbox") or []
    signature = _text_signature(text)
    return bool(signature and signature in signatures and _looks_like_page_margin_text(text, bbox))


def _is_bid_package_context_title(title: str) -> bool:
    signature = _text_signature(title)
    if not signature:
        return False
    return any(keyword in signature for keyword in ("包号", "包名称", "商务投标文件", "测控及在线监测系统"))


def _fallback_context_title(
    *,
    nearest: dict[str, Any] | None,
    section_candidates: list[ReusableCandidate],
    page_no: int,
    path_parts: list[str],
    default_title: str,
) -> str:
    if nearest:
        title = str(nearest.get("title") or nearest.get("raw_title") or "").strip()
        if title and not _is_bid_package_context_title(title):
            return title
    container_title = _container_title_for_page(section_candidates, page_no)
    if container_title and not _is_bid_package_context_title(container_title):
        return container_title
    if path_parts:
        return path_parts[-1]
    return default_title


def _attachment_match_key(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", sanitize_display_title(attachment_heading_title(text))).lower()


def _is_authorization_attachment_leaf(section_path: str) -> bool:
    parts = _section_parts(section_path)
    if len(parts) < 2:
        return False
    return parts[0] == "法定代表人授权委托书" and any(keyword in parts[-1] for keyword in ("身份证", "扫描件", "有效身份证件"))


def _is_identity_card_like_image(image: dict[str, Any]) -> bool:
    rect = image.get("rect") or [0, 0, 0, 0]
    if len(rect) < 4:
        return False
    rect_width = abs(float(rect[2]) - float(rect[0]))
    rect_height = abs(float(rect[3]) - float(rect[1]))
    rect_area = rect_width * rect_height
    intrinsic_width = int(image.get("width") or 0)
    intrinsic_height = int(image.get("height") or 0)
    intrinsic_area = intrinsic_width * intrinsic_height
    if rect_width < 120 or rect_height < 70 or rect_area < 15000:
        return False
    if intrinsic_width and intrinsic_height and intrinsic_area < 120000:
        return False
    ratio = rect_width / rect_height if rect_height else 0.0
    return 1.2 <= ratio <= 8.0


def _limit_authorization_identity_images(section_path: str, images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not _is_authorization_attachment_leaf(section_path):
        return images
    return [image for image in sorted(images, key=_image_sort_key) if _is_identity_card_like_image(image)][:2]


def _attachment_scope_for_section(section_path: str, blocks: list[PdfTextBlock]) -> dict[str, Any] | None:
    if not _is_authorization_attachment_leaf(section_path):
        return None
    target = _attachment_match_key(_section_parts(section_path)[-1])
    anchors = _attachment_anchor_blocks(blocks)
    for index, anchor in enumerate(anchors):
        anchor_key = _attachment_match_key(anchor.text)
        if not anchor_key or not target:
            continue
        if anchor_key != target and anchor_key not in target and target not in anchor_key:
            continue
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else None
        return {
            "start_page": anchor.page_no,
            "start_y": _block_top_y(anchor),
            "end_page": next_anchor.page_no if next_anchor else max([block.page_no for block in blocks], default=anchor.page_no),
            "end_y": _block_top_y(next_anchor) if next_anchor else None,
            "start_block_id": anchor.block_id,
            "end_block_id": next_anchor.block_id if next_anchor else None,
        }
    return None


def _text_content_from_blocks(blocks: list[PdfTextBlock]) -> str:
    return "\n\n".join(block.text.strip() for block in blocks if block.source_type != "ocr" and block.text and block.text.strip()).strip()


def _write_text_item(
    item_dir: Path,
    folder_title: str,
    text_blocks: list[PdfTextBlock],
    section_path: str,
    path_parts: list[str],
    pdf_path: str | Path | None,
) -> dict[str, Any] | None:
    content = _text_content_from_blocks(text_blocks)
    if not content:
        return None

    title = _text_item_base_title(folder_title)
    pages = sorted({block.page_no for block in text_blocks})
    json_path = item_dir / _item_filename(title, "json")
    md_path = item_dir / _item_filename(title, "md")
    item = {
        "item_type": "text",
        "text_item_title": title,
        "source_title": folder_title,
        "section_path": section_path,
        "folder_parts": path_parts,
        "page_start": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None,
        "content": content,
        "blocks": [_block_dict(block) for block in text_blocks],
        "source_block_ids": [block.block_id for block in text_blocks],
        "source_file": str(pdf_path or ""),
        "review_status": "pending",
        "json_path": str(json_path),
        "md_path": str(md_path),
    }
    write_json(json_path, item)
    md = f"# {title}\n\n来源标题：{folder_title}\n\n来源页码：{pages[0]}-{pages[-1]}\n\n{content}\n"
    md_path.write_text(md, encoding="utf-8")
    return item


def _write_original_capture(
    original_dir: Path,
    doc: Any,
    page_start: int,
    page_end: int,
) -> dict[str, Any]:
    ensure_dir(original_dir)
    if doc is None:
        status = {
            "available": False,
            "reason": "PyMuPDF is unavailable or source PDF was not provided.",
            "source_pages_pdf": None,
            "source_preview_png": None,
        }
        write_json(original_dir / "source_capture_status.json", status)
        return status

    start_index = max(0, int(page_start) - 1)
    end_index = min(int(page_end) - 1, int(doc.page_count) - 1)
    if start_index > end_index:
        status = {
            "available": False,
            "reason": f"Page range {page_start}-{page_end} is outside source PDF page count {doc.page_count}.",
            "source_pages_pdf": None,
            "source_preview_png": None,
        }
        write_json(original_dir / "source_capture_status.json", status)
        return status

    import fitz

    source_pdf = original_dir / "source_pages.pdf"
    preview_png = original_dir / "source_preview.png"
    subset = fitz.open()
    try:
        subset.insert_pdf(doc, from_page=start_index, to_page=end_index)
        subset.save(source_pdf)
    finally:
        subset.close()

    page = doc.load_page(start_index)
    pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
    pix.save(preview_png)
    status = {
        "available": True,
        "source_pages_pdf": str(source_pdf),
        "source_preview_png": str(preview_png),
    }
    write_json(original_dir / "source_capture_status.json", status)
    return status


def _ordered_material_items(
    material_dir: Path,
    material_path: str,
    rule_section_path: str,
    nearest_heading: str,
    text_blocks: list[PdfTextBlock],
    text_item: dict[str, Any] | None,
    table_items: list[dict[str, Any]],
    image_items: list[dict[str, Any]],
    submaterial_items: list[dict[str, Any]] | None = None,
    page_material_items: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    ordered: list[dict[str, Any]] = []
    decorative_text = _decorative_text_signatures(text_blocks)
    heading_candidates = build_heading_candidates([_block_dict(block) for block in text_blocks if not _is_decorative_text_block(block, decorative_text)])
    table_regions = _table_regions_by_page(table_items)
    for block in text_blocks:
        if _is_decorative_text_block(block, decorative_text):
            continue
        if block.source_type == "ocr":
            continue
        if _block_inside_any_table(block, table_regions):
            continue
        ordered.append(
            MaterialItemRef(
                type="text",
                item_type="text",
                item_id=block.block_id,
                page_no=block.page_no,
                top_y=_block_top_y(block) or 0.0,
                block_id=block.block_id,
                text=block.text,
                bbox=block.bbox,
                nearest_heading=nearest_heading,
                rule_section_path=rule_section_path,
                material_path=material_path,
                source_type=block.source_type,
                payload_ref=str(Path(text_item["json_path"]).relative_to(material_dir)) if text_item and text_item.get("json_path") else None,
            ).model_dump(exclude_none=True)
        )
    for table in table_items:
        ordered.append(
            MaterialItemRef(
                type="table",
                item_type="table",
                item_id=str(table.get("table_id") or ""),
                page_no=table.get("page_no"),
                top_y=table.get("_top_y", 0.0),
                table_id=table.get("table_id"),
                table_title=table.get("table_title"),
                json_path=table.get("json_path"),
                bbox=table.get("bbox"),
                nearest_heading=nearest_heading,
                rule_section_path=rule_section_path,
                material_path=material_path,
                payload_ref=str(Path(table["json_path"]).relative_to(material_dir)) if table.get("json_path") else None,
            ).model_dump(exclude_none=True)
        )
    for image in image_items:
        ordered.append(
            MaterialItemRef(
                type="image",
                item_type="image",
                item_id=str(image.get("image_id") or ""),
                page_no=image.get("page_no"),
                top_y=image.get("_top_y", 0.0),
                image_id=image.get("image_id"),
                image_title=image.get("image_title"),
                file_path=image.get("file_path"),
                json_path=image.get("json_path"),
                rect=image.get("rect"),
                nearest_heading=nearest_heading,
                rule_section_path=rule_section_path,
                material_path=material_path,
                payload_ref=str(Path(image["json_path"]).relative_to(material_dir)) if image.get("json_path") else None,
            ).model_dump(exclude_none=True)
        )
    for submaterial in submaterial_items or []:
        ordered.append(
            MaterialItemRef(
                type="submaterial",
                item_type="submaterial",
                item_id=str(submaterial.get("item_id") or ""),
                page_no=submaterial.get("page_no"),
                top_y=submaterial.get("top_y", 0.0),
                nearest_heading=submaterial.get("nearest_heading", ""),
                rule_section_path=submaterial.get("rule_section_path", rule_section_path),
                material_path=submaterial.get("material_path", material_path),
                payload_ref=submaterial.get("payload_ref"),
            ).model_dump(exclude_none=True)
        )
    for stream_item in page_material_items or []:
        item_type = str(stream_item.get("item_type") or stream_item.get("type") or "")
        if item_type not in {"text", "table", "image"}:
            continue
        if _is_decorative_page_material_text(stream_item, decorative_text):
            continue
        bbox = stream_item.get("bbox") or []
        top_y = float(stream_item.get("top_y") or (bbox[1] if len(bbox) >= 2 else 0.0))
        page_no = int(stream_item.get("page_no") or 0)
        nearest = find_nearest_heading(heading_candidates, page_no, top_y)
        stream_heading = nearest_heading
        if nearest:
            raw_title = str(nearest.get("raw_title") or "")
            stream_heading = raw_title if raw_title.strip().startswith("附") else str(nearest.get("title") or raw_title)
        ordered.append(
            MaterialItemRef(
                type=item_type,
                item_type=item_type,
                item_id=str(stream_item.get("item_id") or ""),
                page_no=stream_item.get("page_no"),
                top_y=top_y,
                bbox=bbox if item_type != "image" else None,
                rect=bbox if item_type == "image" else None,
                text=stream_item.get("text") if item_type == "text" else None,
                image_title=stream_item.get("image_title") if item_type == "image" else None,
                file_path=stream_item.get("file_path") if item_type == "image" else None,
                json_path=stream_item.get("json_path"),
                nearest_heading=stream_heading,
                rule_section_path=rule_section_path,
                material_path=material_path,
                payload_ref=str(Path(stream_item["json_path"]).relative_to(material_dir)) if stream_item.get("json_path") else stream_item.get("payload_ref"),
                source_type=stream_item.get("source_type"),
                payload=stream_item.get("payload") or {},
            ).model_dump(exclude_none=True)
        )
    sorted_items = sorted(ordered, key=lambda item: (int(item.get("page_no") or 0), float(item.get("top_y") or 0.0), item["type"]))
    for index, item in enumerate(sorted_items, start=1):
        item["order"] = index
    return sorted_items


def _table_regions_by_page(table_items: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for table in table_items:
        page_no = int(table.get("page_no") or 0)
        bbox = table.get("bbox")
        if page_no and isinstance(bbox, list) and len(bbox) >= 4:
            grouped[page_no].append(
                {
                    "bbox": [float(value) for value in bbox[:4]],
                    "cell_signatures": _table_cell_signatures(table.get("rows") or []),
                }
            )
    return grouped


def _table_cell_signatures(rows: list[list[Any]]) -> set[str]:
    signatures: set[str] = set()
    for row in rows:
        if not isinstance(row, list):
            continue
        for cell in row:
            signature = _text_signature(str(cell or ""))
            if signature:
                signatures.add(signature)
    return signatures


def _block_text_matches_table_cell(block_text: str, cell_signatures: set[str]) -> bool:
    signature = _text_signature(block_text)
    if not signature:
        return False
    return any(signature == cell or signature in cell or cell in signature for cell in cell_signatures)


def _block_inside_any_table(block: PdfTextBlock, table_regions: dict[int, list[dict[str, Any]]]) -> bool:
    if not block.bbox or len(block.bbox) < 4:
        return False
    block_bbox = [float(value) for value in block.bbox[:4]]
    x0, y0, x1, y1 = block_bbox
    center_x = (x0 + x1) / 2
    center_y = (y0 + y1) / 2
    for region in table_regions.get(int(block.page_no), []):
        tx0, ty0, tx1, ty1 = region["bbox"]
        inside_by_center = tx0 <= center_x <= tx1 and ty0 <= center_y <= ty1
        inside_by_overlap = _bbox_overlap_ratio(block_bbox, region["bbox"]) >= 0.15
        if (inside_by_center or inside_by_overlap) and _block_text_matches_table_cell(block.text, region["cell_signatures"]):
            return True
    return False


def _bbox_overlap_ratio(bbox: list[float], other: list[float]) -> float:
    if len(bbox) < 4 or len(other) < 4:
        return 0.0
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
    return intersection / area


def _material_path(parts: list[str]) -> str:
    return " / ".join(["商务文件", *parts])


def _material_types(*, text_item: dict[str, Any] | None, table_items: list[dict[str, Any]], image_items: list[dict[str, Any]]) -> list[str]:
    kinds: list[str] = []
    if text_item:
        kinds.append("text")
    if table_items:
        kinds.append("table")
    if image_items:
        kinds.append("image")
    return kinds


def _merge_material_types(base_types: list[str], page_material_items: list[dict[str, Any]] | None) -> list[str]:
    kinds = list(base_types)
    for item in page_material_items or []:
        item_type = str(item.get("item_type") or "")
        if item_type in {"text", "table", "image"} and item_type not in kinds:
            kinds.append(item_type)
    return kinds


def _dominant_material_type(material_types: list[str]) -> str:
    if not material_types:
        return "unknown"
    if len(material_types) == 1:
        return material_types[0]
    return "mixed"


def _relative_markdown_path(material_dir: Path, path_value: str | None) -> str:
    if not path_value:
        return ""
    path = Path(path_value)
    try:
        return str(path.relative_to(material_dir))
    except ValueError:
        return str(path)


def _render_table_markdown(rows: list[list[Any]]) -> str:
    if not rows:
        return ""
    normalized = [[_escape_markdown_table_cell(str(cell or "")) for cell in row] for row in rows]
    width = max(len(row) for row in normalized)
    padded = [row + [""] * (width - len(row)) for row in normalized]
    header = padded[0]
    body = padded[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def _should_inline_table_markdown(rows: list[list[Any]]) -> bool:
    if not rows:
        return False
    width = max((len(row) for row in rows if isinstance(row, list)), default=0)
    if width == 0:
        return False
    cells = [str(cell or "").strip() for row in rows if isinstance(row, list) for cell in row if str(cell or "").strip()]
    if not cells:
        return False
    average_len = sum(len(cell) for cell in cells) / len(cells)
    short_ratio = sum(1 for cell in cells if len(cell) <= 1) / len(cells)
    if width >= 6 and (average_len <= 1.6 or short_ratio >= 0.65):
        return False
    return True


def _escape_markdown_table_cell(value: str) -> str:
    return value.replace("\n", "<br>").replace("|", "\\|").strip()


def _load_json_if_exists(material_dir: Path, relative_path: str | None) -> dict[str, Any]:
    if not relative_path:
        return {}
    path = material_dir / relative_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _is_ocr_derived_material_text(item: dict[str, Any]) -> bool:
    source_type = str(item.get("source_type") or "")
    if source_type == "ocr":
        return True
    if source_type.startswith("pp_structure_text"):
        return True
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    return bool(payload.get("ocr_texts"))


def _is_field_label_text(text: str) -> bool:
    stripped = str(text or "").strip()
    return bool(stripped and len(stripped) <= 40 and re.search(r"[：:]\s*$", stripped))


def _clean_field_label(text: str) -> str:
    return re.sub(r"[：:]\s*$", "", str(text or "").strip()).strip()


def _flush_text_markdown_lines(buffer: list[dict[str, Any]], seen_texts: set[str]) -> list[str]:
    lines: list[str] = []
    index = 0
    while index < len(buffer):
        pairs: list[list[str]] = []
        cursor = index
        while cursor + 1 < len(buffer):
            label = str(buffer[cursor].get("text") or "").strip()
            value = str(buffer[cursor + 1].get("text") or "").strip()
            if not _is_field_label_text(label) or _is_field_label_text(value) or not value:
                break
            pairs.append([_clean_field_label(label), value])
            cursor += 2
        if len(pairs) >= 2:
            lines.extend([_render_table_markdown([["字段", "内容"], *pairs]), ""])
            for label, value in pairs:
                seen_texts.add(re.sub(r"\s+", "", label))
                seen_texts.add(re.sub(r"\s+", "", value))
            index = cursor
            continue

        text = str(buffer[index].get("text") or "").strip()
        text_key = re.sub(r"\s+", "", text)
        if text and text_key not in seen_texts:
            seen_texts.add(text_key)
            lines.extend([text, ""])
        index += 1
    return lines


def _write_material_markdown(material_dir: Path, material_title: str, ordered_items: list[dict[str, Any]]) -> Path:
    lines: list[str] = []
    has_non_image = any(
        str(item.get("item_type") or item.get("type") or "") not in {"image", "text"}
        or (
            str(item.get("item_type") or item.get("type") or "") == "text"
            and not _is_ocr_derived_material_text(item)
        )
        for item in ordered_items
    )
    if has_non_image:
        lines.extend([f"# {material_title}", ""])

    seen_texts: set[str] = set()
    text_buffer: list[dict[str, Any]] = []
    for item in ordered_items:
        item_type = str(item.get("item_type") or item.get("type") or "")
        if item_type == "text":
            if _is_ocr_derived_material_text(item):
                continue
            text_buffer.append(item)
        elif item_type == "image":
            lines.extend(_flush_text_markdown_lines(text_buffer, seen_texts))
            text_buffer = []
            image_path = _relative_markdown_path(material_dir, item.get("file_path"))
            title = str(item.get("image_title") or item.get("nearest_heading") or item.get("image_id") or "图片").strip()
            if image_path:
                lines.extend([f"![{title}]({image_path})", ""])
        elif item_type == "table":
            lines.extend(_flush_text_markdown_lines(text_buffer, seen_texts))
            text_buffer = []
            payload_ref = item.get("payload_ref")
            if payload_ref:
                title = str(item.get("table_title") or item.get("nearest_heading") or item.get("table_id") or "表格").strip()
                table_data = _load_json_if_exists(material_dir, str(payload_ref))
                rows = table_data.get("rows") if isinstance(table_data.get("rows"), list) else []
                table_markdown = _render_table_markdown(rows) if _should_inline_table_markdown(rows) else ""
                if table_markdown:
                    lines.extend([table_markdown, ""])
                else:
                    lines.extend([f"[表格：{title}]({payload_ref})", ""])
        elif item_type == "submaterial" and item.get("payload_ref"):
            lines.extend(_flush_text_markdown_lines(text_buffer, seen_texts))
            text_buffer = []
            sub_md = str(item["payload_ref"]).replace("ordered_material.json", "material.md")
            title = str(item.get("nearest_heading") or item.get("material_path") or "子材料").strip()
            lines.extend([f"[{title}]({sub_md})", ""])
    lines.extend(_flush_text_markdown_lines(text_buffer, seen_texts))

    markdown_path = material_dir / "material.md"
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return markdown_path


def _write_material_index_markdown(
    material_dir: Path,
    title: str,
    entries: list[tuple[str, Path]],
) -> Path:
    lines = [f"# {title}", ""]
    if entries:
        for entry_title, target_path in entries:
            lines.append(f"- [{entry_title}]({_relative_markdown_path(material_dir, target_path)})")
    else:
        lines.append("暂无可直接复用内容。")

    markdown_path = material_dir / "material.md"
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return markdown_path


def _backfill_missing_material_indexes(root_dir: Path) -> None:
    skip_names = {"text_items", "table_items", "image_items", "original"}
    directories = sorted(
        [path for path in root_dir.rglob("*") if path.is_dir() and path.name not in skip_names],
        key=lambda path: len(path.parts),
        reverse=True,
    )
    for directory in directories:
        child_entries = [
            (child.name, child / "material.md")
            for child in sorted(directory.iterdir(), key=lambda item: item.name)
            if child.is_dir() and (child / "material.md").exists()
        ]
        if (directory / "material.md").exists():
            _append_child_links_to_markdown(directory, child_entries)
            continue
        has_metadata = any(
            (directory / filename).exists()
            for filename in ("module_meta.json", "section_meta.json", "compound_instance_meta.json", "compound_materials_manifest.json")
        )
        if child_entries or has_metadata:
            _write_material_index_markdown(directory, directory.name, child_entries)


def _write_material_package(
    material_dir: Path,
    subfolder: dict[str, Any],
    section_path: str,
    path_parts: list[str],
    pdf_path: str | Path | None,
    doc: Any,
    text_blocks: list[PdfTextBlock],
    text_item: dict[str, Any] | None,
    table_items: list[dict[str, Any]],
    image_items: list[dict[str, Any]],
    page_material_items: list[dict[str, Any]] | None = None,
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None = None,
    allow_submaterials: bool = True,
    image_only: bool = False,
) -> dict[str, Any]:
    page_start = int(subfolder["page_start"])
    page_end = int(subfolder["page_end"])
    original_status = _write_original_capture(material_dir / "original", doc, page_start, page_end)
    material_path = _material_path(path_parts + [subfolder["folder_title"]])
    raw_context_title = text_blocks[0].text if text_blocks else subfolder["folder_title"]
    if image_only:
        text_item = None
        table_items = []
        page_material_items = [item for item in page_material_items or [] if str(item.get("item_type") or item.get("type") or "") == "image"]
    if image_items:
        page_material_items = [
            item
            for item in page_material_items or []
            if str(item.get("item_type") or item.get("type") or "") != "image"
        ]
    submaterial_items = (
        _write_attachment_submaterials(
            material_dir=material_dir,
            section_path=section_path,
            path_parts=path_parts + [subfolder["folder_title"]],
            pdf_path=pdf_path,
            doc=doc,
            text_blocks=text_blocks,
            table_items=table_items,
            image_items=image_items,
            page_material_items=page_material_items or [],
            image_bytes_resolver=image_bytes_resolver,
        )
        if allow_submaterials
        else []
    )
    submaterial_ranges = _submaterial_ranges(submaterial_items)
    if submaterial_ranges:
        text_blocks = [
            block
            for block in text_blocks
            if not _item_in_submaterial_ranges(block.page_no, _block_top_y(block), submaterial_ranges)
        ]
        table_items = [
            table
            for table in table_items
            if not _item_in_submaterial_ranges(
                int(table.get("page_no") or 0),
                float(table.get("_top_y") or 0.0),
                submaterial_ranges,
            )
        ]
        image_items = [
            image
            for image in image_items
            if not _item_in_submaterial_ranges(
                int(image.get("page_no") or 0),
                float(image.get("_top_y") or 0.0),
                submaterial_ranges,
            )
        ]
        page_material_items = [
            item
            for item in page_material_items or []
            if not _item_in_submaterial_ranges(
                int(item.get("page_no") or 0),
                float(item.get("top_y") or 0.0),
                submaterial_ranges,
            )
        ]
    page_material_items = _export_page_material_image_regions(
        material_dir=material_dir,
        section_path=section_path,
        material_path=material_path,
        nearest_heading=raw_context_title,
        text_blocks=text_blocks,
        page_material_items=page_material_items or [],
        doc=doc,
    )
    ordered_text_blocks = [] if image_only else text_blocks
    material_types = _merge_material_types(
        _material_types(text_item=text_item, table_items=table_items, image_items=image_items),
        page_material_items,
    )
    dominant_material_type = _dominant_material_type(material_types)
    ordered = OrderedMaterialPackage(
        material_title=subfolder["folder_title"],
        section_path=section_path,
        material_path=material_path,
        rule_section_path=section_path,
        material_types=material_types,
        dominant_material_type=dominant_material_type,
        items=[
            MaterialItemRef(**item)
            for item in _ordered_material_items(
                material_dir=material_dir,
                material_path=material_path,
                rule_section_path=section_path,
                nearest_heading=raw_context_title,
                text_blocks=ordered_text_blocks,
                text_item=text_item,
                table_items=table_items,
                image_items=image_items,
                submaterial_items=submaterial_items,
                page_material_items=page_material_items or [],
            )
        ],
    )
    write_json(material_dir / "ordered_material.json", ordered)
    markdown_path = _write_material_markdown(material_dir, subfolder["folder_title"], [item.model_dump(exclude_none=True) for item in ordered.items])
    meta = MaterialMeta(
        material_title=subfolder["folder_title"],
        section_path=section_path,
        material_path=material_path,
        rule_section_path=section_path,
        rule_module_name=path_parts[0] if path_parts else "",
        folder_parts=path_parts + [subfolder["folder_title"]],
        source_file=str(pdf_path or ""),
        source_page_start=page_start,
        source_page_end=page_end,
        source_start_y=subfolder.get("start_y"),
        source_end_y=subfolder.get("end_y"),
        source_start_block_id=subfolder.get("start_block_id"),
        source_end_block_id=subfolder.get("end_block_id"),
        original_capture=original_status,
        material_types=material_types,
        dominant_material_type=dominant_material_type,
        raw_context_title=raw_context_title,
        title_mapping=TitleMapping(
            raw_context_title=raw_context_title,
            normalized_context_title=sanitize_display_title(raw_context_title),
            material_title=subfolder["folder_title"],
            rule_section_path=section_path,
        ),
        text_item_count=1 if text_item else 0,
        table_item_count=len(table_items),
        image_item_count=len(image_items),
        ordered_item_count=len(ordered.items),
        material_markdown_path=str(markdown_path.relative_to(material_dir)),
        review_status="pending",
    )
    write_json(material_dir / "material_meta.json", meta)
    return meta.model_dump()


def _attachment_anchor_blocks(text_blocks: list[PdfTextBlock]) -> list[PdfTextBlock]:
    return [
        block
        for block in sorted(text_blocks, key=lambda item: (item.page_no, _block_top_y(item) or 0.0, item.block_no))
        if is_attachment_heading(block.text)
    ]


def _unique_submaterial_dir(base_dir: Path, title: str) -> tuple[Path, str]:
    base_name = _safe_dirname(title)
    candidate = base_dir / base_name
    if not candidate.exists():
        return candidate, base_name
    suffix = 2
    while True:
        name = f"{base_name}_{suffix}"
        candidate = base_dir / name
        if not candidate.exists():
            return candidate, name
        suffix += 1


def _copy_table_item_for_submaterial(
    table: dict[str, Any],
    child_dir: Path,
    child_title: str,
    section_path: str,
    folder_parts: list[str],
    pdf_path: str | Path | None,
    table_index: int,
) -> dict[str, Any]:
    table_title = _sanitize_item_title(child_title, f"表{table_index}")
    item_dir = ensure_dir(child_dir / "table_items")
    json_path = item_dir / _item_filename(table_title, "json")
    item = {
        **{key: value for key, value in table.items() if not str(key).startswith("_")},
        "section_path": section_path,
        "folder_parts": folder_parts,
        "table_title": table_title,
        "context_title": child_title,
        "parent_section_title": table.get("parent_section_title") or child_title,
        "source_file": str(pdf_path or ""),
        "review_status": "pending",
        "json_path": str(json_path),
        "_top_y": float(table.get("_top_y") or 0.0),
    }
    write_json(json_path, item)
    return item


def _copy_image_item_for_submaterial(
    image: dict[str, Any],
    child_dir: Path,
    child_title: str,
    section_path: str,
    folder_parts: list[str],
    pdf_path: str | Path | None,
    image_index: int,
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None,
    doc: Any,
) -> dict[str, Any]:
    image_title = _sanitize_item_title(child_title, f"图{image_index}")
    item_dir = ensure_dir(child_dir / "image_items")
    image_bytes, ext = _resolve_image_bytes(image, image_bytes_resolver, doc)
    image_path = item_dir / _item_filename(image_title, ext)
    if image_bytes is not None:
        image_path.write_bytes(image_bytes)
    json_path = item_dir / _item_filename(image_title, "json")
    item = {
        **{key: value for key, value in image.items() if not str(key).startswith("_")},
        "section_path": section_path,
        "folder_parts": folder_parts,
        "image_title": image_title,
        "context_title": child_title,
        "parent_section_title": image.get("parent_section_title") or child_title,
        "source_file": str(pdf_path or ""),
        "review_status": "pending",
        "file_path": str(image_path),
        "json_path": str(json_path),
        "_top_y": float(image.get("_top_y") or 0.0),
    }
    write_json(json_path, item)
    return item


def _write_attachment_submaterials(
    material_dir: Path,
    section_path: str,
    path_parts: list[str],
    pdf_path: str | Path | None,
    doc: Any,
    text_blocks: list[PdfTextBlock],
    table_items: list[dict[str, Any]],
    image_items: list[dict[str, Any]],
    page_material_items: list[dict[str, Any]] | None = None,
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None = None,
) -> list[dict[str, Any]]:
    anchors = _attachment_anchor_blocks(text_blocks)
    if not anchors:
        return []

    submaterials_dir = ensure_dir(material_dir / "submaterials")
    references: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        next_anchor = anchors[index + 1] if index + 1 < len(anchors) else None
        start_page = anchor.page_no
        start_y = _block_top_y(anchor)
        end_page = next_anchor.page_no if next_anchor else max([block.page_no for block in text_blocks], default=start_page)
        end_y = _block_top_y(next_anchor) if next_anchor else None
        child_title = attachment_heading_title(anchor.text)
        child_dir, _child_dir_name = _unique_submaterial_dir(submaterials_dir, child_title)
        child_dir = ensure_dir(child_dir)

        child_blocks = [
            block
            for block in text_blocks
            if _item_in_range(block.page_no, _block_top_y(block), start_page, start_y, end_page, end_y)
        ]
        child_tables = [
            table
            for table in table_items
            if _item_in_range(
                int(table.get("page_no") or 0),
                float(table.get("_top_y") or 0.0),
                start_page,
                start_y,
                end_page,
                end_y,
            )
        ]
        child_images = [
            image
            for image in image_items
            if _item_in_range(
                int(image.get("page_no") or 0),
                float(image.get("_top_y") or 0.0),
                start_page,
                start_y,
                end_page,
                end_y,
            )
        ]
        child_page_material_items = [
            item
            for item in page_material_items or []
            if _item_in_range(
                int(item.get("page_no") or 0),
                float(item.get("top_y") or 0.0),
                start_page,
                start_y,
                end_page,
                end_y,
            )
        ]

        child_text_item = _write_text_item(
            item_dir=ensure_dir(child_dir / "text_items"),
            folder_title=child_title,
            text_blocks=child_blocks,
            section_path=section_path,
            path_parts=path_parts + [child_title],
            pdf_path=pdf_path,
        )
        copied_tables = [
            _copy_table_item_for_submaterial(
                table=table,
                child_dir=child_dir,
                child_title=child_title,
                section_path=section_path,
                folder_parts=path_parts + [child_title],
                pdf_path=pdf_path,
                table_index=table_index,
            )
            for table_index, table in enumerate(child_tables, start=1)
        ]
        copied_images = [
            _copy_image_item_for_submaterial(
                image=image,
                child_dir=child_dir,
                child_title=child_title,
                section_path=section_path,
                folder_parts=path_parts + [child_title],
                pdf_path=pdf_path,
                image_index=image_index,
                image_bytes_resolver=image_bytes_resolver,
                doc=doc,
            )
            for image_index, image in enumerate(child_images, start=1)
        ]
        _write_material_package(
            material_dir=child_dir,
            subfolder={
                "folder_title": child_title,
                "page_start": start_page,
                "page_end": end_page,
                "start_y": start_y,
                "end_y": end_y,
                "start_block_id": anchor.block_id,
                "end_block_id": next_anchor.block_id if next_anchor else None,
            },
            section_path=section_path,
            path_parts=path_parts,
            pdf_path=pdf_path,
            doc=doc,
            text_blocks=child_blocks,
            text_item=child_text_item,
            table_items=copied_tables,
            image_items=copied_images,
            page_material_items=child_page_material_items,
            image_bytes_resolver=image_bytes_resolver,
            allow_submaterials=False,
        )
        references.append(
            {
                "item_id": make_stable_id("submaterial", f"{section_path}:{anchor.block_id}:{child_title}"),
                "page_no": anchor.page_no,
                "top_y": start_y or 0.0,
                "start_page": start_page,
                "start_y": start_y,
                "end_page": end_page,
                "end_y": end_y,
                "nearest_heading": anchor.text,
                "rule_section_path": section_path,
                "material_path": _material_path(path_parts + [child_title]),
                "payload_ref": str((child_dir / "ordered_material.json").relative_to(material_dir)),
            }
        )
    return references


def _submaterial_ranges(submaterial_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranges: list[dict[str, Any]] = []
    for item in submaterial_items:
        if item.get("start_page") and item.get("end_page"):
            ranges.append(
                {
                    "start_page": int(item["start_page"]),
                    "start_y": item.get("start_y"),
                    "end_page": int(item["end_page"]),
                    "end_y": item.get("end_y"),
                }
            )
    return ranges


def _item_in_submaterial_ranges(page_no: int, top_y: float | None, ranges: list[dict[str, Any]]) -> bool:
    return any(
        _item_in_range(
            page_no,
            top_y,
            int(item["start_page"]),
            item.get("start_y"),
            int(item["end_page"]),
            item.get("end_y"),
        )
        for item in ranges
    )


def _safe_dirname(raw: str) -> str:
    base = sanitize_asset_name(raw).strip() or "未命名层级"
    base = re.sub(r"\s+", " ", base).strip()
    if len(base) <= 60:
        return base
    return f"{base[:36].rstrip(' _')}_{make_stable_id('dir', raw)[-8:]}"


def _is_under_section_path(section_path: str, anchor_path: str) -> bool:
    return section_path == anchor_path or section_path.startswith(f"{anchor_path} / ")


def _text_matches_any_pattern(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text or "") for pattern in patterns or [])


def _normalize_compound_rules(rules: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    source_rules = rules if rules is not None else DEFAULT_COMPOUND_MATERIAL_RULES
    normalized: list[dict[str, Any]] = []
    for rule in source_rules:
        anchor = str(rule.get("excel_anchor_path") or "").strip()
        patterns = [str(item) for item in rule.get("instance_title_patterns") or [] if str(item).strip()]
        if not anchor or not patterns:
            continue
        normalized.append(
            {
                **rule,
                "excel_anchor_path": anchor,
                "instance_title_patterns": patterns,
                "auto_detect_children": bool(rule.get("auto_detect_children", True)),
                "store_unlisted_children": bool(rule.get("store_unlisted_children", True)),
                "child_title_include_patterns": [str(item) for item in rule.get("child_title_include_patterns") or []],
                "child_title_exclude_patterns": [str(item) for item in rule.get("child_title_exclude_patterns") or []],
                "child_title_rename_map": dict(rule.get("child_title_rename_map") or {}),
            }
        )
    return normalized


def _position_key(page_no: int, top_y: float | None) -> tuple[int, float]:
    return int(page_no), float(top_y or 0.0)


def _item_in_range(
    page_no: int,
    top_y: float | None,
    start_page: int,
    start_y: float | None,
    end_page: int,
    end_y: float | None,
) -> bool:
    current = _position_key(page_no, top_y)
    start = _position_key(start_page, start_y)
    end = _position_key(end_page, end_y) if end_y is not None else (int(end_page), float("inf"))
    return start <= current < end


def _is_compound_child_title(block: PdfTextBlock, rule: dict[str, Any]) -> bool:
    text = re.sub(r"\s+", "", block.text or "")
    if not text:
        return False
    if text in {"财务报表", "财务会计报表", "审计报告", "财务审计报告"}:
        return False
    if _text_matches_any_pattern(text, rule.get("instance_title_patterns") or []):
        return False
    if _text_matches_any_pattern(text, rule.get("child_title_exclude_patterns") or []):
        return False
    include_patterns = rule.get("child_title_include_patterns") or []
    if include_patterns and _text_matches_any_pattern(text, include_patterns):
        return True
    if len(text) > 32:
        return False
    if re.search(r"[。；;：:，,]$", text):
        return False
    if block.font_size is not None and float(block.font_size) >= 12:
        return True
    if block.font_size is not None:
        return False
    return len(text) <= 12


def _renamed_compound_child_title(title: str, rule: dict[str, Any]) -> str:
    clean = sanitize_asset_name(sanitize_display_title(title)).strip() or "未命名子项"
    for source, target in (rule.get("child_title_rename_map") or {}).items():
        if source and re.search(str(source), clean):
            return str(target)
    return clean


def _compound_relative_parts(section_path: str, anchor_path: str) -> list[str]:
    if section_path == anchor_path:
        return []
    prefix = f"{anchor_path} / "
    if not section_path.startswith(prefix):
        return []
    return [part.strip() for part in section_path[len(prefix):].split(" / ") if part.strip()]


def _looks_like_compound_instance_title(title: str, rule: dict[str, Any]) -> bool:
    compact = re.sub(r"\s+", "", title or "")
    if not compact:
        return False
    if _text_matches_any_pattern(compact, rule.get("instance_title_patterns") or []):
        return True
    return bool(re.search(r"20\d{2}.*(?:会计|财务|审计).*(?:报表|报告)", compact))


def _candidate_page_range(candidates: list[ReusableCandidate]) -> tuple[int, int]:
    pages = [page for candidate in candidates for page in _page_numbers(candidate)]
    if not pages:
        return 0, 0
    return min(pages), max(pages)


def _compound_instances_from_candidate_paths(
    anchor_path: str,
    child_paths: list[str],
    grouped_candidates: dict[str, list[ReusableCandidate]],
    rule: dict[str, Any],
) -> list[dict[str, Any]]:
    instances: dict[str, dict[str, Any]] = {}
    for path in child_paths:
        relative_parts = _compound_relative_parts(path, anchor_path)
        if not relative_parts:
            continue
        candidates = grouped_candidates.get(path, [])
        instance_title = sanitize_asset_name(relative_parts[0]).strip()
        child_title_source = relative_parts[1] if len(relative_parts) >= 2 else relative_parts[0]
        if not _looks_like_compound_instance_title(instance_title, rule):
            source_titles = [
                sanitize_asset_name(str(candidate.source_container_title or "")).strip()
                for candidate in candidates
            ]
            instance_title = next((title for title in source_titles if _looks_like_compound_instance_title(title, rule)), "")
            child_title_source = relative_parts[0]
        if not instance_title:
            continue
        child_title = _renamed_compound_child_title(child_title_source, rule)
        page_start, page_end = _candidate_page_range(candidates)
        instance = instances.setdefault(instance_title, {"title": instance_title, "children": {}})
        child = instance["children"].setdefault(child_title, {"title": child_title, "candidates": []})
        child["candidates"].extend(candidates)
        if page_start:
            child["page_start"] = min(int(child.get("page_start") or page_start), page_start)
            child["page_end"] = max(int(child.get("page_end") or page_end), page_end)

    normalized: list[dict[str, Any]] = []
    for instance in instances.values():
        children = [
            child
            for child in instance["children"].values()
            if int(child.get("page_start") or 0) > 0
        ]
        if not children:
            continue
        children = sorted(children, key=lambda child: (int(child.get("page_start") or 0), str(child.get("title") or "")))
        normalized.append(
            {
                "title": instance["title"],
                "page_start": min(int(child["page_start"]) for child in children),
                "page_end": max(int(child["page_end"]) for child in children),
                "children": children,
            }
        )
    return sorted(normalized, key=lambda item: (int(item["page_start"]), str(item["title"])))


def _package_compound_materials(
    rules: list[dict[str, Any]],
    grouped_candidates: dict[str, list[ReusableCandidate]],
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
    modules_dir: Path,
    pdf_path: str | Path | None,
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None,
    doc: Any,
    decorative_signatures: set[tuple[Any, ...]],
    layout_masks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for rule in rules:
        anchor_path = str(rule["excel_anchor_path"])
        child_paths = [path for path in grouped_candidates if _is_under_section_path(path, anchor_path)]
        if not child_paths:
            continue

        anchor_dir = ensure_dir(modules_dir.joinpath(*_section_dirnames([anchor_path])[anchor_path]))
        anchor_candidates = [candidate for path in child_paths for candidate in grouped_candidates.get(path, [])]
        pages = sorted({page for candidate in anchor_candidates for page in _page_numbers(candidate)})
        if not pages:
            continue

        page_set = set(pages)
        scoped_blocks = [block for block in blocks if block.page_no in page_set]
        scoped_tables = [table for table in tables if table.page_no in page_set]
        scoped_images = sorted(
            [
                image
                for image in images
                if int(image.get("page_no") or 0) in page_set
                and image.get("rect")
                and not _is_decorative_image(image, decorative_signatures)
                and not _is_tiny_artifact_image(image)
            ],
            key=_image_sort_key,
        )
        scoped_blocks, scoped_tables, scoped_images, _ = _filter_items_by_layout_masks(
            blocks=scoped_blocks,
            tables=scoped_tables,
            images=scoped_images,
            page_material_items=[],
            layout_masks=layout_masks,
            doc=doc,
        )
        path_instances = _compound_instances_from_candidate_paths(anchor_path, child_paths, grouped_candidates, rule)
        anchor_manifest: dict[str, Any] = {
            "material_type": "compound",
            "excel_anchor_path": anchor_path,
            "instance_count": 0,
            "instances": [],
        }
        instance_markdown_entries: list[tuple[str, Path]] = []
        if path_instances:
            for instance_data in path_instances:
                instance_title = str(instance_data["title"])
                instance_dir = ensure_dir(anchor_dir / _safe_dirname(instance_title))
                path_parts = _section_parts(anchor_path) + [instance_title]
                children_meta: list[dict[str, Any]] = []
                child_markdown_entries: list[tuple[str, Path]] = []
                for child_data in instance_data["children"]:
                    child_title = str(child_data["title"])
                    child_start_page = int(child_data["page_start"])
                    child_end_page = int(child_data["page_end"])
                    child_page_set = set(range(child_start_page, child_end_page + 1))
                    child_blocks = [block for block in scoped_blocks if block.page_no in child_page_set]
                    child_tables = [table for table in scoped_tables if table.page_no in child_page_set]
                    child_images = [image for image in scoped_images if int(image.get("page_no") or 0) in child_page_set]
                    child_dir = ensure_dir(instance_dir / _safe_dirname(child_title))
                    text_item = _write_text_item(
                        item_dir=ensure_dir(child_dir / "text_items"),
                        folder_title=child_title,
                        text_blocks=child_blocks,
                        section_path=anchor_path,
                        path_parts=path_parts,
                        pdf_path=pdf_path,
                    )

                    table_items: list[dict[str, Any]] = []
                    for table_index, table in enumerate(sorted(child_tables, key=lambda item: (item.page_no, (item.bbox or [0, 0, 0, 0])[1])), start=1):
                        top_y = float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else 0.0
                        table_title = _sanitize_item_title(child_title, f"表{table_index}")
                        item_dir = ensure_dir(child_dir / "table_items")
                        json_path = item_dir / _item_filename(table_title, "json")
                        item = {
                            **_table_dict(table),
                            "section_path": anchor_path,
                            "folder_parts": path_parts + [child_title],
                            "compound_instance_title": instance_title,
                            "child_title": child_title,
                            "table_title": table_title,
                            "context_title": child_title,
                            "source_file": str(pdf_path or ""),
                            "review_status": "pending",
                            "json_path": str(json_path),
                            "_top_y": top_y,
                        }
                        write_json(json_path, item)
                        table_items.append(item)

                    image_items: list[dict[str, Any]] = []
                    for image_index, image in enumerate(child_images, start=1):
                        rect = image.get("rect") or [0, 0, 0, 0]
                        top_y = float(rect[1]) if len(rect) >= 2 else 0.0
                        image_title = _sanitize_item_title(child_title, f"图{image_index}")
                        item_dir = ensure_dir(child_dir / "image_items")
                        image_bytes, ext = _resolve_image_bytes(image, image_bytes_resolver, doc)
                        image_path = item_dir / _item_filename(image_title, ext)
                        if image_bytes is not None:
                            image_path.write_bytes(image_bytes)
                        json_path = item_dir / _item_filename(image_title, "json")
                        item = {
                            **image,
                            "section_path": anchor_path,
                            "folder_parts": path_parts + [child_title],
                            "compound_instance_title": instance_title,
                            "child_title": child_title,
                            "image_title": image_title,
                            "context_title": child_title,
                            "source_file": str(pdf_path or ""),
                            "review_status": "pending",
                            "file_path": str(image_path),
                            "json_path": str(json_path),
                            "_top_y": top_y,
                        }
                        write_json(json_path, item)
                        image_items.append(item)

                    child_meta = _write_material_package(
                        material_dir=child_dir,
                        subfolder={
                            "folder_title": child_title,
                            "page_start": child_start_page,
                            "page_end": child_end_page,
                            "start_y": _block_top_y(child_blocks[0]) if child_blocks else None,
                            "end_y": _block_top_y(child_blocks[-1]) if child_blocks else None,
                            "start_block_id": child_blocks[0].block_id if child_blocks else None,
                            "end_block_id": child_blocks[-1].block_id if child_blocks else None,
                        },
                        section_path=anchor_path,
                        path_parts=path_parts,
                        pdf_path=pdf_path,
                        doc=doc,
                        text_blocks=child_blocks,
                        text_item=text_item,
                        table_items=table_items,
                        image_items=image_items,
                        image_bytes_resolver=image_bytes_resolver,
                        allow_submaterials=False,
                    )
                    children_meta.append(child_meta)
                    child_markdown_entries.append((child_title, child_dir / "material.md"))

                instance_markdown_path = _write_material_index_markdown(instance_dir, instance_title, child_markdown_entries)
                instance_meta = CompoundInstanceMeta(
                    material_type="compound_instance",
                    excel_anchor_path=anchor_path,
                    rule_anchor_path=anchor_path,
                    instance_title=instance_title,
                    instance_path=_material_path(_section_parts(anchor_path) + [instance_title]),
                    source_page_start=int(instance_data["page_start"]),
                    source_page_end=int(instance_data["page_end"]),
                    source_start_y=None,
                    source_end_y=None,
                    child_count=len(children_meta),
                    children=[MaterialMeta(**child) for child in children_meta],
                    review_status="pending",
                    material_markdown_path=str(instance_markdown_path.relative_to(instance_dir)),
                )
                write_json(instance_dir / "compound_instance_meta.json", instance_meta)
                anchor_manifest["instances"].append(instance_meta)
                instance_markdown_entries.append((instance_title, instance_dir / "material.md"))

            anchor_manifest["instance_count"] = len(anchor_manifest["instances"])
            anchor_manifest["material_markdown_path"] = str(_write_material_index_markdown(
                anchor_dir,
                _section_parts(anchor_path)[-1] if _section_parts(anchor_path) else anchor_path,
                instance_markdown_entries,
            ).relative_to(anchor_dir))
            write_json(anchor_dir / "compound_materials_manifest.json", anchor_manifest)
            manifests.append(anchor_manifest)
            continue

        instance_blocks = sorted(
            [
                block
                for block in scoped_blocks
                if _text_matches_any_pattern(re.sub(r"\s+", "", block.text or ""), rule["instance_title_patterns"])
            ],
            key=lambda item: (item.page_no, _block_top_y(item) or 0.0, item.block_no),
        )
        if not instance_blocks:
            continue

        for index, instance in enumerate(instance_blocks):
            next_instance = instance_blocks[index + 1] if index + 1 < len(instance_blocks) else None
            start_page = instance.page_no
            start_y = _block_top_y(instance)
            end_page = next_instance.page_no if next_instance else max(pages)
            end_y = _block_top_y(next_instance) if next_instance else None
            instance_blocks_in_range = [
                block
                for block in scoped_blocks
                if _item_in_range(block.page_no, _block_top_y(block), start_page, start_y, end_page, end_y)
            ]
            child_title_blocks = sorted(
                [
                    block
                    for block in instance_blocks_in_range
                    if block.block_id != instance.block_id and _is_compound_child_title(block, rule)
                ],
                key=lambda item: (item.page_no, _block_top_y(item) or 0.0, item.block_no),
            )
            if not child_title_blocks:
                child_title_blocks = [instance]

            instance_title = sanitize_asset_name(instance.text).strip() or "未命名主体"
            instance_dir = ensure_dir(anchor_dir / _safe_dirname(instance_title))
            children_meta: list[dict[str, Any]] = []
            child_markdown_entries: list[tuple[str, Path]] = []
            for child_index, child in enumerate(child_title_blocks):
                next_child = child_title_blocks[child_index + 1] if child_index + 1 < len(child_title_blocks) else None
                child_start_page = child.page_no
                child_start_y = _block_top_y(child)
                child_end_page = next_child.page_no if next_child else end_page
                child_end_y = _block_top_y(next_child) if next_child else end_y
                child_blocks = [
                    block
                    for block in instance_blocks_in_range
                    if _item_in_range(block.page_no, _block_top_y(block), child_start_page, child_start_y, child_end_page, child_end_y)
                ]
                child_tables = [
                    table
                    for table in scoped_tables
                    if _item_in_range(
                        table.page_no,
                        float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else None,
                        child_start_page,
                        child_start_y,
                        child_end_page,
                        child_end_y,
                    )
                ]
                child_images = [
                    image
                    for image in scoped_images
                    if _item_in_range(
                        int(image.get("page_no") or 0),
                        float((image.get("rect") or [0, 0, 0, 0])[1]),
                        child_start_page,
                        child_start_y,
                        child_end_page,
                        child_end_y,
                    )
                ]

                child_title = _renamed_compound_child_title(child.text, rule)
                child_dir = ensure_dir(instance_dir / _safe_dirname(child_title))
                path_parts = _section_parts(anchor_path) + [instance_title]
                text_item = _write_text_item(
                    item_dir=ensure_dir(child_dir / "text_items"),
                    folder_title=child_title,
                    text_blocks=child_blocks,
                    section_path=anchor_path,
                    path_parts=path_parts,
                    pdf_path=pdf_path,
                )

                table_items: list[dict[str, Any]] = []
                for table_index, table in enumerate(sorted(child_tables, key=lambda item: (item.page_no, (item.bbox or [0, 0, 0, 0])[1])), start=1):
                    top_y = float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else 0.0
                    table_title = _sanitize_item_title(child_title, f"表{table_index}")
                    item_dir = ensure_dir(child_dir / "table_items")
                    json_path = item_dir / _item_filename(table_title, "json")
                    item = {
                        **_table_dict(table),
                        "section_path": anchor_path,
                        "folder_parts": path_parts + [child_title],
                        "compound_instance_title": instance_title,
                        "child_title": child_title,
                        "table_title": table_title,
                        "context_title": child_title,
                        "source_file": str(pdf_path or ""),
                        "review_status": "pending",
                        "json_path": str(json_path),
                        "_top_y": top_y,
                    }
                    write_json(json_path, item)
                    table_items.append(item)

                image_items: list[dict[str, Any]] = []
                for image_index, image in enumerate(child_images, start=1):
                    rect = image.get("rect") or [0, 0, 0, 0]
                    top_y = float(rect[1]) if len(rect) >= 2 else 0.0
                    image_title = _sanitize_item_title(child_title, f"图{image_index}")
                    item_dir = ensure_dir(child_dir / "image_items")
                    image_bytes, ext = _resolve_image_bytes(image, image_bytes_resolver, doc)
                    image_path = item_dir / _item_filename(image_title, ext)
                    if image_bytes is not None:
                        image_path.write_bytes(image_bytes)
                    json_path = item_dir / _item_filename(image_title, "json")
                    item = {
                        **image,
                        "section_path": anchor_path,
                        "folder_parts": path_parts + [child_title],
                        "compound_instance_title": instance_title,
                        "child_title": child_title,
                        "image_title": image_title,
                        "context_title": child_title,
                        "source_file": str(pdf_path or ""),
                        "review_status": "pending",
                        "file_path": str(image_path),
                        "json_path": str(json_path),
                        "_top_y": top_y,
                    }
                    write_json(json_path, item)
                    image_items.append(item)

                child_meta = _write_material_package(
                    material_dir=child_dir,
                    subfolder={
                        "folder_title": child_title,
                        "page_start": child_start_page,
                        "page_end": child_end_page,
                        "start_y": child_start_y,
                        "end_y": child_end_y,
                        "start_block_id": child.block_id,
                        "end_block_id": next_child.block_id if next_child else (next_instance.block_id if next_instance else None),
                    },
                    section_path=anchor_path,
                    path_parts=path_parts,
                    pdf_path=pdf_path,
                    doc=doc,
                    text_blocks=child_blocks,
                    text_item=text_item,
                    table_items=table_items,
                    image_items=image_items,
                    image_bytes_resolver=image_bytes_resolver,
                    allow_submaterials=False,
                )
                children_meta.append(child_meta)
                child_markdown_entries.append((child_title, child_dir / "material.md"))

            instance_markdown_path = _write_material_index_markdown(instance_dir, instance_title, child_markdown_entries)
            instance_meta = CompoundInstanceMeta(
                material_type="compound_instance",
                excel_anchor_path=anchor_path,
                rule_anchor_path=anchor_path,
                instance_title=instance_title,
                instance_path=_material_path(_section_parts(anchor_path) + [instance_title]),
                source_page_start=start_page,
                source_page_end=end_page,
                source_start_y=start_y,
                source_end_y=end_y,
                child_count=len(children_meta),
                children=[MaterialMeta(**child) for child in children_meta],
                review_status="pending",
                material_markdown_path=str(instance_markdown_path.relative_to(instance_dir)),
            )
            write_json(instance_dir / "compound_instance_meta.json", instance_meta)
            anchor_manifest["instances"].append(instance_meta)
            instance_markdown_entries.append((instance_title, instance_dir / "material.md"))

        anchor_manifest["instance_count"] = len(anchor_manifest["instances"])
        anchor_manifest["material_markdown_path"] = str(_write_material_index_markdown(
            anchor_dir,
            _section_parts(anchor_path)[-1] if _section_parts(anchor_path) else anchor_path,
            instance_markdown_entries,
        ).relative_to(anchor_dir))
        write_json(anchor_dir / "compound_materials_manifest.json", anchor_manifest)
        manifests.append(anchor_manifest)
    return manifests


def _block_dict(block: PdfTextBlock) -> dict[str, Any]:
    return block.model_dump()


def _table_dict(table: ParsedTable) -> dict[str, Any]:
    return table.model_dump()


def _image_sort_key(image: dict[str, Any]) -> tuple[int, float, float]:
    rect = image.get("rect") or [0, 0, 0, 0]
    top = float(rect[1]) if len(rect) >= 2 else 0.0
    left = float(rect[0]) if len(rect) >= 1 else 0.0
    return int(image.get("page_no") or 0), top, left


def _bbox_center(bbox: list[Any] | None) -> tuple[float, float] | None:
    if not bbox or len(bbox) < 4:
        return None
    try:
        x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    except (TypeError, ValueError):
        return None
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _page_size_for_mask_scaling(doc: Any, page_no: int) -> tuple[float | None, float | None]:
    if doc is None:
        return None, None
    try:
        page = doc.load_page(int(page_no) - 1)
    except Exception:
        return None, None
    return float(page.rect.width), float(page.rect.height)


def _scaled_mask_bbox(mask: dict[str, Any], doc: Any) -> list[float]:
    bbox = [float(value) for value in (mask.get("bbox") or [])[:4]]
    if len(bbox) < 4:
        return []
    source_width = mask.get("page_width")
    source_height = mask.get("page_height")
    try:
        source_width_value = float(source_width) if source_width else None
        source_height_value = float(source_height) if source_height else None
    except (TypeError, ValueError):
        source_width_value = None
        source_height_value = None
    target_width, target_height = _page_size_for_mask_scaling(doc, int(mask.get("page_no") or 0))
    if not source_width_value or not source_height_value or not target_width or not target_height:
        return bbox
    scale_x = target_width / source_width_value
    scale_y = target_height / source_height_value
    return [bbox[0] * scale_x, bbox[1] * scale_y, bbox[2] * scale_x, bbox[3] * scale_y]


def _bbox_center_in_mask(bbox: list[Any] | None, mask: dict[str, Any], doc: Any) -> bool:
    center = _bbox_center(bbox)
    if center is None:
        return False
    mask_bbox = _scaled_mask_bbox(mask, doc)
    if len(mask_bbox) < 4:
        return False
    center_x, center_y = center
    return float(mask_bbox[0]) <= center_x <= float(mask_bbox[2]) and float(mask_bbox[1]) <= center_y <= float(mask_bbox[3])


def _filter_items_by_layout_masks(
    *,
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
    page_material_items: list[dict[str, Any]],
    layout_masks: list[dict[str, Any]] | None,
    doc: Any,
) -> tuple[list[PdfTextBlock], list[ParsedTable], list[dict[str, Any]], list[dict[str, Any]]]:
    if not layout_masks:
        return blocks, tables, images, page_material_items
    masks_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for mask in layout_masks:
        masks_by_page[int(mask.get("page_no") or 0)].append(mask)

    def masked(page_no: int, bbox: list[Any] | None) -> bool:
        return any(_bbox_center_in_mask(bbox, mask, doc) for mask in masks_by_page.get(int(page_no), []))

    filtered_blocks = [block for block in blocks if not masked(block.page_no, block.bbox)]
    filtered_tables = [table for table in tables if not masked(table.page_no, table.bbox)]
    filtered_images = [image for image in images if not masked(int(image.get("page_no") or 0), image.get("rect") or [])]
    filtered_page_items = [
        item
        for item in page_material_items
        if not masked(int(item.get("page_no") or 0), item.get("bbox") or item.get("rect") or [])
    ]
    return filtered_blocks, filtered_tables, filtered_images, filtered_page_items


def _decorative_image_signatures(images: list[dict[str, Any]]) -> set[tuple[Any, ...]]:
    counts: dict[tuple[Any, ...], int] = {}
    for image in images:
        rect = image.get("rect") or [0, 0, 0, 0]
        left = float(rect[0]) if len(rect) >= 1 else 0.0
        top = float(rect[1]) if len(rect) >= 2 else 0.0
        signature = (
            image.get("xref"),
            round(left, 1),
            round(top, 1),
            int(image.get("width") or 0),
            int(image.get("height") or 0),
        )
        counts[signature] = counts.get(signature, 0) + 1

    decorative: set[tuple[Any, ...]] = set()
    for signature, count in counts.items():
        _xref, left, top, width, height = signature
        is_small_header = left <= 120 and top <= 80 and width <= 200 and height <= 120
        if is_small_header and count >= 10:
            decorative.add(signature)
    return decorative


def _is_decorative_image(image: dict[str, Any], signatures: set[tuple[Any, ...]]) -> bool:
    rect = image.get("rect") or [0, 0, 0, 0]
    signature = (
        image.get("xref"),
        round(float(rect[0]) if len(rect) >= 1 else 0.0, 1),
        round(float(rect[1]) if len(rect) >= 2 else 0.0, 1),
        int(image.get("width") or 0),
        int(image.get("height") or 0),
    )
    return signature in signatures


def _is_tiny_artifact_image(image: dict[str, Any]) -> bool:
    rect = image.get("rect") or [0, 0, 0, 0]
    rect_width = abs(float(rect[2]) - float(rect[0])) if len(rect) >= 4 else 0.0
    rect_height = abs(float(rect[3]) - float(rect[1])) if len(rect) >= 4 else 0.0
    width = int(image.get("width") or 0)
    height = int(image.get("height") or 0)

    tiny_on_page = rect_width <= 80 and rect_height <= 40
    tiny_intrinsic = width <= 220 and height <= 120
    very_small_area = rect_width * rect_height <= 1500
    return tiny_intrinsic and (tiny_on_page or very_small_area)


def _page_material_item_dict(item: PageMaterialItem | dict[str, Any]) -> dict[str, Any]:
    if isinstance(item, PageMaterialItem):
        return item.model_dump()
    return dict(item)


def _page_material_source_size(item: dict[str, Any]) -> tuple[float | None, float | None]:
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    width = payload.get("page_width")
    height = payload.get("page_height")
    try:
        width_value = float(width) if width else None
    except (TypeError, ValueError):
        width_value = None
    try:
        height_value = float(height) if height else None
    except (TypeError, ValueError):
        height_value = None
    return width_value, height_value


def _clip_from_page_material_bbox(fitz_module: Any, page: Any, bbox: list[Any], source_width: float | None, source_height: float | None) -> Any:
    x0, y0, x1, y1 = [float(value) for value in bbox[:4]]
    page_width = float(getattr(page.rect, "width", 0.0) or 0.0)
    page_height = float(getattr(page.rect, "height", 0.0) or 0.0)
    scale_x = page_width / source_width if source_width else 1.0
    scale_y = page_height / source_height if source_height else 1.0
    return fitz_module.Rect(x0 * scale_x, y0 * scale_y, x1 * scale_x, y1 * scale_y)


def _export_page_material_image_regions(
    *,
    material_dir: Path,
    section_path: str,
    material_path: str,
    nearest_heading: str,
    text_blocks: list[PdfTextBlock],
    page_material_items: list[dict[str, Any]],
    doc: Any,
) -> list[dict[str, Any]]:
    if not page_material_items:
        return []
    try:
        import fitz
    except ImportError:
        fitz = None

    exported: list[dict[str, Any]] = []
    decorative_text = _decorative_text_signatures(text_blocks)
    heading_candidates = build_heading_candidates([_block_dict(block) for block in text_blocks if not _is_decorative_text_block(block, decorative_text)])
    image_counts: dict[str, int] = {}
    for item in page_material_items:
        stream_item = dict(item)
        if str(stream_item.get("item_type") or stream_item.get("type") or "") != "image":
            exported.append(stream_item)
            continue
        if stream_item.get("file_path"):
            exported.append(stream_item)
            continue
        bbox = stream_item.get("bbox") or []
        if len(bbox) < 4 or doc is None or fitz is None:
            exported.append(stream_item)
            continue
        page_no = int(stream_item.get("page_no") or 0)
        top_y = float(stream_item.get("top_y") or bbox[1] or 0.0)
        nearest = find_nearest_heading(heading_candidates, page_no, top_y)
        context_title = nearest_heading
        if nearest:
            raw_title = str(nearest.get("raw_title") or "")
            context_title = raw_title if raw_title.strip().startswith("附") else str(nearest.get("title") or raw_title)
        clean_context_title = attachment_heading_title(context_title) if str(context_title).strip().startswith("附") else context_title
        image_counts[clean_context_title] = image_counts.get(clean_context_title, 0) + 1
        image_title = _sanitize_item_title(clean_context_title, f"图{image_counts[clean_context_title]}")
        item_dir = ensure_dir(material_dir / "image_items")
        image_path = item_dir / _item_filename(image_title, "png")
        try:
            page = doc.load_page(page_no - 1)
            source_width, source_height = _page_material_source_size(stream_item)
            clip = _clip_from_page_material_bbox(fitz, page, bbox, source_width, source_height)
            pix = page.get_pixmap(clip=clip, alpha=False)
            pix.save(image_path)
        except Exception:
            exported.append(stream_item)
            continue
        json_path = item_dir / _item_filename(image_title, "json")
        stream_item.update(
            {
                "image_title": image_title,
                "context_title": clean_context_title,
                "nearest_heading": context_title,
                "rule_section_path": section_path,
                "material_path": material_path,
                "file_path": str(image_path),
                "json_path": str(json_path),
                "payload_ref": str(json_path.relative_to(material_dir)),
            }
        )
        write_json(json_path, stream_item)
        exported.append(stream_item)
    return exported


def _page_material_items_for_pages(
    items: list[PageMaterialItem | dict[str, Any]],
    pages: list[int],
) -> list[dict[str, Any]]:
    page_set = set(pages)
    scoped = [_page_material_item_dict(item) for item in items if int(_page_material_item_dict(item).get("page_no") or 0) in page_set]
    return sorted(
        scoped,
        key=lambda item: (
            int(item.get("page_no") or 0),
            float(item.get("top_y") or 0.0),
            int(item.get("reading_order") or 0),
            str(item.get("item_type") or ""),
        ),
    )


def _page_material_items_in_range(
    items: list[dict[str, Any]],
    start_page: int,
    start_y: float | None,
    end_page: int,
    end_y: float | None,
) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if _item_in_range(
            int(item.get("page_no") or 0),
            float(item.get("top_y") or 0.0),
            start_page,
            start_y,
            end_page,
            end_y,
        )
    ]


def _resolve_image_bytes(
    image: dict[str, Any],
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None,
    doc: Any,
) -> tuple[bytes | None, str]:
    if image_bytes_resolver:
        return image_bytes_resolver(image)
    if doc is None:
        return None, str(image.get("ext") or "png")
    extracted = doc.extract_image(int(image["xref"]))
    return extracted.get("image"), extracted.get("ext", str(image.get("ext") or "png"))


def _container_title_for_page(candidates: list[ReusableCandidate], page_no: int) -> str | None:
    matches = [candidate for candidate in candidates if page_no in _page_numbers(candidate)]
    if not matches:
        return None
    matches = sorted(
        matches,
        key=lambda item: (
            ((item.source_page_end or item.source_page or 0) - (item.source_page or 0)),
            item.source_page or 0,
        ),
    )
    return matches[0].source_container_title or matches[0].title


def _section_dirnames(section_paths: list[str]) -> dict[str, list[str]]:
    registry: dict[tuple[str, ...], dict[str, dict[str, str]]] = {}
    mapping: dict[str, list[str]] = {}
    for section_path in sorted(section_paths):
        safe_parts: list[str] = []
        for raw_part in _section_parts(section_path):
            parent = tuple(safe_parts)
            base = _safe_dirname(raw_part)
            siblings = registry.setdefault(parent, {}).setdefault(base, {})
            if raw_part in siblings:
                safe_name = siblings[raw_part]
            elif not siblings:
                safe_name = base
                siblings[raw_part] = safe_name
            else:
                safe_name = f"{base}__{make_stable_id('dir', raw_part)[-6:]}"
                siblings[raw_part] = safe_name
            safe_parts.append(safe_name)
        mapping[section_path] = safe_parts
    return mapping


def _section_parts_tuple(section_path: str) -> tuple[str, ...]:
    return tuple(_section_parts(section_path))


def _parent_prefixes(section_paths: list[str]) -> set[tuple[str, ...]]:
    prefixes: set[tuple[str, ...]] = set()
    for section_path in section_paths:
        parts = _section_parts(section_path)
        for index in range(1, len(parts)):
            prefixes.add(tuple(parts[:index]))
    return prefixes


def _parent_dirs_from_mapping(path_mapping: dict[str, list[str]]) -> dict[tuple[str, ...], Path]:
    parent_dirs: dict[tuple[str, ...], Path] = {}
    for section_path, safe_parts in path_mapping.items():
        raw_parts = _section_parts(section_path)
        for index in range(1, len(raw_parts)):
            parent_dirs[tuple(raw_parts[:index])] = Path(*safe_parts[:index])
    return parent_dirs


def _candidate_start_position(candidate: ReusableCandidate) -> tuple[int, float]:
    evidence = candidate.material_evidence if isinstance(candidate.material_evidence, dict) else {}
    start_y = evidence.get("start_y")
    return int(candidate.source_page or 0), float(start_y) if start_y is not None else 0.0


def _find_parent_preface_scope(
    parent_parts: tuple[str, ...],
    grouped_candidates: dict[str, list[ReusableCandidate]],
    blocks: list[PdfTextBlock],
) -> dict[str, Any] | None:
    child_candidates = [
        candidate
        for section_path, candidates in grouped_candidates.items()
        if _section_parts_tuple(section_path)[: len(parent_parts)] == parent_parts
        and len(_section_parts_tuple(section_path)) > len(parent_parts)
        for candidate in candidates
        if candidate.source_page
    ]
    if not child_candidates:
        return None
    first_child = sorted(child_candidates, key=_candidate_start_position)[0]
    child_start_page, child_start_y = _candidate_start_position(first_child)
    normalized_parent = normalize_section_title(parent_parts[-1])
    if not normalized_parent:
        return None

    exact_title_blocks: list[PdfTextBlock] = []
    fuzzy_title_blocks: list[PdfTextBlock] = []
    for block in blocks:
        if block.page_no > child_start_page:
            continue
        top_y = _block_top_y(block)
        if block.page_no == child_start_page and top_y is not None and top_y >= child_start_y:
            continue
        normalized_block = normalize_section_title(block.text or "")
        if normalized_block == normalized_parent:
            exact_title_blocks.append(block)
        elif normalized_block and (normalized_parent in normalized_block or normalized_block in normalized_parent):
            fuzzy_title_blocks.append(block)
    title_blocks = exact_title_blocks or fuzzy_title_blocks
    if not title_blocks:
        return None
    title_block = sorted(title_blocks, key=lambda item: (item.page_no, _block_top_y(item) or 0.0))[-1]
    evidence = first_child.material_evidence if isinstance(first_child.material_evidence, dict) else {}
    return {
        "title": parent_parts[-1],
        "start_page": title_block.page_no,
        "start_y": _block_bottom_y(title_block) or _block_top_y(title_block),
        "end_page": child_start_page,
        "end_y": child_start_y,
        "start_block_id": title_block.block_id,
        "end_block_id": evidence.get("start_block_id"),
    }


def _direct_child_markdown_entries(parent_dir: Path) -> list[tuple[str, Path]]:
    return [
        (child.name, child / "material.md")
        for child in sorted(parent_dir.iterdir(), key=lambda item: item.name)
        if child.is_dir() and (child / "material.md").exists()
    ]


def _append_child_links_to_markdown(material_dir: Path, entries: list[tuple[str, Path]]) -> None:
    if not entries:
        return
    markdown_path = material_dir / "material.md"
    current = markdown_path.read_text(encoding="utf-8").rstrip() if markdown_path.exists() else f"# {material_dir.name}"
    current = _strip_child_links_section(current)
    lines = [current, "", "## 子章节", ""]
    lines.extend(f"- [{title}]({_relative_markdown_path(material_dir, path)})" for title, path in entries)
    markdown_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _strip_child_links_section(markdown: str) -> str:
    return re.split(r"\n## 子章节\n", markdown.rstrip(), maxsplit=1)[0].rstrip()


def _write_parent_preface_packages(
    modules_dir: Path,
    all_section_paths: list[str],
    path_mapping: dict[str, list[str]],
    grouped_candidates: dict[str, list[ReusableCandidate]],
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
    pdf_path: str | Path | None,
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None,
    doc: Any,
    decorative_signatures: set[tuple[Any, ...]],
    layout_masks: list[dict[str, Any]] | None = None,
) -> None:
    parent_dirs = _parent_dirs_from_mapping(path_mapping)
    for parent_parts in sorted(_parent_prefixes(all_section_paths), key=len, reverse=True):
        parent_relative_dir = parent_dirs.get(parent_parts)
        if not parent_relative_dir:
            continue
        parent_dir = ensure_dir(modules_dir / parent_relative_dir)
        if (parent_dir / "ordered_material.json").exists():
            continue
        scope = _find_parent_preface_scope(parent_parts, grouped_candidates, blocks)
        if not scope:
            continue
        scoped_blocks = [
            block
            for block in blocks
            if _item_in_range(block.page_no, _block_top_y(block), int(scope["start_page"]), scope.get("start_y"), int(scope["end_page"]), scope.get("end_y"))
        ]
        decorative_text = _decorative_text_signatures(scoped_blocks)
        scoped_blocks = [block for block in scoped_blocks if not _is_decorative_text_block(block, decorative_text)]
        scoped_tables = [
            table
            for table in tables
            if _item_in_range(
                table.page_no,
                float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else 0.0,
                int(scope["start_page"]),
                scope.get("start_y"),
                int(scope["end_page"]),
                scope.get("end_y"),
            )
        ]
        scoped_images = [
            image
            for image in images
            if image.get("rect")
            and not _is_decorative_image(image, decorative_signatures)
            and not _is_tiny_artifact_image(image)
            and _item_in_range(
                int(image.get("page_no") or 0),
                float((image.get("rect") or [0, 0, 0, 0])[1]),
                int(scope["start_page"]),
                scope.get("start_y"),
                int(scope["end_page"]),
                scope.get("end_y"),
            )
        ]
        scoped_blocks, scoped_tables, scoped_images, _ = _filter_items_by_layout_masks(
            blocks=scoped_blocks,
            tables=scoped_tables,
            images=scoped_images,
            page_material_items=[],
            layout_masks=layout_masks,
            doc=doc,
        )
        if not scoped_blocks and not scoped_tables and not scoped_images:
            continue

        parent_title = parent_parts[-1]
        section_path = " / ".join(["PDF", *parent_parts])
        text_item = _write_text_item(
            item_dir=ensure_dir(parent_dir / "text_items"),
            folder_title=parent_title,
            text_blocks=scoped_blocks,
            section_path=section_path,
            path_parts=list(parent_parts[:-1]),
            pdf_path=pdf_path,
        )
        table_items: list[dict[str, Any]] = []
        for table_index, table in enumerate(sorted(scoped_tables, key=lambda item: (item.page_no, (item.bbox or [0, 0, 0, 0])[1])), start=1):
            top_y = float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else 0.0
            table_title = _sanitize_item_title(parent_title, f"表{table_index}")
            json_path = ensure_dir(parent_dir / "table_items") / _item_filename(table_title, "json")
            item = {
                **_table_dict(table),
                "section_path": section_path,
                "folder_parts": list(parent_parts),
                "table_title": table_title,
                "context_title": parent_title,
                "source_file": str(pdf_path or ""),
                "review_status": "pending",
                "json_path": str(json_path),
                "_top_y": top_y,
            }
            write_json(json_path, item)
            table_items.append(item)

        image_items: list[dict[str, Any]] = []
        for image_index, image in enumerate(sorted(scoped_images, key=_image_sort_key), start=1):
            rect = image.get("rect") or [0, 0, 0, 0]
            top_y = float(rect[1]) if len(rect) >= 2 else 0.0
            image_title = _sanitize_item_title(parent_title, f"图{image_index}")
            image_bytes, ext = _resolve_image_bytes(image, image_bytes_resolver, doc)
            image_path = ensure_dir(parent_dir / "image_items") / _item_filename(image_title, ext)
            if image_bytes is not None:
                image_path.write_bytes(image_bytes)
            json_path = ensure_dir(parent_dir / "image_items") / _item_filename(image_title, "json")
            item = {
                **image,
                "section_path": section_path,
                "folder_parts": list(parent_parts),
                "image_title": image_title,
                "context_title": parent_title,
                "source_file": str(pdf_path or ""),
                "review_status": "pending",
                "file_path": str(image_path),
                "json_path": str(json_path),
                "_top_y": top_y,
            }
            write_json(json_path, item)
            image_items.append(item)

        _write_material_package(
            material_dir=parent_dir,
            subfolder={
                "folder_title": parent_title,
                "page_start": int(scope["start_page"]),
                "page_end": int(scope["end_page"]),
                "start_y": scope.get("start_y"),
                "end_y": scope.get("end_y"),
                "start_block_id": scope.get("start_block_id"),
                "end_block_id": scope.get("end_block_id"),
            },
            section_path=section_path,
            path_parts=list(parent_parts[:-1]),
            pdf_path=pdf_path,
            doc=doc,
            text_blocks=scoped_blocks,
            text_item=text_item,
            table_items=table_items,
            image_items=image_items,
            page_material_items=[],
            image_bytes_resolver=image_bytes_resolver,
        )
        _append_child_links_to_markdown(parent_dir, _direct_child_markdown_entries(parent_dir))


def _subfolder_range_map(entries: list[dict[str, Any]], blocks: list[PdfTextBlock]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in build_precise_folder_ranges(entries, blocks):
        grouped[item["section_path"]].append(item)
    return grouped


def _subfolder_for_position(ranges: list[dict[str, Any]], page_no: int, top_y: float | None) -> dict[str, Any] | None:
    for item in ranges:
        if not (item["page_start"] <= page_no <= item["page_end"]):
            continue
        start_y = item.get("start_y")
        end_y = item.get("end_y")
        if top_y is not None and page_no == item["page_start"] and start_y is not None and top_y < float(start_y):
            continue
        if top_y is not None and page_no == item["page_end"] and end_y is not None and top_y >= float(end_y):
            continue
        return item
    return None


def _ordered_capture(
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in blocks:
        y = float((block.bbox or [0, 0, 0, 0])[1]) if block.bbox else 0.0
        items.append(
            {
                "type": "text",
                "page_no": block.page_no,
                "top_y": y,
                "block_id": block.block_id,
                "text": block.text,
                "bbox": block.bbox,
            }
        )
    for table in tables:
        bbox = table.bbox or [0, 0, 0, 0]
        y = float(bbox[1]) if len(bbox) >= 2 else 0.0
        items.append(
            {
                "type": "table",
                "page_no": table.page_no,
                "top_y": y,
                "table_id": table.table_id,
                "rows": table.rows,
                "bbox": table.bbox,
            }
        )
    for image in images:
        rect = image.get("rect") or [0, 0, 0, 0]
        y = float(rect[1]) if len(rect) >= 2 else 0.0
        items.append(
            {
                "type": "image",
                "page_no": int(image.get("page_no") or 0),
                "top_y": y,
                "image_id": image.get("image_id"),
                "xref": image.get("xref"),
                "rect": rect,
                "ext": image.get("ext"),
            }
        )
    return sorted(items, key=lambda item: (item["page_no"], item["top_y"], item["type"]))


def _entry_page_end(
    entry: dict[str, Any],
    section_candidates: list[ReusableCandidate],
) -> int:
    candidate_end = max((candidate.source_page_end or candidate.source_page or entry["page_start"]) for candidate in section_candidates) if section_candidates else entry["page_start"]
    return max(int(entry.get("page_end") or entry["page_start"]), int(candidate_end))


def _candidate_precise_scope(section_candidates: list[ReusableCandidate]) -> dict[str, Any] | None:
    if not section_candidates:
        return None
    if not any(
        isinstance(candidate.material_evidence, dict)
        and (
            candidate.material_evidence.get("source") == "pdf_toc_leaf"
            or candidate.material_evidence.get("start_y") is not None
            or candidate.material_evidence.get("end_y") is not None
        )
        for candidate in section_candidates
    ):
        return None
    candidates_with_pages = [candidate for candidate in section_candidates if candidate.source_page]
    if not candidates_with_pages:
        return None
    start_page = min(int(candidate.source_page or 0) for candidate in candidates_with_pages)
    end_page = max(int(candidate.source_page_end or candidate.source_page or 0) for candidate in candidates_with_pages)
    start_candidates = [candidate for candidate in candidates_with_pages if int(candidate.source_page or 0) == start_page]
    end_candidates = [candidate for candidate in candidates_with_pages if int(candidate.source_page_end or candidate.source_page or 0) == end_page]

    def evidence_value(candidate: ReusableCandidate, key: str) -> Any:
        evidence = candidate.material_evidence if isinstance(candidate.material_evidence, dict) else {}
        return evidence.get(key)

    start_y_values = [evidence_value(candidate, "start_y") for candidate in start_candidates if evidence_value(candidate, "start_y") is not None]
    end_y_values = [evidence_value(candidate, "end_y") for candidate in end_candidates if evidence_value(candidate, "end_y") is not None]
    start_block_id = next((evidence_value(candidate, "start_block_id") for candidate in start_candidates if evidence_value(candidate, "start_block_id")), None)
    end_block_id = next((evidence_value(candidate, "end_block_id") for candidate in end_candidates if evidence_value(candidate, "end_block_id")), None)
    return {
        "start_page": start_page,
        "end_page": end_page,
        "start_y": min(float(value) for value in start_y_values) if start_y_values else None,
        "end_y": max(float(value) for value in end_y_values) if end_y_values else None,
        "start_block_id": start_block_id,
        "end_block_id": end_block_id,
    }


def package_module_artifacts(
    candidates: list[ReusableCandidate],
    blocks: list[PdfTextBlock],
    tables: list[ParsedTable],
    images: list[dict[str, Any]],
    out_dir: str | Path,
    pdf_path: str | Path | None = None,
    image_bytes_resolver: Callable[[dict[str, Any]], tuple[bytes, str]] | None = None,
    top_level_modules: list[str] | None = None,
    planned_section_paths: list[str] | None = None,
    compound_material_rules: list[dict[str, Any]] | None = None,
    page_material_items: list[PageMaterialItem | dict[str, Any]] | None = None,
    layout_masks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        import fitz
    except ImportError:  # pragma: no cover
        fitz = None

    root = ensure_dir(Path(out_dir))
    modules_dir = ensure_dir(root / "modules")
    history_candidates = _history_candidates(candidates)
    decorative_signatures = _decorative_image_signatures(images)
    grouped_candidates: dict[str, list[ReusableCandidate]] = {}
    for candidate in history_candidates:
        grouped_candidates.setdefault(candidate.section_path, []).append(candidate)

    top_level_mapping = _section_dirnames([f"商务文件 / {module}" for module in (top_level_modules or []) if str(module).strip()])
    for module in top_level_modules or []:
        module_path = f"商务文件 / {module}"
        safe_parts = top_level_mapping.get(module_path, [_safe_dirname(module)])
        module_dir = ensure_dir(modules_dir.joinpath(*safe_parts))
        write_json(
            module_dir / "module_meta.json",
            {
                "module_name": module,
                "section_path": module_path,
                "history_candidate_count": sum(1 for candidate in history_candidates if _section_parts(candidate.section_path)[:1] == [module]),
            },
        )

    compound_rules = _normalize_compound_rules(compound_material_rules)
    global_manifest: dict[str, Any] = {"sections": [], "compound_materials": []}
    doc = fitz.open(pdf_path) if pdf_path and fitz else None
    try:
        global_manifest["compound_materials"] = _package_compound_materials(
            rules=compound_rules,
            grouped_candidates=grouped_candidates,
            blocks=blocks,
            tables=tables,
            images=images,
            modules_dir=modules_dir,
            pdf_path=pdf_path,
            image_bytes_resolver=image_bytes_resolver,
            doc=doc,
            decorative_signatures=decorative_signatures,
            layout_masks=layout_masks,
        )
        generated_compound_anchors = {
            str(manifest.get("excel_anchor_path") or "")
            for manifest in global_manifest["compound_materials"]
            if int(manifest.get("instance_count") or 0) > 0
        }
        compound_covered_paths = {
            path
            for path in set(grouped_candidates) | set(planned_section_paths or [])
            for anchor_path in generated_compound_anchors
            if _is_under_section_path(path, anchor_path)
        }
        all_section_paths = sorted((set((planned_section_paths or [])) | set(grouped_candidates)) - compound_covered_paths)
        review_index_entries = align_business_review_index_entries(parse_business_review_index(blocks, tables), set(all_section_paths))
        review_index_map = _subfolder_range_map(review_index_entries, blocks)
        path_mapping = _section_dirnames(all_section_paths)
        for section_path in all_section_paths:
            section_candidates = grouped_candidates.get(section_path, [])
            safe_parts = path_mapping.get(section_path, [_safe_dirname(section_path)])
            section_dir = ensure_dir(modules_dir.joinpath(*safe_parts))
            section_subfolders = review_index_map.get(section_path, [])
            section_pages = {page for candidate in section_candidates for page in _page_numbers(candidate)}
            for subfolder in section_subfolders:
                section_pages.update(range(int(subfolder["page_start"]), int(subfolder["page_end"]) + 1))
            pages = sorted(section_pages)
            module_blocks = [block for block in blocks if block.page_no in pages]
            decorative_text = _decorative_text_signatures(module_blocks)
            module_blocks = [block for block in module_blocks if not _is_decorative_text_block(block, decorative_text)]
            candidate_scope = _candidate_precise_scope(section_candidates)
            if candidate_scope:
                module_blocks = [
                    block
                    for block in module_blocks
                    if _item_in_range(
                        block.page_no,
                        _block_top_y(block),
                        int(candidate_scope["start_page"]),
                        candidate_scope.get("start_y"),
                        int(candidate_scope["end_page"]),
                        candidate_scope.get("end_y"),
                    )
                ]
            attachment_scope = _attachment_scope_for_section(section_path, module_blocks)
            if attachment_scope:
                module_blocks = [
                    block
                    for block in module_blocks
                    if _item_in_range(
                        block.page_no,
                        _block_top_y(block),
                        int(attachment_scope["start_page"]),
                        attachment_scope.get("start_y"),
                        int(attachment_scope["end_page"]),
                        attachment_scope.get("end_y"),
                    )
                ]
            module_tables = [table for table in tables if table.page_no in pages]
            if candidate_scope:
                module_tables = [
                    table
                    for table in module_tables
                    if _item_in_range(
                        table.page_no,
                        float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else 0.0,
                        int(candidate_scope["start_page"]),
                        candidate_scope.get("start_y"),
                        int(candidate_scope["end_page"]),
                        candidate_scope.get("end_y"),
                    )
                ]
            if attachment_scope:
                module_tables = [
                    table
                    for table in module_tables
                    if _item_in_range(
                        table.page_no,
                        float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else 0.0,
                        int(attachment_scope["start_page"]),
                        attachment_scope.get("start_y"),
                        int(attachment_scope["end_page"]),
                        attachment_scope.get("end_y"),
                    )
                ]
            module_images = sorted(
                [
                    image
                    for image in images
                    if int(image.get("page_no") or 0) in set(pages) and image.get("rect")
                    and not _is_decorative_image(image, decorative_signatures)
                    and not _is_tiny_artifact_image(image)
                ],
                key=_image_sort_key,
            )
            if candidate_scope:
                module_images = [
                    image
                    for image in module_images
                    if _item_in_range(
                        int(image.get("page_no") or 0),
                        float((image.get("rect") or [0, 0, 0, 0])[1]),
                        int(candidate_scope["start_page"]),
                        candidate_scope.get("start_y"),
                        int(candidate_scope["end_page"]),
                        candidate_scope.get("end_y"),
                    )
                ]
            if attachment_scope:
                module_images = [
                    image
                    for image in module_images
                    if _item_in_range(
                        int(image.get("page_no") or 0),
                        float((image.get("rect") or [0, 0, 0, 0])[1]),
                        int(attachment_scope["start_page"]),
                        attachment_scope.get("start_y"),
                        int(attachment_scope["end_page"]),
                        attachment_scope.get("end_y"),
                    )
                ]
            if attachment_scope:
                module_images = _limit_authorization_identity_images(section_path, module_images)
            module_page_material_items = _page_material_items_for_pages(page_material_items or [], pages)
            if candidate_scope:
                module_page_material_items = _page_material_items_in_range(
                    module_page_material_items,
                    int(candidate_scope["start_page"]),
                    candidate_scope.get("start_y"),
                    int(candidate_scope["end_page"]),
                    candidate_scope.get("end_y"),
                )
            if attachment_scope:
                module_page_material_items = _page_material_items_in_range(
                    module_page_material_items,
                    int(attachment_scope["start_page"]),
                    attachment_scope.get("start_y"),
                    int(attachment_scope["end_page"]),
                    attachment_scope.get("end_y"),
                )
            module_blocks, module_tables, module_images, module_page_material_items = _filter_items_by_layout_masks(
                blocks=module_blocks,
                tables=module_tables,
                images=module_images,
                page_material_items=module_page_material_items,
                layout_masks=layout_masks,
                doc=doc,
            )
            heading_candidates = build_heading_candidates([_block_dict(block) for block in module_blocks])
            path_parts = _section_parts(section_path)

            write_json(
                section_dir / "section_meta.json",
                {
                    "section_path": section_path,
                    "folder_parts": path_parts,
                    "pages": pages,
                    "candidate_count": len(section_candidates),
                    "has_standard_template": any(candidate.has_standard_template for candidate in section_candidates),
                    "is_empty_placeholder": not bool(section_candidates),
                    "section_markdown_path": "material.md",
                },
            )
            write_json(section_dir / "candidates.json", section_candidates)
            write_json(section_dir / "text_blocks.json", module_blocks)

            tables_index: list[dict[str, Any]] = []
            images_index: list[dict[str, Any]] = []
            text_index: list[dict[str, Any]] = []
            table_items_dir = ensure_dir(section_dir / "table_items")
            image_items_dir = ensure_dir(section_dir / "image_items")
            text_items_dir = ensure_dir(section_dir / "text_items")
            for subfolder in section_subfolders:
                ensure_dir(section_dir / _safe_dirname(subfolder["folder_title"]) / "table_items")
                ensure_dir(section_dir / _safe_dirname(subfolder["folder_title"]) / "image_items")
                ensure_dir(section_dir / _safe_dirname(subfolder["folder_title"]) / "text_items")

            text_groups: dict[str, dict[str, Any]] = {}
            for block in sorted(module_blocks, key=lambda item: (item.page_no, _block_top_y(item) or 0.0, item.block_no)):
                subfolder = _subfolder_for_position(section_subfolders, block.page_no, _block_top_y(block))
                if not subfolder:
                    continue
                key = str(subfolder["folder_title"])
                text_groups.setdefault(key, {"subfolder": subfolder, "blocks": []})["blocks"].append(block)

            text_items_by_folder: dict[str, dict[str, Any]] = {}
            text_blocks_by_folder: dict[str, list[PdfTextBlock]] = {}
            for group in text_groups.values():
                subfolder = group["subfolder"]
                item_dir = ensure_dir(section_dir / _safe_dirname(subfolder["folder_title"]) / "text_items")
                item = _write_text_item(
                    item_dir=item_dir,
                    folder_title=subfolder["folder_title"],
                    text_blocks=group["blocks"],
                    section_path=section_path,
                    path_parts=path_parts,
                    pdf_path=pdf_path,
                )
                if item:
                    text_index.append(item)
                    text_items_by_folder[str(subfolder["folder_title"])] = item
                    text_blocks_by_folder[str(subfolder["folder_title"])] = group["blocks"]

            table_items_by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
            table_counts: dict[str, int] = {}
            for table in sorted(module_tables, key=lambda item: (item.page_no, (item.bbox or [0, 0, 0, 0])[1])):
                top_y = float((table.bbox or [0, 0, 0, 0])[1]) if table.bbox else None
                nearest = find_nearest_heading(heading_candidates, table.page_no, top_y)
                context_title = _fallback_context_title(
                    nearest=nearest,
                    section_candidates=section_candidates,
                    page_no=table.page_no,
                    path_parts=path_parts,
                    default_title=f"第{table.page_no}页表格",
                )
                table_counts[context_title] = table_counts.get(context_title, 0) + 1
                table_title = _sanitize_item_title(context_title, f"表{table_counts[context_title]}")
                subfolder = _subfolder_for_position(section_subfolders, table.page_no, top_y)
                item_dir = table_items_dir
                if subfolder:
                    item_dir = ensure_dir(section_dir / _safe_dirname(subfolder["folder_title"]) / "table_items")
                item = {
                    **_table_dict(table),
                    "section_path": section_path,
                    "folder_parts": path_parts,
                    "review_index_folder": subfolder["folder_title"] if subfolder else None,
                    "table_title": table_title,
                    "context_title": context_title,
                    "parent_section_title": nearest["raw_title"] if nearest else context_title,
                    "container_title": _container_title_for_page(section_candidates, table.page_no),
                    "table_index_in_context": table_counts[context_title],
                    "source_file": str(pdf_path or ""),
                    "review_status": "pending",
                }
                json_path = item_dir / _item_filename(table_title, "json")
                item["json_path"] = str(json_path)
                write_json(json_path, item)
                tables_index.append(item)
                if subfolder:
                    table_items_by_folder[str(subfolder["folder_title"])].append({**item, "_top_y": top_y or 0.0})

            image_items_by_folder: dict[str, list[dict[str, Any]]] = defaultdict(list)
            image_counts: dict[str, int] = {}
            for image in module_images:
                rect = image.get("rect") or [0, 0, 0, 0]
                top_y = float(rect[1]) if len(rect) >= 2 else None
                page_no = int(image.get("page_no") or 0)
                nearest = find_nearest_heading(heading_candidates, page_no, top_y)
                context_title = _fallback_context_title(
                    nearest=nearest,
                    section_candidates=section_candidates,
                    page_no=page_no,
                    path_parts=path_parts,
                    default_title=f"第{page_no}页图片",
                )
                image_counts[context_title] = image_counts.get(context_title, 0) + 1
                image_title = _sanitize_item_title(context_title, f"图{image_counts[context_title]}")
                subfolder = _subfolder_for_position(section_subfolders, page_no, top_y)
                item_dir = image_items_dir
                if subfolder:
                    item_dir = ensure_dir(section_dir / _safe_dirname(subfolder["folder_title"]) / "image_items")
                image_bytes, ext = _resolve_image_bytes(image, image_bytes_resolver, doc)
                image_path = item_dir / _item_filename(image_title, ext)
                if image_bytes is not None:
                    image_path.write_bytes(image_bytes)
                item = {
                    **image,
                    "section_path": section_path,
                    "folder_parts": path_parts,
                    "review_index_folder": subfolder["folder_title"] if subfolder else None,
                    "image_title": image_title,
                    "context_title": context_title,
                    "parent_section_title": nearest["raw_title"] if nearest else context_title,
                    "container_title": _container_title_for_page(section_candidates, page_no),
                    "item_index_in_context": image_counts[context_title],
                    "source_file": str(pdf_path or ""),
                    "review_status": "pending",
                    "file_path": str(image_path),
                }
                json_path = item_dir / _item_filename(image_title, "json")
                item["json_path"] = str(json_path)
                write_json(json_path, item)
                images_index.append(item)
                if subfolder:
                    image_items_by_folder[str(subfolder["folder_title"])].append({**item, "_top_y": top_y or 0.0})

            material_index: list[dict[str, Any]] = []
            material_markdown_entries: list[tuple[str, Path]] = []
            for subfolder in section_subfolders:
                folder_title = str(subfolder["folder_title"])
                material_dir = ensure_dir(section_dir / _safe_dirname(folder_title))
                material_meta = _write_material_package(
                    material_dir=material_dir,
                    subfolder=subfolder,
                    section_path=section_path,
                    path_parts=path_parts,
                    pdf_path=pdf_path,
                    doc=doc,
                    text_blocks=text_blocks_by_folder.get(folder_title, []),
                    text_item=text_items_by_folder.get(folder_title),
                    table_items=table_items_by_folder.get(folder_title, []),
                    image_items=image_items_by_folder.get(folder_title, []),
                    page_material_items=_page_material_items_in_range(
                        module_page_material_items,
                        int(subfolder["page_start"]),
                        subfolder.get("start_y"),
                        int(subfolder["page_end"]),
                        subfolder.get("end_y"),
                    ),
                    image_bytes_resolver=image_bytes_resolver,
                )
                material_index.append(material_meta)
                material_markdown_entries.append((folder_title, material_dir / "material.md"))

            if not section_subfolders and section_candidates:
                root_folder_title = path_parts[-1] if path_parts else section_path
                root_image_only = _is_authorization_attachment_leaf(section_path)
                root_text_item = None if root_image_only else _write_text_item(
                    item_dir=text_items_dir,
                    folder_title=root_folder_title,
                    text_blocks=module_blocks,
                    section_path=section_path,
                    path_parts=path_parts,
                    pdf_path=pdf_path,
                )
                root_table_items = [{**item, "_top_y": float((item.get("bbox") or [0, 0, 0, 0])[1]) if item.get("bbox") else 0.0} for item in tables_index]
                root_image_items = [{**item, "_top_y": float((item.get("rect") or [0, 0, 0, 0])[1]) if item.get("rect") else 0.0} for item in images_index]
                material_index.append(
                    _write_material_package(
                        material_dir=section_dir,
                        subfolder={
                            "folder_title": root_folder_title,
                            "page_start": pages[0] if pages else 0,
                            "page_end": pages[-1] if pages else 0,
                            "start_y": _block_top_y(module_blocks[0]) if module_blocks else None,
                            "end_y": _block_top_y(module_blocks[-1]) if module_blocks else None,
                            "start_block_id": module_blocks[0].block_id if module_blocks else None,
                            "end_block_id": module_blocks[-1].block_id if module_blocks else None,
                        },
                        section_path=section_path,
                        path_parts=path_parts[:-1],
                        pdf_path=pdf_path,
                        doc=doc,
                        text_blocks=module_blocks,
                        text_item=root_text_item,
                        table_items=root_table_items,
                        image_items=root_image_items,
                        page_material_items=module_page_material_items,
                        image_bytes_resolver=image_bytes_resolver,
                        allow_submaterials=not _is_authorization_attachment_leaf(section_path),
                        image_only=root_image_only,
                    )
                )
            elif section_subfolders:
                _write_material_index_markdown(section_dir, path_parts[-1] if path_parts else section_path, material_markdown_entries)
            else:
                _write_material_index_markdown(section_dir, path_parts[-1] if path_parts else section_path, [])

            write_json(section_dir / "tables.json", tables_index)
            write_json(section_dir / "images.json", images_index)
            write_json(section_dir / "texts.json", text_index)
            write_json(section_dir / "materials.json", material_index)
            if any(candidate.has_standard_template for candidate in section_candidates):
                write_json(
                    section_dir / "source_capture.json",
                    {
                        "section_path": section_path,
                        "capture_items": _ordered_capture(module_blocks, module_tables, module_images),
                    },
                )

            global_manifest["sections"].append(
                {
                    "section_path": section_path,
                    "path": str(section_dir),
                    "has_standard_template": any(candidate.has_standard_template for candidate in section_candidates),
                    "table_count": len(tables_index),
                    "image_count": len(images_index),
                    "text_count": len(text_index),
                    "candidate_count": len(section_candidates),
                }
            )
        _write_parent_preface_packages(
            modules_dir=modules_dir,
            all_section_paths=all_section_paths,
            path_mapping=path_mapping,
            grouped_candidates=grouped_candidates,
            blocks=blocks,
            tables=tables,
            images=images,
            pdf_path=pdf_path,
            image_bytes_resolver=image_bytes_resolver,
            doc=doc,
            decorative_signatures=decorative_signatures,
            layout_masks=layout_masks,
        )
    finally:
        if doc is not None:
            doc.close()

    _backfill_missing_material_indexes(modules_dir)
    write_json(root / "global" / "modules_manifest.json", global_manifest)
    return global_manifest
