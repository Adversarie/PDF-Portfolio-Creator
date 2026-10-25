"""
src/ui/worker.py
----------------
Asynchronous QThread worker for building PDF Portfolios off the UI thread.
"""

from typing import List
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from src.engine.portfolio_builder import SourceFile, build_portfolio


class PortfolioBuilderWorker(QThread):
    """Executes ISO 32000-1 portfolio generation without blocking the GUI."""

    progress = Signal(int, str)
    finished = Signal(bool, str)

    def __init__(
        self,
        output_path: str,
        sources: List[SourceFile],
        title: str,
        subtitle: str,
        organization: str,
        is_evaluation: bool = True,
    ):
        super().__init__()
        self.output_path = output_path
        self.sources = sources
        self.title = title
        self.subtitle = subtitle
        self.organization = organization
        self.is_evaluation = is_evaluation

    def run(self):
        try:
            build_portfolio(
                output_target=self.output_path,
                files=self.sources,
                title=self.title,
                subtitle=self.subtitle,
                organization=self.organization,
                is_evaluation=self.is_evaluation,
                progress_callback=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished.emit(True, f"PDF Portfolio successfully created at:\n{self.output_path}")
        except Exception as e:
            self.finished.emit(False, str(e))
