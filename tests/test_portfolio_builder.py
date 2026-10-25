"""
tests/test_portfolio_builder.py
--------------------------------
Comprehensive unit tests for ISO 32000-1 Portfolio Engine.
"""

import io
import datetime
from pathlib import Path
import pytest
import pypdf

from src.engine.portfolio_builder import (
    SourceFile,
    build_portfolio,
    infer_file_type,
    create_source_file_from_path,
)


def test_infer_file_type():
    assert infer_file_type(".pdf") == "PDF Document"
    assert infer_file_type(".xlsx") == "Excel Spreadsheet"
    assert infer_file_type(".docx") == "Word Document"
    assert infer_file_type(".msg") == "Outlook Email Message"
    assert infer_file_type(".png") == "PNG Image"
    assert infer_file_type(".xyz") == "XYZ File"
    assert infer_file_type("") == "Binary File"


def test_source_file_from_path(tmp_path):
    test_file = tmp_path / "exhibit_a.pdf"
    test_file.write_bytes(b"%PDF-1.4 sample content")

    source = create_source_file_from_path(test_file, description="Contract Exhibit")
    assert source.filename == "exhibit_a.pdf"
    assert source.size == len(b"%PDF-1.4 sample content")
    assert source.file_type == "PDF Document"
    assert source.description == "Contract Exhibit"
    assert source.read_bytes() == b"%PDF-1.4 sample content"


def test_build_portfolio_structure():
    files = [
        SourceFile(
            filepath="dummy1.pdf",
            filename="Audit_Report.pdf",
            size=100,
            file_type="PDF Document",
            modified_date=datetime.datetime(2026, 10, 1, 12, 0, tzinfo=datetime.timezone.utc),
            description="Q3 external audit report",
            data=b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF",
        ),
        SourceFile(
            filepath="dummy2.xlsx",
            filename="Balance_Sheet.xlsx",
            size=200,
            file_type="Excel Spreadsheet",
            modified_date=datetime.datetime(2026, 10, 5, 15, 30, tzinfo=datetime.timezone.utc),
            description="FY2026 balance sheet",
            data=b"PK\x03\x04DummyExcelBytes",
        ),
    ]

    out_buf = io.BytesIO()
    build_portfolio(
        output_target=out_buf,
        files=files,
        title="Court Exhibits",
        subtitle="Civil Action No. 2026-CV-9821",
        organization="Sterling & Partners LLP",
        is_evaluation=False,
    )

    pdf_bytes = out_buf.getvalue()
    assert len(pdf_bytes) > 1000
    assert pdf_bytes.startswith(b"%PDF-1.7")

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    root = reader.trailer["/Root"]

    # 1. Assert ISO 32000-1 Collection Dictionary
    assert "/Collection" in root
    collection = root["/Collection"]
    assert collection["/View"] == "/D"  # Details mode
    assert "/Schema" in collection
    schema = collection["/Schema"]
    assert "/FileName" in schema
    assert "/FileSize" in schema
    assert "/DocType" in schema
    assert "/ModDate" in schema
    assert "/Description" in schema

    # 2. Assert PageMode & Cover Sheet
    assert root["/PageMode"] == "/UseAttachments"
    assert len(reader.pages) == 1  # 1 Cover Sheet page

    # 3. Assert Embedded Attachments
    assert "Audit_Report.pdf" in reader.attachments
    assert "Balance_Sheet.xlsx" in reader.attachments
    assert reader.attachments["Audit_Report.pdf"][0] == b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF"
    assert reader.attachments["Balance_Sheet.xlsx"][0] == b"PK\x03\x04DummyExcelBytes"

    # 4. Assert Collection Items (/CI) on each filespec
    names_tree = root["/Names"]["/EmbeddedFiles"]["/Names"]
    # Names array structure: [name1, filespec1, name2, filespec2]
    filespecs = [names_tree[i] for i in range(1, len(names_tree), 2)]
    assert len(filespecs) == 2
    for fs in filespecs:
        assert "/CI" in fs
        ci = fs["/CI"]
        assert "/DocType" in ci
        assert "/Description" in ci
        assert "/FileSize" in ci


def test_evaluation_watermark_toggle():
    files = [
        SourceFile(
            filepath="note.txt",
            filename="note.txt",
            size=11,
            file_type="Plain Text Document",
            modified_date=datetime.datetime.now(datetime.timezone.utc),
            data=b"hello world",
        )
    ]

    # Evaluation mode
    eval_buf = io.BytesIO()
    build_portfolio(eval_buf, files, is_evaluation=True)
    eval_bytes = eval_buf.getvalue()
    assert b"DEMO / EVALUATION COPY" in eval_bytes

    # Licensed mode (no watermark)
    licensed_buf = io.BytesIO()
    build_portfolio(licensed_buf, files, is_evaluation=False)
    licensed_bytes = licensed_buf.getvalue()
    assert b"DEMO / EVALUATION COPY" not in licensed_bytes


def test_progress_callback():
    progress_log = []

    def on_progress(pct: int, msg: str):
        progress_log.append((pct, msg))

    files = [
        SourceFile(
            filepath="doc.pdf",
            filename="doc.pdf",
            size=10,
            file_type="PDF Document",
            modified_date=datetime.datetime.now(datetime.timezone.utc),
            data=b"%PDF-1.4",
        )
    ]

    buf = io.BytesIO()
    build_portfolio(buf, files, progress_callback=on_progress)

    assert len(progress_log) >= 5
    percentages = [p[0] for p in progress_log]
    assert percentages[0] == 5
    assert percentages[-1] == 100
    assert sorted(percentages) == percentages  # strictly non-decreasing
