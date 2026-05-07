import json
import sys
from types import SimpleNamespace
from pathlib import Path

from bid_knowledge.parsing.module_packager import package_module_artifacts
from bid_knowledge.schemas.models import PageMaterialItem, ParsedTable, PdfTextBlock, ReusableCandidate


def _candidate(
    section_path: str,
    source_page: int,
    source_page_end: int,
    source_container_title: str,
    *,
    from_history_bid: bool = True,
    has_standard_template: bool = False,
) -> ReusableCandidate:
    return ReusableCandidate(
        candidate_id=f"cand-{source_page}",
        company_id="demo_company",
        document_id="demo_doc",
        rule_id=f"rule-{source_page}",
        section_path=section_path,
        from_history_bid=from_history_bid,
        has_standard_template=has_standard_template,
        title=section_path.split(" / ")[-1],
        content="",
        candidate_type="attachment",
        reuse_method="附件召回",
        reuse_level="long_term",
        enter_long_term_library=True,
        source_file="demo.pdf",
        source_page=source_page,
        source_page_end=source_page_end,
        source_container_title=source_container_title,
    )


def _write_demo_pdf(path: Path, page_count: int) -> Path:
    import fitz

    doc = fitz.open()
    try:
        for index in range(page_count):
            page = doc.new_page()
            page.insert_text((72, 72), f"demo page {index + 1}")
        doc.save(path)
    finally:
        doc.close()
    return path


def test_package_module_artifacts_exports_named_items_under_module(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 商务评分标准涉及的支撑材料 / 一、履约能力评价 / 经营状况",
            100,
            101,
            "3.8.1.2 企业整体经营状况优良",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=100, text="3.8.1.2 企业整体经营状况优良", bbox=[0, 10, 100, 20], block_no=1),
        PdfTextBlock(block_id="b2", page_no=100, text="（1）、企业发展稳健", bbox=[0, 30, 100, 40], block_no=2),
        PdfTextBlock(block_id="b3", page_no=101, text="（2）、具备优秀的团队", bbox=[0, 20, 100, 30], block_no=3),
    ]
    tables = [
        ParsedTable(table_id="table-1", page_no=101, rows=[["姓名", "岗位"]], bbox=[10, 40, 200, 180]),
    ]
    images = [
        {"image_id": "img-1", "page_no": 100, "xref": 10, "width": 500, "height": 400, "rect": [10, 50, 150, 120], "ext": "jpeg"},
        {"image_id": "img-2", "page_no": 100, "xref": 11, "width": 500, "height": 400, "rect": [10, 130, 150, 200], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
    )

    module_dir = tmp_path / "modules" / "商务评分标准涉及的支撑材料" / "一、履约能力评价" / "经营状况"
    assert module_dir.exists()
    assert (module_dir / "section_meta.json").exists()
    assert (module_dir / "tables.json").exists()
    assert (module_dir / "images.json").exists()

    table_item = module_dir / "table_items" / "具备优秀的团队_表1.json"
    image_item_1 = module_dir / "image_items" / "企业发展稳健_图1.json"
    image_item_2 = module_dir / "image_items" / "企业发展稳健_图2.json"
    image_file_1 = module_dir / "image_items" / "企业发展稳健_图1.jpeg"
    image_file_2 = module_dir / "image_items" / "企业发展稳健_图2.jpeg"

    assert table_item.exists()
    assert image_item_1.exists()
    assert image_item_2.exists()
    assert image_file_1.exists()
    assert image_file_2.exists()


def test_package_module_artifacts_uses_previous_page_heading_when_current_page_has_no_new_heading(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人（单位负责人）身份证（扫描件）",
            200,
            201,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=200, text="（3.1）、安全生产标准化证书", bbox=[0, 20, 100, 30], block_no=1),
    ]
    images = [
        {"image_id": "img-1", "page_no": 201, "xref": 20, "width": 600, "height": 500, "rect": [10, 40, 150, 180], "ext": "png"},
        {"image_id": "img-2", "page_no": 201, "xref": 21, "width": 600, "height": 500, "rect": [10, 190, 150, 330], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    module_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人（单位负责人）身份证（扫描件）" / "image_items"
    assert (module_dir / "安全生产标准化证书_图1.json").exists()
    assert (module_dir / "安全生产标准化证书_图2.json").exists()


def test_package_module_artifacts_skips_non_history_items_and_writes_template_capture(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 商务评分标准涉及的支撑材料 / 一、履约能力评价 / 售后服务",
            10,
            10,
            "3.8.2 售后服务",
            from_history_bid=True,
            has_standard_template=True,
        ),
        _candidate(
            "商务文件 / 商务评分标准涉及的支撑材料 / 二、高质量发展评价 / 绿色发展",
            11,
            11,
            "3.9.1 绿色发展",
            from_history_bid=False,
        ),
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=10, text="（1）、售后服务承诺", bbox=[0, 10, 100, 20], block_no=1),
        PdfTextBlock(block_id="b2", page_no=10, text="承诺内容正文", bbox=[0, 30, 100, 40], block_no=2),
        PdfTextBlock(block_id="b3", page_no=11, text="绿色发展", bbox=[0, 10, 100, 20], block_no=3),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        top_level_modules=["商务偏差表", "投标保证保险", "补充文件", "法定代表人授权委托书"],
    )

    kept_dir = tmp_path / "modules" / "商务评分标准涉及的支撑材料" / "一、履约能力评价" / "售后服务"
    skipped_dir = tmp_path / "modules" / "商务评分标准涉及的支撑材料" / "二、高质量发展评价" / "绿色发展"
    assert kept_dir.exists()
    assert not skipped_dir.exists()
    assert (kept_dir / "source_capture.json").exists()
    assert (tmp_path / "modules" / "商务偏差表").exists()
    assert (tmp_path / "modules" / "投标保证保险").exists()


def test_package_module_artifacts_precreates_empty_history_tree_dirs(tmp_path: Path) -> None:
    package_module_artifacts(
        candidates=[],
        blocks=[],
        tables=[],
        images=[],
        out_dir=tmp_path,
        top_level_modules=["商务偏差表", "投标保证保险", "补充文件", "法定代表人授权委托书"],
        planned_section_paths=[
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 一、履约能力评价 / 经营状况",
            "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表 / 利润表",
            "商务文件 / 法定代表人授权委托书 / 被授权人身份证等有效身份证件（扫描件）",
        ],
    )

    assert (tmp_path / "modules" / "商务偏差表" / "module_meta.json").exists()
    assert (tmp_path / "modules" / "投标保证保险" / "module_meta.json").exists()
    assert (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "一、履约能力评价"
        / "经营状况"
        / "section_meta.json"
    ).exists()
    assert (
        tmp_path
        / "modules"
        / "补充文件"
        / "财务状况"
        / "经会计师事务所或审计机构审计的财务会计报表"
        / "利润表"
        / "section_meta.json"
    ).exists()
    assert (
        tmp_path
        / "modules"
        / "法定代表人授权委托书"
        / "被授权人身份证等有效身份证件（扫描件）"
        / "section_meta.json"
    ).exists()
    empty_material_md = (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "一、履约能力评价"
        / "经营状况"
        / "material.md"
    ).read_text(encoding="utf-8")
    assert empty_material_md.startswith("# 经营状况")
    assert "暂无可直接复用内容" in empty_material_md


def test_package_module_artifacts_filters_repeated_header_logo_images(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 一、履约能力评价 / 经营状况",
            1,
            20,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="（1.1）、部分业主出具的运行报告16份", bbox=[0, 80, 100, 90], block_no=1),
    ]
    repeated_logo = [
        {
            "image_id": f"logo-{page}",
            "page_no": page,
            "xref": 16,
            "width": 154,
            "height": 70,
            "rect": [72.0, 30.4, 122.5, 53.3],
            "ext": "png",
        }
        for page in range(1, 21)
    ]
    real_image = {
        "image_id": "real-1",
        "page_no": 1,
        "xref": 200,
        "width": 1200,
        "height": 800,
        "rect": [100.0, 160.0, 420.0, 360.0],
        "ext": "jpeg",
    }

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=repeated_logo + [real_image],
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    image_dir = tmp_path / "modules" / "补充文件" / "“商务评分标准”涉及的支撑材料" / "一、履约能力评价" / "经营状况" / "image_items"
    exported = sorted(path.name for path in image_dir.glob("*.json"))

    assert "部分业主出具的运行报告16份_图1.json" in exported
    assert all("logo" not in name.lower() for name in exported)
    assert len(exported) == 1


