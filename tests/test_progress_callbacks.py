import sys
import types
from pathlib import Path

from bid_knowledge.parsing.ocr_client import run_ocr
from bid_knowledge.parsing.table_extractor import extract_tables
from bid_knowledge.schemas.models import OCRResult


def test_run_ocr_reports_progress(monkeypatch) -> None:
    events: list[tuple[int, int]] = []

    monkeypatch.setattr(
        "bid_knowledge.parsing.ocr_client.ocr_page_image",
        lambda image_path, page_no, endpoint=None, model=None, api_key=None: OCRResult(page_no=page_no, image_path=str(image_path), blocks=[]),
    )

    run_ocr(
        [{"page_no": 1, "image_path": "page1.png"}, {"page_no": 2, "image_path": "page2.png"}],
        progress_callback=lambda current, total: events.append((current, total)),
    )

    assert events == [(1, 2), (2, 2)]


def test_extract_tables_reports_progress(tmp_path: Path, monkeypatch) -> None:
    events: list[tuple[int, int]] = []
    pdf_path = tmp_path / "demo.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    class FakeFoundTable:
        bbox = (0, 0, 10, 10)

        def extract(self):
            return [["名称", "值"]]

    class FakePage:
        def find_tables(self):
            return [FakeFoundTable()]

    class FakePdf:
        pages = [FakePage(), FakePage()]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

    fake_pdfplumber = types.SimpleNamespace(open=lambda _path: FakePdf())
    monkeypatch.setitem(sys.modules, "pdfplumber", fake_pdfplumber)

    tables = extract_tables(pdf_path, progress_callback=lambda current, total: events.append((current, total)))

    assert len(tables) == 2
    assert tables[0].table_model["row_count"] == 1
    assert tables[0].table_model["col_count"] == 2
    assert tables[0].table_model["cells"][0]["text"] == "名称"
    assert events == [(1, 2), (2, 2)]
