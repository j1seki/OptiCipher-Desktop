"""
app.pages.analyze
=================

The research-metrics screen.

This is the original "Analyze" tab, rebuilt with the design system. It runs
the same :class:`app.workers.AnalyzeWorker` and reports the same numbers:
per-channel entropy, adjacent-pixel correlation, histograms, and NPCR/UACI
when two comparable images are selected.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..charts import CHANNEL_LABELS, HistogramBars, ValueBar
from ..theme import GAP_MD, GAP_SM
from ..widgets import Card, FileList, PrimaryButton
from .base import BasePage

HINT = (
    "Select 1 image for entropy / correlation / histogram — or pair an image "
    "with its OptiCipher ciphertext (or two same-size images) for NPCR/UACI."
)


class AnalyzePage(BasePage):
    """Research metrics for the selected image(s)."""

    key = "analyze"
    title = "Analyze"
    subtitle = (
        "Research metrics for the selected image: entropy, adjacent-pixel "
        "correlation and histograms — plus NPCR/UACI for a ciphertext pair."
    )

    def __init__(self, window=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(window, parent)
        self._build()
        self._hist_data: dict = {}

    def _build(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(1)

        # -- left: input ------------------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(GAP_MD)

        source = Card("Images", "One image, or a pair for NPCR/UACI.")
        self.files = FileList()
        source.body.addWidget(self.files)
        left_layout.addWidget(source)

        hint = QLabel(HINT)
        hint.setObjectName("Faint")
        hint.setWordWrap(True)
        hint.setToolTip(HINT)
        left_layout.addWidget(hint)

        self.run_btn = PrimaryButton("Run analysis")
        self.run_btn.setObjectName("analyze_run")
        self.run_btn.setToolTip(
            "Compute entropy, adjacent-pixel correlation and histograms for "
            "the selection (1 image) — plus NPCR/UACI for a ciphertext pair"
        )
        left_layout.addWidget(self.run_btn)
        self.status_label = QLabel("")
        self.status_label.setObjectName("Faint")
        self.status_label.setWordWrap(True)
        left_layout.addWidget(self.status_label)
        left_layout.addStretch(1)
        splitter.addWidget(left)

        # -- right: results ---------------------------------------------------
        results = QWidget()
        results_layout = QVBoxLayout(results)
        results_layout.setContentsMargins(0, 0, 0, 0)
        results_layout.setSpacing(GAP_MD)

        metrics = Card("Metrics", "Ideal ranges are marked in green.")
        self.header_label = QLabel("")
        self.header_label.setObjectName("Muted")
        self.header_label.setWordWrap(True)
        self.header_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        metrics.body.addWidget(self.header_label)

        self.metric_bars: dict = {}
        for name, ideal in (
            ("Entropy (mean)", (7.9, 8.0)),
            ("NPCR %", (99.5, 99.7)),
            ("UACI %", (33.3, 33.5)),
        ):
            bar = ValueBar(
                name, maximum=100.0 if "%" in name else 8.0, ideal=ideal
            )
            self.metric_bars[name] = bar
            metrics.body.addWidget(bar)
        self.metric_bars["Entropy (mean)"].setToolTip(
            "Shannon entropy in bits/byte — ideal ciphertext sits at 8.0 "
            "(uniform noise); the green band marks the target range"
        )
        self.metric_bars["NPCR %"].setToolTip(
            "Number of Pixel Change Rate between two encryptions — ideal "
            "~99.6%; measures how completely a one-pixel change spreads"
        )
        self.metric_bars["UACI %"].setToolTip(
            "Unified Average Changing Intensity between two encryptions — "
            "ideal ~33.5%"
        )
        results_layout.addWidget(metrics)

        correlation = Card("Adjacent-pixel correlation", "Ideal ciphertext is near 0.")
        self.corr_table = QTableWidget(0, 3)
        self.corr_table.setHorizontalHeaderLabels(
            ["horizontal", "vertical", "diagonal"]
        )
        self.corr_table.verticalHeader().setVisible(True)
        self.corr_table.horizontalHeader().setStretchLastSection(True)
        correlation.body.addWidget(self.corr_table)
        results_layout.addWidget(correlation)

        histogram = Card("Histogram", "Distribution of byte values (256 bins).")
        hist_row = QHBoxLayout()
        hist_row.setSpacing(GAP_SM)
        hist_label = QLabel("Channel")
        hist_label.setObjectName("FieldLabel")
        hist_label.setToolTip("Which colour channel the histogram below displays")
        hist_row.addWidget(hist_label)
        self.hist_channel = QComboBox()
        self.hist_channel.setToolTip(
            "Pick a colour channel — bar colours follow it (red / green / "
            "blue / amber)"
        )
        self.hist_channel.currentIndexChanged.connect(self._update_hist)
        hist_row.addWidget(self.hist_channel)
        hist_row.addStretch(1)
        histogram.body.addLayout(hist_row)

        self.hist_widget = HistogramBars()
        self.hist_widget.setToolTip(
            "Distribution of byte values (256 bins, sqrt height) — a flat "
            "histogram indicates good diffusion"
        )
        histogram.body.addWidget(self.hist_widget)
        results_layout.addWidget(histogram)
        results_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(results)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 5)

        self.content.addWidget(splitter, 1)

    # -- results ------------------------------------------------------------
    def set_status(self, text: str) -> None:
        self.status_label.setText(text)

    def show_result(self, data: dict) -> None:
        """Render an analysis payload (see app.workers.AnalyzeWorker)."""
        header = data.get("header")
        if header:
            self.header_label.setText(
                "OptiCipher v{version} header · original {width}×{height} "
                "{channels}ch · PBKDF2 {iterations:,} iters · strip "
                "{strip_rows} rows".format(**header)
            )
        else:
            self.header_label.setText(
                "No OptiCipher header found (plain image, or not a v1 ciphertext)"
            )
        entropy = data["entropy"]
        self.metric_bars["Entropy (mean)"].set_value(entropy.get("mean"))
        self.metric_bars["NPCR %"].set_value(data.get("npcr"))
        self.metric_bars["UACI %"].set_value(data.get("uaci"))

        corr = data["correlation"]
        self.corr_table.setRowCount(len(corr))
        for row, (chan, vals) in enumerate(corr.items()):
            for col, key in enumerate(("horizontal", "vertical", "diagonal")):
                self.corr_table.setItem(
                    row, col, QTableWidgetItem(f"{vals[key]:.4f}")
                )
            self.corr_table.setVerticalHeaderItem(row, QTableWidgetItem(chan))

        self._hist_data = data["histograms"]
        self.hist_channel.blockSignals(True)
        self.hist_channel.clear()
        for key in self._hist_data:
            self.hist_channel.addItem(CHANNEL_LABELS.get(key, key), key)
        self.hist_channel.blockSignals(False)
        self._update_hist()

    def _update_hist(self) -> None:
        key = self.hist_channel.currentData() or self.hist_channel.currentText()
        if key and key in self._hist_data:
            self.hist_widget.set_counts(self._hist_data[key], key=key)