def test_package_module_artifacts_filters_items_inside_pp_layout_masks(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / 企业名称变更",
            1,
            1,
            "企业名称变更",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="header", page_no=1, text="国网甘肃省电力公司 商务投标文件", bbox=[20, 20, 500, 40], block_no=1),
        PdfTextBlock(block_id="body", page_no=1, text="企业名称变更正文", bbox=[20, 120, 500, 150], block_no=2),
        PdfTextBlock(block_id="footer", page_no=1, text="22", bbox=[290, 760, 310, 780], block_no=3),
    ]
    tables = [
        ParsedTable(table_id="body-table", page_no=1, rows=[["项目", "内容"]], bbox=[20, 180, 500, 260]),
    ]
    images = [
        {"image_id": "header-logo", "page_no": 1, "xref": 10, "width": 300, "height": 80, "rect": [20, 10, 160, 60], "ext": "png"},
        {"image_id": "body-image", "page_no": 1, "xref": 11, "width": 600, "height": 500, "rect": [20, 320, 260, 520], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
        layout_masks=[
            {"page_no": 1, "label": "header", "bbox": [0, 0, 600, 80], "page_width": 600, "page_height": 800},
            {"page_no": 1, "label": "number", "bbox": [0, 740, 600, 800], "page_width": 600, "page_height": 800},
        ],
    )

    material_dir = tmp_path / "modules" / "补充文件" / "企业名称变更"
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")
    image_files = sorted(path.name for path in (material_dir / "image_items").glob("*.png"))

    assert "国网甘肃省电力公司" not in material_md
    assert "\n22\n" not in material_md
    assert "企业名称变更正文" in material_md
    assert "| 项目 | 内容 |" in material_md
    assert "| --- | --- |" in material_md
    assert image_files == ["企业名称变更_图1.png"]


def test_package_module_artifacts_filters_repeated_page_header_text(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / 企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
            22,
            23,
            "3.4、企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
        )
    ]
    header = "国网甘肃省电力公司【测控及在线监测系统】包05、包06、包07、包08——商务投标文件"
    blocks = [
        PdfTextBlock(block_id="h22", page_no=22, text=header, bbox=[824, 23, 1666, 48], block_no=1),
        PdfTextBlock(block_id="b22", page_no=22, text="企业营业执照副本", bbox=[700, 140, 950, 163], block_no=2),
        PdfTextBlock(block_id="h23", page_no=23, text=header, bbox=[824, 23, 1666, 48], block_no=1),
        PdfTextBlock(block_id="b23", page_no=23, text="统一社会信用代码 913302007251641924", bbox=[180, 240, 900, 260], block_no=2),
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-header-22",
            item_type="text",
            source_type="pp_structure_text_region",
            page_no=22,
            top_y=23,
            bbox=[824, 23, 1666, 48],
            text=header,
            payload={"layout_label": "header"},
        ),
        PageMaterialItem(
            item_id="pp-body-22",
            item_type="text",
            source_type="pp_structure_text_region",
            page_no=22,
            top_y=140,
            bbox=[700, 140, 950, 163],
            text="企业营业执照副本",
            payload={"layout_label": "text"},
        ),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        page_material_items=page_material_items,
    )

    ordered_path = (
        tmp_path
        / "modules"
        / "补充文件"
        / "企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）"
        / "ordered_material.json"
    )
    ordered = json.loads(ordered_path.read_text(encoding="utf-8"))
    dumped = json.dumps(ordered, ensure_ascii=False)

    assert header not in dumped
    assert "企业营业执照副本" in dumped


def test_package_module_artifacts_assigns_stream_image_to_nearest_body_heading(tmp_path: Path, monkeypatch) -> None:
    pdf_path = tmp_path / "source.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class FakePixmap:
        def save(self, path: str | Path) -> None:
            Path(path).write_bytes(b"fake-cropped-image")

    class FakePage:
        rect = SimpleNamespace(width=300.0, height=300.0)

        def get_pixmap(self, **kwargs):
            if "clip" in kwargs:
                assert kwargs["clip"].x0 > 0
            return FakePixmap()

    class FakeDoc:
        page_count = 1

        def load_page(self, index: int) -> FakePage:
            assert index == 0
            return FakePage()

        def insert_pdf(self, *_args, **_kwargs) -> None:
            return None

        def save(self, path: str | Path) -> None:
            Path(path).write_bytes(b"fake-pdf")

        def close(self) -> None:
            return None

    class FakeRect:
        def __init__(self, x0, y0, x1, y1):
            self.x0 = x0
            self.y0 = y0
            self.x1 = x1
            self.y1 = y1

    monkeypatch.setitem(sys.modules, "fitz", SimpleNamespace(open=lambda *_args, **_kwargs: FakeDoc(), Rect=FakeRect, Matrix=lambda *_args: None))

    candidates = [
        _candidate(
            "商务文件 / 补充文件 / 企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
            1,
            1,
            "3.4、企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
        )
    ]
    header = "国网甘肃省电力公司【测控及在线监测系统】包05、包06、包07、包08——商务投标文件"
    blocks = [
        PdfTextBlock(block_id="h22", page_no=1, text=header, bbox=[824, 23, 1666, 48], block_no=1),
        PdfTextBlock(
            block_id="title22",
            page_no=1,
            text="3.4、企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）",
            bbox=[20, 90, 950, 117],
            block_no=2,
        ),
        PdfTextBlock(
            block_id="seat-title",
            page_no=1,
            text="（1）座位图片",
            bbox=[20, 150, 300, 170],
            block_no=3,
        ),
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-image-1",
            item_type="image",
            source_type="pp_structure_image_region",
            page_no=1,
            top_y=200,
            bbox=[164, 200, 1502, 1024],
            text="",
            payload={"layout_label": "image", "page_width": 1684, "page_height": 1191},
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        pdf_path=pdf_path,
        page_material_items=page_material_items,
    )

    ordered_path = (
        tmp_path
        / "modules"
        / "补充文件"
        / "企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）"
        / "ordered_material.json"
    )
    ordered = json.loads(ordered_path.read_text(encoding="utf-8"))
    stream_image = next(item for item in ordered["items"] if item.get("item_id") == "pp-image-1")

    assert stream_image["nearest_heading"] == "座位图片"
    assert header not in stream_image["nearest_heading"]
    assert stream_image["file_path"].endswith("image_items/座位图片_图1.png")
    material_md = (
        tmp_path
        / "modules"
        / "补充文件"
        / "企业营业执照（或事业单位法人证书或其他组织登记证书）（扫描件）"
        / "material.md"
    ).read_text(encoding="utf-8")
    assert "![座位图片_图1](image_items/座位图片_图1.png)" in material_md


def test_package_module_artifacts_assigns_attachment_stream_image_to_fu_heading(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人授权委托书",
            1,
            1,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="4、法定代表人授权委托书", bbox=[0, 20, 300, 40], block_no=1),
        PdfTextBlock(block_id="b2", page_no=1, text="授权正文", bbox=[0, 80, 300, 100], block_no=2),
        PdfTextBlock(block_id="b3", page_no=1, text="附：被授权人身份证等有效身份证件（扫描件）", bbox=[0, 120, 300, 140], block_no=3),
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-image-id-card",
            item_type="image",
            source_type="pp_structure_image_region",
            page_no=1,
            top_y=180,
            bbox=[10, 180, 500, 420],
            text="",
            payload={"layout_label": "image"},
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        page_material_items=page_material_items,
    )

    child_ordered_path = (
        tmp_path
        / "modules"
        / "法定代表人授权委托书"
        / "法定代表人授权委托书"
        / "submaterials"
        / "被授权人身份证等有效身份证件（扫描件）"
        / "ordered_material.json"
    )
    child_ordered = json.loads(child_ordered_path.read_text(encoding="utf-8"))
    stream_image = next(item for item in child_ordered["items"] if item.get("item_id") == "pp-image-id-card")

    assert stream_image["nearest_heading"] == "附：被授权人身份证等有效身份证件（扫描件）"


