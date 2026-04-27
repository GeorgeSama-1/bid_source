from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from bid_knowledge.utils.io_utils import ensure_dir, write_json


def _normalize_pp_structure_result(result: Any, page_index: int) -> dict[str, Any]:
    if isinstance(result, dict):
        payload = dict(result)
    elif hasattr(result, "res"):
        payload = {"res": getattr(result, "res")}
    elif hasattr(result, "json"):
        raw = getattr(result, "json")
        payload = raw if isinstance(raw, dict) else {"res": raw}
    else:
        payload = {"res": result}
    payload.setdefault("page_index", page_index)
    return payload


def run_pp_structure(
    input_path: str | Path,
    *,
    out_path: str | Path | None = None,
    device: str = "gpu",
    use_doc_orientation_classify: bool = False,
    use_doc_unwarping: bool = False,
    use_textline_orientation: bool = False,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    try:
        from paddleocr import PPStructureV3
    except ImportError as exc:  # pragma: no cover - dependency-driven
        raise RuntimeError("需要先安装 paddleocr[all] 才能运行 PP-StructureV3。") from exc

    pipeline = PPStructureV3(
        device=device,
        use_doc_orientation_classify=use_doc_orientation_classify,
        use_doc_unwarping=use_doc_unwarping,
        use_textline_orientation=use_textline_orientation,
    )
    expected_total = 1
    input_suffix = str(input_path).lower()
    if input_suffix.endswith(".pdf"):
        try:
            import fitz

            doc = fitz.open(str(input_path))
            try:
                expected_total = max(1, int(doc.page_count))
            finally:
                doc.close()
        except Exception:  # pragma: no cover - dependency/environment driven
            expected_total = 1

    results: list[dict[str, Any]] = []
    for index, result in enumerate(pipeline.predict(input=str(input_path)), start=1):
        results.append(_normalize_pp_structure_result(result, page_index=index - 1))
        if progress_callback:
            progress_callback(index, expected_total)
    if out_path:
        write_json(out_path, results)
    return results


def ensure_pp_structure_output_dir(out_dir: str | Path) -> Path:
    return ensure_dir(out_dir)
