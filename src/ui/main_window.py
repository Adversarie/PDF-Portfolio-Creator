"""
src/ui/main_window.py
---------------------
Main application window for PDF Portfolio Maker.
Provides source file grid, Explorer drag-and-drop, metadata editing,
cover sheet configuration, and asynchronous export workflow.
"""

import os
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QPushButton,
    QLabel,
    QLineEdit,
    QGroupBox,
    QProgressBar,
    QFileDialog,
    QMessageBox,
    QSplitter,
    QAbstractItemView,
)
from PySide6.QtGui import QFont, QKeySequence, QShortcut, QDragEnterEvent, QDropEvent

from src.config import APP_NAME, APP_VERSION
from src.engine.portfolio_builder import (
    SourceFile,
    create_source_file_from_path,
)
from src.licensing.verifier import get_active_license_status, LicenseStatus
from src.ui.dialogs import LicenseDialog, AboutDialog
from src.ui.worker import PortfolioBuilderWorker


def format_size(bytes_count: int) -> str:
    """Formats raw byte count into human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_count < 1024.0:
            return f"{bytes_count:.1f} {unit}" if unit != "B" else f"{bytes_count} B"
        bytes_count /= 1024.0
    return f"{bytes_count:.1f} TB"


class MainWindow(QMainWindow):
    """Primary application window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 700)
        self.setAcceptDrops(True)

        self.source_files: List[SourceFile] = []
        self.current_license: LicenseStatus = get_active_license_status()
        self.worker: Optional[PortfolioBuilderWorker] = None

        self.init_menus()
        self.init_ui()
        self.init_shortcuts()
        self.refresh_license_status()

    def init_menus(self):
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&File")
        file_menu.addAction("&Add Files...", self.action_add_files, QKeySequence.StandardKey.Open)
        file_menu.addAction("&Create Portfolio...", self.action_export, QKeySequence.StandardKey.Save)
        file_menu.addSeparator()
        file_menu.addAction("Clear &All", self.action_clear_all)
        file_menu.addSeparator()
        file_menu.addAction("E&xit", self.close, QKeySequence.StandardKey.Quit)

        # Edit Menu
        edit_menu = menubar.addMenu("&Edit")
        edit_menu.addAction("&Remove Selected", self.action_remove_selected, QKeySequence.StandardKey.Delete)
        edit_menu.addAction("Move &Up", self.action_move_up, QKeySequence("Alt+Up"))
        edit_menu.addAction("Move &Down", self.action_move_down, QKeySequence("Alt+Down"))

        # Help Menu
        help_menu = menubar.addMenu("&Help")
        help_menu.addAction("&Enter License Key...", self.action_open_license_dialog)
        help_menu.addAction(f"&About {APP_NAME}", self.action_open_about_dialog)

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)

        # 1. Header with Title & License Badge
        header_layout = QHBoxLayout()
        title_label = QLabel(APP_NAME)
        title_label.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        header_layout.addWidget(title_label)

        header_layout.addStretch()

        self.license_badge = QPushButton()
        self.license_badge.setCursor(Qt.CursorShape.PointingHandCursor)
        self.license_badge.clicked.connect(self.action_open_license_dialog)
        header_layout.addWidget(self.license_badge)
        main_layout.addLayout(header_layout)

        # 2. Main Content Splitter (Table + Cover Sheet)
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top Container: Action Bar + Table
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(8)

        # Toolbar
        btn_layout = QHBoxLayout()
        self.btn_add = QPushButton("+ Add Files...")
        self.btn_add.setStyleSheet(
            "background-color: #2563EB; color: white; font-weight: bold; padding: 7px 16px; border-radius: 4px;"
        )
        self.btn_add.clicked.connect(self.action_add_files)
        btn_layout.addWidget(self.btn_add)

        self.btn_remove = QPushButton("Remove Selected (Del)")
        self.btn_remove.clicked.connect(self.action_remove_selected)
        btn_layout.addWidget(self.btn_remove)

        self.btn_up = QPushButton("↑ Move Up")
        self.btn_up.clicked.connect(self.action_move_up)
        btn_layout.addWidget(self.btn_up)

        self.btn_down = QPushButton("↓ Move Down")
        self.btn_down.clicked.connect(self.action_move_down)
        btn_layout.addWidget(self.btn_down)

        self.btn_clear = QPushButton("Clear All")
        self.btn_clear.clicked.connect(self.action_clear_all)
        btn_layout.addWidget(self.btn_clear)

        btn_layout.addStretch()
        table_layout.addLayout(btn_layout)

        # Table Grid
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels([
            "File Name", "Size", "Type", "Date Modified", "Description (Double-click to edit)"
        ])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setColumnWidth(0, 260)
        self.table.itemChanged.connect(self.on_table_item_changed)
        table_layout.addWidget(self.table)

        splitter.addWidget(table_container)

        # Bottom Container: Cover Sheet Configuration
        cover_group = QGroupBox("Cover Sheet Configuration (Displayed in non-portfolio PDF readers)")
        cover_layout = QVBoxLayout(cover_group)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Portfolio Title:"))
        self.input_title = QLineEdit("Confidential Document Portfolio")
        row1.addWidget(self.input_title)

        row1.addWidget(QLabel("Organization / Author:"))
        self.input_org = QLineEdit("Legal & Compliance")
        row1.addWidget(self.input_org)
        cover_layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Subtitle / Scope:"))
        self.input_subtitle = QLineEdit("ISO 32000-1 Standardized Interactive Document Collection")
        row2.addWidget(self.input_subtitle)
        cover_layout.addLayout(row2)

        splitter.addWidget(cover_group)
        main_layout.addWidget(splitter, stretch=1)

        # 3. Footer: Progress Bar, Status Label, and Export Button
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        main_layout.addWidget(self.progress_bar)

        footer_layout = QHBoxLayout()
        self.lbl_status = QLabel("Drag & drop files from Windows Explorer or click '+ Add Files...'")
        self.lbl_status.setStyleSheet("color: #64748B;")
        footer_layout.addWidget(self.lbl_status)

        footer_layout.addStretch()

        self.btn_export = QPushButton("Create PDF Portfolio...")
        self.btn_export.setStyleSheet(
            "background-color: #16A34A; color: white; font-size: 15px; font-weight: bold; padding: 10px 26px; border-radius: 6px;"
        )
        self.btn_export.clicked.connect(self.action_export)
        footer_layout.addWidget(self.btn_export)

        main_layout.addLayout(footer_layout)

    def init_shortcuts(self):
        """Registers keyboard shortcuts."""
        del_shortcut = QShortcut(QKeySequence.StandardKey.Delete, self)
        del_shortcut.activated.connect(self.action_remove_selected)

    # -----------------------------------------------------------------------
    # Drag and Drop Handlers
    # -----------------------------------------------------------------------

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        filepaths = [u.toLocalFile() for u in urls if os.path.isfile(u.toLocalFile())]
        if filepaths:
            self.add_file_paths(filepaths)

    # -----------------------------------------------------------------------
    # Table & File Management
    # -----------------------------------------------------------------------

    def action_add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Source Files for PDF Portfolio",
            "",
            "All Supported Documents (*.pdf *.docx *.xlsx *.msg *.eml *.png *.jpg *.txt *.zip);;All Files (*.*)"
        )
        if files:
            self.add_file_paths(files)

    def add_file_paths(self, paths: List[str]):
        for p in paths:
            path_obj = Path(p)
            if any(str(item.filepath) == str(path_obj) for item in self.source_files):
                continue
            try:
                source = create_source_file_from_path(path_obj)
                self.source_files.append(source)
            except Exception as e:
                QMessageBox.warning(self, "Error Reading File", f"Could not read {path_obj.name}:\n{e}")

        self.refresh_table()

    def refresh_table(self):
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.source_files))

        for row, item in enumerate(self.source_files):
            # 0: File Name
            name_item = QTableWidgetItem(item.filename)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, name_item)

            # 1: Size
            size_item = QTableWidgetItem(format_size(item.size))
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            size_item.setFlags(size_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 1, size_item)

            # 2: Type
            type_item = QTableWidgetItem(item.file_type)
            type_item.setFlags(type_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 2, type_item)

            # 3: Date Modified
            date_str = item.modified_date.strftime("%Y-%m-%d %H:%M")
            date_item = QTableWidgetItem(date_str)
            date_item.setFlags(date_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, date_item)

            # 4: Description (Editable)
            desc_item = QTableWidgetItem(item.description)
            self.table.setItem(row, 4, desc_item)

        self.table.blockSignals(False)
        self.lbl_status.setText(f"{len(self.source_files)} file(s) ready for portfolio.")

    def on_table_item_changed(self, item: QTableWidgetItem):
        if item.column() == 4:
            row = item.row()
            if 0 <= row < len(self.source_files):
                self.source_files[row].description = item.text().strip()

    def action_remove_selected(self):
        selected_rows = sorted(set(index.row() for index in self.table.selectedIndexes()), reverse=True)
        for r in selected_rows:
            del self.source_files[r]
        self.refresh_table()

    def action_move_up(self):
        selected = sorted(set(index.row() for index in self.table.selectedIndexes()))
        if not selected or selected[0] == 0:
            return
        for r in selected:
            self.source_files[r - 1], self.source_files[r] = self.source_files[r], self.source_files[r - 1]
        self.refresh_table()
        self.table.selectRow(selected[0] - 1)

    def action_move_down(self):
        selected = sorted(set(index.row() for index in self.table.selectedIndexes()), reverse=True)
        if not selected or selected[0] >= len(self.source_files) - 1:
            return
        for r in selected:
            self.source_files[r + 1], self.source_files[r] = self.source_files[r], self.source_files[r + 1]
        self.refresh_table()
        self.table.selectRow(selected[0] + 1)

    def action_clear_all(self):
        if not self.source_files:
            return
        if QMessageBox.question(
            self,
            "Clear All Files",
            "Are you sure you want to remove all files from this portfolio?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            self.source_files.clear()
            self.refresh_table()

    # -----------------------------------------------------------------------
    # License & Export Flow
    # -----------------------------------------------------------------------

    def refresh_license_status(self):
        self.current_license = get_active_license_status()
        if self.current_license.is_valid:
            plan_name = self.current_license.plan.capitalize() if self.current_license.plan else "Pro"
            self.license_badge.setText(f"  ✓ Licensed: {self.current_license.customer_name} ({plan_name})  ")
            self.license_badge.setStyleSheet(
                "background-color: #14532D; color: #86EFAC; border: 1px solid #16A34A; "
                "border-radius: 4px; padding: 4px 10px; font-weight: bold;"
            )
        else:
            self.license_badge.setText("  Evaluation Copy (Click to Register)  ")
            self.license_badge.setStyleSheet(
                "background-color: #334155; color: #CBD5E1; border: 1px solid #475569; "
                "border-radius: 4px; padding: 4px 10px; font-weight: bold;"
            )

    def action_open_license_dialog(self):
        dlg = LicenseDialog(self)
        dlg.license_updated.connect(self.refresh_license_status)
        dlg.exec()

    def action_open_about_dialog(self):
        dlg = AboutDialog(self)
        dlg.exec()

    def action_export(self):
        if not self.source_files:
            QMessageBox.warning(self, "No Files", "Please add at least one source file to create a portfolio.")
            return

        save_path, _ = QFileDialog.getSaveFileName(
            self,
            "Save PDF Portfolio As",
            "Portfolio.pdf",
            "PDF Files (*.pdf)"
        )
        if not save_path:
            return

        self.btn_export.setEnabled(False)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(True)

        is_eval = not self.current_license.is_valid

        self.worker = PortfolioBuilderWorker(
            output_path=save_path,
            sources=list(self.source_files),
            title=self.input_title.text().strip() or "Document Portfolio",
            subtitle=self.input_subtitle.text().strip() or "Standardized Collection",
            organization=self.input_org.text().strip() or "Organization",
            is_evaluation=is_eval,
        )
        self.worker.progress.connect(self.on_worker_progress)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_worker_progress(self, percent: int, message: str):
        self.progress_bar.setValue(percent)
        self.lbl_status.setText(message)

    def on_worker_finished(self, success: bool, message: str):
        self.btn_export.setEnabled(True)
        self.progress_bar.setVisible(False)
        if success:
            QMessageBox.showinfo(self, "Portfolio Created", message)
            self.lbl_status.setText(f"Portfolio created successfully with {len(self.source_files)} files.")
        else:
            QMessageBox.critical(self, "Error Creating Portfolio", f"An error occurred:\n{message}")
            self.lbl_status.setText("Error during creation.")
