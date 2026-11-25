"""
src/ui/dialogs.py
-----------------
License Activation and About Dialogs for PDF Portfolio Maker.
"""

from typing import Optional
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QMessageBox,
    QGroupBox,
    QApplication,
)
from PySide6.QtGui import QFont, QDesktopServices
from PySide6.QtCore import QUrl

from src.config import APP_NAME, APP_VERSION, APP_BUILD_DATE, SUPPORT_EMAIL, PURCHASE_URL
from src.licensing.verifier import (
    OfflineLicenseVerifier,
    get_active_license_status,
    save_installed_license,
    remove_installed_license,
    load_installed_license,
    get_machine_fingerprint,
    LicenseStatus,
)


class LicenseDialog(QDialog):
    """Modal dialog allowing users to enter, activate, or view their offline license key."""

    license_updated = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("License Activation - PDF Portfolio Maker")
        self.resize(580, 470)
        self.verifier = OfflineLicenseVerifier()

        self.init_ui()
        self.refresh_display()

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Status Banner
        self.status_group = QGroupBox("Current License Status & Workstation Binding")
        status_layout = QVBoxLayout(self.status_group)
        self.lbl_status = QLabel()
        self.lbl_status.setWordWrap(True)
        self.lbl_status.setTextFormat(Qt.TextFormat.RichText)
        status_layout.addWidget(self.lbl_status)

        machine_row = QHBoxLayout()
        self.machine_id_str = get_machine_fingerprint()
        self.lbl_machine = QLabel(f"<b>Workstation Machine ID:</b> <code>{self.machine_id_str}</code>")
        self.lbl_machine.setTextFormat(Qt.TextFormat.RichText)
        machine_row.addWidget(self.lbl_machine)
        machine_row.addStretch()
        self.btn_copy_machine = QPushButton("Copy Machine ID")
        self.btn_copy_machine.clicked.connect(self.action_copy_machine_id)
        machine_row.addWidget(self.btn_copy_machine)
        status_layout.addLayout(machine_row)

        layout.addWidget(self.status_group)

        # Key Input Section
        self.input_group = QGroupBox("Enter License Key")
        input_layout = QVBoxLayout(self.input_group)
        lbl_hint = QLabel(
            "Paste your offline PPM1 License Key block below. "
            "One-time perpetual licensing ($49 Solo / $149 Firm 5-Seat — replaces $240/yr Acrobat Pro subscriptions):"
        )
        lbl_hint.setWordWrap(True)
        lbl_hint.setStyleSheet("color: #64748B;")
        input_layout.addWidget(lbl_hint)

        self.txt_key = QPlainTextEdit()
        self.txt_key.setPlaceholderText("PPM1.eyJjdXN0b21lcl9uYW1lIjoiLi4uIn0....")
        self.txt_key.setFont(QFont("Consolas", 10))
        input_layout.addWidget(self.txt_key)
        layout.addWidget(self.input_group)

        # Buttons
        btn_layout = QHBoxLayout()

        self.btn_buy = QPushButton("Buy Perpetual License ($49 Solo / $149 Firm)")
        self.btn_buy.clicked.connect(self.action_buy)
        btn_layout.addWidget(self.btn_buy)

        self.btn_deactivate = QPushButton("Deactivate")
        self.btn_deactivate.setStyleSheet("color: #DC2626;")
        self.btn_deactivate.clicked.connect(self.action_deactivate)
        btn_layout.addWidget(self.btn_deactivate)

        btn_layout.addStretch()

        self.btn_cancel = QPushButton("Close")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        self.btn_activate = QPushButton("Activate License")
        self.btn_activate.setStyleSheet("background-color: #2563EB; color: white; font-weight: bold; padding: 6px 16px;")
        self.btn_activate.clicked.connect(self.action_activate)
        btn_layout.addWidget(self.btn_activate)

        layout.addLayout(btn_layout)

    def action_copy_machine_id(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.machine_id_str)
            self.btn_copy_machine.setText("Copied!")

    def refresh_display(self):
        status = get_active_license_status()
        if status.is_valid:
            plan_title = status.plan.capitalize() if status.plan else "Pro"
            binding_info = (
                f"Hardware-bound ({len(status.bound_machines)} machine(s))"
                if status.bound_machines
                else f"Active on workstation {self.machine_id_str}"
            )
            self.lbl_status.setText(
                f"<b>Status:</b> <span style='color: #16A34A;'>Licensed ({plan_title} Edition)</span><br>"
                f"<b>Licensed to:</b> {status.customer_name} &lt;{status.customer_email}&gt;<br>"
                f"<b>Seats:</b> {status.seats} workstation(s) · {binding_info}<br>"
                f"<i>All Cover Sheet watermarks removed. Operating 100% air-gapped &amp; offline.</i>"
            )
            self.btn_deactivate.setVisible(True)
            self.txt_key.clear()
        else:
            self.lbl_status.setText(
                "<b>Status:</b> <span style='color: #EA580C;'>Evaluation Mode (Unregistered)</span><br>"
                "PDF Portfolios created in evaluation mode include a notice banner on the Cover Sheet.<br>"
                "Enter a valid License Key below to unlock unwatermarked court &amp; compliance exports."
            )
            self.btn_deactivate.setVisible(False)

    def action_activate(self):
        raw_input = self.txt_key.toPlainText().strip()
        if not raw_input:
            QMessageBox.warning(self, "Empty Key", "Please paste your license key into the text box.")
            return

        status = self.verifier.activate_on_machine(raw_input)
        if status.is_valid:
            save_installed_license(raw_input)
            QMessageBox.information(
                self,
                "License Activated",
                f"Thank you, {status.customer_name}!\n\n"
                f"Your {status.plan.capitalize() if status.plan else 'Pro'} license has been successfully activated "
                f"on workstation {self.machine_id_str}.\n"
                "All Cover Sheet evaluation banners have been removed."
            )
            self.refresh_display()
            self.license_updated.emit()
            self.accept()
        else:
            QMessageBox.critical(self, "Invalid License Key", f"Activation failed:\n\n{status.message}")

    def action_deactivate(self):
        if QMessageBox.question(
            self,
            "Deactivate License",
            "Are you sure you want to remove your license from this machine?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        ) == QMessageBox.StandardButton.Yes:
            remove_installed_license()
            QMessageBox.information(self, "Deactivated", "License removed. The app has returned to Evaluation Mode.")
            self.refresh_display()
            self.license_updated.emit()

    def action_buy(self):
        QDesktopServices.openUrl(QUrl(PURCHASE_URL))


class AboutDialog(QDialog):
    """About box detailing version, build date, and privacy guarantees."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {APP_NAME}")
        self.setFixedSize(480, 320)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel(APP_NAME)
        title.setFont(QFont("Segoe UI", 16, QFont.Weight.Bold))
        layout.addWidget(title)

        ver = QLabel(f"Version {APP_VERSION} (Build {APP_BUILD_DATE[:10]})")
        ver.setStyleSheet("color: #64748B;")
        layout.addWidget(ver)

        desc = QLabel(
            "A lightweight, privacy-first desktop application for creating "
            "standardized ISO 32000-1 (PDF 1.7) interactive Portfolios.<br><br>"
            "<b>100% Offline Promise:</b> This software performs all processing "
            "locally on your machine and never connects to the internet or transmits "
            "document telemetry."
        )
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(desc)

        layout.addStretch()

        contact = QLabel(f"Support & Legal: <a href='mailto:{SUPPORT_EMAIL}'>{SUPPORT_EMAIL}</a>")
        contact.setOpenExternalLinks(True)
        layout.addWidget(contact)

        btn_box = QHBoxLayout()
        btn_box.addStretch()
        btn_close = QPushButton("OK")
        btn_close.clicked.connect(self.accept)
        btn_box.addWidget(btn_close)
        layout.addLayout(btn_box)