def test_package_module_artifacts_does_not_name_image_from_bid_package_context(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人（单位负责人）身份证（扫描件）",
            1,
            1,
            "测控及在线监测系统）（包号：包05、包06、包07、包08）（包名称：测控及在线监测系统）",
        )
    ]
    blocks = [
        PdfTextBlock(
            block_id="package-context",
            page_no=1,
            text="测控及在线监测系统）（包号：包05、包06、包07、包08）（包名称：测控及在线监测系统）",
            bbox=[0, 80, 500, 100],
            block_no=1,
        ),
    ]
    images = [
        {"image_id": "id-card", "page_no": 1, "xref": 20, "width": 600, "height": 500, "rect": [10, 200, 500, 420], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    image_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人（单位负责人）身份证（扫描件）" / "image_items"
    exported = sorted(path.name for path in image_dir.glob("*.json"))

    assert exported == ["法定代表人（单位负责人）身份证（扫描件）_图1.json"]


def test_package_module_artifacts_scopes_planned_authorization_attachment_to_matching_fu_anchor(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人（单位负责人）身份证（扫描件）",
            1,
            1,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="4、法定代表人授权委托书", bbox=[0, 20, 300, 40], block_no=1),
        PdfTextBlock(block_id="b2", page_no=1, text="附：法定代表人（单位负责人）身份证（扫描件）", bbox=[0, 100, 300, 120], block_no=2),
        PdfTextBlock(block_id="b3", page_no=1, text="法人身份证文字", bbox=[0, 140, 300, 160], block_no=3),
        PdfTextBlock(block_id="b4", page_no=1, text="附：被授权人身份证等有效身份证件（扫描件）", bbox=[0, 300, 300, 320], block_no=4),
        PdfTextBlock(block_id="b5", page_no=1, text="被授权人身份证文字", bbox=[0, 340, 300, 360], block_no=5),
    ]
    images = [
        {"image_id": "legal-id", "page_no": 1, "xref": 21, "width": 600, "height": 500, "rect": [10, 180, 500, 260], "ext": "png"},
        {"image_id": "agent-id", "page_no": 1, "xref": 22, "width": 600, "height": 500, "rect": [10, 380, 500, 460], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    section_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人（单位负责人）身份证（扫描件）"
    ordered = json.loads((section_dir / "ordered_material.json").read_text(encoding="utf-8"))
    dumped = json.dumps(ordered, ensure_ascii=False)
    exported_images = sorted(path.name for path in (section_dir / "image_items").glob("*.json"))

    assert "被授权人身份证" not in dumped
    assert exported_images == ["法定代表人（单位负责人）身份证（扫描件）_图1.json"]


def test_package_module_artifacts_keeps_two_id_card_sides_and_filters_seal(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人（单位负责人）身份证（扫描件）",
            1,
            1,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="4、法定代表人授权委托书", bbox=[0, 20, 300, 40], block_no=1),
        PdfTextBlock(block_id="b2", page_no=1, text="附：法定代表人（单位负责人）身份证（扫描件）", bbox=[0, 100, 300, 120], block_no=2),
        PdfTextBlock(block_id="b3", page_no=1, text="身份证正反面", bbox=[0, 130, 300, 150], block_no=3),
        PdfTextBlock(block_id="b4", page_no=1, text="附：被授权人身份证等有效身份证件（扫描件）", bbox=[0, 520, 300, 540], block_no=4),
    ]
    images = [
        {"image_id": "front", "page_no": 1, "xref": 31, "width": 900, "height": 560, "rect": [10, 170, 420, 300], "ext": "png"},
        {"image_id": "back", "page_no": 1, "xref": 32, "width": 900, "height": 560, "rect": [10, 320, 420, 450], "ext": "png"},
        {"image_id": "seal", "page_no": 1, "xref": 33, "width": 180, "height": 180, "rect": [450, 220, 510, 280], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    image_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人（单位负责人）身份证（扫描件）" / "image_items"
    exported_json = sorted(path.name for path in image_dir.glob("*.json"))
    exported = [json.loads((image_dir / name).read_text(encoding="utf-8")) for name in exported_json]

    assert exported_json == [
        "法定代表人（单位负责人）身份证（扫描件）_图1.json",
        "法定代表人（单位负责人）身份证（扫描件）_图2.json",
    ]
    assert [item["image_id"] for item in exported] == ["front", "back"]
    assert [item["rect"] for item in exported] == [[10, 170, 420, 300], [10, 320, 420, 450]]


def test_package_module_artifacts_filters_tiny_artifact_images(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / 符合招标文件投标人资格要求的证明文件 / 符合招标公告投标人资格要求的证明文件",
            24,
            24,
            "3.6、符合招标文件投标人资格要求的证明文件",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=24, text="3.6.1、符合投标文件投标人资格要求的证明文件", bbox=[0, 80, 100, 90], block_no=1),
    ]
    tiny_artifact = {
        "image_id": "artifact-1",
        "page_no": 24,
        "xref": 1145,
        "width": 129,
        "height": 25,
        "rect": [72.36, 122.04, 118.98, 131.22],
        "ext": "png",
    }
    real_image = {
        "image_id": "real-1",
        "page_no": 24,
        "xref": 300,
        "width": 900,
        "height": 600,
        "rect": [90.0, 180.0, 420.0, 500.0],
        "ext": "jpeg",
    }

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[tiny_artifact, real_image],
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    image_dir = (
        tmp_path
        / "modules"
        / "补充文件"
        / "符合招标文件投标人资格要求的证明文件"
        / "符合招标公告投标人资格要求的证明文件"
        / "image_items"
    )
    exported = sorted(path.name for path in image_dir.glob("*.json"))

    assert exported == ["符合投标文件投标人资格要求的证明文件_图1.json"]


def test_package_module_artifacts_creates_review_index_subfolders(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 一、履约能力评价 / 经营状况",
            574,
            640,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="b1", page_no=574, text="（1）、绩效评价结果查询", bbox=[0, 100, 100, 110], block_no=1),
        PdfTextBlock(block_id="b2", page_no=627, text="（1）、企业发展稳健", bbox=[0, 100, 100, 110], block_no=2),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["一、履约能力评价", "经营状况", "", "详见第574页：3.8.1.1、企业履约能力强", ""],
                ["", "", "", "第627页：3.8.1.2、企业整体经营状况优良", ""],
            ],
        ),
        ParsedTable(table_id="real-table-1", page_no=574, rows=[["名称", "分值"]], bbox=[0, 120, 200, 180]),
        ParsedTable(table_id="real-table-2", page_no=627, rows=[["指标", "说明"]], bbox=[0, 120, 200, 180]),
    ]
    images = [
        {"image_id": "img-1", "page_no": 574, "xref": 200, "width": 800, "height": 600, "rect": [10, 200, 210, 340], "ext": "jpeg"},
        {"image_id": "img-2", "page_no": 627, "xref": 201, "width": 800, "height": 600, "rect": [10, 200, 210, 340], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
    )

    base = tmp_path / "modules" / "补充文件" / "“商务评分标准”涉及的支撑材料" / "一、履约能力评价" / "经营状况"
    sub_1 = base / "3.8.1.1、企业履约能力强"
    sub_2 = base / "3.8.1.2、企业整体经营状况优良"
    assert (sub_1 / "table_items" / "绩效评价结果查询_表1.json").exists()
    assert (sub_1 / "image_items" / "绩效评价结果查询_图1.json").exists()
    assert (sub_2 / "table_items" / "企业发展稳健_表1.json").exists()
    assert (sub_2 / "image_items" / "企业发展稳健_图1.json").exists()
    parent_markdown = (base / "material.md").read_text(encoding="utf-8")
    assert parent_markdown.startswith("# 经营状况")
    assert "[3.8.1.1、企业履约能力强](3.8.1.1、企业履约能力强/material.md)" in parent_markdown
    assert "[3.8.1.2、企业整体经营状况优良](3.8.1.2、企业整体经营状况优良/material.md)" in parent_markdown


def test_package_module_artifacts_expands_pages_using_review_index_ranges(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 一、履约能力评价 / 经营状况",
            574,
            627,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="b1", page_no=628, text="（2）、具备优秀的团队", bbox=[0, 100, 100, 110], block_no=1),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["一、履约能力评价", "经营状况", "", "详见第574页：3.8.1.1、企业履约能力强", ""],
                ["", "", "", "第627页：3.8.1.2、企业整体经营状况优良", ""],
                ["", "售后服务", "", "详见第641页：3.8.2、售后服务", ""],
            ],
        ),
        ParsedTable(table_id="real-table-2", page_no=628, rows=[["指标", "说明"]], bbox=[0, 120, 200, 180]),
    ]
    images = [
        {"image_id": "img-2", "page_no": 628, "xref": 201, "width": 800, "height": 600, "rect": [10, 200, 210, 340], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
    )

    sub_2 = (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "一、履约能力评价"
        / "经营状况"
        / "3.8.1.2、企业整体经营状况优良"
    )
    assert (sub_2 / "table_items" / "具备优秀的团队_表1.json").exists()
    assert (sub_2 / "image_items" / "具备优秀的团队_图1.json").exists()


def test_package_module_artifacts_applies_review_index_to_other_score_elements(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 一、履约能力评价 / 售后服务",
            641,
            641,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="b1", page_no=641, text="（1）、制定完善的售后服务方案", bbox=[0, 100, 100, 110], block_no=1),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["一、履约能力评价", "经营状况", "", "详见第574页：3.8.1.1、企业履约能力强", ""],
                ["", "售后服务", "", "详见第641页：3.8.2、售后服务", ""],
            ],
        ),
        ParsedTable(table_id="real-table-1", page_no=641, rows=[["服务", "内容"]], bbox=[0, 120, 200, 180]),
    ]
    images = [
        {"image_id": "img-1", "page_no": 641, "xref": 201, "width": 800, "height": 600, "rect": [10, 200, 210, 340], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
    )

    subfolder = (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "一、履约能力评价"
        / "售后服务"
        / "3.8.2、售后服务"
    )
    assert (subfolder / "table_items" / "制定完善的售后服务方案_表1.json").exists()
    assert (subfolder / "image_items" / "制定完善的售后服务方案_图1.json").exists()


def test_package_module_artifacts_does_not_apply_review_index_outside_score_materials(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / 企业名称变更",
            574,
            574,
            "3.9、投标人自述的企业名称变更原因说明",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="b1", page_no=574, text="3.9.2、2007年企业名称变更证明材料", bbox=[0, 100, 100, 110], block_no=1),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["一、履约能力评价", "经营状况", "", "详见第574页：3.8.1.1、企业履约能力强", ""],
            ],
        )
    ]
    images = [
        {"image_id": "img-1", "page_no": 574, "xref": 201, "width": 800, "height": 600, "rect": [10, 200, 210, 340], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
    )

    section_dir = tmp_path / "modules" / "补充文件" / "企业名称变更"
    assert (section_dir / "image_items" / "2007年企业名称变更证明材料_图1.json").exists()
    assert not (section_dir / "3.8.1.1、企业履约能力强").exists()


def test_package_module_artifacts_maps_review_index_elements_to_excel_paths(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 研发团队规模",
            769,
            770,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="b1", page_no=771, text="3.8.10.2、职称证书37人", bbox=[0, 100, 100, 110], block_no=1),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["一、履约能力评价", "经营状况", "", "详见第574页：3.8.1.1、企业履约能力强", ""],
                ["", "研发团队规模", "", "详见第769页：3.8.10、研发团队规模", ""],
                ["", "", "", "第771页：3.8.10.2、职称证书37人", ""],
            ],
        ),
        ParsedTable(table_id="real-table-1", page_no=771, rows=[["姓名", "职称"]], bbox=[0, 120, 200, 180]),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=[],
        out_dir=tmp_path,
        planned_section_paths=[
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 研发团队规模",
        ],
    )

    subfolder = (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "二、高质量发展评价"
        / "研发团队规模"
        / "3.8.10.2、职称证书37人"
    )
    assert (subfolder / "table_items" / "职称证书37人_表1.json").exists()


