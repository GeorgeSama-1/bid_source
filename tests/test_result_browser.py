import json
from pathlib import Path

import pytest

from bid_knowledge.service.result_browser import ResultBrowser, ResultNotFoundError


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def make_sample_outputs(root: Path) -> Path:
    outputs = root / "outputs"
    material = outputs / "history_run" / "modules" / "商务模块" / "材料A"
    write_json(material / "material_meta.json", {"material_title": "材料A"})
    write_json(
        material / "ordered_material.json",
        {
            "material_title": "材料A",
            "items": [
                {"type": "text", "text": "第一段"},
                {
                    "type": "table",
                    "table_title": "表1",
                    "json_path": str(material / "table_items" / "表1.json"),
                },
                {
                    "type": "image",
                    "image_title": "图1",
                    "file_path": str(material / "image_items" / "图1.png"),
                    "json_path": str(material / "image_items" / "图1.json"),
                },
                {
                    "type": "submaterial",
                    "title": "子材料",
                    "path": str(material / "submaterials" / "子材料"),
                },
            ],
        },
    )
    write_json(material / "table_items" / "表1.json", {"rows": [["a", "b"]]})
    write_json(material / "image_items" / "图1.json", {"image_title": "图1"})
    (material / "image_items" / "图1.png").write_bytes(b"png")
    (outputs / "history_run" / "parsed").mkdir(parents=True)
    (outputs / "not_a_run").mkdir()
    return outputs


def test_lists_runs_with_modules_directory(tmp_path: Path) -> None:
    outputs = make_sample_outputs(tmp_path)

    runs = ResultBrowser(outputs).list_runs()

    assert [run["name"] for run in runs] == ["history_run"]


def test_builds_module_tree_and_marks_materials(tmp_path: Path) -> None:
    outputs = make_sample_outputs(tmp_path)

    tree = ResultBrowser(outputs).get_module_tree("history_run")

    assert tree["name"] == "modules"
    module = tree["children"][0]
    material = module["children"][0]
    assert module["name"] == "商务模块"
    assert material["name"] == "材料A"
    assert material["is_material"] is True
    assert material["path"] == "商务模块/材料A"


def test_reads_material_meta_and_enriches_ordered_image_and_submaterial(tmp_path: Path) -> None:
    outputs = make_sample_outputs(tmp_path)
    browser = ResultBrowser(outputs)

    assert browser.get_material_meta("history_run", "商务模块/材料A") == {"material_title": "材料A"}
    ordered = browser.get_ordered_material("history_run", "商务模块/材料A")

    assert [item["type"] for item in ordered["items"]] == ["text", "table", "image", "submaterial"]
    image = ordered["items"][2]
    assert image["preview_url"].startswith("/api/runs/history_run/images?path=")
    assert image["image_path"] == "商务模块/材料A/image_items/图1.png"
    assert ordered["items"][3]["target_material_path"] == "商务模块/材料A/submaterials/子材料"


def test_reads_item_detail_and_blocks_path_escape(tmp_path: Path) -> None:
    outputs = make_sample_outputs(tmp_path)
    browser = ResultBrowser(outputs)

    detail = browser.get_item_detail("history_run", "商务模块/材料A", "table", "表1.json")
    assert detail == {"rows": [["a", "b"]]}

    with pytest.raises(ResultNotFoundError):
        browser.get_material_meta("history_run", "../outside")
