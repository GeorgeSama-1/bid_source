import zipfile
from pathlib import Path

from bid_knowledge.export.lightweight_material_pack import export_lightweight_material_pack


def test_export_lightweight_material_pack_keeps_material_markdown_and_images_only(tmp_path: Path) -> None:
    output_dir = tmp_path / "outputs" / "structure_run"
    material_dir = output_dir / "modules" / "补充文件" / "材料A"
    image_dir = material_dir / "image_items"
    text_dir = material_dir / "text_items"
    original_dir = material_dir / "original"
    image_dir.mkdir(parents=True)
    text_dir.mkdir()
    original_dir.mkdir()
    (material_dir / "material.md").write_text("![图1](image_items/图1.png)\n", encoding="utf-8")
    (material_dir / "material_meta.json").write_text("{}", encoding="utf-8")
    (image_dir / "图1.png").write_bytes(b"png")
    (image_dir / "图1.json").write_text("{}", encoding="utf-8")
    (text_dir / "材料A.md").write_text("text", encoding="utf-8")
    (original_dir / "source_pages.pdf").write_bytes(b"pdf")

    result = export_lightweight_material_pack(output_dir)

    package_dir = Path(result["package_dir"])
    zip_path = Path(result["zip_path"])
    assert result["material_count"] == 1
    assert result["image_count"] == 1
    assert (package_dir / "modules" / "补充文件" / "材料A" / "material.md").exists()
    assert (package_dir / "modules" / "补充文件" / "材料A" / "image_items" / "图1.png").exists()
    assert not (package_dir / "modules" / "补充文件" / "材料A" / "image_items" / "图1.json").exists()
    assert not (package_dir / "modules" / "补充文件" / "材料A" / "material_meta.json").exists()
    assert not (package_dir / "modules" / "补充文件" / "材料A" / "text_items").exists()
    assert not (package_dir / "modules" / "补充文件" / "材料A" / "original").exists()

    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
    assert "modules/补充文件/材料A/material.md" in names
    assert "modules/补充文件/材料A/image_items/图1.png" in names
    assert "modules/补充文件/材料A/image_items/图1.json" not in names