def test_package_module_artifacts_uses_heading_y_bounds_for_cross_page_index_items(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 绿色发展规划",
            706,
            707,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="h1", page_no=706, text="3.8.4.1、绿色发展顶层规划", bbox=[0, 100, 100, 110], block_no=1),
        PdfTextBlock(block_id="h2", page_no=707, text="3.8.4.2、绿色发展执行情况", bbox=[0, 200, 100, 210], block_no=2),
        PdfTextBlock(block_id="before-h2", page_no=707, text="上一小节跨页延续内容", bbox=[0, 120, 100, 130], block_no=3),
        PdfTextBlock(block_id="after-h2", page_no=707, text="下一小节内容", bbox=[0, 240, 100, 250], block_no=4),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["二、高质量发展评价", "绿色发展规划", "", "详见第706页：3.8.4.1、绿色发展顶层规划", ""],
                ["", "", "", "第707页：3.8.4.2、绿色发展执行情况", ""],
            ],
        ),
        ParsedTable(table_id="cross-page-table", page_no=707, rows=[["跨页", "内容"]], bbox=[0, 140, 200, 180]),
        ParsedTable(table_id="next-table", page_no=707, rows=[["执行", "情况"]], bbox=[0, 260, 200, 300]),
    ]
    images = [
        {"image_id": "img-before", "page_no": 707, "xref": 301, "width": 800, "height": 600, "rect": [10, 150, 210, 190], "ext": "jpeg"},
        {"image_id": "img-after", "page_no": 707, "xref": 302, "width": 800, "height": 600, "rect": [10, 270, 210, 330], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
    )

    base = tmp_path / "modules" / "补充文件" / "“商务评分标准”涉及的支撑材料" / "二、高质量发展评价" / "绿色发展规划"
    sub_1 = base / "3.8.4.1、绿色发展顶层规划"
    sub_2 = base / "3.8.4.2、绿色发展执行情况"
    assert (sub_1 / "table_items" / "绿色发展顶层规划_表1.json").exists()
    assert (sub_1 / "image_items" / "绿色发展顶层规划_图1.json").exists()
    assert (sub_2 / "table_items" / "绿色发展执行情况_表1.json").exists()
    assert (sub_2 / "image_items" / "绿色发展执行情况_图1.json").exists()


def test_package_module_artifacts_writes_text_items_for_review_index_text_sections(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 创新激励机制、供应链保障措施",
            803,
            807,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="h1", page_no=803, text="3.8.13.2、供应链保障措施", bbox=[0, 100, 100, 110], block_no=1),
        PdfTextBlock(
            block_id="p1",
            page_no=803,
            text="公司建立供应链风险识别机制，\n并制定供应链保障措施。",
            bbox=[0, 130, 200, 180],
            block_no=2,
        ),
        PdfTextBlock(block_id="h2", page_no=808, text="3.8.14、数智化评价", bbox=[0, 100, 100, 110], block_no=3),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["二、高质量发展评价", "创新激励机制、供应链保障措施", "", "详见第803页：3.8.13.2、供应链保障措施", ""],
                ["", "数智化评价", "", "详见第808页：3.8.14、数智化评价", ""],
            ],
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=[],
        out_dir=tmp_path,
    )

    text_dir = (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "二、高质量发展评价"
        / "创新激励机制、供应链保障措施"
        / "3.8.13.2、供应链保障措施"
        / "text_items"
    )
    json_path = text_dir / "供应链保障措施.json"
    md_path = text_dir / "供应链保障措施.md"

    assert json_path.exists()
    assert md_path.exists()
    assert "供应链风险识别机制" in md_path.read_text(encoding="utf-8")


