from bid_knowledge.parsing.pp_table_extractor import extract_pp_structure_tables


def test_extract_pp_structure_tables_keeps_table_content_and_skips_duplicate_layout_box() -> None:
    results = [
        {
            "res": {
                "page_index": 0,
                "parsing_res_list": [
                    {
                        "block_label": "table",
                        "block_content": "<table><tr><td>姓名</td><td>岗位</td></tr></table>",
                        "block_bbox": [10, 100, 500, 260],
                        "block_id": 7,
                        "block_order": 3,
                    }
                ],
                "layout_det_res": {
                    "boxes": [
                        {
                            "label": "table",
                            "score": 0.91,
                            "coordinate": [11, 101, 501, 261],
                        }
                    ]
                },
            },
            "page_index": 0,
        }
    ]

    tables = extract_pp_structure_tables(results)

    assert len(tables) == 1
    assert tables[0].page_no == 1
    assert tables[0].bbox == [10.0, 100.0, 500.0, 260.0]
    assert tables[0].source_type == "pp_structure_table"
    assert tables[0].table_content == "<table><tr><td>姓名</td><td>岗位</td></tr></table>"
    assert tables[0].source_detail == "parsing_res_list"


def test_extract_pp_structure_tables_uses_layout_boxes_when_structured_content_is_missing() -> None:
    results = [
        {
            "res": {
                "page_index": 2,
                "parsing_res_list": [],
                "layout_det_res": {
                    "boxes": [
                        {
                            "label": "table",
                            "score": 0.76,
                            "coordinate": [20, 80, 520, 300],
                        }
                    ]
                },
            },
            "page_index": 2,
        }
    ]

    tables = extract_pp_structure_tables(results)

    assert len(tables) == 1
    assert tables[0].page_no == 3
    assert tables[0].bbox == [20.0, 80.0, 520.0, 300.0]
    assert tables[0].rows == []
    assert tables[0].source_type == "pp_structure_table"
    assert tables[0].source_detail == "layout_det_res"
