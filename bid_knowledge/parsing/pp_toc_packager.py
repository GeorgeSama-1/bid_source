from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from bid_knowledge.parsing.attachment_asset_exporter import sanitize_asset_name
from bid_knowledge.schemas.models import ReusableCandidate
from bid_knowledge.utils.id_utils import make_stable_id
from bid_knowledge.utils.io_utils import ensure_dir, write_json


IGNORED_LABELS = {"header", "header_image", "footer", "footer_image", "number", "footnote", "aside_text"}
TEXT_LABELS = {"doc_title", "paragraph_title", "text"}


def _safe_dirname(raw: str) -> str:
    safe = sanitize_asset_name(raw).strip()
    return safe or "未命名章节"


def _item_filename(title: str, extension: str) -> str:
    base = sanitize_asset_name(title).strip() or "未命名材料"
    if len(base) <= 80:
        return f"{base}.{extension}"
    return f"{base[:48].rstrip(' _')}_{make_stable_id('item', base)[-8:]}.{extension}"


def _section_parts(section_path: str) -> list[str]:
    parts = [part.strip() for part in str(section_path or "").split(" / ") if part.strip()]
    return parts[1:] if len(parts) > 1 else parts


def _bbox(values: Any) -> list[float]:
    if not isinstance(values, list):
        return []
    bbox: list[float] = []
    for value in values[:4]:
        try:
            bbox.append(float(value))
        except (TypeError, ValueError):
            return []
    return bbox if len(bbox) == 4 else []


def _top_y(bbox: list[float]) -> float:
    return float(bbox[1]) if len(bbox) >= 2 else 0.0


def _page_no(result: dict[str, Any], payload: dict[str, Any]) -> int:
    value = payload.get("page_no")
    if value is None:
        value = payload.get("page_index")
    if value is None:
        value = result.get("page_index")
    try:
        index = int(value)
    except (TypeError, ValueError):
        index = 0
    return index + 1 if index <= 0 else index + 1 if payload.get("page_no") is None else index


