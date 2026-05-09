from pathlib import Path
from threading import Lock
from types import SimpleNamespace

from bid_knowledge.parsing.vlm_table_extractor import (
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