def test_package_module_artifacts_writes_complete_material_package_for_review_index_section(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 创新激励机制、供应链保障措施",
            3,
            4,
            "3.8、招标文件第三章评标办法前附表之三“商务评分标准”涉及的支撑材料",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="idx-title", page_no=2, text="商务评审索引表", bbox=[0, 0, 10, 10], block_no=1),
        PdfTextBlock(block_id="h1", page_no=3, text="3.8.13.2、供应链保障措施", bbox=[0, 100, 100, 110], block_no=1),
        PdfTextBlock(block_id="p1", page_no=3, text="供应链保障正文", bbox=[0, 130, 200, 180], block_no=2),
        PdfTextBlock(block_id="h2", page_no=5, text="3.8.14、数智化评价", bbox=[0, 100, 100, 110], block_no=3),
    ]
    tables = [
        ParsedTable(
            table_id="index-table",
            page_no=2,
            rows=[
                ["项目", "评审要素", "评审细则", "", ""],
                ["二、高质量发展评价", "创新激励机制、供应链保障措施", "", "详见第3页：3.8.13.2、供应链保障措施", ""],
                ["", "数智化评价", "", "详见第5页：3.8.14、数智化评价", ""],
            ],
        ),
        ParsedTable(table_id="material-table", page_no=3, rows=[["措施", "说明"]], bbox=[10, 190, 200, 240]),
    ]
    images = [
        {"image_id": "img-1", "page_no": 3, "xref": 10, "width": 500, "height": 400, "rect": [10, 260, 150, 360], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
        planned_section_paths=[
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 创新激励机制、供应链保障措施",
            "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 数智化评价",
        ],
    )

    material_dir = (
        tmp_path
        / "modules"
        / "补充文件"
        / "“商务评分标准”涉及的支撑材料"
        / "二、高质量发展评价"
        / "创新激励机制、供应链保障措施"
        / "3.8.13.2、供应链保障措施"
    )
    meta = json.loads((material_dir / "material_meta.json").read_text(encoding="utf-8"))
    ordered = json.loads((material_dir / "ordered_material.json").read_text(encoding="utf-8"))

    assert meta["source_page_start"] == 3
    assert meta["source_page_end"] == 5
    assert meta["source_end_y"] == 100.0
    assert meta["original_capture"]["available"] is False
    assert meta["text_item_count"] == 1
    assert meta["table_item_count"] == 1
    assert meta["image_item_count"] == 1
    assert meta["material_path"] == "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 创新激励机制、供应链保障措施 / 3.8.13.2、供应链保障措施"
    assert meta["rule_section_path"] == "商务文件 / 补充文件 / “商务评分标准”涉及的支撑材料 / 二、高质量发展评价 / 创新激励机制、供应链保障措施"
    assert meta["rule_module_name"] == "补充文件"
    assert meta["material_types"] == ["text", "table", "image"]
    assert meta["dominant_material_type"] == "mixed"
    assert meta["raw_context_title"] == "3.8.13.2、供应链保障措施"
    assert meta["title_mapping"]["raw_context_title"] == "3.8.13.2、供应链保障措施"
    assert meta["title_mapping"]["material_title"] == "3.8.13.2、供应链保障措施"
    assert ordered["material_path"] == meta["material_path"]
    assert ordered["rule_section_path"] == meta["rule_section_path"]
    assert ordered["material_types"] == ["text", "table", "image"]
    assert ordered["dominant_material_type"] == "mixed"
    assert [item["type"] for item in ordered["items"]] == ["text", "text", "table", "image"]
    assert ordered["items"][0]["block_id"] == "h1"
    assert [item["order"] for item in ordered["items"]] == [1, 2, 3, 4]
    assert ordered["items"][0]["item_type"] == "text"
    assert ordered["items"][0]["payload_ref"] == "text_items/供应链保障措施.json"
    assert ordered["items"][0]["nearest_heading"] == "3.8.13.2、供应链保障措施"
    assert ordered["items"][0]["rule_section_path"] == meta["rule_section_path"]
    assert ordered["items"][2]["item_type"] == "table"
    assert ordered["items"][2]["payload_ref"].endswith("json")
    assert ordered["items"][3]["item_type"] == "image"
    assert ordered["items"][3]["payload_ref"].endswith("json")
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")
    assert "3.8.13.2、供应链保障措施" in material_md
    assert "供应链保障正文" in material_md
    assert "![供应链保障措施_图1](image_items/供应链保障措施_图1.png)" in material_md
    assert meta["material_markdown_path"] == "material.md"


def test_package_module_artifacts_writes_complete_section_markdown_with_table_and_image_refs(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 补充文件 / 企业名称变更",
            1,
            1,
            "企业名称变更",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="h1", page_no=1, text="企业名称变更", bbox=[0, 80, 200, 100], block_no=1, font_size=16),
        PdfTextBlock(block_id="p1", page_no=1, text="公司名称已完成变更。", bbox=[0, 120, 300, 140], block_no=2, font_size=10),
        PdfTextBlock(block_id="p2", page_no=1, text="相关证明如下。", bbox=[0, 320, 300, 340], block_no=3, font_size=10),
    ]
    tables = [
        ParsedTable(table_id="name-change-table", page_no=1, rows=[["变更前", "变更后"], ["旧公司", "新公司"]], bbox=[10, 180, 300, 260]),
    ]
    images = [
        {"image_id": "proof-img", "page_no": 1, "xref": 20, "width": 600, "height": 500, "rect": [10, 360, 300, 520], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=tables,
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    material_dir = tmp_path / "modules" / "补充文件" / "企业名称变更"
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")

    assert material_md.startswith("# 企业名称变更")
    assert "公司名称已完成变更。" in material_md
    assert "相关证明如下。" in material_md
    assert "| 变更前 | 变更后 |" in material_md
    assert "| --- | --- |" in material_md
    assert "| 旧公司 | 新公司 |" in material_md
    assert "[表格：企业名称变更_表1]" not in material_md
    assert "![企业名称变更_图1](image_items/企业名称变更_图1.png)" in material_md
    assert material_md.index("公司名称已完成变更。") < material_md.index("| 变更前 | 变更后 |")
    assert material_md.index("| 旧公司 | 新公司 |") < material_md.index("相关证明如下。")
    assert material_md.index("相关证明如下。") < material_md.index("![企业名称变更_图1]")
    assert (material_dir / "table_items" / "企业名称变更_表1.json").exists()
    assert (material_dir / "image_items" / "企业名称变更_图1.png").exists()


def test_package_module_artifacts_scopes_toc_leaf_sections_by_same_page_y_bounds(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "PDF / 3、 补充文件 / 3.1、 投标保证金 / 3.1.1、 汇款凭证",
            1,
            1,
            "3.1、 投标保证金",
        ),
        _candidate(
            "PDF / 3、 补充文件 / 3.1、 投标保证金 / 3.1.2、 投标保证金银行保函（无、本项目采用电汇）",
            1,
            1,
            "3.1、 投标保证金",
        ),
        _candidate(
            "PDF / 3、 补充文件 / 3.1、 投标保证金 / 3.1.3、 银行基本账户证明扫描件",
            1,
            1,
            "3.1、 投标保证金",
        ),
    ]
    candidates[0].material_evidence = {"start_y": 100.0, "end_y": 300.0, "start_block_id": "h311", "end_block_id": "h312"}
    candidates[1].material_evidence = {"start_y": 300.0, "end_y": 500.0, "start_block_id": "h312", "end_block_id": "h313"}
    candidates[2].material_evidence = {"start_y": 500.0, "end_y": None, "start_block_id": "h313", "end_block_id": None}
    blocks = [
        PdfTextBlock(block_id="p", page_no=1, text="3、补充文件", bbox=[0, 20, 200, 40], block_no=1),
        PdfTextBlock(block_id="p31", page_no=1, text="3.1、投标保证金", bbox=[0, 60, 200, 80], block_no=2),
        PdfTextBlock(block_id="h311", page_no=1, text="3.1.1、汇款凭证", bbox=[0, 100, 200, 120], block_no=3),
        PdfTextBlock(block_id="h312", page_no=1, text="3.1.2、投标保证金银行保函（无、本项目采用电汇）", bbox=[0, 300, 400, 320], block_no=4),
        PdfTextBlock(block_id="h313", page_no=1, text="3.1.3、银行基本账户证明扫描件", bbox=[0, 500, 300, 520], block_no=5),
    ]
    images = [
        {"image_id": "transfer", "page_no": 1, "xref": 10, "width": 600, "height": 500, "rect": [20, 150, 300, 260], "ext": "jpeg"},
        {"image_id": "bank", "page_no": 1, "xref": 11, "width": 600, "height": 500, "rect": [20, 560, 300, 700], "ext": "jpeg"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "jpeg")),
        top_level_modules=["3、 补充文件"],
        planned_section_paths=[candidate.section_path for candidate in candidates],
    )

    base = tmp_path / "modules" / "3、 补充文件" / "3.1、 投标保证金"
    guarantee_md = (base / "3.1.2、 投标保证金银行保函（无、本项目采用电汇）" / "material.md").read_text(encoding="utf-8")
    transfer_md = (base / "3.1.1、 汇款凭证" / "material.md").read_text(encoding="utf-8")

    assert "3.1.2、投标保证金银行保函" in guarantee_md
    assert "汇款凭证_图1" not in guarantee_md
    assert "银行基本账户证明扫描件_图1" not in guarantee_md
    assert "3.1.1、汇款凭证" not in guarantee_md
    assert "3.1.3、银行基本账户证明扫描件" not in guarantee_md
    assert "![汇款凭证_图1](image_items/汇款凭证_图1.jpeg)" in transfer_md


