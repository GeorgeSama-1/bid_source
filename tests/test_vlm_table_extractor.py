from pathlib import Path
from threading import Lock
from types import SimpleNamespace

from bid_knowledge.parsing.vlm_table_extractor import (
    _call_vlm_table_model,
    _parse_table_model_text,
    enhance_tables_with_vlm,
)
from bid_knowledge.schemas.models import ParsedTable
from bid_knowledge.utils.io_utils import read_json


def test_parse_table_model_text_accepts_json_fences_and_table_model_wrapper() -> None:
    text = """```json
    {
      "table_model": {
        "row_count": 1,
        "col_count": 2,
        "cells": [
          {"row": 0, "col": 0, "text": "招标编号", "rowspan": 1, "colspan": 1},
          {"row": 0, "col": 1, "text": "包号", "rowspan": 1, "colspan": 1}
        ]
      }
    }
    ```"""

    model = _parse_table_model_text(text)

    assert model["row_count"] == 1
    assert model["col_count"] == 2
    assert model["cells"][0]["text"] == "招标编号"


def test_parse_table_model_text_accepts_qwen_list_rows_json() -> None:
    text = """```json
    [
      ["本企业人员基本信息", "国家电网公司系统人员基本信息"],
      ["人员姓名", "性别", "身份证号"],
      ["无", "—", "—"]
    ]
    ```"""

    model = _parse_table_model_text(text)

    assert model["source"] == "vlm_rows_json"
    assert model["row_count"] == 3
    assert model["col_count"] == 3
    assert model["rows"] == [
        ["本企业人员基本信息", "国家电网公司系统人员基本信息", ""],
        ["人员姓名", "性别", "身份证号"],
        ["无", "—", "—"],
    ]
    assert model["cells"][0] == {
        "row": 0,
        "col": 0,
        "text": "本企业人员基本信息",
        "rowspan": 1,
        "colspan": 1,
        "bbox": None,
    }


def test_parse_table_model_text_expands_wrong_row_and_col_counts_from_cells() -> None:
    text = """{
      "row_count": 4,
      "col_count": 12,
      "cells": [
        {"row": 0, "col": 0, "text": "本企业人员基本信息", "rowspan": 1, "colspan": 6},
        {"row": 0, "col": 6, "text": "国家电网公司系统人员基本信息", "rowspan": 1, "colspan": 7},
        {"row": 1, "col": 12, "text": "离职/退休时间", "rowspan": 1, "colspan": 1},
        {"row": 2, "col": 12, "text": "—", "rowspan": 1, "colspan": 1}
      ],
      "merged_cells": []
    }"""

    model = _parse_table_model_text(text)

    assert model["row_count"] == 3
    assert model["col_count"] == 13
    assert len(model["rows"]) == 3
    assert all(len(row) == 13 for row in model["rows"])
    assert model["rows"][2][12] == "—"


def test_enhance_tables_with_vlm_updates_table_model_and_keeps_raw_response(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    table = ParsedTable(
        table_id="table-1",
        page_no=1,
        rows=[],
        bbox=[10, 20, 110, 120],
    )

    def fake_render(*, pdf_path, table, out_dir, zoom):
        image_path = Path(out_dir) / "table-1.png"
        image_path.write_bytes(b"fake-png")
        return image_path

    def fake_post(_endpoint, headers=None, json=None, timeout=None):
        assert json["max_tokens"] == 4096
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": '{"row_count":1,"col_count":1,"cells":[{"row":0,"col":0,"text":"272608","rowspan":1,"colspan":1}]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._render_table_crop", fake_render)
    monkeypatch.setattr("requests.post", fake_post)

    enhanced = enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=[table],
        out_dir=tmp_path / "vlm_tables",
        endpoint="http://127.0.0.1:8118/v1/chat/completions",
        model="PaddleOCR-VL-1.5",
        max_tokens=4096,
    )

    assert enhanced[0].table_model_source == "paddleocr_vl"
    assert enhanced[0].table_model["cells"][0]["text"] == "272608"
    assert enhanced[0].vlm_table_model["row_count"] == 1
    assert enhanced[0].vlm_raw_response["choices"][0]["message"]["content"]
    assert enhanced[0].table_image_path.endswith("table-1.png")


