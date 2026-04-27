from pathlib import Path

from typer.testing import CliRunner

from bid_knowledge import cli
from bid_knowledge.schemas.models import (
    ManualConfig,
    PageMaterialItem,
    PdfTextBlock,
    ProcessingPlan,
    ProcessingPlanItem,
    ReconstructedSection,
    SectionMatchResult,
    SectionRule,
)
from bid_knowledge.utils.io_utils import write_json


def test_pipeline_prints_stage_progress_and_empty_ocr_notice(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    rule = SectionRule(rule_id="rule-1", section_path="商务文件 / 证明材料")
    plan = ProcessingPlan(
        company_id="demo_company",
        document_id="demo_document",
        file_type="商务文件",
        sections=[
            ProcessingPlanItem(
                rule_id="rule-1",
                section_path="商务文件 / 证明材料",
                use_ocr=True,
                expected_pages=[],
            )
        ],
    )
    block = PdfTextBlock(
        block_id="block-1",
        page_no=1,
        text="证明材料",
        bbox=[],
        block_no=0,
    )
    section = ReconstructedSection(
        section_id="section-1",
        title="证明材料",
        normalized_title="证明材料",
        level=1,
        page_start=1,
        page_end=1,
    )
    match = SectionMatchResult(
        rule_id="rule-1",
        rule_section_path="商务文件 / 证明材料",
        matched=True,
    )

    def fake_load_rules_from_excel(*args, out_path=None, report_path=None, **kwargs):
        write_json(out_path, [rule])
        write_json(report_path, {"loaded": 1})
        return [rule], {"loaded": 1}

    def fake_parse_pdf(*args, out_dir=None, **kwargs):
        out = Path(out_dir)
        write_json(out / "document_meta.json", {"page_count": 1})
        write_json(out / "toc.json", [])
        write_json(out / "text_blocks.json", [block])
        write_json(out / "images.json", [])

    monkeypatch.setattr(cli, "load_rules_from_excel", fake_load_rules_from_excel)
    monkeypatch.setattr(cli, "load_manual_config", lambda *_: ManualConfig(file_type="商务文件"))
    monkeypatch.setattr(cli, "build_processing_plan", lambda *_: plan)
    monkeypatch.setattr(cli, "parse_pdf", fake_parse_pdf)
    monkeypatch.setattr(cli, "extract_tables", lambda *_, **__: [])
    monkeypatch.setattr(cli, "merge_ocr_results", lambda blocks, _ocr, out_path=None: write_json(out_path, blocks) or blocks)
    monkeypatch.setattr(cli, "build_sections", lambda *_, out_path=None, **__: write_json(out_path, [section]) or [section])
    monkeypatch.setattr(cli, "match_sections", lambda *_, out_path=None, **__: write_json(out_path, [match]) or [match])
    monkeypatch.setattr(cli, "extract_candidates", lambda *_, out_json=None, out_csv=None, **__: write_json(out_json, []) or Path(out_csv).write_text("") or [])
    monkeypatch.setattr(cli, "package_module_artifacts", lambda **_: {"sections": []})
    monkeypatch.setattr(cli, "build_chunks", lambda _candidates, out_path=None: Path(out_path).write_text("") or [])
    monkeypatch.setattr(cli, "evaluate_retrieval", lambda *_, **__: {"skipped": True})
    monkeypatch.setattr(
        cli,
        "build_combined_page_material_stream",
        lambda **_: [PageMaterialItem(item_id="block-1", item_type="text", source_type="pdf_text", page_no=1, reading_order=1, top_y=0.0, bbox=[], text="证明材料")],
    )

    result = runner.invoke(
        cli.app,
        [
            "pipeline",
            "--rules-xlsx",
            "rules.xlsx",
            "--pdf",
            "document.pdf",
            "--out-dir",
            str(tmp_path / "out"),
            "--enable-ocr",
            "true",
        ],
    )

    assert result.exit_code == 0
    assert "[1/13] Loading Excel rules" in result.output
    assert "[5/13] OCR enabled but no explicit OCR pages were configured; skipping OCR requests." in result.output
    assert "[6/13] PP-StructureV3 disabled; using PDF-native parsing only" in result.output
    assert "[7/13] Building page material stream" in result.output
    assert "Pipeline completed ->" in result.output


def test_run_pp_structure_command_reports_page_count(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    out_path = tmp_path / "pp_structure_results.json"
    fake_results = [{"res": {"parsing_res_list": []}, "page_index": 0}]

    def fake_run_pp_structure(*_, out_path=None, **__):
        write_json(out_path, fake_results)
        return fake_results

    monkeypatch.setattr(
        cli,
        "run_pp_structure",
        fake_run_pp_structure,
    )

    result = runner.invoke(
        cli.app,
        [
            "run-pp-structure",
            "--input",
            "document.pdf",
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0
    assert "PP-StructureV3 finished for 1 pages" in result.output
