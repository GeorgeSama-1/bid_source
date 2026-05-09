from pathlib import Path

from bid_knowledge.parsing.table_region_detector import (
    CandidateTableRegion,
    _line_regions_from_segments,
    _merge_candidate_regions,
    _normalize_regions_to_pdf_coords,
    regions_to_parsed_tables,
)
from bid_knowledge.schemas.models import ParsedTable


def test_merge_candidate_regions_deduplicates_overlapping_regions_and_combines_evidence() -> None:
    regions = [
        CandidateTableRegion(
            region_id="pdf-1",
            page_no=1,
            bbox=[10, 100, 300, 220],
            detectors=["pdfplumber"],
            confidence=0.7,
            evidence={"source": "pdfplumber"},
        ),
        CandidateTableRegion(
            region_id="pp-1",
            page_no=1,
            bbox=[12, 98, 302, 224],
            detectors=["pp_structure"],
            confidence=0.6,
            evidence={"pp_score": 0.91},
        ),
        CandidateTableRegion(
            region_id="lines-1",
            page_no=1,
            bbox=[400, 100, 550, 180],
            detectors=["pymupdf_lines"],
            confidence=0.8,
        ),
    ]

    merged = _merge_candidate_regions(regions)

    assert len(merged) == 2
    first = merged[0]
    assert first.detectors == ["pdfplumber", "pp_structure"]
    assert first.bbox == [10.0, 98.0, 302.0, 224.0]
    assert first.confidence == 0.75
    assert first.evidence["source"] == "pdfplumber"
    assert first.evidence["pp_score"] == 0.91


def test_regions_to_parsed_tables_reuses_source_rows_and_records_debug_crop_path(tmp_path: Path) -> None:
    region = CandidateTableRegion(
        region_id="region-1",
        page_no=3,
        bbox=[10, 100, 300, 220],
        expanded_bbox=[5, 90, 310, 235],
        detectors=["pdfplumber", "pymupdf_lines"],
        confidence=0.9,
        crop_image_path=str(tmp_path / "debug" / "region-1.png"),
        source_table_ids=["pdf-table-1"],
    )
    source_table = ParsedTable(
        table_id="pdf-table-1",
        page_no=3,
        rows=[["招标编号", "包号"], ["272608", "包05"]],
        bbox=[12, 102, 298, 218],
        table_model={"source": "pdfplumber"},
    )

    tables = regions_to_parsed_tables([region], [source_table])

    assert len(tables) == 1
    assert tables[0].table_id == "region-1"
    assert tables[0].bbox == [5.0, 90.0, 310.0, 235.0]
    assert tables[0].rows == [["招标编号", "包号"], ["272608", "包05"]]
    assert tables[0].candidate_detectors == ["pdfplumber", "pymupdf_lines"]
    assert tables[0].table_image_path.endswith("region-1.png")
    assert tables[0].table_region_confidence == 0.9


def test_line_regions_from_segments_keeps_separate_tables_on_same_page() -> None:
    horizontal = [
        (10, 100, 200, 100),
        (10, 140, 200, 140),
        (10, 180, 200, 180),
        (300, 100, 500, 100),
        (300, 140, 500, 140),
        (300, 180, 500, 180),
    ]
    vertical = [
        (10, 100, 10, 180),
        (100, 100, 100, 180),
        (200, 100, 200, 180),
        (300, 100, 300, 180),
        (400, 100, 400, 180),
        (500, 100, 500, 180),
    ]

    regions = _line_regions_from_segments(1, horizontal, vertical)

    assert len(regions) == 2
    assert regions[0].bbox == [10.0, 100.0, 200.0, 180.0]
    assert regions[1].bbox == [300.0, 100.0, 500.0, 180.0]


def test_normalize_regions_to_pdf_coords_converts_pp_pixel_bbox_before_merge() -> None:
    regions = [
        CandidateTableRegion(
            region_id="pp-1",
            page_no=1,
            bbox=[168.4, 119.1, 842.0, 595.5],
            detectors=["pp_structure"],
            confidence=0.7,
            page_width=1684,
            page_height=1191,
        )
    ]

    normalized = _normalize_regions_to_pdf_coords(regions, {1: (842.0, 595.5)})

    assert normalized[0].bbox == [84.2, 59.55, 421.0, 297.75]
    assert normalized[0].page_width is None
    assert normalized[0].page_height is None
    assert normalized[0].evidence["source_page_width"] == 1684
