"""
app.py
------
Production entry point for PDF Portfolio Maker.
Launches the PySide6 desktop GUI with native scaling and styling.
"""

import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon

from src.config import APP_NAME, APP_VERSION
from src.ui.main_window import MainWindow


def main():
    # Set application metadata
    QApplication.setApplicationName(APP_NAME)
    QApplication.setApplicationVersion(APP_VERSION)
    QApplication.setOrganizationName("PDF Portfolio Maker")

    app = QApplication(sys.argv)

    # Optional icon loading if asset exists
    icon_path = os.path.join(os.path.dirname(__file__), "assets", "app_icon.ico")
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
