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


def test_streaming_chunks_and_constant_ram_digests(tmp_path):
    # Create a 2.5 MB file on disk and stream it in 512 KB chunks (5 chunks * 512 KB = 2.5 MB)
    payload = b"ABCD1234" * (320 * 1024)  # 2,621,440 bytes
    large_file = tmp_path / "evidence_video.mp4"
    large_file.write_bytes(payload)

    source = create_source_file_from_path(large_file, description="Bodycam footage")
    chunks = list(source.iter_chunks(chunk_size=512 * 1024))
    assert len(chunks) == 5
    assert b"".join(chunks) == payload

    md5_bytes, sha256_hex, total_len = source.compute_digests(chunk_size=512 * 1024)
    assert total_len == len(payload)
    assert len(md5_bytes) == 16
    assert len(sha256_hex) == 64
    assert source.sha256 == sha256_hex


def test_bates_stamping_nested_folders_and_sha256_manifest():
    files = [
        SourceFile(
            filepath="motion.pdf",
            filename="Motion_to_Dismiss.pdf",
            size=20,
            file_type="PDF Document",
            modified_date=datetime.datetime(2026, 11, 1, 9, 0, tzinfo=datetime.timezone.utc),
            description="Primary pleading",
            data=b"%PDF-1.4 motion bytes",
            folder="Pleadings/Motions",
        ),
        SourceFile(
            filepath="ledger.xlsx",
            filename="Q4_Ledger.xlsx",
            size=18,
            file_type="Excel Spreadsheet",
            modified_date=datetime.datetime(2026, 11, 2, 10, 0, tzinfo=datetime.timezone.utc),
            description="Financial exhibit",
            data=b"PK\x03\x04ExcelLedger",
            folder="Exhibits/Financials",
        ),
    ]

    buf = io.BytesIO()
    build_portfolio(
        output_target=buf,
        files=files,
        title="Discovery Production",
        subtitle="Bates & Folder Hierarchy Test",
        organization="Litigation Support",
        is_evaluation=False,
        bates_prefix="DISC-",
        bates_start=101,
        bates_digits=6,
        include_sha256_manifest=True,
    )

    pdf_bytes = buf.getvalue()
    # Cover Sheet must include SHA-256 manifest header and Bates IDs
    assert b"CHAIN-OF-CUSTODY SHA-256 EXHIBIT MANIFEST" in pdf_bytes
    assert b"DISC-000101" in pdf_bytes
    assert b"DISC-000102" in pdf_bytes

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    root = reader.trailer["/Root"]
    collection = root["/Collection"]

    # Verify ISO 32000-1 /Folders hierarchy was generated
    assert "/Folders" in collection
    root_folder = collection["/Folders"].get_object()
    assert root_folder["/Type"] == "/CollectionFolder"
    assert "/Child" in root_folder

    # Verify /BatesNumber, /Folder, and /SHA256 in /CollectionSchema
    schema = collection["/Schema"]
    assert "/BatesNumber" in schema
    assert "/Folder" in schema
    assert "/SHA256" in schema


def test_round_trip_inspect_extract_and_append(tmp_path):
    from src.engine.portfolio_builder import (
        inspect_portfolio,
        extract_portfolio,
        append_to_portfolio,
    )

    initial_files = [
        SourceFile(
            filepath="doc1.txt",
            filename="Contract.txt",
            size=16,
            file_type="Plain Text Document",
            modified_date=datetime.datetime(2026, 5, 10, 14, 0, tzinfo=datetime.timezone.utc),
            description="Initial agreement",
            data=b"Signed agreement",
            folder="Contracts",
        )
    ]

    portfolio_path = tmp_path / "Initial_Portfolio.pdf"
    build_portfolio(
        output_target=portfolio_path,
        files=initial_files,
        title="Round Trip Case",
        subtitle="Phase 1",
        organization="Counsel LLP",
        is_evaluation=False,
        bates_prefix="RT-",
        bates_start=1,
    )

    # 1. Inspect existing PDF Portfolio
    manifest = inspect_portfolio(portfolio_path)
    assert manifest.title == "Round Trip Case"
    assert manifest.subtitle == "Phase 1"
    assert manifest.organization == "Counsel LLP"
    assert manifest.is_evaluation is False
    assert len(manifest.files) == 1
    assert manifest.files[0].filename == "Contract.txt"
    assert manifest.files[0].folder == "Contracts"
    assert manifest.files[0].bates_number == "RT-000001"
    assert manifest.files[0].read_bytes() == b"Signed agreement"

    # 2. Append a second Source File to existing PDF Portfolio
    updated_path = tmp_path / "Updated_Portfolio.pdf"
    new_file = SourceFile(
        filepath="addendum.txt",
        filename="Addendum.txt",
        size=14,
        file_type="Plain Text Document",
        modified_date=datetime.datetime(2026, 5, 12, 16, 0, tzinfo=datetime.timezone.utc),
        description="Signed addendum",
        data=b"Addendum bytes",
        folder="Contracts/Addenda",
    )
    updated_manifest = append_to_portfolio(
        existing_portfolio=portfolio_path,
        output_target=updated_path,
        additional_files=[new_file],
        bates_prefix="RT-",
        bates_start=1,
    )
    assert len(updated_manifest.files) == 2

    # 3. Extract all Source Files from updated PDF Portfolio to disk preserving folders
    extract_dir = tmp_path / "unpacked"
    extracted_paths = extract_portfolio(updated_path, extract_dir)
    assert len(extracted_paths) == 2
    assert (extract_dir / "Contracts" / "Contract.txt").read_bytes() == b"Signed agreement"
    assert (extract_dir / "Contracts" / "Addenda" / "Addendum.txt").read_bytes() == b"Addendum bytes"


def test_email_archive_extraction_eml_mbox_and_pst(tmp_path):
    from src.engine.portfolio_builder import extract_email_archive

    raw_eml = (
        b"From: counsel@firm.example\r\n"
        b"To: client@corp.example\r\n"
        b"Subject: Litigation Hold Notice\r\n"
        b"Date: Mon, 04 Nov 2026 10:00:00 +0000\r\n"
        b"MIME-Version: 1.0\r\n"
        b'Content-Type: multipart/mixed; boundary="BOUND123"\r\n\r\n'
        b"--BOUND123\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
        b"Please preserve all records.\r\n"
        b"--BOUND123\r\n"
        b'Content-Type: application/pdf; name="Hold_Memo.pdf"\r\n'
        b'Content-Disposition: attachment; filename="Hold_Memo.pdf"\r\n\r\n'
        b"%PDF-1.4 memo attachment\r\n"
        b"--BOUND123--\r\n"
    )

    # 1. Test .eml extraction (message + attachment)
    eml_path = tmp_path / "hold.eml"
    eml_path.write_bytes(raw_eml)
    eml_items = extract_email_archive(eml_path)
    assert len(eml_items) == 2
    assert any(item.filename.endswith(".eml") for item in eml_items)
    assert any(item.filename == "Hold_Memo.pdf" and item.folder.endswith("Attachments") for item in eml_items)

    # 2. Test .pst container extraction
    pst_path = tmp_path / "custodian_inbox.pst"
    pst_path.write_bytes(b"!BDN\x00\x00\x00\x00" + raw_eml + b"\x00\x00")
    pst_items = extract_email_archive(pst_path)
    assert len(pst_items) >= 2
    assert any("Litigation_Hold_Notice" in item.filename for item in pst_items)
    assert any(item.filename == "Hold_Memo.pdf" for item in pst_items)