def test_package_module_artifacts_deduplicates_pdf_and_pp_structure_text_in_markdown(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 投标保证保险",
            1,
            1,
            "投标保证保险",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="投标保证保险正文", bbox=[0, 100, 300, 120], block_no=1),
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-text-1",
            item_type="text",
            source_type="pp_structure_text_region",
            page_no=1,
            top_y=100,
            bbox=[0, 100, 300, 120],
            text="投标保证保险正文",
            payload={"ocr_texts": ["投标保证保险正文"]},
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        page_material_items=page_material_items,
    )

    material_md = (tmp_path / "modules" / "投标保证保险" / "material.md").read_text(encoding="utf-8")
    assert material_md.count("投标保证保险正文") == 1


def test_package_module_artifacts_keeps_pp_ocr_text_out_of_material_markdown(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 企业营业执照扫描件",
            1,
            1,
            "企业营业执照扫描件",
        )
    ]
    images = [
        {"image_id": "license", "page_no": 1, "xref": 31, "width": 900, "height": 560, "rect": [10, 170, 420, 300], "ext": "png"},
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-text-license",
            item_type="text",
            source_type="pp_structure_text_region",
            page_no=1,
            top_y=180,
            bbox=[10, 180, 420, 280],
            text="营业执照\n统一社会信用代码 913302007251641924",
            payload={"ocr_texts": ["营业执照", "统一社会信用代码 913302007251641924"]},
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=[],
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"pdf-image", item.get("ext", "png")),
        page_material_items=page_material_items,
    )

    material_dir = tmp_path / "modules" / "企业营业执照扫描件"
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")
    ordered = json.loads((material_dir / "ordered_material.json").read_text(encoding="utf-8"))

    assert "统一社会信用代码" not in material_md
    assert "![企业营业执照扫描件_图1](image_items/企业营业执照扫描件_图1.png)" in material_md
    assert any(item.get("item_id") == "pp-text-license" for item in ordered["items"])


def test_package_module_artifacts_writes_authorization_identity_attachment_as_images_only_with_pp_text(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 被授权人身份证等有效身份证件（扫描件）",
            1,
            1,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="附：被授权人身份证等有效身份证件（扫描件）", bbox=[0, 80, 300, 100], block_no=1),
        PdfTextBlock(block_id="b2", page_no=1, text="姓名 张三", bbox=[0, 120, 300, 140], block_no=2),
    ]
    images = [
        {"image_id": "front", "page_no": 1, "xref": 31, "width": 900, "height": 560, "rect": [10, 170, 420, 300], "ext": "png"},
        {"image_id": "back", "page_no": 1, "xref": 32, "width": 900, "height": 560, "rect": [10, 320, 420, 450], "ext": "png"},
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-text-id",
            item_type="text",
            source_type="pp_structure_text_region",
            page_no=1,
            top_y=120,
            bbox=[0, 120, 300, 140],
            text="姓名 张三\n身份证号 330000000000000000",
            payload={"ocr_texts": ["姓名 张三", "身份证号 330000000000000000"]},
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
        page_material_items=page_material_items,
    )

    material_dir = tmp_path / "modules" / "法定代表人授权委托书" / "被授权人身份证等有效身份证件（扫描件）"
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")
    assert material_md.count("![") == 2
    assert "姓名 张三" not in material_md
    assert "身份证号" not in material_md
    assert "被授权人身份证等有效身份证件（扫描件）_图1.png" in material_md
    assert "被授权人身份证等有效身份证件（扫描件）_图2.png" in material_md


