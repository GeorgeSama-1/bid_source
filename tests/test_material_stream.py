from bid_knowledge.parsing.material_stream import (
    build_combined_page_material_stream,
    build_page_material_stream,
    build_pp_structure_page_material_items,
)
from bid_knowledge.schemas.models import ParsedTable, PdfTextBlock


def test_build_page_material_stream_merges_text_table_and_image_items() -> None:
    blocks = [
        PdfTextBlock(
            block_id="block-1",
            page_no=3,
            text="3.8.13.2、供应链保障措施",
            bbox=[0, 100, 100, 120],
            block_no=1,
        ),
        PdfTextBlock(
            block_id="block-2",
            page_no=3,
            text="供应链保障正文",
            bbox=[0, 130, 200, 180],
            block_no=2,
        ),
    ]
    tables = [
        ParsedTable(
            table_id="table-1",
            page_no=3,
            rows=[["措施", "说明"]],
            bbox=[10, 190, 200, 240],
        )
    ]
    images = [
        {
            "image_id": "img-1",
            "page_no": 3,
            "xref": 10,
            "width": 500,
            "height": 400,
            "rect": [10, 260, 150, 360],
            "ext": "png",
        }
    ]

    stream = build_page_material_stream(blocks=blocks, tables=tables, images=images)

    assert [item.item_type for item in stream] == ["text", "text", "table", "image"]
    assert [item.reading_order for item in stream] == [1, 2, 3, 4]
    assert stream[0].source_type == "pdf_text"
    assert stream[2].source_type == "pdf_table"
    assert stream[3].source_type == "pdf_embedded_image"


def test_build_pp_structure_page_material_items_normalizes_layout_blocks() -> None:
    pp_result = {
        "parsing_res_list": [
            {
                "block_label": "doc_title",
                "block_content": "3.4、企业营业执照（扫描件）",
                "block_bbox": [21, 90, 952, 117],
                "block_order": 1,
            },
            {
                "block_label": "text",
                "block_content": "企业营业执照副本",
                "block_bbox": [753, 140, 950, 163],
                "block_order": 2,
            },
        ],
        "layout_det_res": {
            "boxes": [
                {
                    "label": "image",
                    "coordinate": [164.3, 183.9, 1502.2, 1023.9],
                    "score": 0.56,
                }
            ]
        },
    }

    items = build_pp_structure_page_material_items(pp_result, page_no=22)

    assert [item.item_type for item in items] == ["text", "text", "image"]
    assert items[0].source_type == "pp_structure_text"
    assert items[2].source_type == "pp_structure_image_region"
    assert items[2].payload["layout_label"] == "image"


def test_build_combined_page_material_stream_includes_pp_structure_items() -> None:
    blocks = [
        PdfTextBlock(
            block_id="block-1",
            page_no=22,
            text="3.4、企业营业执照（扫描件）",
            bbox=[0, 100, 100, 120],
            block_no=1,
        )
    ]
    pp_results = [
        {
            "res": {
                "parsing_res_list": [
                    {
                        "block_label": "text",
                        "block_content": "企业营业执照副本",
                        "block_bbox": [753, 140, 950, 163],
                        "block_order": 1,
                    }
                ],
                "layout_det_res": {
                    "boxes": [
                        {"label": "image", "coordinate": [164.3, 183.9, 1502.2, 1023.9], "score": 0.56}
                    ]
                },
            },
            "page_index": 21,
        }
    ]

    items = build_combined_page_material_stream(blocks=blocks, tables=[], images=[], pp_structure_results=pp_results)

    assert any(item.source_type == "pdf_text" for item in items)
    assert any(item.source_type == "pp_structure_text" for item in items)
    assert any(item.source_type == "pp_structure_image_region" for item in items)
