"""PySide6 desktop interface for multi-source, multi-series retrieval and preview/clean export."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import keyring
import pandas as pd
from PySide6.QtCore import QDate, QThread, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QScrollArea,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from economic_data_exporter.models import (
    DATA_COLUMNS,
    DEFAULT_EXPORT_COLUMNS,
    ExportFormatOptions,
    ExportSummary,
    FailureRecord,
    FetchSummary,
    SeriesMetadata,
    SeriesRequest,
)
from economic_data_exporter.network import HttpClient
from economic_data_exporter.services.job import JobRunner
from economic_data_exporter.services.preparation import prepare_export_data, preview_frame
from economic_data_exporter.sources.fred import KEYRING_SERVICE, KEYRING_USER
from economic_data_exporter.sources.registry import build_sources
from economic_data_exporter.utils.validation import (
    split_series_ids,
    GEOGRAPHY_REQUIRED_SOURCES,
    validate_date_range,
    validate_geography,
    validate_output_path,
    validate_series_id,
)
from economic_data_exporter.gui.worker import ExportWorker, FetchWorker, SearchWorker

APP_STYLESHEET = """
QMainWindow, QWidget {
    background: #f5f7fb;
    color: #172033;
    font-size: 13px;
}
QFrame#sidebar {
    background: #0f1b2d;
    border: 1px solid #1d2b42;
    border-radius: 16px;
}
QLabel#brandBadge {
    background: #1769e0;
    color: #ffffff;
    border-radius: 10px;
    padding: 8px 10px;
    font-size: 16px;
    font-weight: 800;
}
QLabel#appTitle {
    background: transparent;
    color: #f8fafc;
    font-size: 20px;
    font-weight: 750;
}
QLabel#appSubtitle {
    background: transparent;
    color: #9fb0c7;
    font-size: 12px;
}
QLabel#sideSection {
    background: transparent;
    color: #8fa3bd;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 1px;
    padding-top: 4px;
}
QFrame#sidebarDivider {
    background: #253650;
    border: none;
    max-height: 1px;
}
QCheckBox#sourceCheck {
    background: #15243a;
    color: #e8eef7;
    border: 1px solid #1f3049;
    border-radius: 9px;
    padding: 8px 10px;
    spacing: 9px;
    font-weight: 600;
}
QCheckBox#sourceCheck:hover {
    background: #1b2d47;
    border-color: #315078;
}
QCheckBox#sourceCheck:checked {
    background: #173b6d;
    border-color: #2e7df6;
    color: #ffffff;
}
QCheckBox#sourceCheck::indicator {
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid #61738d;
    background: #0f1b2d;
}
QCheckBox#sourceCheck::indicator:hover {
    border-color: #82b1ff;
}
QCheckBox#sourceCheck::indicator:checked {
    background: #2e7df6;
    border-color: #2e7df6;
}
QFrame#credentialCard {
    background: #15243a;
    border: 1px solid #243754;
    border-radius: 12px;
}
QLabel#sideCardTitle {
    background: transparent;
    color: #f8fafc;
    font-size: 12px;
    font-weight: 750;
}
QLabel#sideHint {
    background: transparent;
    color: #8fa3bd;
    font-size: 11px;
}
QLineEdit#credentialEdit {
    background: #0f1b2d;
    color: #f8fafc;
    border: 1px solid #30445f;
    border-radius: 8px;
    padding: 7px 9px;
}
QLineEdit#credentialEdit:focus {
    border-color: #4d8ff7;
}
QPushButton#sideButton {
    background: #1b2c44;
    color: #e8eef7;
    border: 1px solid #2e4563;
    border-radius: 8px;
    padding: 7px 10px;
    font-weight: 650;
}
QPushButton#sideButton:hover { background: #243b5b; }
QPushButton#sidePrimary {
    background: #1769e0;
    color: white;
    border: 1px solid #1769e0;
    border-radius: 8px;
    padding: 7px 10px;
    font-weight: 700;
}
QPushButton#sidePrimary:hover { background: #1258bf; }
QLabel#credentialStatus {
    background: #102d26;
    color: #79d7ad;
    border: 1px solid #1d5b48;
    border-radius: 8px;
    padding: 7px 9px;
    font-size: 10px;
}
QFrame#card, QFrame#topbar {
    background: #ffffff;
    border: 1px solid #dfe5ee;
    border-radius: 14px;
}
QLabel#statusPill {
    background: #edf9f3;
    color: #087443;
    border: 1px solid #c8ecd9;
    border-radius: 999px;
    padding: 5px 10px;
    font-size: 11px;
    font-weight: 750;
}
QLabel#sectionTitle {
    background: transparent;
    color: #172033;
    font-size: 16px;
    font-weight: 750;
}
QLabel#eyebrow {
    background: transparent;
    color: #66758a;
    font-size: 10px;
    font-weight: 800;
    letter-spacing: 0.8px;
}
QLabel#step {
    background: #f0f3f8;
    color: #526074;
    border: 1px solid #e0e6ef;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 650;
}
QLabel#stepActive {
    background: #e8f1ff;
    color: #155eef;
    border: 1px solid #cfe0ff;
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 750;
}
QLineEdit, QPlainTextEdit, QComboBox, QDateEdit {
    background: #ffffff;
    color: #172033;
    border: 1px solid #ccd5e1;
    border-radius: 9px;
    padding: 7px 9px;
    min-height: 20px;
}
QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QDateEdit:focus {
    border: 1px solid #5a93ef;
}
QPushButton {
    background: #ffffff;
    color: #263246;
    border: 1px solid #ccd5e1;
    border-radius: 9px;
    padding: 8px 12px;
    font-weight: 650;
}
QPushButton:hover { background: #f5f7fa; border-color: #b7c3d3; }
QPushButton:pressed { background: #e9edf3; }
QPushButton:disabled { color: #98a2b3; }
QPushButton#primaryButton {
    background: #1769e0;
    color: white;
    border: 1px solid #1769e0;
    padding: 9px 16px;
    font-weight: 750;
}
QPushButton#primaryButton:hover { background: #1258bf; }
QPushButton#dangerButton { color: #b42318; }
QTableWidget {
    background: #ffffff;
    alternate-background-color: #fafbfd;
    border: 1px solid #dfe5ee;
    border-radius: 9px;
    gridline-color: #edf0f4;
    selection-background-color: #e7f0ff;
    selection-color: #172033;
}
QHeaderView::section {
    background: #f4f6f9;
    color: #526074;
    border: none;
    border-bottom: 1px solid #dfe5ee;
    padding: 8px;
    font-weight: 750;
}
QProgressBar {
    background: #e9edf3;
    border: none;
    border-radius: 5px;
    min-height: 9px;
}
QProgressBar::chunk { background: #1769e0; border-radius: 5px; }
QScrollArea { border: none; background: transparent; }
QGroupBox {
    background: #fbfcfe;
    border: 1px solid #e2e7ef;
    border-radius: 10px;
    margin-top: 10px;
    padding-top: 8px;
    font-weight: 700;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #526074; }
"""


class MetadataDialog(QDialog):
    def __init__(self, results: list[SeriesMetadata], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select metadata results")
        self.resize(900, 520)
        layout = QVBoxLayout(self)
        intro = QLabel("Select one or more results. Each selected result can be added as an export request.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        for metadata in results:
            item = QListWidgetItem(
                f"[{metadata.source}] {metadata.series_id} — {metadata.name}"
                + (f" [{metadata.units}]" if metadata.units else "")
            )
            item.setData(Qt.ItemDataRole.UserRole, metadata)
            item.setToolTip(metadata.notes or metadata.source_url)
            self.list.addItem(item)
        if self.list.count():
            self.list.selectAll()
        layout.addWidget(self.list, 1)

        selection_buttons = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.clicked.connect(self.list.selectAll)
        clear = QPushButton("Clear selection")
        clear.clicked.connect(self.list.clearSelection)
        selection_buttons.addWidget(select_all)
        selection_buttons.addWidget(clear)
        selection_buttons.addStretch(1)
        layout.addLayout(selection_buttons)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected(self) -> list[SeriesMetadata]:
        results: list[SeriesMetadata] = []
        for item in self.list.selectedItems():
            metadata = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(metadata, SeriesMetadata) and metadata.extra.get("selectable", True):
                results.append(metadata)
        return results


class PreviewCleanDialog(QDialog):
    """Preview the retrieved data and build an auditable derived export configuration."""

    def __init__(
        self,
        results: list,
        failures: list,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.results = results
        self.failures = failures
        self.setWindowTitle("Preview and clean data before export")
        self.resize(1260, 780)
        self._column_checks: dict[str, QCheckBox] = {}
        self._updating_profile = False

        root = QVBoxLayout(self)
        summary = QLabel(
            f"Retrieved {len(results)} successful series. {len(failures)} independent series failed. "
            "The raw provider observations remain unchanged; the options below create a derived export view."
        )
        summary.setWordWrap(True)
        root.addWidget(summary)

        controls = QGroupBox("Shape and cleaning")
        form = QFormLayout(controls)

        self.profile_combo = QComboBox()
        self.profile_combo.addItems(["Clean research", "Full provenance", "Minimal observations", "Custom"])
        self.profile_combo.setCurrentText("Clean research")
        self.profile_combo.currentTextChanged.connect(self._profile_changed)
        form.addRow("Output profile", self.profile_combo)

        self.shape_combo = QComboBox()
        self.shape_combo.addItems(["Long / tidy", "Wide / one column per series"])
        self.shape_combo.currentTextChanged.connect(self._refresh_preview)
        form.addRow("Output shape", self.shape_combo)

        cleaning = QHBoxLayout()
        self.drop_missing = QCheckBox("Drop rows with missing values")
        self.remove_duplicates = QCheckBox("Remove exact duplicate rows")
        self.remove_duplicates.setChecked(True)
        self.sort_by_date = QCheckBox("Sort by date and series")
        self.sort_by_date.setChecked(True)
        cleaning.addWidget(self.drop_missing)
        cleaning.addWidget(self.remove_duplicates)
        cleaning.addWidget(self.sort_by_date)
        cleaning.addStretch(1)
        form.addRow("Cleaning", cleaning)

        columns_box = QGroupBox("Columns for long/tidy output")
        columns_layout = QGridLayout(columns_box)
        for index, column in enumerate(DATA_COLUMNS):
            check = QCheckBox(column)
            check.stateChanged.connect(self._refresh_preview)
            self._column_checks[column] = check
            columns_layout.addWidget(check, index // 3, index % 3)
        form.addRow(columns_box)

        formatting = QHBoxLayout()
        self.freeze_header = QCheckBox("Freeze header")
        self.freeze_header.setChecked(True)
        self.autofilter = QCheckBox("Enable filter row")
        self.autofilter.setChecked(True)
        self.auto_width = QCheckBox("Auto-size columns")
        self.auto_width.setChecked(True)
        self.series_sheets = QCheckBox("Add worksheet per series")
        formatting.addWidget(self.freeze_header)
        formatting.addWidget(self.autofilter)
        formatting.addWidget(self.auto_width)
        formatting.addWidget(self.series_sheets)
        formatting.addStretch(1)
        form.addRow("Excel formatting", formatting)

        root.addWidget(controls)

        preview_header = QHBoxLayout()
        self.preview_label = QLabel("Preview not generated")
        refresh_button = QPushButton("Refresh preview")
        refresh_button.clicked.connect(self._refresh_preview)
        preview_header.addWidget(self.preview_label, 1)
        preview_header.addWidget(refresh_button)
        root.addLayout(preview_header)

        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export this cleaned view")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._apply_profile("Clean research")
        self._refresh_preview()

    def _apply_profile(self, profile: str) -> None:
        profiles = {
            "Clean research": set(DEFAULT_EXPORT_COLUMNS),
            "Full provenance": set(DATA_COLUMNS),
            "Minimal observations": {"date", "value", "source", "series_id", "geography"},
            "Custom": set(DEFAULT_EXPORT_COLUMNS),
        }
        selected = profiles[profile]
        for column, check in self._column_checks.items():
            check.blockSignals(True)
            check.setChecked(column in selected)
            check.blockSignals(False)

    def _profile_changed(self, profile: str) -> None:
        if self._updating_profile:
            return
        self._updating_profile = True
        try:
            if profile != "Custom":
                self._apply_profile(profile)
        finally:
            self._updating_profile = False
        self._refresh_preview()

    def _shape(self) -> str:
        return "wide" if self.shape_combo.currentIndex() == 1 else "long"

    def _options(self) -> ExportFormatOptions:
        columns = tuple(column for column in DATA_COLUMNS if self._column_checks[column].isChecked())
        return ExportFormatOptions(
            output_shape=self._shape(),
            columns=columns,
            drop_missing_values=self.drop_missing.isChecked(),
            remove_duplicate_rows=self.remove_duplicates.isChecked(),
            sort_by_date=self.sort_by_date.isChecked(),
            freeze_header=self.freeze_header.isChecked(),
            autofilter=self.autofilter.isChecked(),
            auto_width=self.auto_width.isChecked(),
            include_series_sheets=self.series_sheets.isChecked(),
        )

    def _refresh_preview(self) -> None:
        try:
            options = self._options()
            data, transformations = prepare_export_data(self.results, options)
            preview = preview_frame(data, max_rows=options.preview_rows)
            self.preview_label.setText(
                f"Export shape: {options.output_shape}. {len(data):,} rows × {len(data.columns):,} columns. "
                f"Showing first {len(preview):,} rows. "
                f"{transformations[-1]}"
            )
            self._populate_table(preview)
        except Exception as exc:
            self.preview_label.setText(f"Preview error: {exc}")
            self.table.clear()
            self.table.setRowCount(0)
            self.table.setColumnCount(0)

    def _populate_table(self, frame) -> None:
        self.table.clear()
        self.table.setRowCount(len(frame))
        self.table.setColumnCount(len(frame.columns))
        self.table.setHorizontalHeaderLabels([str(column) for column in frame.columns])
        for row_index, row in enumerate(frame.itertuples(index=False, name=None)):
            for column_index, value in enumerate(row):
                text = "" if value is None or pd.isna(value) else str(value)
                self.table.setItem(row_index, column_index, QTableWidgetItem(text))
        self.table.resizeColumnsToContents()

    def _accept(self) -> None:
        try:
            self._options()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid export configuration", str(exc))
            return
        self.accept()

    def options(self) -> ExportFormatOptions:
        return self._options()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Economic Data Exporter")
        self.resize(1440, 920)
        self.setMinimumSize(1120, 760)
        self.client = HttpClient()
        self.sources = build_sources(self.client)
        self.requests: list[SeriesRequest] = []
        self.metadata_names: dict[tuple[str, str], str] = {}
        self.runner: JobRunner | None = None
        self._worker_thread: QThread | None = None
        self._worker: object | None = None
        self.pending_fetch: FetchSummary | None = None

        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(18, 18, 18, 18)
        root_layout.setSpacing(16)

        # Persistent source/credential sidebar.
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(292)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16, 16, 16, 16)
        side.setSpacing(9)

        brand_row = QHBoxLayout()
        badge = QLabel("▥")
        badge.setObjectName("brandBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setFixedSize(40, 40)
        brand_row.addWidget(badge)
        brand_text = QVBoxLayout()
        title = QLabel("Economic Data\nExporter")
        title.setObjectName("appTitle")
        subtitle = QLabel("Research Data Workspace")
        subtitle.setObjectName("appSubtitle")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand_row.addLayout(brand_text, 1)
        side.addLayout(brand_row)
        side.addSpacing(6)

        divider = QFrame()
        divider.setObjectName("sidebarDivider")
        side.addWidget(divider)

        source_label = QLabel("DATA SOURCES")
        source_label.setObjectName("sideSection")
        side.addWidget(source_label)

        self.source_checks: dict[str, QCheckBox] = {}
        source_container = QWidget()
        source_layout = QVBoxLayout(source_container)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(5)
        for source_name in self.sources:
            check = QCheckBox(source_name)
            check.setObjectName("sourceCheck")
            check.setToolTip(self._source_description(source_name))
            check.stateChanged.connect(self._source_selection_changed)
            source_layout.addWidget(check)
            self.source_checks[source_name] = check
        if self.source_checks:
            next(iter(self.source_checks.values())).setChecked(True)
        side.addWidget(source_container, 1)

        source_buttons = QHBoxLayout()
        select_all = QPushButton("Select all")
        select_all.setObjectName("sideButton")
        select_all.clicked.connect(self._select_all_sources)
        clear_all = QPushButton("Clear")
        clear_all.setObjectName("sideButton")
        clear_all.clicked.connect(self._clear_sources)
        source_buttons.addWidget(select_all)
        source_buttons.addWidget(clear_all)
        side.addLayout(source_buttons)

        divider2 = QFrame()
        divider2.setObjectName("sidebarDivider")
        side.addWidget(divider2)

        credentials = QFrame()
        credentials.setObjectName("credentialCard")
        credentials_layout = QVBoxLayout(credentials)
        credentials_layout.setContentsMargins(12, 11, 12, 11)
        credentials_layout.setSpacing(7)
        cred_title = QLabel("FRED API credentials")
        cred_title.setObjectName("sideCardTitle")
        credentials_layout.addWidget(cred_title)
        cred_hint = QLabel("Optional. Stored securely in your OS keyring.")
        cred_hint.setObjectName("sideHint")
        cred_hint.setWordWrap(True)
        credentials_layout.addWidget(cred_hint)
        self.fred_key_edit = QLineEdit()
        self.fred_key_edit.setObjectName("credentialEdit")
        self.fred_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.fred_key_edit.setPlaceholderText("32-character API key")
        credentials_layout.addWidget(self.fred_key_edit)
        key_buttons = QHBoxLayout()
        load_key = QPushButton("Load")
        load_key.setObjectName("sideButton")
        load_key.clicked.connect(self._load_fred_key)
        save_key = QPushButton("Save")
        save_key.setObjectName("sidePrimary")
        save_key.clicked.connect(self._save_fred_key)
        delete_key = QPushButton("Clear")
        delete_key.setObjectName("sideButton")
        delete_key.clicked.connect(self._delete_fred_key)
        key_buttons.addWidget(load_key)
        key_buttons.addWidget(save_key)
        key_buttons.addWidget(delete_key)
        credentials_layout.addLayout(key_buttons)
        self.fred_key_status = QLabel()
        self.fred_key_status.setObjectName("credentialStatus")
        self.fred_key_status.setWordWrap(True)
        credentials_layout.addWidget(self.fred_key_status)
        side.addWidget(credentials)

        footer = QHBoxLayout()
        settings_button = QPushButton("⚙  Settings")
        settings_button.setObjectName("sideButton")
        settings_button.clicked.connect(lambda: QMessageBox.information(self, "Settings", "Settings are currently managed through the export controls and OS credential store."))
        about_button = QPushButton("ⓘ  About")
        about_button.setObjectName("sideButton")
        about_button.clicked.connect(lambda: QMessageBox.information(self, "Economic Data Exporter", "Research-oriented economic data retrieval and Excel export.\nVersion 0.6.0"))
        footer.addWidget(settings_button)
        footer.addWidget(about_button)
        side.addLayout(footer)

        root_layout.addWidget(sidebar)

        # Main workspace scroll area.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        workspace = QWidget()
        work = QVBoxLayout(workspace)
        work.setContentsMargins(2, 2, 8, 2)
        work.setSpacing(14)

        topbar = QFrame()
        topbar.setObjectName("topbar")
        top_layout = QVBoxLayout(topbar)
        top_layout.setContentsMargins(20, 16, 20, 16)
        heading_row = QHBoxLayout()
        heading = QLabel("Build an export")
        heading.setObjectName("sectionTitle")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.status_label = QLabel("●  Ready")
        self.status_label.setObjectName("statusPill")
        heading_row.addWidget(self.status_label)
        top_layout.addLayout(heading_row)
        sub = QLabel("Choose sources, add indicators, review the queue, then retrieve and shape the data before Excel export.")
        sub.setStyleSheet("color:#667085;")
        top_layout.addWidget(sub)
        steps = QHBoxLayout()
        for text in ("1  Select", "2  Build queue", "3  Preview & clean", "4  Export"):
            label = QLabel(text)
            label.setObjectName("stepActive" if text.startswith("1") else "step")
            steps.addWidget(label)
        steps.addStretch(1)
        top_layout.addLayout(steps)
        work.addWidget(topbar)

        # Request builder card.
        builder = QFrame()
        builder.setObjectName("card")
        form = QFormLayout(builder)
        form.setContentsMargins(20, 18, 20, 18)
        form.setVerticalSpacing(12)

        self.series_edit = QPlainTextEdit()
        self.series_edit.setPlaceholderText("Paste multiple IDs — one per line, comma-separated, or semicolon-separated\nExample: FSR2018JUNEC10AS2, bcpien, FXUSDCAD")
        self.series_edit.setMinimumHeight(86)
        ids_row = QHBoxLayout()
        ids_row.addWidget(self.series_edit, 1)
        self.search_button = QPushButton("Search metadata")
        self.search_button.setToolTip("Search the selected providers for matching series/indicator metadata")
        self.search_button.clicked.connect(self._search_metadata)
        ids_row.addWidget(self.search_button)
        form.addRow("Indicators / series", ids_row)

        options_row = QHBoxLayout()
        self.geography_edit = QLineEdit()
        self.geography_edit.setPlaceholderText("Optional shared geography, e.g. CAN or US")
        self.frequency_edit = QLineEdit()
        self.frequency_edit.setPlaceholderText("Optional; provider-specific")
        options_row.addWidget(self.geography_edit, 2)
        options_row.addWidget(self.frequency_edit, 1)
        form.addRow("Geography / frequency", options_row)

        dates = QHBoxLayout()
        self.start_date = QDateEdit(QDate(2000, 1, 1))
        self.end_date = QDateEdit(QDate.currentDate())
        for widget in (self.start_date, self.end_date):
            widget.setCalendarPopup(True)
            widget.setDisplayFormat("yyyy-MM-dd")
        dates.addWidget(QLabel("Start"))
        dates.addWidget(self.start_date)
        dates.addWidget(QLabel("End"))
        dates.addWidget(self.end_date)
        dates.addStretch(1)
        form.addRow("Date range", dates)

        retrieval = QHBoxLayout()
        self.ignore_cache = QCheckBox("Refresh / ignore cache")
        self.fail_fast = QCheckBox("Fail fast")
        retrieval.addWidget(self.ignore_cache)
        retrieval.addWidget(self.fail_fast)
        retrieval.addStretch(1)
        self.add_button = QPushButton("＋ Add to export queue")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self._add_requests)
        retrieval.addWidget(self.add_button)
        form.addRow("Retrieval", retrieval)
        work.addWidget(builder)

        queue_card = QFrame()
        queue_card.setObjectName("card")
        queue_layout = QVBoxLayout(queue_card)
        queue_layout.setContentsMargins(20, 16, 20, 16)
        queue_heading = QHBoxLayout()
        queue_title = QLabel("Export queue")
        queue_title.setObjectName("sectionTitle")
        queue_heading.addWidget(queue_title)
        queue_heading.addStretch(1)
        self.queue_count = QLabel("0 requests")
        self.queue_count.setStyleSheet("color:#667085;font-weight:600;")
        queue_heading.addWidget(self.queue_count)
        queue_layout.addLayout(queue_heading)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["Source", "Series ID", "Name", "Geography", "Start", "End", "Frequency", "Status"])
        self.table.setMinimumHeight(230)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        queue_layout.addWidget(self.table)
        selection_buttons = QHBoxLayout()
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_selected)
        clear_button = QPushButton("Clear queue")
        clear_button.setObjectName("dangerButton")
        clear_button.clicked.connect(self._clear_selection)
        selection_buttons.addWidget(remove_button)
        selection_buttons.addWidget(clear_button)
        selection_buttons.addStretch(1)
        queue_layout.addLayout(selection_buttons)
        work.addWidget(queue_card)

        output_card = QFrame()
        output_card.setObjectName("card")
        output_layout = QVBoxLayout(output_card)
        output_layout.setContentsMargins(20, 16, 20, 16)
        output_title = QLabel("Output")
        output_title.setObjectName("sectionTitle")
        output_layout.addWidget(output_title)
        output_row = QHBoxLayout()
        self.output_edit = QLineEdit(str(Path.home() / "economic_data_export.xlsx"))
        browse_button = QPushButton("Choose file…")
        browse_button.clicked.connect(self._browse_output)
        output_row.addWidget(self.output_edit, 1)
        output_row.addWidget(browse_button)
        output_layout.addLayout(output_row)
        hint = QLabel("The final Excel file is written atomically after retrieval and preview/clean configuration are validated.")
        hint.setStyleSheet("color:#667085;font-size:11px;")
        output_layout.addWidget(hint)
        action_row = QHBoxLayout()
        self.generate_button = QPushButton("Retrieve → Preview & Clean → Export")
        self.generate_button.setObjectName("primaryButton")
        self.generate_button.clicked.connect(self._generate)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        action_row.addWidget(self.generate_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.progress, 1)
        output_layout.addLayout(action_row)
        work.addWidget(output_card)
        work.addStretch(1)

        scroll.setWidget(workspace)
        root_layout.addWidget(scroll, 1)

        self._update_fred_key_status()
        self._source_selection_changed()
        self._update_queue_count()

    def _source_description(self, source_name: str) -> str:
        descriptions = {
            "Bank of Canada": "Valet API · Canadian macro and financial series",
            "FRED": "Federal Reserve economic data · API key required",
            "World Bank": "Indicators API · global development indicators",
            "Our World in Data": "Grapher data · research-ready global series",
            "Penn World Table": "PWT 11.0 · productivity, prices and national accounts",
            "Statistics Canada": "WDS / SDMX · Canadian official statistics",
            "OECD": "Data Explorer SDMX · OECD and member-economy statistics",
            "IMF": "DataMapper / IMF data · macroeconomic indicators",
            "BIS": "SDMX · banking, credit and financial statistics",
            "ILOSTAT": "Labour statistics · employment, wages and labour markets",
            "FAOSTAT": "FAO statistics · agricultural and food data",
        }
        return descriptions.get(source_name, source_name)

    def _to_date(self, widget: QDateEdit) -> date:
        value = widget.date()
        return date(value.year(), value.month(), value.day())

    def _selected_sources(self) -> list[str]:
        return [name for name, check in self.source_checks.items() if check.isChecked()]

    def _source_selection_changed(self, *_args) -> None:
        selected = self._selected_sources()
        self.frequency_edit.setEnabled("FRED" in selected)
        self.fred_key_edit.setEnabled("FRED" in selected)
        self.fred_key_status.setEnabled("FRED" in selected)
        self._update_fred_key_status()

    def _select_all_sources(self) -> None:
        for check in self.source_checks.values():
            check.setChecked(True)

    def _clear_sources(self) -> None:
        for check in self.source_checks.values():
            check.setChecked(False)

    def _options_for_source(self, source: str) -> dict[str, object]:
        options: dict[str, object] = {"ignore_cache": self.ignore_cache.isChecked()}
        key = self.fred_key_edit.text().strip()
        if source == "FRED" and key:
            options["api_key"] = key
        return options

    def _update_fred_key_status(self) -> None:
        env_present = bool(os.environ.get("FRED_API_KEY", "").strip())
        try:
            keyring_present = bool((keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or "").strip())
        except keyring.errors.KeyringError:
            keyring_present = False
        states = []
        if env_present:
            states.append("environment variable detected")
        if keyring_present:
            states.append("saved in OS keyring")
        if self.fred_key_edit.text().strip():
            states.append("key entered in this session")
        self.fred_key_status.setText("FRED credential status: " + (", ".join(states) if states else "not configured"))

    def _load_fred_key(self) -> None:
        try:
            key = keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
        except keyring.errors.KeyringError as exc:
            QMessageBox.warning(self, "Credential error", f"Could not read the OS keyring: {exc}")
            return
        if not key:
            QMessageBox.information(self, "No saved key", "No FRED API key is currently saved in the OS keyring.")
            return
        self.fred_key_edit.setText(key)
        self._update_fred_key_status()

    def _save_fred_key(self) -> None:
        key = self.fred_key_edit.text().strip()
        if len(key) != 32 or not key.isalnum() or key.lower() != key:
            QMessageBox.warning(self, "Invalid FRED key", "FRED API keys must be 32-character lowercase alphanumeric keys.")
            return
        try:
            keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
        except keyring.errors.KeyringError as exc:
            QMessageBox.warning(self, "Credential error", f"Could not save the key to the OS keyring: {exc}")
            return
        self._update_fred_key_status()
        QMessageBox.information(self, "Key saved", "The FRED API key was saved to the OS keyring.")

    def _delete_fred_key(self) -> None:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except keyring.errors.PasswordDeleteError:
            pass
        except keyring.errors.KeyringError as exc:
            QMessageBox.warning(self, "Credential error", f"Could not delete the key: {exc}")
            return
        self._update_fred_key_status()

    def _search_metadata(self) -> None:
        sources = self._selected_sources()
        query = self.series_edit.toPlainText().strip()
        if not sources:
            QMessageBox.warning(self, "No sources selected", "Select at least one data source before searching metadata.")
            return
        if not query:
            QMessageBox.warning(self, "Missing search", "Enter search text or an exact identifier before searching metadata.")
            return
        self._set_busy(True, "Searching metadata")
        source_map = {name: self.sources[name] for name in sources}
        worker = SearchWorker(source_map, query, self._options_for_source("FRED"))
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._search_finished)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._worker_thread, self._worker = thread, worker
        thread.start()

    def _search_finished(self, results: list[SeriesMetadata]) -> None:
        self._set_busy(False, "Ready")
        if not results:
            QMessageBox.information(self, "No results", "No matching metadata was returned from the selected sources.")
            return
        dialog = MetadataDialog(results, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = dialog.selected()
            if selected:
                self._add_metadata_requests(selected)

    def _add_metadata_requests(self, metadata_list: list[SeriesMetadata]) -> None:
        try:
            start = self._to_date(self.start_date)
            end = self._to_date(self.end_date)
            validate_date_range(start, end)
            shared_geography = self.geography_edit.text().strip()
        except Exception as exc:
            QMessageBox.warning(self, "Validation error", str(exc))
            return

        added = 0
        for metadata in metadata_list:
            geography = metadata.geography or shared_geography
            if metadata.source in {"World Bank", "Penn World Table", "IMF"}:
                geography = validate_geography(geography, required=True)
            elif geography:
                geography = validate_geography(geography)
            request = SeriesRequest(
                source=metadata.source,
                series_id=validate_series_id(metadata.series_id, source=metadata.source),
                start_date=start,
                end_date=end,
                geography=geography,
                frequency=self.frequency_edit.text().strip() if metadata.source == "FRED" else "",
                options=self._options_for_source(metadata.source),
            )
            if self._append_request(request, metadata.name):
                added += 1
        self.status_label.setText(f"Added {added} metadata result(s)")

    def _add_requests(self) -> None:
        sources = self._selected_sources()
        if not sources:
            QMessageBox.warning(self, "No sources selected", "Select one or more data sources first.")
            return
        try:
            start = self._to_date(self.start_date)
            end = self._to_date(self.end_date)
            validate_date_range(start, end)
            shared_geography = self.geography_edit.text().strip()
            requests: list[tuple[SeriesRequest, str]] = []
            raw_ids = split_series_ids(self.series_edit.toPlainText())
            for source in sources:
                geography = shared_geography
                if source in GEOGRAPHY_REQUIRED_SOURCES:
                    geography = validate_geography(geography, required=True)
                elif geography:
                    geography = validate_geography(geography)
                for series_id in raw_ids:
                    valid_id = validate_series_id(series_id, source=source)
                    request = SeriesRequest(
                        source=source,
                        series_id=valid_id,
                        start_date=start,
                        end_date=end,
                        geography=geography,
                        frequency=self.frequency_edit.text().strip() if source == "FRED" else "",
                        options=self._options_for_source(source),
                    )
                    requests.append((request, self.metadata_names.get((source, valid_id), "Metadata retrieved during export")))
        except Exception as exc:
            QMessageBox.warning(self, "Validation error", str(exc))
            return

        added = sum(self._append_request(request, name) for request, name in requests)
        self.status_label.setText(f"Added {added} new request(s) from {len(raw_ids)} ID(s) × {len(sources)} source(s)")

    def _append_request(self, request: SeriesRequest, name: str) -> bool:
        signature = (
            request.source,
            request.series_id,
            request.geography,
            request.start_date,
            request.end_date,
            request.frequency,
        )
        existing = {
            (item.source, item.series_id, item.geography, item.start_date, item.end_date, item.frequency)
            for item in self.requests
        }
        if signature in existing:
            return False
        self.requests.append(request)
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            request.source,
            request.series_id,
            name,
            request.geography,
            request.start_date.isoformat(),
            request.end_date.isoformat(),
            request.frequency,
            "Queued",
        ]
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))
        self._update_queue_count()
        return True

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
            del self.requests[row]
        self._update_queue_count()

    def _clear_selection(self) -> None:
        self.requests.clear()
        self.table.setRowCount(0)
        self._update_queue_count()

    def _update_queue_count(self) -> None:
        count = len(self.requests)
        self.queue_count.setText(f"{count:,} request" + ("" if count == 1 else "s"))

    def _browse_output(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Choose Excel output",
            self.output_edit.text(),
            "Excel workbook (*.xlsx)",
        )
        if filename:
            if not filename.lower().endswith(".xlsx"):
                filename += ".xlsx"
            self.output_edit.setText(filename)

    def _current_requests(self) -> list[SeriesRequest]:
        requests: list[SeriesRequest] = []
        for item in self.requests:
            options = dict(item.options)
            options["ignore_cache"] = self.ignore_cache.isChecked()
            if item.source == "FRED" and self.fred_key_edit.text().strip():
                options["api_key"] = self.fred_key_edit.text().strip()
            requests.append(
                SeriesRequest(
                    source=item.source,
                    series_id=item.series_id,
                    start_date=item.start_date,
                    end_date=item.end_date,
                    geography=item.geography,
                    frequency=item.frequency,
                    options=options,
                )
            )
        return requests

    def _generate(self) -> None:
        try:
            output = validate_output_path(Path(self.output_edit.text()))
            if not self.requests:
                raise ValueError("Add at least one request before retrieving data.")
            requests = self._current_requests()
        except Exception as exc:
            QMessageBox.warning(self, "Validation error", str(exc))
            return

        self.runner = JobRunner(self.sources)
        thread = QThread(self)
        worker = FetchWorker(self.runner, requests, fail_fast=self.fail_fast.isChecked())
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._progress_update)
        worker.finished.connect(lambda summary: self._fetch_finished(summary, output))
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._worker_thread, self._worker = thread, worker
        self._set_busy(True, "Retrieving data")
        self.cancel_button.setEnabled(True)
        thread.start()

    def _fetch_finished(self, summary: FetchSummary, output: Path) -> None:
        # Treat an HTTP-successful response with zero observations as a distinct
        # no-data outcome. It must not open a blank preview window.
        empty_results = [result for result in summary.successful if result.data.empty]
        if empty_results:
            summary.successful[:] = [result for result in summary.successful if not result.data.empty]
            summary.failures.extend(
                FailureRecord(
                    source=result.request.source,
                    series_id=result.request.series_id,
                    geography=result.request.geography,
                    error_type="NoData",
                    message="The provider returned no observations for the requested date range.",
                )
                for result in empty_results
            )

        self.pending_fetch = summary
        self._set_busy(False, "Ready for preview")
        self.cancel_button.setEnabled(False)
        if summary.cancelled:
            QMessageBox.information(self, "Cancelled", "Retrieval was cancelled; no output workbook was created.")
            return
        if not summary.successful:
            details = "\n".join(
                f"• {failure.source} / {failure.series_id}: {failure.error_type}: {failure.message}"
                for failure in summary.failures
            )
            message = (
                "No observations were retrieved, so no preview or workbook was created.\n\n"
                f"Failures ({len(summary.failures)}):\n{details or 'No failure details were returned.'}"
            )
            self.status_label.setText("No data retrieved")
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("No data retrieved")
            box.setText("No observations were retrieved.")
            box.setInformativeText("The request finished, but there is no data available to preview or export.")
            box.setDetailedText(message)
            box.exec()
            return

        dialog = PreviewCleanDialog(summary.successful, summary.failures, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            self.status_label.setText("●  Preview closed; no workbook written")
            return
        self._start_export(output, summary, dialog.options())

    def _start_export(self, output: Path, summary: FetchSummary, options: ExportFormatOptions) -> None:
        self._set_busy(True, "Exporting cleaned Excel workbook")
        self.progress.setRange(0, 0)
        thread = QThread(self)
        worker = ExportWorker(output, summary.successful, summary.failures, options)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._job_finished)
        worker.failed.connect(self._operation_failed)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._thread_finished)
        self._worker_thread, self._worker = thread, worker
        thread.start()

    def _progress_update(self, done: int, total: int, text: str) -> None:
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status_label.setText(text)

    def _job_finished(self, summary: ExportSummary) -> None:
        self._set_busy(False, "Ready")
        self.cancel_button.setEnabled(False)
        if summary.output_path:
            QMessageBox.information(
                self,
                "Export complete",
                f"Workbook: {summary.output_path}\nSuccessful series: {len(summary.successful)}\n"
                f"Failed series: {len(summary.failures)}\n"
                "The workbook contains a README describing the export/cleaning choices.",
            )
        else:
            QMessageBox.warning(self, "Export failed", f"No workbook was created. Failures: {len(summary.failures)}")

    def _operation_failed(self, message: str) -> None:
        self._set_busy(False, "Error")
        self.cancel_button.setEnabled(False)
        QMessageBox.critical(self, "Operation failed", message)

    def _cancel(self) -> None:
        if self.runner:
            self.runner.cancel()
            self.status_label.setText("Cancelling at the next safe checkpoint")

    def _set_busy(self, busy: bool, text: str) -> None:
        self.generate_button.setEnabled(not busy)
        self.search_button.setEnabled(not busy)
        self.add_button.setEnabled(not busy)
        for check in self.source_checks.values():
            check.setEnabled(not busy)
        self.series_edit.setEnabled(not busy)
        self.status_label.setText(text)
        if not busy and self.progress.maximum() <= 1:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)

    def _thread_finished(self) -> None:
        # Worker/thread lifetime is owned by the Qt signal connections above.
        # This slot only releases the Python references held by MainWindow.
        self._worker_thread = None
        self._worker = None

    def closeEvent(self, event: object) -> None:
        if self.runner:
            self.runner.cancel()
        self.client.close()
        super().closeEvent(event)  # type: ignore[arg-type]


def run_gui() -> int:
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLESHEET)
    window = MainWindow()
    window.show()
    return app.exec()