def test_package_module_artifacts_writes_image_only_material_markdown_in_order(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人（单位负责人）身份证（扫描件）",
            1,
            1,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="附：法定代表人（单位负责人）身份证（扫描件）", bbox=[0, 100, 300, 120], block_no=1),
    ]
    images = [
        {"image_id": "front", "page_no": 1, "xref": 31, "width": 900, "height": 560, "rect": [10, 170, 420, 300], "ext": "png"},
        {"image_id": "back", "page_no": 1, "xref": 32, "width": 900, "height": 560, "rect": [10, 320, 420, 450], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    material_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人（单位负责人）身份证（扫描件）"
    material_md = (material_dir / "material.md").read_text(encoding="utf-8")
    image_lines = [line for line in material_md.splitlines() if line.startswith("![")]

    assert image_lines == [
        "![法定代表人（单位负责人）身份证（扫描件）_图1](image_items/法定代表人（单位负责人）身份证（扫描件）_图1.png)",
        "![法定代表人（单位负责人）身份证（扫描件）_图2](image_items/法定代表人（单位负责人）身份证（扫描件）_图2.png)",
    ]
    assert "```json" not in material_md


def test_package_module_artifacts_packages_compound_financial_reports_by_detected_instances_and_children(tmp_path: Path) -> None:
    anchor = "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表"
    candidates = [
        _candidate(
            f"{anchor} / 利润表",
            10,
            25,
            "财务状况",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="i2022", page_no=10, text="2022年度财务报表", bbox=[0, 80, 200, 95], block_no=1, font_size=16),
        PdfTextBlock(block_id="generic2022", page_no=10, text="财务报表", bbox=[0, 100, 160, 115], block_no=2, font_size=15),
        PdfTextBlock(block_id="toc2022", page_no=11, text="目录", bbox=[0, 80, 100, 95], block_no=2, font_size=15),
        PdfTextBlock(block_id="profit2022", page_no=12, text="利润表", bbox=[0, 80, 100, 95], block_no=3, font_size=15),
        PdfTextBlock(block_id="note2022", page_no=13, text="财务报表附注", bbox=[0, 80, 120, 95], block_no=4, font_size=15),
        PdfTextBlock(block_id="i2023", page_no=20, text="2023年度财务报表", bbox=[0, 80, 200, 95], block_no=5, font_size=16),
        PdfTextBlock(block_id="toc2023", page_no=21, text="目录", bbox=[0, 80, 100, 95], block_no=6, font_size=15),
        PdfTextBlock(block_id="profit2023", page_no=22, text="利润表", bbox=[0, 80, 100, 95], block_no=7, font_size=15),
    ]
    images = [
        {"image_id": "toc-img", "page_no": 11, "xref": 101, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
        {"image_id": "profit-img", "page_no": 12, "xref": 102, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
        {"image_id": "note-img", "page_no": 13, "xref": 103, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
        {"image_id": "profit-2023-img", "page_no": 22, "xref": 104, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
        compound_material_rules=[
            {
                "excel_anchor_path": anchor,
                "instance_title_patterns": [r"20\d{2}.*财务报表"],
                "auto_detect_children": True,
                "store_unlisted_children": True,
            }
        ],
    )

    base = tmp_path / "modules" / "补充文件" / "财务状况" / "经会计师事务所或审计机构审计的财务会计报表"
    instance_meta = json.loads((base / "2022年度财务报表" / "compound_instance_meta.json").read_text(encoding="utf-8"))
    anchor_markdown = (base / "material.md").read_text(encoding="utf-8")
    instance_markdown = (base / "2022年度财务报表" / "material.md").read_text(encoding="utf-8")
    assert anchor_markdown.startswith("# 经会计师事务所或审计机构审计的财务会计报表")
    assert "[2022年度财务报表](2022年度财务报表/material.md)" in anchor_markdown
    assert "[2023年度财务报表](2023年度财务报表/material.md)" in anchor_markdown
    assert instance_markdown.startswith("# 2022年度财务报表")
    assert "[财务报表](财务报表/material.md)" not in instance_markdown
    assert "[目录](目录/material.md)" in instance_markdown
    assert "[利润表](利润表/material.md)" in instance_markdown
    assert (base / "2022年度财务报表" / "目录" / "image_items" / "目录_图1.json").exists()
    assert (base / "2022年度财务报表" / "利润表" / "image_items" / "利润表_图1.json").exists()
    assert (base / "2022年度财务报表" / "财务报表附注" / "image_items" / "财务报表附注_图1.json").exists()
    assert (base / "2023年度财务报表" / "利润表" / "image_items" / "利润表_图1.json").exists()
    assert not (base / "2022年度财务报表" / "财务报表").exists()
    assert not (base / "利润表" / "image_items" / "目录_图1.json").exists()
    assert instance_meta["instance_path"] == "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表 / 2022年度财务报表"
    assert instance_meta["rule_anchor_path"] == anchor
    assert instance_meta["children"][0]["material_path"].endswith("/ 目录")
    assert instance_meta["children"][0]["material_types"] == ["text", "image"]
    assert instance_meta["children"][0]["dominant_material_type"] == "mixed"


def test_package_module_artifacts_uses_excel_instance_layer_for_compound_financial_reports(tmp_path: Path) -> None:
    anchor = "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表"
    candidates = [
        _candidate(f"{anchor} / 3.7.1、2022 年度财务审计报告 / 封面", 10, 10, "财务状况"),
        _candidate(f"{anchor} / 3.7.1、2022 年度财务审计报告 / 利润表", 12, 12, "财务状况"),
        _candidate(f"{anchor} / 3.7.2、2023 年度财务审计报告 / 封面", 20, 20, "财务状况"),
    ]
    blocks = [
        PdfTextBlock(block_id="cover2022", page_no=10, text="封面正文", bbox=[0, 80, 200, 95], block_no=1, font_size=10),
        PdfTextBlock(block_id="profit2022", page_no=12, text="利润表正文", bbox=[0, 80, 200, 95], block_no=2, font_size=10),
        PdfTextBlock(block_id="cover2023", page_no=20, text="封面正文", bbox=[0, 80, 200, 95], block_no=3, font_size=10),
    ]
    images = [
        {"image_id": "cover-img", "page_no": 10, "xref": 101, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
        {"image_id": "profit-img", "page_no": 12, "xref": 102, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
        {"image_id": "cover-2023-img", "page_no": 20, "xref": 103, "width": 600, "height": 500, "rect": [20, 120, 300, 360], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
        compound_material_rules=[
            {
                "excel_anchor_path": anchor,
                "instance_title_patterns": [r"20\d{2}.*(?:财务|审计).*报告"],
                "auto_detect_children": True,
                "store_unlisted_children": True,
            }
        ],
    )

    base = tmp_path / "modules" / "补充文件" / "财务状况" / "经会计师事务所或审计机构审计的财务会计报表"
    anchor_markdown = (base / "material.md").read_text(encoding="utf-8")
    instance_markdown = (base / "3.7.1、2022 年度财务审计报告" / "material.md").read_text(encoding="utf-8")
    instance_meta = json.loads((base / "3.7.1、2022 年度财务审计报告" / "compound_instance_meta.json").read_text(encoding="utf-8"))

    assert "[3.7.1、2022 年度财务审计报告](3.7.1、2022 年度财务审计报告/material.md)" in anchor_markdown
    assert "[封面](封面/material.md)" in instance_markdown
    assert "[利润表](利润表/material.md)" in instance_markdown
    assert (base / "3.7.1、2022 年度财务审计报告" / "封面" / "image_items" / "封面_图1.json").exists()
    assert (base / "3.7.1、2022 年度财务审计报告" / "利润表" / "image_items" / "利润表_图1.json").exists()
    assert not (base / "封面").exists()
    assert instance_meta["instance_title"] == "3.7.1、2022 年度财务审计报告"
    assert instance_meta["children"][0]["material_path"].endswith("/ 3.7.1、2022 年度财务审计报告 / 封面")


def test_package_module_artifacts_keeps_planned_compound_paths_when_no_compound_instance_was_built(tmp_path: Path) -> None:
    anchor = "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表"

    package_module_artifacts(
        candidates=[],
        blocks=[],
        tables=[],
        images=[],
        out_dir=tmp_path,
        planned_section_paths=[
            f"{anchor} / 3.7.1、2022 年度财务审计报告 / 封面",
            f"{anchor} / 3.7.1、2022 年度财务审计报告 / 利润表",
        ],
        compound_material_rules=[
            {
                "excel_anchor_path": anchor,
                "instance_title_patterns": [r"20\d{2}.*(?:财务|审计).*报告"],
                "auto_detect_children": True,
                "store_unlisted_children": True,
            }
        ],
    )

    base = tmp_path / "modules" / "补充文件" / "财务状况" / "经会计师事务所或审计机构审计的财务会计报表"
    assert (base / "material.md").exists()
    assert (base / "3.7.1、2022 年度财务审计报告" / "封面" / "material.md").exists()
    assert (base / "3.7.1、2022 年度财务审计报告" / "利润表" / "material.md").exists()


def test_package_module_artifacts_keeps_matched_compound_child_when_no_instance_was_built(tmp_path: Path) -> None:
    anchor = "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表"
    candidates = [
        _candidate(f"{anchor} / 利润表", 12, 12, "财务状况"),
    ]
    blocks = [
        PdfTextBlock(block_id="profit2022", page_no=12, text="利润表正文", bbox=[0, 80, 200, 95], block_no=1, font_size=10),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        compound_material_rules=[
            {
                "excel_anchor_path": anchor,
                "instance_title_patterns": [r"20\d{2}.*(?:财务|审计).*报告"],
                "auto_detect_children": True,
                "store_unlisted_children": True,
            }
        ],
    )

    base = tmp_path / "modules" / "补充文件" / "财务状况" / "经会计师事务所或审计机构审计的财务会计报表"
    assert (base / "利润表" / "material.md").exists()
    assert "利润表正文" in (base / "利润表" / "material.md").read_text(encoding="utf-8")


def test_package_module_artifacts_uses_candidate_container_as_compound_instance(tmp_path: Path) -> None:
    anchor = "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表"
    candidates = [
        _candidate(f"{anchor} / 利润表", 12, 12, "3.7.1、2022 年度财务审计报告"),
        _candidate(f"{anchor} / 资产负债表", 11, 11, "3.7.1、2022 年度财务审计报告"),
    ]
    blocks = [
        PdfTextBlock(block_id="balance2022", page_no=11, text="资产负债表正文", bbox=[0, 80, 200, 95], block_no=1, font_size=10),
        PdfTextBlock(block_id="profit2022", page_no=12, text="利润表正文", bbox=[0, 80, 200, 95], block_no=2, font_size=10),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        compound_material_rules=[
            {
                "excel_anchor_path": anchor,
                "instance_title_patterns": [r"20\d{2}.*(?:财务|审计).*报告"],
                "auto_detect_children": True,
                "store_unlisted_children": True,
            }
        ],
    )

    base = tmp_path / "modules" / "补充文件" / "财务状况" / "经会计师事务所或审计机构审计的财务会计报表"
    assert (base / "3.7.1、2022 年度财务审计报告" / "利润表" / "material.md").exists()
    assert (base / "3.7.1、2022 年度财务审计报告" / "资产负债表" / "material.md").exists()
    assert not (base / "利润表").exists()
    assert "利润表正文" in (base / "3.7.1、2022 年度财务审计报告" / "利润表" / "material.md").read_text(encoding="utf-8")


def test_package_module_artifacts_ignores_pp_structure_titles_for_financial_instance_headings(tmp_path: Path) -> None:
    anchor = "商务文件 / 补充文件 / 财务状况 / 经会计师事务所或审计机构审计的财务会计报表"
    candidates = [
        _candidate(f"{anchor} / 利润表", 12, 22, "财务状况"),
    ]
    blocks = [
        PdfTextBlock(block_id="status-title", page_no=9, text="财务状况", bbox=[0, 80, 200, 95], block_no=1, font_size=16),
        PdfTextBlock(block_id="profit2022", page_no=12, text="利润表正文", bbox=[0, 130, 200, 150], block_no=2, font_size=10),
        PdfTextBlock(block_id="profit2023", page_no=22, text="利润表正文", bbox=[0, 130, 200, 150], block_no=3, font_size=10),
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-instance-2022",
            item_type="text",
            source_type="pp_structure_text",
            page_no=10,
            top_y=80,
            bbox=[0, 80, 300, 100],
            text="3.7.1、2022 年度财务审计报告",
            payload={"layout_label": "doc_title"},
        ),
        PageMaterialItem(
            item_id="pp-child-2022",
            item_type="text",
            source_type="pp_structure_text",
            page_no=12,
            top_y=80,
            bbox=[0, 80, 120, 100],
            text="利润表",
            payload={"layout_label": "paragraph_title"},
        ),
        PageMaterialItem(
            item_id="pp-instance-2023",
            item_type="text",
            source_type="pp_structure_text",
            page_no=20,
            top_y=80,
            bbox=[0, 80, 300, 100],
            text="3.7.2、2023 年度财务审计报告",
            payload={"layout_label": "doc_title"},
        ),
        PageMaterialItem(
            item_id="pp-child-2023",
            item_type="text",
            source_type="pp_structure_text",
            page_no=22,
            top_y=80,
            bbox=[0, 80, 120, 100],
            text="利润表",
            payload={"layout_label": "paragraph_title"},
        ),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        compound_material_rules=[
            {
                "excel_anchor_path": anchor,
                "instance_title_patterns": [r"20\d{2}.*(?:财务|审计).*报告"],
                "auto_detect_children": True,
                "store_unlisted_children": True,
            }
        ],
        page_material_items=page_material_items,
    )

    base = tmp_path / "modules" / "补充文件" / "财务状况" / "经会计师事务所或审计机构审计的财务会计报表"
    anchor_markdown = (base / "material.md").read_text(encoding="utf-8")

    assert "3.7.1、2022 年度财务审计报告" not in anchor_markdown
    assert "3.7.2、2023 年度财务审计报告" not in anchor_markdown
    assert not (base / "3.7.1、2022 年度财务审计报告").exists()
    assert (base / "利润表" / "material.md").exists()


def test_package_module_artifacts_prefers_pdf_embedded_images_over_pp_structure_crops(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 企业营业执照扫描件",
            1,
            1,
            "企业营业执照扫描件",
        )
    ]
    images = [
        {"image_id": "pdf-img", "page_no": 1, "xref": 31, "width": 900, "height": 560, "rect": [10, 170, 420, 300], "ext": "png"},
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-image-1",
            item_type="image",
            source_type="pp_structure_image_region",
            page_no=1,
            top_y=170,
            bbox=[10, 170, 420, 300],
            text="",
            payload={"layout_label": "image", "page_width": 500, "page_height": 700},
        )
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=[],
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"pdf-image", item.get("ext", "png")),
        page_material_items=page_material_items,
    )

    material_dir = tmp_path / "modules" / "企业营业执照扫描件"
    image_files = sorted(path.name for path in (material_dir / "image_items").glob("*.png"))
    ordered = json.loads((material_dir / "ordered_material.json").read_text(encoding="utf-8"))

    assert image_files == ["企业营业执照扫描件_图1.png"]
    assert all(item.get("item_id") != "pp-image-1" for item in ordered["items"])


def test_package_module_artifacts_creates_global_fu_submaterial(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人授权委托书",
            1,
            2,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="4、法定代表人授权委托书", bbox=[0, 20, 300, 40], block_no=1),
        PdfTextBlock(block_id="b2", page_no=1, text="授权正文第一页", bbox=[0, 60, 300, 80], block_no=2),
        PdfTextBlock(block_id="b3", page_no=1, text="附：法定代表人（单位负责人）身份证（扫描件）", bbox=[0, 120, 300, 140], block_no=3),
        PdfTextBlock(block_id="b4", page_no=1, text="身份证说明文字", bbox=[0, 160, 300, 180], block_no=4),
    ]
    images = [
        {"image_id": "img-1", "page_no": 1, "xref": 20, "width": 600, "height": 500, "rect": [10, 200, 150, 360], "ext": "png"},
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=images,
        out_dir=tmp_path,
        image_bytes_resolver=lambda item: (b"fake-image", item.get("ext", "png")),
    )

    section_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人授权委托书"
    submaterial_dir = section_dir / "submaterials" / "法定代表人（单位负责人）身份证（扫描件）"
    assert (section_dir / "ordered_material.json").exists()
    assert (submaterial_dir / "ordered_material.json").exists()
    assert (submaterial_dir / "material_meta.json").exists()

    parent_ordered = json.loads((section_dir / "ordered_material.json").read_text(encoding="utf-8"))
    child_ordered = json.loads((submaterial_dir / "ordered_material.json").read_text(encoding="utf-8"))

    assert any(item["item_type"] == "submaterial" for item in parent_ordered["items"])
    assert any(item["payload_ref"].endswith("submaterials/法定代表人（单位负责人）身份证（扫描件）/ordered_material.json") for item in parent_ordered["items"] if item["item_type"] == "submaterial")
    assert child_ordered["material_title"] == "法定代表人（单位负责人）身份证（扫描件）"
    assert child_ordered["items"][0]["nearest_heading"] == "附：法定代表人（单位负责人）身份证（扫描件）"
    assert [item["item_type"] for item in child_ordered["items"]] == ["text", "text", "image"]


def test_package_module_artifacts_suffixes_duplicate_fu_submaterials(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人授权委托书",
            1,
            2,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=1, text="4、法定代表人授权委托书", bbox=[0, 20, 300, 40], block_no=1),
        PdfTextBlock(block_id="b2", page_no=1, text="附：营业执照副本", bbox=[0, 80, 300, 100], block_no=2),
        PdfTextBlock(block_id="b3", page_no=1, text="第一页附件说明", bbox=[0, 120, 300, 140], block_no=3),
        PdfTextBlock(block_id="b4", page_no=2, text="附：营业执照副本", bbox=[0, 80, 300, 100], block_no=4),
        PdfTextBlock(block_id="b5", page_no=2, text="第二页附件说明", bbox=[0, 120, 300, 140], block_no=5),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
    )

    submaterials_dir = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人授权委托书" / "submaterials"
    names = sorted(path.name for path in submaterials_dir.iterdir() if path.is_dir())
    assert "营业执照副本" in names
    assert any(name.startswith("营业执照副本_") for name in names)


def test_package_module_artifacts_preserves_cross_page_material_stream_order(tmp_path: Path) -> None:
    candidates = [
        _candidate(
            "商务文件 / 法定代表人授权委托书 / 法定代表人授权委托书",
            10,
            12,
            "4、法定代表人授权委托书",
        )
    ]
    blocks = [
        PdfTextBlock(block_id="b1", page_no=10, text="4、法定代表人授权委托书", bbox=[0, 20, 300, 40], block_no=1),
    ]
    page_material_items = [
        PageMaterialItem(
            item_id="pp-text-10",
            item_type="text",
            source_type="pp_structure_text_region",
            page_no=10,
            top_y=80,
            bbox=[0, 80, 300, 120],
            text="第一页授权正文",
            payload={"ocr_texts": ["第一页授权正文"]},
        ),
        PageMaterialItem(
            item_id="pp-image-11",
            item_type="image",
            source_type="pp_structure_image_region",
            page_no=11,
            top_y=100,
            bbox=[10, 100, 500, 500],
            text="",
            payload={"layout_label": "image"},
        ),
        PageMaterialItem(
            item_id="pp-table-12",
            item_type="table",
            source_type="pp_structure_table_region",
            page_no=12,
            top_y=90,
            bbox=[20, 90, 520, 360],
            text="",
            payload={"layout_label": "table"},
        ),
    ]

    package_module_artifacts(
        candidates=candidates,
        blocks=blocks,
        tables=[],
        images=[],
        out_dir=tmp_path,
        page_material_items=page_material_items,
    )

    ordered_path = tmp_path / "modules" / "法定代表人授权委托书" / "法定代表人授权委托书" / "ordered_material.json"
    ordered = json.loads(ordered_path.read_text(encoding="utf-8"))
    stream_items = [item for item in ordered["items"] if str(item.get("source_type", "")).startswith("pp_structure")]

    assert [item["item_id"] for item in stream_items] == ["pp-text-10", "pp-image-11", "pp-table-12"]
    assert [item["item_type"] for item in stream_items] == ["text", "image", "table"]
    assert stream_items[0]["text"] == "第一页授权正文"
    assert stream_items[0]["payload"]["ocr_texts"] == ["第一页授权正文"]
