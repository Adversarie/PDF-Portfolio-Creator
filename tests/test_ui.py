"""
tests/test_ui.py
----------------
Headless unit and integration tests for PySide6 MainWindow and Worker.
"""

import sys
import datetime
from pathlib import Path
import pytest
from PySide6.QtWidgets import QApplication

from src.ui.main_window import MainWindow, format_size
from src.ui.worker import PortfolioBuilderWorker
from src.engine.portfolio_builder import SourceFile


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_format_size():
    assert format_size(500) == "500 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024 * 1024 * 1024) == "1.0 GB"


def test_main_window_initial_state(qapp):
    window = MainWindow()
    assert window.table.columnCount() == 5
    assert window.table.rowCount() == 0
    assert len(window.source_files) == 0
    assert window.input_title.text() == "Confidential Document Portfolio"
    assert window.progress_bar.isVisible() is False


def test_main_window_add_and_remove_files(qapp, tmp_path):
    window = MainWindow()

    file_a = tmp_path / "Contract_2026.pdf"
    file_a.write_bytes(b"%PDF-1.4 sample contract content")

    file_b = tmp_path / "Evidence_Photo.png"
    file_b.write_bytes(b"\x89PNG\r\n\x1a\nsample png content")

    window.add_file_paths([str(file_a), str(file_b)])

    assert len(window.source_files) == 2
    assert window.table.rowCount() == 2
    assert window.table.item(0, 0).text() == "Contract_2026.pdf"
    assert window.table.item(0, 2).text() == "PDF Document"
    assert window.table.item(1, 0).text() == "Evidence_Photo.png"
    assert window.table.item(1, 2).text() == "PNG Image"

    # Test Reordering (Move Down row 0)
    window.table.selectRow(0)
    window.action_move_down()
    assert window.source_files[0].filename == "Evidence_Photo.png"
    assert window.source_files[1].filename == "Contract_2026.pdf"

    # Test Reordering (Move Up row 1)
    window.table.selectRow(1)
    window.action_move_up()
    assert window.source_files[0].filename == "Contract_2026.pdf"
    assert window.source_files[1].filename == "Evidence_Photo.png"

    # Test Removing Selected Row
    window.table.selectRow(0)
    window.action_remove_selected()
    assert len(window.source_files) == 1
    assert window.source_files[0].filename == "Evidence_Photo.png"

    # Test Clear All
    window.source_files.clear()
    window.refresh_table()
    assert len(window.source_files) == 0
    assert window.table.rowCount() == 0


def test_main_window_description_inline_edit(qapp, tmp_path):
    window = MainWindow()
    f = tmp_path / "Brief.docx"
    f.write_bytes(b"PK\x03\x04WordDocumentContent")

    window.add_file_paths([str(f)])
    assert window.source_files[0].description == ""

    # Simulate user editing the Description cell (column 4)
    item = window.table.item(0, 4)
    item.setText("Confidential legal brief submitted by plaintiff")

    assert window.source_files[0].description == "Confidential legal brief submitted by plaintiff"


def test_worker_execution(qapp, tmp_path):
    out_pdf = tmp_path / "worker_output.pdf"
    sources = [
        SourceFile(
            filepath="dummy.txt",
            filename="Memo.txt",
            size=15,
            file_type="Plain Text Document",
            modified_date=datetime.datetime.now(datetime.timezone.utc),
            description="Important case memo",
            data=b"Case notes text",
        )
    ]

    worker = PortfolioBuilderWorker(
        output_path=str(out_pdf),
        sources=sources,
        title="Test Portfolio",
        subtitle="Worker Test",
        organization="Legal Tech Unit",
        is_evaluation=True,
    )

    progress_events = []
    worker.progress.connect(lambda pct, msg: progress_events.append((pct, msg)))

    # Execute directly synchronously for test
    worker.run()

    assert out_pdf.is_file()
    assert out_pdf.stat().st_size > 500
    assert len(progress_events) >= 5
    assert progress_events[-1][0] == 100