def test_call_vlm_table_model_omits_authorization_when_api_key_is_missing(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "table.png"
    image_path.write_bytes(b"fake-png")
    captured_headers = {}

    def fake_post(_endpoint, headers=None, json=None, timeout=None):
        captured_headers.update(headers or {})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": '{"row_count":1,"col_count":1,"cells":[{"row":0,"col":0,"text":"无","rowspan":1,"colspan":1}]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    table_model, _raw = _call_vlm_table_model(
        image_path=image_path,
        endpoint="http://127.0.0.1:8688/v1/chat/completions",
        model="Qwen3.6-27B",
    )

    assert table_model["rows"] == [["无"]]
    assert "Authorization" not in captured_headers


def test_call_vlm_table_model_adds_bearer_authorization_when_api_key_is_present(tmp_path: Path, monkeypatch) -> None:
    image_path = tmp_path / "table.png"
    image_path.write_bytes(b"fake-png")
    captured_headers = {}

    def fake_post(_endpoint, headers=None, json=None, timeout=None):
        captured_headers.update(headers or {})
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": '{"row_count":1,"col_count":1,"cells":[{"row":0,"col":0,"text":"包05","rowspan":1,"colspan":1}]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("requests.post", fake_post)

    table_model, _raw = _call_vlm_table_model(
        image_path=image_path,
        endpoint="https://api.example.com/v1/chat/completions",
        model="external-vlm",
        api_key="sk-test",
    )

    assert table_model["rows"] == [["包05"]]
    assert captured_headers["Authorization"] == "Bearer sk-test"


def test_enhance_tables_with_vlm_reads_api_key_from_custom_env_var(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    table = ParsedTable(
        table_id="table-1",
        page_no=1,
        rows=[],
        bbox=[10, 20, 110, 120],
    )
    seen_api_keys: list[str | None] = []

    def fake_render(*, pdf_path, table, out_dir, zoom):
        image_path = Path(out_dir) / "table-1.png"
        image_path.write_bytes(b"fake-png")
        return image_path

    def fake_call(*, image_path, endpoint, model, api_key=None, request_timeout=180, max_tokens=4096):
        seen_api_keys.append(api_key)
        return (
            {
                "row_count": 1,
                "col_count": 1,
                "rows": [["ok"]],
                "cells": [{"row": 0, "col": 0, "text": "ok", "rowspan": 1, "colspan": 1}],
                "merged_cells": [],
            },
            {"id": "ok"},
        )

    monkeypatch.setenv("QWEN_VL_API_KEY", "custom-key")
    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._render_table_crop", fake_render)
    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._call_vlm_table_model", fake_call)

    enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=[table],
        out_dir=tmp_path / "vlm_tables",
        endpoint="https://api.example.com/v1/chat/completions",
        model="external-vlm",
        api_key_env="QWEN_VL_API_KEY",
    )

    assert seen_api_keys == ["custom-key"]


def test_enhance_tables_with_vlm_reuses_existing_candidate_crop(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    crop_path = tmp_path / "debug_table_regions" / "region-1.png"
    crop_path.parent.mkdir()
    crop_path.write_bytes(b"fake-png")
    table = ParsedTable(
        table_id="region-1",
        page_no=1,
        rows=[],
        bbox=[10, 20, 110, 120],
        table_image_path=str(crop_path),
    )

    def fail_render(*_, **__):
        raise AssertionError("existing candidate crop should be reused")

    def fake_post(_endpoint, headers=None, json=None, timeout=None):
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {
                "choices": [
                    {
                        "message": {
                            "content": '{"row_count":1,"col_count":1,"cells":[{"row":0,"col":0,"text":"包05","rowspan":1,"colspan":1}]}'
                        }
                    }
                ]
            },
        )

    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._render_table_crop", fail_render)
    monkeypatch.setattr("requests.post", fake_post)

    enhanced = enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=[table],
        out_dir=tmp_path / "vlm_tables",
        endpoint="http://127.0.0.1:8118/v1/chat/completions",
        model="PaddleOCR-VL-1.5",
    )

    assert enhanced[0].table_image_path == str(crop_path)
    assert enhanced[0].table_model["cells"][0]["text"] == "包05"