def build_pp_toc_items(pp_structure_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for result in pp_structure_results or []:
        payload = result.get("res") if isinstance(result.get("res"), dict) else result
        if not isinstance(payload, dict):
            continue
        page_no = _page_no(result, payload)
        for index, block in enumerate(payload.get("parsing_res_list") or [], start=1):
            label = str(block.get("block_label") or "")
            if label in IGNORED_LABELS:
                continue
            bbox = _bbox(block.get("block_bbox") or block.get("bbox") or [])
            if label in TEXT_LABELS:
                text = str(block.get("block_content") or "").strip()
                if text:
                    items.append(
                        {
                            "type": "text",
                            "source_type": "pp_structure",
                            "page_no": page_no,
                            "top_y": _top_y(bbox),
                            "bbox": bbox,
                            "text": text,
                            "label": label,
                            "order": int(block.get("block_order") or index),
                        }
                    )
            elif label == "table":
                items.append(
                    {
                        "type": "table",
                        "source_type": "pp_structure",
                        "page_no": page_no,
                        "top_y": _top_y(bbox),
                        "bbox": bbox,
                        "text": str(block.get("block_content") or "").strip(),
                        "label": label,
                        "order": int(block.get("block_order") or index),
                        "payload": dict(block),
                    }
                )

        for index, box in enumerate((payload.get("layout_det_res") or {}).get("boxes") or [], start=1):
            label = str(box.get("label") or "")
            if label in IGNORED_LABELS:
                continue
            if label not in {"image", "table"}:
                continue
            bbox = _bbox(box.get("coordinate") or [])
            if not bbox:
                continue
            if label == "table" and any(
                item["type"] == "table"
                and item["page_no"] == page_no
                and _bbox_overlap_ratio(item.get("bbox") or [], bbox) > 0.5
                for item in items
            ):
                continue
            items.append(
                {
                    "type": label,
                    "source_type": "pp_structure_layout",
                    "page_no": page_no,
                    "top_y": _top_y(bbox),
                    "bbox": bbox,
                    "text": "",
                    "label": label,
                    "order": index,
                    "page_width": payload.get("width"),
                    "page_height": payload.get("height"),
                    "payload": dict(box),
                }
            )
    return sorted(items, key=lambda item: (int(item["page_no"]), float(item["top_y"]), str(item["type"])))


def _bbox_overlap_ratio(bbox: list[float], other: list[float]) -> float:
    if len(bbox) < 4 or len(other) < 4:
        return 0.0
    x0, y0, x1, y1 = bbox
    ox0, oy0, ox1, oy1 = other
    ix0 = max(x0, ox0)
    iy0 = max(y0, oy0)
    ix1 = min(x1, ox1)
    iy1 = min(y1, oy1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area = max((x1 - x0) * (y1 - y0), 1.0)
    return intersection / area


def _candidate_range(candidate: ReusableCandidate) -> tuple[int, float | None, int, float | None]:
    evidence = candidate.material_evidence if isinstance(candidate.material_evidence, dict) else {}
    start_page = int(candidate.source_page or 1)
    end_page = int(candidate.source_page_end or candidate.source_page or start_page)
    start_y = evidence.get("start_y")
    end_y = evidence.get("end_y")
    return start_page, float(start_y) if start_y is not None else None, end_page, float(end_y) if end_y is not None else None


def _item_in_candidate(item: dict[str, Any], candidate: ReusableCandidate) -> bool:
    start_page, start_y, end_page, end_y = _candidate_range(candidate)
    page_no = int(item.get("page_no") or 0)
    top_y = float(item.get("top_y") or 0.0)
    if page_no < start_page or page_no > end_page:
        return False
    if page_no == start_page and start_y is not None and top_y < start_y:
        return False
    if page_no == end_page and end_y is not None and top_y >= end_y:
        return False
    return True


def _relative_path(base: Path, target: Path) -> str:
    try:
        return str(target.relative_to(base))
    except ValueError:
        return str(target)


def _write_image_asset(image_path: Path, item: dict[str, Any], pdf_doc: Any | None) -> None:
    if pdf_doc is not None:
        try:
            page_no = int(item.get("page_no") or 1)
            page = pdf_doc.load_page(max(0, page_no - 1))
            page_rect = page.rect
            bbox = [float(value) for value in item.get("bbox") or []]
            page_width = float(item.get("page_width") or 0.0)
            page_height = float(item.get("page_height") or 0.0)
            if len(bbox) == 4 and page_width > 0 and page_height > 0:
                scale_x = float(page_rect.width) / page_width
                scale_y = float(page_rect.height) / page_height
                clip = page_rect & type(page_rect)(
                    bbox[0] * scale_x,
                    bbox[1] * scale_y,
                    bbox[2] * scale_x,
                    bbox[3] * scale_y,
                )
                if not clip.is_empty:
                    pix = page.get_pixmap(clip=clip, alpha=False)
                    pix.save(image_path)
                    return
        except Exception:
            pass
    image_path.write_bytes(b"")


def _write_leaf_material(
    material_dir: Path,
    candidate: ReusableCandidate,
    items: list[dict[str, Any]],
    pdf_path: str | Path | None,
    pdf_doc: Any | None = None,
) -> dict[str, Any]:
    title = _section_parts(candidate.section_path)[-1]
    lines = [f"# {title}", ""]
    table_index = 0
    image_index = 0
    ordered: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        item_type = str(item["type"])
        if item_type == "text":
            text = str(item.get("text") or "").strip()
            if text:
                lines.extend([text, ""])
        elif item_type == "table":
            table_index += 1
            table_title = f"{title}_表{table_index}"
            table_dir = ensure_dir(material_dir / "table_items")
            table_path = table_dir / _item_filename(table_title, "json")
            table_payload = {
                **item,
                "table_title": table_title,
                "section_path": candidate.section_path,
                "source_file": str(pdf_path or ""),
            }
            write_json(table_path, table_payload)
            lines.extend([f"[表格：{table_title}]({_relative_path(material_dir, table_path)})", ""])
            item = {**item, "payload_ref": _relative_path(material_dir, table_path), "table_title": table_title}
        elif item_type == "image":
            image_index += 1
            image_title = f"{title}_图{image_index}"
            image_dir = ensure_dir(material_dir / "image_items")
            image_path = image_dir / _item_filename(image_title, "png")
            _write_image_asset(image_path, item, pdf_doc)
            image_json_path = image_dir / _item_filename(image_title, "json")
            image_payload = {
                **item,
                "image_title": image_title,
                "file_path": str(image_path),
                "section_path": candidate.section_path,
                "source_file": str(pdf_path or ""),
            }
            write_json(image_json_path, image_payload)
            lines.extend([f"![{image_title}]({_relative_path(material_dir, image_path)})", ""])
            item = {**item, "payload_ref": _relative_path(material_dir, image_json_path), "image_title": image_title, "file_path": str(image_path)}
        ordered.append({**item, "order": index})

    (material_dir / "material.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    write_json(
        material_dir / "ordered_material.json",
        {
            "material_title": title,
            "section_path": candidate.section_path,
            "items": ordered,
        },
    )
    return {
        "material_title": title,
        "section_path": candidate.section_path,
        "material_markdown_path": "material.md",
        "item_count": len(ordered),
    }


def _write_parent_indexes(modules_dir: Path) -> None:
    skip = {"table_items", "image_items", "text_items", "original"}
    directories = sorted([path for path in modules_dir.rglob("*") if path.is_dir() and path.name not in skip], key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        children = [
            child
            for child in sorted(directory.iterdir(), key=lambda item: item.name)
            if child.is_dir() and (child / "material.md").exists() and child.name not in skip
        ]
        if not children:
            continue
        if (directory / "ordered_material.json").exists():
            continue
        lines = [f"# {directory.name}", ""]
        for child in children:
            lines.append(f"- [{child.name}]({_relative_path(directory, child / 'material.md')})")
        (directory / "material.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def package_pp_toc_materials(
    *,
    candidates: list[ReusableCandidate],
    pp_structure_results: list[dict[str, Any]],
    out_dir: str | Path,
    pdf_path: str | Path | None = None,
) -> dict[str, Any]:
    root = ensure_dir(out_dir)
    modules_dir = ensure_dir(root / "modules")
    pp_items = build_pp_toc_items(pp_structure_results)
    materials: list[dict[str, Any]] = []
    pdf_doc = None
    if pdf_path:
        try:
            import fitz

            pdf_doc = fitz.open(str(pdf_path))
        except Exception:
            pdf_doc = None
    try:
        for candidate in candidates:
            parts = _section_parts(candidate.section_path)
            if not parts:
                continue
            material_dir = ensure_dir(modules_dir.joinpath(*[_safe_dirname(part) for part in parts]))
            scoped_items = [item for item in pp_items if _item_in_candidate(item, candidate)]
            materials.append(_write_leaf_material(material_dir, candidate, scoped_items, pdf_path, pdf_doc=pdf_doc))
    finally:
        if pdf_doc is not None:
            pdf_doc.close()
    _write_parent_indexes(modules_dir)
    manifest = {"material_count": len(materials), "materials": materials}
    write_json(root / "pp_toc_pipeline_manifest.json", manifest)
    return manifest
