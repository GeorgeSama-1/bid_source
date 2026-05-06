from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable

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


def _text_content_from_blocks(blocks: list[PdfTextBlock]) -> str:
    return "\n\n".join(block.text.strip() for block in blocks if block.text and block.text.strip()).strip()


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
    for block in text_blocks:
        if _is_decorative_text_block(block, decorative_text):
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
                nearest_heading=nearest_heading,
                rule_section_path=rule_section_path,
                material_path=material_path,
                source_type=stream_item.get("source_type"),
                payload=stream_item.get("payload") or {},
            ).model_dump(exclude_none=True)
        )
    sorted_items = sorted(ordered, key=lambda item: (int(item.get("page_no") or 0), float(item.get("top_y") or 0.0), item["type"]))
    for index, item in enumerate(sorted_items, start=1):
        item["order"] = index
    return sorted_items


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
) -> dict[str, Any]:
    page_start = int(subfolder["page_start"])
    page_end = int(subfolder["page_end"])
    original_status = _write_original_capture(material_dir / "original", doc, page_start, page_end)
    material_path = _material_path(path_parts + [subfolder["folder_title"]])
    material_types = _merge_material_types(
        _material_types(text_item=text_item, table_items=table_items, image_items=image_items),
        page_material_items,
    )
    dominant_material_type = _dominant_material_type(material_types)
    raw_context_title = text_blocks[0].text if text_blocks else subfolder["folder_title"]
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
                text_blocks=text_blocks,
                text_item=text_item,
                table_items=table_items,
                image_items=image_items,
                submaterial_items=submaterial_items,
                page_material_items=page_material_items or [],
            )
        ],
    )
    write_json(material_dir / "ordered_material.json", ordered)
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
                "nearest_heading": anchor.text,
                "rule_section_path": section_path,
                "material_path": _material_path(path_parts + [child_title]),
                "payload_ref": str((child_dir / "ordered_material.json").relative_to(material_dir)),
            }
        )
    return references


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
    return len(text) <= 12


def _renamed_compound_child_title(title: str, rule: dict[str, Any]) -> str:
    clean = sanitize_asset_name(sanitize_display_title(title)).strip() or "未命名子项"
    for source, target in (rule.get("child_title_rename_map") or {}).items():
        if source and re.search(str(source), clean):
            return str(target)
    return clean


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

        anchor_manifest: dict[str, Any] = {
            "material_type": "compound",
            "excel_anchor_path": anchor_path,
            "instance_count": 0,
            "instances": [],
        }
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

                children_meta.append(
                    _write_material_package(
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
                )

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
            )
            write_json(instance_dir / "compound_instance_meta.json", instance_meta)
            anchor_manifest["instances"].append(instance_meta)

        anchor_manifest["instance_count"] = len(anchor_manifest["instances"])
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
    compound_covered_paths = {
        path
        for path in set(grouped_candidates)
        for rule in compound_rules
        if _is_under_section_path(path, str(rule["excel_anchor_path"]))
    }
    all_section_paths = sorted((set((planned_section_paths or [])) | set(grouped_candidates)) - compound_covered_paths)
    review_index_entries = align_business_review_index_entries(parse_business_review_index(blocks, tables), set(all_section_paths))
    review_index_map = _subfolder_range_map(review_index_entries, blocks)
    path_mapping = _section_dirnames(all_section_paths)
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
        )
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
            module_tables = [table for table in tables if table.page_no in pages]
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
            module_page_material_items = _page_material_items_for_pages(page_material_items or [], pages)
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
                context_title = nearest["title"] if nearest else _container_title_for_page(section_candidates, table.page_no) or f"第{table.page_no}页表格"
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
                context_title = nearest["title"] if nearest else _container_title_for_page(section_candidates, page_no) or f"第{page_no}页图片"
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
            for subfolder in section_subfolders:
                folder_title = str(subfolder["folder_title"])
                material_dir = ensure_dir(section_dir / _safe_dirname(folder_title))
                material_index.append(
                    _write_material_package(
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
                )

            if not section_subfolders and section_candidates:
                root_folder_title = path_parts[-1] if path_parts else section_path
                root_text_item = _write_text_item(
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
                    )
                )

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
    finally:
        if doc is not None:
            doc.close()

    write_json(root / "global" / "modules_manifest.json", global_manifest)
    return global_manifest