def test_enhance_tables_with_vlm_calls_model_even_for_reliable_pdfplumber_geometry_table(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    table_model = {
        "schema_version": "table_model_v1",
        "source": "pdfplumber_geometry",
        "row_count": 3,
        "col_count": 13,
        "rows": [["本企业人员基本信息", "", "", "", "", "", "国家电网公司系统人员基本信息"], ["人员姓名"], ["无"]],
        "cells": [
            {"row": 0, "col": 0, "text": "本企业人员基本信息", "rowspan": 1, "colspan": 6},
            {"row": 0, "col": 6, "text": "国家电网公司系统人员基本信息", "rowspan": 1, "colspan": 7},
            {"row": 1, "col": 0, "text": "人员姓名", "rowspan": 1, "colspan": 1},
            {"row": 2, "col": 0, "text": "无", "rowspan": 1, "colspan": 1},
        ],
        "merged_cells": [
            {"row": 0, "col": 0, "rowspan": 1, "colspan": 6},
            {"row": 0, "col": 6, "rowspan": 1, "colspan": 7},
        ],
        "preserves_spans": True,
    }
    table = ParsedTable(
        table_id="pdfplumber-table",
        page_no=1,
        rows=table_model["rows"],
        bbox=[10, 20, 110, 120],
        table_model=table_model,
    )

    calls: list[str] = []

    crop_path = tmp_path / "reliable-table.png"
    crop_path.write_bytes(b"fake-png")

    def record_render(*_, **__):
        calls.append("render")
        return crop_path

    def record_call(*_, **__):
        calls.append("call")
        return (
            {
                "source": "paddleocr_vl",
                "row_count": 1,
                "col_count": 2,
                "rows": [["VLM", "结果"]],
                "cells": [{"row": 0, "col": 0, "text": "VLM", "rowspan": 1, "colspan": 1}],
                "merged_cells": [],
            },
            {"id": "vlm-ok"},
        )

    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._render_table_crop", record_render)
    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._call_vlm_table_model", record_call)

    enhanced = enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=[table],
        out_dir=tmp_path / "vlm_tables",
        endpoint="http://127.0.0.1:8688/v1/chat/completions",
        model="Qwen3.6-27B",
    )

    assert enhanced[0].table_id == "pdfplumber-table"
    assert enhanced[0].table_model["source"] == "paddleocr_vl"
    assert enhanced[0].table_model["rows"] == [["VLM", "结果"]]
    assert calls == ["render", "call"]
    assert not getattr(enhanced[0], "vlm_error", None)
    assert enhanced[0].vlm_raw_response == {"id": "vlm-ok"}


def test_enhance_tables_with_vlm_calls_model_for_low_quality_pdfplumber_geometry(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    crop_path = tmp_path / "debug_table_regions" / "page574.png"
    crop_path.parent.mkdir()
    crop_path.write_bytes(b"fake-png")
    table_model = {
        "schema_version": "table_model_v1",
        "source": "pdfplumber_geometry",
        "row_count": 2,
        "col_count": 1,
        "rows": [["绩效评价结果查询"], ["内容"]],
        "cells": [
            {"row": 0, "col": 0, "text": "绩效评价结果查询", "rowspan": 1, "colspan": 1},
            {"row": 1, "col": 0, "text": "内容", "rowspan": 1, "colspan": 1},
        ],
        "merged_cells": [],
        "preserves_spans": False,
    }
    table = ParsedTable(
        table_id="table-group_afaf31f7e922",
        page_no=574,
        rows=table_model["rows"],
        bbox=[5.6, 167.6, 835.8, 438.2],
        table_model=table_model,
        table_image_path=str(crop_path),
        candidate_detectors=["pdfplumber", "pp_structure"],
    )
    calls: list[str] = []

    def fake_call(*, image_path, endpoint, model, api_key=None, request_timeout=180, max_tokens=4096):
        calls.append(str(image_path))
        return (
            {
                "source": "paddleocr_vl",
                "row_count": 3,
                "col_count": 4,
                "rows": [["项目", "结果", "等级", "时间"], ["绩效", "优秀", "A", "2024"], ["备注", "", "", ""]],
                "cells": [{"row": 0, "col": 0, "text": "项目", "rowspan": 1, "colspan": 1}],
                "merged_cells": [],
            },
            {"id": "vlm-ok"},
        )

    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._call_vlm_table_model", fake_call)

    enhanced = enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=[table],
        out_dir=tmp_path / "vlm_tables",
        endpoint="http://127.0.0.1:8688/v1/chat/completions",
        model="Qwen3.6-27B",
    )

    assert calls == [str(crop_path)]
    assert enhanced[0].table_model["source"] == "paddleocr_vl"
    assert enhanced[0].table_model["row_count"] == 3
    assert enhanced[0].vlm_raw_response == {"id": "vlm-ok"}


