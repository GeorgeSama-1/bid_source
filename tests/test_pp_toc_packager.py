from pathlib import Path

from bid_knowledge.parsing.pp_toc_packager import (
    build_pp_toc_items,
    package_pp_toc_materials,
)
from bid_knowledge.schemas.models import ReusableCandidate


def _candidate(section_path: str, start_y: float | None = None, end_y: float | None = None) -> ReusableCandidate:
    return ReusableCandidate(
        candidate_id="cand-1",
        company_id="pdf",
        document_id="demo",
        rule_id="rule-1",
        section_path=section_path,
        from_history_bid=True,
        has_standard_template=True,
        title=section_path.split(" / ")[-1],
        content="",
        candidate_type="pdf_toc_leaf",
        reuse_method="PDF目录叶子章节",
        reuse_level="document",
        enter_long_term_library=True,
        source_file="demo.pdf",
        source_page=1,
        source_page_end=1,
        source_container_title="3.2、 补充文件",
        material_evidence={
            "source": "pdf_toc_leaf",
            "start_y": start_y,
            "end_y": end_y,
        },
    )


def _pp_result() -> dict:
    return {
        "page_index": 0,
        "res": {
            "page_index": 0,
            "width": 1000,
            "height": 1400,
            "parsing_res_list": [
                {
                    "block_label": "header",
                    "block_content": "国网甘肃省电力公司 商务投标文件",
                    "block_bbox": [20, 10, 800, 50],
                    "block_order": 1,
                },
                {
                    "block_label": "doc_title",
                    "block_content": "3.2、 投标人与国家电网公司系统人员关系说明",
                    "block_bbox": [50, 100, 900, 130],
                    "block_order": 2,
                },
                {
                    "block_label": "text",
                    "block_content": "截至投标截止日，不存在相关情形。",
                    "block_bbox": [50, 160, 900, 190],
                    "block_order": 3,
                },
                {
                    "block_label": "table",
                    "block_content": "本企业员工与国家电网公司系统人员关系说明表",
                    "block_bbox": [50, 220, 950, 520],
                    "block_order": 4,
                },
                {
                    "block_label": "number",
                    "block_content": "22",
                    "block_bbox": [490, 1350, 510, 1380],
                    "block_order": 5,
                },
            ],
            "layout_det_res": {
                "boxes": [
                    {
                        "label": "image",
                        "score": 0.9,
                        "coordinate": [100, 600, 500, 850],
                    }
                ]
            },
        },
    }


def test_build_pp_toc_items_uses_pp_layout_and_ignores_headers() -> None:
    items = build_pp_toc_items([_pp_result()])

    assert [item["type"] for item in items] == ["text", "text", "table", "image"]
    assert "国网甘肃省电力公司" not in "\n".join(str(item.get("text") or "") for item in items)
    assert items[2]["text"] == "本企业员工与国家电网公司系统人员关系说明表"


def test_package_pp_toc_materials_writes_leaf_markdown_with_table_link(tmp_path: Path) -> None:
    candidate = _candidate(
        "PDF / 3、 补充文件 / 3.2、 投标人与国家电网公司系统人员关系说明",
        start_y=90,
    )

    package_pp_toc_materials(
        candidates=[candidate],
        pp_structure_results=[_pp_result()],
        out_dir=tmp_path,
        pdf_path=None,
    )

    material_dir = tmp_path / "modules" / "3、 补充文件" / "3.2、 投标人与国家电网公司系统人员关系说明"
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")

    assert "# 3.2、 投标人与国家电网公司系统人员关系说明" in material_md
    assert "截至投标截止日，不存在相关情形。" in material_md
    assert "[表格：3.2、 投标人与国家电网公司系统人员关系说明_表1](table_items/3.2、 投标人与国家电网公司系统人员关系说明_表1.json)" in material_md
    assert "| 本企业人员基本信息 |" not in material_md
    assert "![3.2、 投标人与国家电网公司系统人员关系说明_图1](image_items/3.2、 投标人与国家电网公司系统人员关系说明_图1.png)" in material_md
    assert (material_dir / "table_items" / "3.2、 投标人与国家电网公司系统人员关系说明_表1.json").exists()
    assert (material_dir / "image_items" / "3.2、 投标人与国家电网公司系统人员关系说明_图1.json").exists()