def test_enhance_tables_with_vlm_calls_model_for_sparse_fragmented_wide_pdfplumber_geometry(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    crop_path = tmp_path / "debug_table_regions" / "page579.png"
    crop_path.parent.mkdir()
    crop_path.write_bytes(b"fake-png")
    rows = [
        ["", "", "", "序", "", "", "", "", "出具", "", "出具的报告名称", "", ""],
        ["", "号", "", "", "年份", "", "", "", "", "", "", "时间", ""],
        ["", "1", "", "", "", "", "", "", "", "", "", "", ""],
        ["2", "", "", "", "", "", "", "2025", "", "", "运行及评价证明", "", ""],
        ["3", "", "", "", "", "", "", "2022", "", "", "履约评价证明", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", ""],
    ]
    cells = [
        {"row": row_index, "col": col_index, "text": text, "rowspan": 1, "colspan": 1}
        for row_index, row in enumerate(rows)
        for col_index, text in enumerate(row)
    ]
    table_model = {
        "schema_version": "table_model_v1",
        "source": "pdfplumber_geometry",
        "row_count": len(rows),
        "col_count": 13,
        "rows": rows,
        "cells": cells,
        "merged_cells": [],
        "preserves_spans": False,
    }
    table = ParsedTable(
        table_id="table-group_8642dd7bfff8-p1",
        page_no=579,
        rows=rows,
        bbox=[35.4, 44.3, 559.0, 767.0],
        table_model=table_model,
        table_image_path=str(crop_path),
        candidate_detectors=["pp_structure"],
    )
    calls: list[str] = []

    def fake_call(*, image_path, endpoint, model, api_key=None, request_timeout=180, max_tokens=4096):
        calls.append(str(image_path))
        return (
            {
                "source": "paddleocr_vl",
                "row_count": 3,
                "col_count": 4,
                "rows": [["序号", "年份", "出具的报告名称", "出具时间"], ["1", "2025", "运行及评价证明", ""]],
                "cells": [{"row": 0, "col": 0, "text": "序号", "rowspan": 1, "colspan": 1}],
                "merged_cells": [],
            },
            {"id": "vlm-ok"},
        )

    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._call_vlm_table_model", fake_call)

    enhanced = enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=[table],
        out_dir=tmp_path / "vlm_tables",
        endpoint="http://127.0.0.1:8688/v1/chat/completions",
        model="Qwen3.6-27B",
    )

    assert calls == [str(crop_path)]
    assert enhanced[0].table_model["source"] == "paddleocr_vl"
    assert enhanced[0].table_model["rows"][0] == ["序号", "年份", "出具的报告名称", "出具时间"]


def test_enhance_tables_with_vlm_writes_incremental_results_as_each_table_finishes(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")
    tables = [
        ParsedTable(table_id="table-1", page_no=1, rows=[], bbox=[10, 20, 110, 120]),
        ParsedTable(table_id="table-2", page_no=1, rows=[], bbox=[120, 20, 220, 120]),
    ]
    incremental_path = tmp_path / "tables.json"
    writes: list[list[dict]] = []
    lock = Lock()

    def fake_render(*, pdf_path, table, out_dir, zoom):
        image_path = Path(out_dir) / f"{table.table_id}.png"
        image_path.write_bytes(b"fake-png")
        return image_path

    def fake_call(*, image_path, endpoint, model, api_key=None, request_timeout=180, max_tokens=4096):
        table_id = Path(image_path).stem
        return (
            {
                "row_count": 1,
                "col_count": 1,
                "rows": [[table_id]],
                "cells": [{"row": 0, "col": 0, "text": table_id, "rowspan": 1, "colspan": 1}],
                "merged_cells": [],
            },
            {"id": table_id},
        )

    def fake_write_json(path, data):
        with lock:
            writes.append([item.model_dump() if hasattr(item, "model_dump") else item for item in data])
        from bid_knowledge.utils.io_utils import write_json as real_write_json

        return real_write_json(path, data)

    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._render_table_crop", fake_render)
    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor._call_vlm_table_model", fake_call)
    monkeypatch.setattr("bid_knowledge.parsing.vlm_table_extractor.write_json", fake_write_json)

    enhanced = enhance_tables_with_vlm(
        pdf_path=pdf_path,
        tables=tables,
        out_dir=tmp_path / "vlm_tables",
        endpoint="http://127.0.0.1:8688/v1/chat/completions",
        model="Qwen3.6-27B",
        incremental_out_path=incremental_path,
        workers=2,
    )

    assert len(writes) == 2
    written_with_vlm = [item for snapshot in writes for item in snapshot if item.get("vlm_raw_response")]
    assert any(item["vlm_raw_response"]["id"] == "table-1" for item in written_with_vlm)
    assert [table.table_model["rows"][0][0] for table in enhanced] == ["table-1", "table-2"]
    saved = read_json(incremental_path)
    assert [item["table_model"]["rows"][0][0] for item in saved] == ["table-1", "table-2"]
