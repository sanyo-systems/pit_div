# このファイルの役割：メイン画面（Top.vb相当）を PyQt5 で実装します。
# Purpose: Implement the main window (equivalent to Top.vb) using PyQt5.

from __future__ import annotations

"""
業務画面本体を実装するメインモジュール。

旧 VB の `Top.vb` を PyQt5 へ移植したファイルで、責務は大きく以下に分かれる。
1. `setting.ini` と各種定義 JSON の読込
2. CSV 到着監視と取込結果の INI 反映
3. PDF・作業者写真・カメラ映像の画面表示
4. 現場設定変更ダイアログの提供

業務データの正本は CSV と INI にあり、UI はそれらを読み直して再描画する構成にしている。
そのため「CSV 取込」と「表示更新」を分けている点が保守上の重要ポイント。
"""

import csv
import cv2
import json
import logging
import os
import re
import threading
import time
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import fitz  # PyMuPDF
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.access_csv_store import process_new_access_file_entries
from app.csv_watcher import CsvWatchConfig, CsvWatcher
from app.ini_handler import get as ini_get
from app.ini_handler import load_ini, save_ini, set_value
from app.app_metadata import (
    MANIFEST_SECTION,
    UPDATE_TIME_PATH_KEY,
    get_camera_data_path,
    get_ro_data_path,
    get_shiji_data_path,
)
from app.app_update import check_for_update, launch_updater
from app.oracle_pg_status_store import fetch_current_pg_furnace_statuses, fetch_recent_pg_furnace_batches_for_access_match
from app.pg_access_match_batch_store import (
    configure_pg_access_match_batches_path,
    load_pending_pg_access_match_batches_by_furnace,
    update_pg_access_match_batches,
)
from app.shiji_store import (
    configure_shiji_json_path,
    get_confirm_action_label,
    handle_shiji_scan,
    load_latest_group_display_by_furnace,
    load_shiji_furnace_status_overrides,
    resolve_shiji_confirm,
)

logger = logging.getLogger(__name__)


_NUMERIC_RE = re.compile(r"^\d+$")
_PG_FURNACE_NAME_RE = re.compile(r"(PG)[-_ ]?(\d+)", re.IGNORECASE)
_PDF_PANEL_STRETCH = 6
_RIGHT_PANEL_STRETCH = 3
_RIGHT_PANEL_NO_CAMERA_STRETCH = 2
_CAMERA_PANEL_STRETCH = 5
_INFO_PANEL_STRETCH = 1
_RIGHT_PANEL_MARGIN = 4
_RIGHT_PANEL_SPACING = 4
_OPERATOR_BUTTON_WIDTH = 120
_OPERATOR_BUTTON_HEIGHT = 28
_INFO_TITLE_FONT_SIZE = 20
_INFO_VALUE_FONT_SIZE = 24
_OPERATOR_IMAGE_WIDTH = 170
_OPERATOR_IMAGE_HEIGHT = 180
_ORACLE_PG_STATUS_REFRESH_SECONDS = 10.0
_COUNTDOWN_STOP_LABEL_FONT_SIZE = 88
_COUNTDOWN_POPUP_WIDTH = 780
_PDF_ZOOM_MIN_FACTOR = 0.5
_PDF_ZOOM_MAX_FACTOR = 3.0
_PDF_ZOOM_STEP = 0.1
_PDF_FACTORY_ROOT_FOLDER = Path(r"\\192.168.203.202\Sprint\SWPDF")
_PDF_FACTORY_ONLY_NAMES = {"加西工場"}
_CAMERA_RECONNECT_DELAY_SECONDS = 2.0
_CAMERA_OPEN_RETRY_DELAY_SECONDS = 3.0
_CAMERA_MAX_CONSECUTIVE_FAILURES = 5
_CAMERA_THREAD_JOIN_TIMEOUT_SECONDS = 5.0
_CAMERA_IO_TIMEOUT_MILLISECONDS = 5000
_CAMERA_CONNECTION_ERROR_MESSAGE = "接続できません。上限またはネットワーク異常の可能性"
_CAMERA_CONNECTION_ERROR_FONT_SIZE = 22
_UPDATE_HISTORY_PATH = Path(r"\\192.168.203.202\Sprint\DivWorkStandard4\update_history.txt")
_STATUS_PANEL_TITLE_FONT_SIZE = 26
_STATUS_PANEL_VALUE_FONT_SIZE = 24
_RIGHT_PANEL_WIDTH_MIN = 420
_RIGHT_PANEL_WIDTH_MAX = 620
_RIGHT_PANEL_MAIN_TITLE_FONT_MIN = 24
_RIGHT_PANEL_MAIN_TITLE_FONT_MAX = 28
_RIGHT_PANEL_STATUS_TITLE_FONT_MIN = 26
_RIGHT_PANEL_STATUS_TITLE_FONT_MAX = 30
_RIGHT_PANEL_STATUS_HEADER_FONT_MIN = 22
_RIGHT_PANEL_STATUS_HEADER_FONT_MAX = 22
_RIGHT_PANEL_STATUS_VALUE_FONT_MIN = 26
_RIGHT_PANEL_STATUS_VALUE_FONT_MAX = 28
_RIGHT_PANEL_TIME_VALUE_FONT_MIN = 30
_RIGHT_PANEL_TIME_VALUE_FONT_MAX = 32
_RIGHT_PANEL_NOTE_FONT_MIN = 15
_RIGHT_PANEL_NOTE_FONT_MAX = 16
_RIGHT_PANEL_SUMMARY_TITLE_FONT_MIN = 24
_RIGHT_PANEL_SUMMARY_TITLE_FONT_MAX = 30
_RIGHT_PANEL_CURRENT_TIME_FONT_MIN = 40
_RIGHT_PANEL_CURRENT_TIME_FONT_MAX = 54
_RIGHT_PANEL_SUMMARY_VALUE_FONT_MIN = 30
_RIGHT_PANEL_SUMMARY_VALUE_FONT_MAX = 40
_LEFT_PANEL_WIDTH_MIN = 860
_LEFT_PANEL_WIDTH_MAX = 1320
_LEFT_PANEL_MAIN_TITLE_FONT_MIN = 18
_LEFT_PANEL_MAIN_TITLE_FONT_MAX = 28
_LEFT_PANEL_INFO_SECTION_TITLE_FONT_MIN = 15
_LEFT_PANEL_INFO_SECTION_TITLE_FONT_MAX = 22
_LEFT_PANEL_INFO_LABEL_FONT_MIN = 15
_LEFT_PANEL_INFO_LABEL_FONT_MAX = 22
_LEFT_PANEL_INFO_VALUE_FONT_MIN = 18
_LEFT_PANEL_INFO_VALUE_FONT_MAX = 30
_LEFT_PANEL_OPERATOR_SECTION_TITLE_FONT_MIN = 15
_LEFT_PANEL_OPERATOR_SECTION_TITLE_FONT_MAX = 22
_LEFT_PANEL_OPERATOR_NAME_FONT_MIN = 14
_LEFT_PANEL_OPERATOR_NAME_FONT_MAX = 22
_LEFT_PANEL_OPERATOR_IMAGE_WIDTH_MIN = 170
_LEFT_PANEL_OPERATOR_IMAGE_WIDTH_MAX = 210
_LEFT_PANEL_OPERATOR_IMAGE_HEIGHT_MIN = 180
_LEFT_PANEL_OPERATOR_IMAGE_HEIGHT_MAX = 220
_STATUS_COLOR_BY_KIND = {
    "running": "#d8ecff",
    "overdue": "#ffd9d9",
    "stopped": "#e3e3e3",
    "idle": "#f6f1cd",
    "countdown": "#fff1db",
}
_STATUS_TEXT_COLOR_BY_KIND = {
    "running": "#005a9e",
    "overdue": "#c00000",
    "stopped": "#555555",
    "idle": "#222222",
    "countdown": "#c00000",
}
_DEFAULT_FURNACE_NAMES = ("PG-1", "PG-2", "PG-3", "PG-4", "PG-5", "SQ-1", "SQ-2", "SQ-3")


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _interpolate_int(minimum: int, maximum: int, ratio: float) -> int:
    return int(round(minimum + (maximum - minimum) * ratio))


@dataclass(frozen=True)
class FurnaceStatusRow:
    furnace_name: str
    status_text: str
    status_kind: str
    instruction_no_text: str = "-"
    temperature_text: str = "-"
    start_time_text: str = "-"
    end_time_text: str = "-"
    countdown_text: str = ""


def _resolve_furnace_status_kind(status_text: str) -> str:
    normalized_status_text = (status_text or "").strip()
    if "超過" in normalized_status_text:
        return "overdue"
    if "停機" in normalized_status_text:
        return "stopped"
    if "処理中" in normalized_status_text:
        return "running"
    return "idle"


def _build_default_furnace_status_rows() -> tuple[list[FurnaceStatusRow], list[FurnaceStatusRow]]:
    furnace_status_rows = [
        FurnaceStatusRow(furnace_name, "待機", "idle", "-", "-", "-")
        for furnace_name in _DEFAULT_FURNACE_NAMES
    ]
    return furnace_status_rows[:5], furnace_status_rows[5:]


def _parse_today_time(time_text: str) -> Optional[datetime]:
    normalized_time_text = (time_text or "").strip()
    if not normalized_time_text or normalized_time_text == "-":
        return None
    try:
        parsed_time = datetime.strptime(normalized_time_text, "%H:%M")
    except ValueError:
        return None
    now = datetime.now()
    return now.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)


def _resolve_furnace_status_by_time(
    fallback_status_text: str,
    start_time_text: str,
    end_time_text: str,
) -> tuple[str, str]:
    start_time = _parse_today_time(start_time_text)
    end_time = _parse_today_time(end_time_text)
    if start_time is None or end_time is None:
        return fallback_status_text, _resolve_furnace_status_kind(fallback_status_text)

    now = datetime.now()
    if end_time <= now:
        return "終了超過", "overdue"
    if start_time <= now < end_time:
        return "処理中", "running"
    return "停機", "stopped"


def _format_countdown_text(countdown_seconds: int) -> str:
    minutes = max(0, countdown_seconds) // 60
    seconds = max(0, countdown_seconds) % 60
    return f"ソルト上げ | 残り時間 {minutes}:{seconds:02d}"


def _format_countdown_clock(countdown_seconds: int) -> str:
    minutes = max(0, countdown_seconds) // 60
    seconds = max(0, countdown_seconds) % 60
    return f"{minutes}:{seconds:02d}"


def _resolve_countdown_seconds(end_time_text: str) -> int | None:
    end_time = _parse_today_time(end_time_text)
    if end_time is None:
        return None
    now = datetime.now()
    countdown_seconds = int((end_time - now).total_seconds())
    if countdown_seconds <= 0:
        return None
    return countdown_seconds


def _normalize_pg_furnace_name(text: str) -> str:
    match = _PG_FURNACE_NAME_RE.search((text or "").strip())
    if not match:
        return ""
    return f"PG-{int(match.group(2))}"
    return f"繧ｽ繝ｫ繝亥↓縺・ {minutes}:{seconds:02d}"


def _is_numeric(text: str) -> bool:
    """数字のみか判定 / Check if numeric only."""
    return bool(_NUMERIC_RE.match(text.strip()))


def _normalize_operator_id(text: str) -> str:
    """Normalize full-width digits in operator IDs to half-width digits."""
    return unicodedata.normalize("NFKC", text or "").strip()


def _resolve_face_image_path(face_folder: Path, face_id: str) -> Path:
    """Return the expected face image path for an operator ID."""
    return face_folder / f"{face_id}.png"


def _read_text_with_fallback_encodings(path: Path, encodings: list[str]) -> str:
    last_error: Optional[Exception] = None
    for encoding in encodings:
        try:
            return path.read_text(encoding=encoding)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise last_error or RuntimeError(f"Failed to read text file: {path}")


def _load_camera_definitions(camera_data_path: Path) -> dict[str, dict[str, str]]:
    # JSON をそのまま使わず、カテゴリ -> 設備名 -> RTSP URL の辞書へ正規化して扱う。
    """Load camera definitions from JSON with fallback encodings."""
    camera_data_text = _read_text_with_fallback_encodings(camera_data_path, ["utf-8-sig", "utf-8", "cp932"])
    loaded_data = json.loads(camera_data_text)
    if not isinstance(loaded_data, dict):
        raise ValueError("camera_data.json root must be an object")

    camera_definitions: dict[str, dict[str, str]] = {}
    for category, raw_equipment_map in loaded_data.items():
        if not isinstance(raw_equipment_map, dict):
            raise ValueError(f"camera_data.json category must be an object: {category}")
        camera_definitions[str(category)] = {str(name): str(url) for name, url in raw_equipment_map.items()}
    return camera_definitions


def _load_ro_definitions(ro_data_path: Path) -> dict[str, dict[str, list[str]]]:
    # 設定ダイアログで扱いやすいよう、工場 -> 炉種 -> 炉番号一覧の形へそろえる。
    """Load RO definitions from JSON with fallback encodings."""
    ro_data_text = _read_text_with_fallback_encodings(ro_data_path, ["utf-8-sig", "utf-8", "cp932"])
    loaded_data = json.loads(ro_data_text)
    if not isinstance(loaded_data, dict):
        raise ValueError("ro_data.json root must be an object")

    ro_definitions: dict[str, dict[str, list[str]]] = {}
    for factory_name, raw_ro_map in loaded_data.items():
        if not isinstance(raw_ro_map, dict):
            raise ValueError(f"ro_data.json factory values must be objects: {factory_name}")
        ro_map: dict[str, list[str]] = {}
        for ro_name, raw_ro_no_list in raw_ro_map.items():
            if not isinstance(raw_ro_no_list, list):
                raise ValueError(f"ro_data.json RO values must be lists: {factory_name}/{ro_name}")
            ro_map[str(ro_name)] = [str(ro_no) for ro_no in raw_ro_no_list]
        ro_definitions[str(factory_name)] = ro_map
    return ro_definitions


def _resolve_factory_selection_from_pdf_folder(pdf_folder_path: Path) -> tuple[str, str]:
    # 旧 setting.ini では FACTORY / RO が未設定なことがあるため、PDF フォルダ名から逆算する。
    pdf_folder_parts = pdf_folder_path.parts
    root_parts = _PDF_FACTORY_ROOT_FOLDER.parts
    if len(pdf_folder_parts) >= len(root_parts) + 1 and pdf_folder_parts[: len(root_parts)] == root_parts:
        factory_name = pdf_folder_parts[len(root_parts)]
        if factory_name in _PDF_FACTORY_ONLY_NAMES or len(pdf_folder_parts) == len(root_parts) + 1:
            return factory_name, ""
        if len(pdf_folder_parts) >= len(root_parts) + 2:
            return factory_name, pdf_folder_parts[len(root_parts) + 1]
    return "", ""


def _build_pdf_folder_path(factory_name: str, ro_name: str) -> Path:
    # 工場によっては RO 階層を持たないため、例外ケースをここに閉じ込める。
    if not factory_name:
        return Path(".")
    if factory_name in _PDF_FACTORY_ONLY_NAMES:
        return _PDF_FACTORY_ROOT_FOLDER / factory_name
    if not ro_name:
        return Path(".")
    return _PDF_FACTORY_ROOT_FOLDER / factory_name / ro_name


def _resolve_csv_source(csv_folder_text: str, csv_file_text: str) -> tuple[Path, str]:
    """
    CSV の監視フォルダーとファイル名を解決します。
    csv_folder に CSV ファイルパスが入っていた場合は自動で補正します。
    """
    csv_folder_path = Path(csv_folder_text)
    csv_file_name = csv_file_text.strip()

    if csv_folder_path.suffix.lower() == ".csv":
        resolved_folder_path = csv_folder_path.parent
        resolved_file_name = csv_folder_path.name
        logger.warning(
            "CSV_FOLDER points to a file path. Resolved to folder=%s file=%s",
            resolved_folder_path,
            resolved_file_name,
        )
        return resolved_folder_path, resolved_file_name

    return csv_folder_path, csv_file_name


def _render_pdf_first_page(pdf_path: Path, max_width: int = 1400) -> Optional[QPixmap]:
    """
    PDFの1ページ目をレンダリングしてQPixmapを返します。
    Render the first page of a PDF and return QPixmap.
    """
    if not pdf_path.exists():
        return None

    doc = fitz.open(str(pdf_path))
    try:
        if doc.page_count <= 0:
            return None
        page = doc.load_page(0)

        # 画質優先で適度に拡大 / Scale up for better quality
        matrix = fitz.Matrix(2.0, 2.0)
        pix = page.get_pixmap(matrix=matrix, alpha=False)

        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
        qpix = QPixmap.fromImage(image.copy())  # copy to detach from pix buffer

        if qpix.width() > max_width:
            qpix = qpix.scaledToWidth(max_width, Qt.SmoothTransformation)
        return qpix
    finally:
        doc.close()


@dataclass
class AppConfig:
    """起動時に確定した主要パスを `MainWindow` へ渡すための設定オブジェクト。"""

    # setting.ini path / 設定ファイルパス
    ini_path: Path
    # app directory path / main.py or main.exe directory
    app_dir: Path


class CameraSettingDialog(QDialog):
    # 3 つのカメラ枠に対し、カテゴリと設備の組み合わせを選ばせる。
    """Select category and equipment for each camera frame."""

    def __init__(
        self,
        camera_definitions: dict[str, dict[str, str]],
        category_names: list[str],
        selected_settings: list[tuple[str, str]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._camera_definitions = camera_definitions
        self._category_names = category_names
        self._category_boxes: list[QComboBox] = []
        self._equipment_boxes: list[QComboBox] = []

        self.setWindowTitle("カメラ設定")
        self.resize(480, 240)

        root_layout = QVBoxLayout(self)
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(12)
        grid_layout.setVerticalSpacing(8)
        root_layout.addLayout(grid_layout)

        grid_layout.addWidget(QLabel(""), 0, 0)
        grid_layout.addWidget(QLabel("カテゴリ"), 0, 1)
        grid_layout.addWidget(QLabel("設備"), 0, 2)

        for index in range(3):
            row = index + 1
            camera_label = QLabel(f"カメラ{index + 1}")
            category_box = QComboBox(self)
            category_box.addItems(self._category_names)
            equipment_box = QComboBox(self)

            self._category_boxes.append(category_box)
            self._equipment_boxes.append(equipment_box)

            grid_layout.addWidget(camera_label, row, 0)
            grid_layout.addWidget(category_box, row, 1)
            grid_layout.addWidget(equipment_box, row, 2)

            category_box.currentTextChanged.connect(
                lambda category_text, camera_index=index: self._update_equipment_options(camera_index, category_text)
            )

            selected_category, selected_equipment = selected_settings[index]
            initial_category = (
                selected_category if selected_category in self._category_names else self._category_names[0]
            )
            category_box.setCurrentText(initial_category)
            self._update_equipment_options(index, initial_category, selected_equipment)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root_layout.addWidget(button_box)

    def _update_equipment_options(self, index: int, category_text: str, selected_equipment: str = "") -> None:
        """Refresh equipment candidates when a category changes."""
        equipment_box = self._equipment_boxes[index]
        equipment_options = list(self._camera_definitions.get(category_text, {}).keys())

        equipment_box.blockSignals(True)
        equipment_box.clear()
        equipment_box.addItems(equipment_options)
        if selected_equipment in equipment_options:
            equipment_box.setCurrentText(selected_equipment)
        elif equipment_options:
            equipment_box.setCurrentIndex(0)
        equipment_box.blockSignals(False)

    def get_selected_settings(self) -> list[tuple[str, str]]:
        selected_settings: list[tuple[str, str]] = []
        for category_box, equipment_box in zip(self._category_boxes, self._equipment_boxes):
            selected_settings.append((category_box.currentText(), equipment_box.currentText()))
        return selected_settings


class AppSettingDialog(QDialog):
    # 工場・炉・監視フォルダなど、現場運用に依存する設定を編集するダイアログ。
    """Edit setting.ini [setting] values."""

    def __init__(
        self,
        csv_folder_text: str,
        pdf_folder_text: str,
        face_folder_text: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("設定")
        self.resize(560, 200)

        root_layout = QVBoxLayout(self)
        grid_layout = QGridLayout()
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setHorizontalSpacing(12)
        grid_layout.setVerticalSpacing(8)
        root_layout.addLayout(grid_layout)

        self._csv_folder_input = QLineEdit(csv_folder_text, self)
        self._pdf_folder_input = QLineEdit(pdf_folder_text, self)
        self._face_folder_input = QLineEdit(face_folder_text, self)

        grid_layout.addWidget(QLabel("CSV_FOLDER"), 0, 0)
        grid_layout.addWidget(self._csv_folder_input, 0, 1)
        grid_layout.addWidget(QLabel("PDF_FOLDER"), 1, 0)
        grid_layout.addWidget(self._pdf_folder_input, 1, 1)
        grid_layout.addWidget(QLabel("FACE_FOLDER"), 2, 0)
        grid_layout.addWidget(self._face_folder_input, 2, 1)

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        root_layout.addWidget(button_box)

    def get_selected_settings(self) -> tuple[str, str, str]:
        return (
            self._csv_folder_input.text().strip(),
            self._pdf_folder_input.text().strip(),
            self._face_folder_input.text().strip(),
        )


class MainWindow(QMainWindow):
    """
    VB版 From_CSV_Import (Top.vb) の Python 実装。
    Python implementation of VB From_CSV_Import (Top.vb).
    """

    def __init__(self, app_config: AppConfig) -> None:
        super().__init__()
        self._app_config = app_config

        # ワーカースレッド→UIスレッドへの通知 / Worker-to-UI notification
        # CSV 読込は別スレッド、UI 更新はメインスレッドという境界をここで明確にする。
        self._csv_import_done.connect(self._finish_csv_import)
        self._shiji_scan_result_ready.connect(self._handle_shiji_scan_result)

        # 状態保持 / State
        # 現在表示中の状態と、設定ファイルから復元した運用設定をまとめて保持する。
        self._ini = load_ini(self._app_config.ini_path)
        self._ini_last_modified_at = self._get_ini_last_modified_at()
        self._csv_watcher: Optional[CsvWatcher] = None

        self._factory_name = ""
        self._ro_name = ""
        self._ro_no = ""
        self._csv_folder = Path(".")
        self._csv_file = ""
        self._access_file_path = Path("")
        self._pdf_folder = Path(".")
        self._face_folder = Path(".")
        self._shiji_json_path = get_shiji_data_path(self._app_config.app_dir)
        configure_shiji_json_path(self._shiji_json_path)
        configure_pg_access_match_batches_path(self._shiji_json_path.with_name("pg_access_match_batches.json"))

        self._in_time = "0"
        self._face_id1 = "0"
        self._face_id2 = "0"
        self._face_id3 = "0"
        self._sijino = "0"
        self._hin_name = "0"
        self._nisugata = "0"
        self._lot = "0"
        self._pdf_filename = "0"

        # Countdown / カウントダウン
        self._countdown_seconds = 0
        self._countdown_mode = ""
        self._pdf_zoom_factor = 1.0

        self._cam_urls: list[str] = ["0", "0", "0"]
        self._camera_captures: list[Optional[cv2.VideoCapture]] = [None, None, None]
        self._camera_frames: list[Optional[Any]] = [None, None, None]
        self._camera_locks = [threading.Lock() for _ in range(3)]
        self._camera_threads: list[threading.Thread] = []
        self._camera_stop_event = threading.Event()
        self._camera_status_messages: list[str] = ["No Camera", "No Camera", "No Camera"]
        self._camera_failure_counts: list[int] = [0, 0, 0]
        self._oracle_pg_status_by_furnace: dict[str, dict[str, Any]] = {}
        self._oracle_pg_status_loaded_at = 0.0
        self._scheduled_update_checked_key = ""
        self._camera_definitions: dict[str, dict[str, str]] = {}
        self._camera_selection_states: list[tuple[str, str]] = [("", ""), ("", ""), ("", "")]
        self._ro_definitions: dict[str, dict[str, list[str]]] = {}
        self._pg_furnace_status_rows, self._sq_furnace_status_rows = _build_default_furnace_status_rows()
        self._left_panel_font_signature: Optional[tuple[int, ...]] = None
        self._left_panel_main_title_font_size = 22
        self._left_panel_info_section_title_font_size = 18
        self._left_panel_info_label_font_size = _INFO_TITLE_FONT_SIZE
        self._left_panel_info_value_font_size = _INFO_VALUE_FONT_SIZE
        self._left_panel_operator_section_title_font_size = 18
        self._left_panel_operator_name_font_size = 16
        self._left_panel_operator_image_width = _OPERATOR_IMAGE_WIDTH
        self._left_panel_operator_image_height = _OPERATOR_IMAGE_HEIGHT
        self._right_panel_font_signature: Optional[tuple[int, ...]] = None
        self._right_panel_main_title_font_size = 24
        self._right_panel_status_title_font_size = _RIGHT_PANEL_STATUS_TITLE_FONT_MIN
        self._right_panel_status_header_font_size = _RIGHT_PANEL_STATUS_HEADER_FONT_MIN
        self._right_panel_status_value_font_size = _RIGHT_PANEL_STATUS_VALUE_FONT_MIN
        self._right_panel_time_value_font_size = _RIGHT_PANEL_TIME_VALUE_FONT_MIN
        self._right_panel_note_font_size = 13
        self._right_panel_summary_title_font_size = 26
        self._right_panel_current_time_font_size = 48
        self._right_panel_summary_value_font_size = 36

        # UI / 画面
        self._build_ui()

        # 設定ロード / Load settings
        self._load_settings_from_ini()

        # 起動と同時に最大化（VB版に合わせる）/ Maximize on startup
        self.showMaximized()

        # CSV処理中フラグ / CSV import running flag
        self._csv_import_running = False

        # カメラ開始 / Start cameras
        # Qtウィジェット(winId)へ埋め込む処理はUIスレッドで行う必要があるため、
        # 起動直後にUIスレッドで実行する（VB版のTask.Run相当だがQtでは安全側に寄せる）。
        # 起動直後のCSV読込 / Read CSV once at startup
        # CSVはネットワーク共有上の可能性があり、UI停止を避けるためバックグラウンドで実行
        # CSV may be on network share; run in background to avoid freezing UI.
        self._trigger_csv_import()

        # 30秒周期のCSV確認 / Periodic CSV check (30s)
        self._timer_csv = QTimer(self)
        self._timer_csv.setInterval(30_000)
        self._timer_csv.timeout.connect(self._periodic_csv_check)
        self._timer_csv.start()

        # 1秒タイマー（カウントダウン）/ 1-second countdown timer
        self._timer_countdown = QTimer(self)
        self._timer_countdown.setInterval(1000)
        self._timer_countdown.timeout.connect(self.countdown_tick)

        self._timer_clock = QTimer(self)
        self._timer_clock.setInterval(1000)
        self._timer_clock.timeout.connect(self._update_current_time_labels)
        self._timer_clock.start()

        self._timer_ini = QTimer(self)
        self._timer_ini.setInterval(1000)
        self._timer_ini.timeout.connect(self._check_ini_updates)
        self._timer_ini.start()

        self._timer_scheduled_update = QTimer(self)
        self._timer_scheduled_update.setInterval(60_000)
        self._timer_scheduled_update.timeout.connect(self._check_scheduled_update)
        self._timer_scheduled_update.start()

        # watchdog開始 / Start watchdog
        self._start_csv_watcher()

    def _process_access_csv_history(self) -> None:
        if not self._access_file_path:
            return
        pg_access_match_batches_by_furnace: dict[str, list[dict[str, Any]]] = {}
        try:
            updated_batches = update_pg_access_match_batches(fetch_recent_pg_furnace_batches_for_access_match())
            logger.debug(
                "ORACLE_PG_ACCESS_MATCH_LOADED furnaces=%s batches=%s",
                len({str(batch.get("pg_furnace", "") or "").strip() for batch in updated_batches if batch.get("pg_furnace")}),
                len(updated_batches),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ORACLE_PG_ACCESS_MATCH_LOAD_FAILED error=%s", exc)
        try:
            pg_access_match_batches_by_furnace = load_pending_pg_access_match_batches_by_furnace()
        except Exception as exc:  # noqa: BLE001
            logger.warning("PG_ACCESS_MATCH_BATCHES_LOAD_FAILED error=%s", exc)
        try:
            access_result = process_new_access_file_entries(
                self._access_file_path,
                pg_status_by_furnace=self._oracle_pg_status_by_furnace,
                pg_access_match_batches_by_furnace=pg_access_match_batches_by_furnace,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("ACCESS_CSV_HISTORY_FAILED path=%s error=%s", self._access_file_path, exc)
            return
        if access_result.get("result") == "ok" and int(access_result.get("changed_count", 0) or 0) > 0:
            logger.info(
                "ACCESS_CSV_HISTORY_PROCESSED path=%s record_count=%s changed_count=%s",
                self._access_file_path,
                access_result.get("record_count", 0),
                access_result.get("changed_count", 0),
            )

    # ----------------------------
    # CSV import threading / CSV取込のスレッド実行
    # ----------------------------
    def _trigger_csv_import(self) -> None:
        """
        read_csv() + visi_textbox_ws_timecount() をUIを止めずに実行します。
        Run read_csv() + visi_textbox_ws_timecount() without blocking UI.
        """
        if getattr(self, "_csv_import_running", False):
            return

        self._csv_import_running = True

        def worker() -> None:
            try:
                self.read_csv()
                self._process_access_csv_history()
            except Exception as exc:  # noqa: BLE001
                logger.exception("CSV_IMPORT_WORKER_FAILED error=%s", exc)
            finally:
                # UI更新はUIスレッドで実行 / UI updates must run on UI thread
                self._csv_import_done.emit()

        # CSV 読込は共有フォルダ待ちで時間がかかるため、常にデーモンスレッドで実行する。
        threading.Thread(target=worker, daemon=True).start()

    def _finish_csv_import(self) -> None:
        # CSV 取込が終わったら、INI を読み直して画面反映する処理へ一本化する。
        self._csv_import_running = False
        self.visi_textbox_ws_timecount()

    # ----------------------------
    # UI construction / UI構築
    # ----------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("ピット炉作業支援大型モニター")

        root = QWidget(self)
        self.setCentralWidget(root)
        self._root_widget = root

        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(12)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        root_layout.addLayout(header_layout)

        title_label = QLabel("ピット炉作業支援大型モニター画面")
        self._main_title_label = title_label
        title_label.setStyleSheet("font-size: 22px; font-weight: bold;")
        title_label.hide()
        header_layout.addStretch(1)

        self.btn_operator_setting = QPushButton("作業者変更")
        self.btn_operator_setting.clicked.connect(self._on_operator_setting_clicked)
        self.btn_update_history = QPushButton("更新履歴")
        self.btn_update_history.clicked.connect(self._show_update_history_dialog)
        for button in (self.btn_operator_setting, self.btn_update_history):
            button.setFixedHeight(34)

        self.label_sijino = QLabel("")
        self.label_hin = QLabel("")
        self.label_nisugata = QLabel("")
        self.label_lot = QLabel("")
        self.label_stop = QLabel("装入STOP")
        self.label_stop.setAlignment(Qt.AlignCenter)
        self.label_stop.setStyleSheet(
            f"font-size: {_COUNTDOWN_STOP_LABEL_FONT_SIZE}px; font-weight: bold; color: red;"
        )
        self.label_countdown = QLabel("")
        self.label_countdown.setAlignment(Qt.AlignCenter)
        self.label_countdown.setStyleSheet(
            f"font-size: {_COUNTDOWN_STOP_LABEL_FONT_SIZE}px; font-weight: bold; color: red;"
        )
        self.label_stop.hide()
        self.label_countdown.hide()

        self.stop_popup = QFrame(root)
        self.stop_popup.setFrameShape(QFrame.StyledPanel)
        self.stop_popup.setStyleSheet("background: rgba(255, 255, 255, 245); border: 3px solid #cc2222;")
        self.stop_popup.setFixedWidth(_COUNTDOWN_POPUP_WIDTH)
        stop_popup_layout = QVBoxLayout(self.stop_popup)
        stop_popup_layout.setContentsMargins(24, 18, 24, 18)
        stop_popup_layout.setSpacing(12)
        stop_popup_layout.addWidget(self.label_stop)
        stop_popup_layout.addWidget(self.label_countdown)
        self.stop_popup.hide()
        self._update_stop_popup_position()

        body_layout = QHBoxLayout()
        body_layout.setSpacing(12)
        self._middle_split_layout = body_layout
        root_layout.addLayout(body_layout, stretch=1)

        left_column = QVBoxLayout()
        left_column.setSpacing(12)
        body_layout.addLayout(left_column, stretch=3)

        pdf_panel = QFrame()
        pdf_panel.setFrameShape(QFrame.StyledPanel)
        pdf_panel.setStyleSheet("background: white;")
        self._left_reference_panel = pdf_panel
        pdf_layout = QVBoxLayout(pdf_panel)
        pdf_layout.setContentsMargins(8, 8, 8, 8)
        pdf_layout.setSpacing(8)

        pdf_title_label = QLabel("")
        self._pdf_title_label = pdf_title_label
        pdf_title_label.setStyleSheet("font-size: 20px; font-weight: bold;")
        pdf_layout.addWidget(pdf_title_label)

        pdf_toolbar_layout = QHBoxLayout()
        pdf_toolbar_layout.setSpacing(8)
        self.btn_pdf_zoom_out = QPushButton("-")
        self.btn_pdf_zoom_out.setFixedWidth(40)
        self.btn_pdf_zoom_out.clicked.connect(self._zoom_out_pdf)
        self.btn_pdf_zoom_in = QPushButton("+")
        self.btn_pdf_zoom_in.setFixedWidth(40)
        self.btn_pdf_zoom_in.clicked.connect(self._zoom_in_pdf)
        self.btn_pdf_zoom_reset = QPushButton("100%")
        self.btn_pdf_zoom_reset.setFixedWidth(64)
        self.btn_pdf_zoom_reset.clicked.connect(self._reset_pdf_zoom)
        self.input_pdf_zoom = QLineEdit("100%")
        self.input_pdf_zoom.setFixedWidth(72)
        self.input_pdf_zoom.setAlignment(Qt.AlignRight)
        self.input_pdf_zoom.editingFinished.connect(self._apply_pdf_zoom_input)
        pdf_toolbar_layout.addWidget(self.btn_pdf_zoom_out)
        pdf_toolbar_layout.addWidget(self.btn_pdf_zoom_in)
        pdf_toolbar_layout.addWidget(self.btn_pdf_zoom_reset)
        pdf_toolbar_layout.addWidget(self.input_pdf_zoom)
        pdf_toolbar_layout.addStretch(1)
        pdf_layout.addLayout(pdf_toolbar_layout)

        self.pdf_label = QLabel("PDF未表示 / No PDF")
        self.pdf_label.setAlignment(Qt.AlignCenter)
        self.pdf_label.setStyleSheet("background: white; color: #333;")
        self.pdf_scroll = QScrollArea()
        self.pdf_scroll.setWidgetResizable(False)
        self.pdf_scroll.setWidget(self.pdf_label)
        self.pdf_scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.pdf_scroll.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.pdf_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.pdf_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.pdf_scroll.setStyleSheet("background: white;")
        pdf_layout.addWidget(self.pdf_scroll, stretch=1)
        self._pdf_pixmap_original: Optional[QPixmap] = None
        left_column.addWidget(pdf_panel, stretch=8)

        lower_layout = QHBoxLayout()
        lower_layout.setSpacing(8)
        left_column.addLayout(lower_layout, stretch=0)

        info_panel = QFrame()
        info_panel.setFrameShape(QFrame.StyledPanel)
        info_panel.setStyleSheet("background: #fff8ef;")
        info_layout = QVBoxLayout(info_panel)
        info_layout.setContentsMargins(12, 4, 12, 6)
        info_layout.setSpacing(4)
        lower_layout.addWidget(info_panel, stretch=3)

        info_title_label = QLabel("")
        self._info_title_label = info_title_label
        info_title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        info_layout.addWidget(info_title_label)
        info_title_label.hide()

        info_items_layout = QGridLayout()
        info_items_layout.setHorizontalSpacing(12)
        info_items_layout.setVerticalSpacing(6)
        info_layout.addLayout(info_items_layout)

        self._info_summary_label = QLabel("")
        self._info_summary_label.setWordWrap(True)
        self._info_summary_label.setStyleSheet(f"font-size: {_INFO_VALUE_FONT_SIZE}px;")
        info_layout.addWidget(self._info_summary_label)

        self.label_sijino.setWordWrap(True)
        self.label_hin.setWordWrap(True)
        self.label_nisugata.setWordWrap(True)
        self.label_lot.setWordWrap(True)
        self._info_item_title_labels: list[QLabel] = []
        self._info_item_value_labels = [self.label_sijino, self.label_hin, self.label_nisugata, self.label_lot]
        for title, value_label in (("指示書No", self.label_sijino), ("品名", self.label_hin), ("荷姿", self.label_nisugata), ("Lot", self.label_lot)):
            title_label = QLabel(title)
            self._info_item_title_labels.append(title_label)
            title_label.setStyleSheet(f"font-size: {_INFO_TITLE_FONT_SIZE}px; font-weight: bold;")
            title_label.hide()
            value_label.setStyleSheet(f"font-size: {_INFO_VALUE_FONT_SIZE}px;")
            value_label.hide()
            current_row = info_items_layout.rowCount()
            info_items_layout.addWidget(title_label, current_row, 0)
            info_items_layout.addWidget(value_label, current_row, 1)
        info_layout.addStretch(1)

        operator_panel = QFrame()
        self._operator_panel = operator_panel
        operator_panel.setFrameShape(QFrame.StyledPanel)
        operator_panel.setStyleSheet("background: #f4f7fb;")
        operator_layout = QVBoxLayout(operator_panel)
        operator_layout.setContentsMargins(12, 4, 12, 10)
        operator_layout.setSpacing(4)

        operator_title_label = QLabel("")
        self._operator_title_label = operator_title_label
        operator_title_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        operator_layout.addWidget(operator_title_label)
        operator_title_label.hide()

        operator_cards_layout = QHBoxLayout()
        operator_cards_layout.setSpacing(8)
        operator_layout.addLayout(operator_cards_layout)

        self.face_main_title = QLabel("")
        self.face_sub_title = QLabel("")
        self.face_third_title = QLabel("")
        self._operator_name_labels = [self.face_main_title, self.face_sub_title, self.face_third_title]
        self.face_main = QLabel()
        self.face_sub = QLabel()
        self.face_third = QLabel()
        self._operator_image_labels = [self.face_main, self.face_sub, self.face_third]
        for widget in (self.face_main, self.face_sub, self.face_third):
            widget.setFixedSize(_OPERATOR_IMAGE_WIDTH, _OPERATOR_IMAGE_HEIGHT)
            widget.setAlignment(Qt.AlignCenter)
            widget.setStyleSheet("background: #222; color: #bbb; border: 1px solid #999;")
            widget.setScaledContents(True)

        operator_cards_layout.addWidget(self._create_operator_card(self.face_main_title, self.face_main))
        operator_cards_layout.addWidget(self._create_operator_card(self.face_sub_title, self.face_sub))
        self._operator_third_card = self._create_operator_card(self.face_third_title, self.face_third)
        operator_cards_layout.addWidget(self._operator_third_card)
        self._operator_third_card.hide()
        operator_layout.addStretch(1)

        right_panel = QFrame()
        right_panel.setFrameShape(QFrame.StyledPanel)
        right_panel.setStyleSheet("background: #dce9f7;")
        self._right_panel = right_panel
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(12)
        body_layout.addWidget(right_panel, stretch=2)

        furnace_title_label = QLabel("ソルト槽処理状況")
        self._furnace_title_label = furnace_title_label
        furnace_title_label.setText("炉処理状況")
        furnace_title_label.setStyleSheet("font-size: 24px; font-weight: bold;")
        right_header_layout = QHBoxLayout()
        right_header_layout.setSpacing(8)
        right_header_layout.addWidget(furnace_title_label)
        right_header_layout.addStretch(1)
        right_header_layout.addWidget(self.btn_operator_setting)
        right_header_layout.addWidget(self.btn_update_history)
        right_layout.addLayout(right_header_layout)
        self._pg_status_panel_container = QWidget()
        self._pg_status_panel_container_layout = QVBoxLayout(self._pg_status_panel_container)
        self._pg_status_panel_container_layout.setContentsMargins(0, 0, 0, 0)
        self._pg_status_panel_container_layout.setSpacing(0)
        self._pg_status_panel_container_layout.addWidget(
            self._create_furnace_status_panel("", ("炉", "作業指示書No", "開始時間"), self._pg_furnace_status_rows, "pg")
        )
        right_layout.addWidget(self._pg_status_panel_container, stretch=2)

        self._sq_status_panel_container = QWidget()
        self._sq_status_panel_container_layout = QVBoxLayout(self._sq_status_panel_container)
        self._sq_status_panel_container_layout.setContentsMargins(0, 0, 0, 0)
        self._sq_status_panel_container_layout.setSpacing(0)
        self._sq_status_panel_container_layout.addWidget(
            self._create_furnace_status_panel("", self._get_sq_header_texts(), self._sq_furnace_status_rows, "sq")
        )
        right_layout.addWidget(self._sq_status_panel_container, stretch=1)

        status_note_label = QLabel(
            "※ 処理状況に応じて文字色を変化  "
            "<span style='color:#005a9e;'>処理中</span> / "
            "<span style='color:#c00000;'>終了超過</span> / "
            "<span style='color:#555555;'>停機</span>"
        )
        self._status_note_label = status_note_label
        status_note_label.setText(
            "※ 処理状況に応じて文字色を変化  "
            "<span style='color:#005a9e;'>処理中</span> / "
            "<span style='color:#c00000;'>終了超過</span> / "
            "<span style='color:#555555;'>停機</span>"
        )
        status_note_label.setWordWrap(True)
        status_note_label.hide()
        right_layout.addWidget(status_note_label)

        summary_panel = QFrame()
        summary_panel.setFrameShape(QFrame.StyledPanel)
        summary_panel.setStyleSheet("background: white;")
        summary_layout = QVBoxLayout(summary_panel)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_layout.setSpacing(8)
        summary_content_layout = QHBoxLayout()
        summary_content_layout.setSpacing(16)
        summary_layout.addLayout(summary_content_layout)

        current_time_panel = QWidget()
        current_time_layout = QVBoxLayout(current_time_panel)
        current_time_layout.setContentsMargins(0, 0, 0, 0)
        current_time_layout.setSpacing(8)
        current_time_title_label = QLabel("現在時刻")
        self._current_time_title_label = current_time_title_label
        current_time_title_label.setStyleSheet("font-size: 26px; font-weight: bold;")
        current_time_layout.addWidget(current_time_title_label)
        self.label_current_time = QLabel("--:--")
        self.label_current_time.setStyleSheet("font-size: 48px; font-weight: bold;")
        current_time_layout.addWidget(self.label_current_time)
        current_time_layout.addStretch(1)
        summary_content_layout.addWidget(current_time_panel, stretch=1)
        current_time_panel.hide()

        summary_separator = QFrame()
        summary_separator.setFrameShape(QFrame.VLine)
        summary_separator.setStyleSheet("color: #b7c5d6;")
        summary_content_layout.addWidget(summary_separator)
        summary_separator.hide()

        overdue_panel = QWidget()
        overdue_layout = QVBoxLayout(overdue_panel)
        overdue_layout.setContentsMargins(0, 0, 0, 0)
        overdue_layout.setSpacing(8)
        overdue_title_label = QLabel("終了超過炉")
        self._overdue_title_label = overdue_title_label
        overdue_title_label.setText("終了超過炉")
        overdue_title_label.setStyleSheet("font-size: 26px; font-weight: bold;")
        overdue_layout.addWidget(overdue_title_label)
        self.label_overdue_furnaces = QLabel("-")
        self.label_overdue_furnaces.setWordWrap(True)
        self.label_overdue_furnaces.setStyleSheet("font-size: 36px; color: #b00020; font-weight: bold;")
        overdue_layout.addWidget(self.label_overdue_furnaces)
        overdue_layout.addStretch(1)
        summary_content_layout.addWidget(overdue_panel, stretch=1)
        summary_panel.hide()
        right_layout.addWidget(summary_panel, stretch=0)

        right_layout.addWidget(operator_panel, stretch=1)

        self.camera_panel = QFrame()
        self.camera_panel.hide()
        camera_layout = QVBoxLayout(self.camera_panel)
        camera_layout.setSpacing(8)
        self.cam_widgets: list[QLabel] = []
        for _ in range(3):
            frame = QLabel("No Camera")
            frame.setAlignment(Qt.AlignCenter)
            frame.setStyleSheet("background: black; color: #bbb;")
            frame.setMinimumHeight(120)
            frame.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
            camera_layout.addWidget(frame, stretch=1)
            self.cam_widgets.append(frame)

        self.top_bar = QFrame()
        self.top_bar.hide()
        self._refresh_status_summary()
        self._update_current_time_labels()
        self._update_middle_panel_stretch()
        QTimer.singleShot(0, self._refresh_left_panel_fonts)
        QTimer.singleShot(0, self._refresh_right_panel_fonts)

    def _create_operator_card(self, title_label: QLabel, image_label: QLabel) -> QWidget:
        card = QFrame()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(6)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        card_layout.addWidget(title_label)
        card_layout.addWidget(image_label, alignment=Qt.AlignCenter)
        return card

    def _refresh_left_panel_fonts(self) -> None:
        left_reference_panel = getattr(self, "_left_reference_panel", None)
        if not isinstance(left_reference_panel, QWidget):
            return

        width_range = max(1, _LEFT_PANEL_WIDTH_MAX - _LEFT_PANEL_WIDTH_MIN)
        width_ratio = _clamp((left_reference_panel.width() - _LEFT_PANEL_WIDTH_MIN) / width_range, 0.0, 1.0)
        font_signature = (
            _interpolate_int(_LEFT_PANEL_MAIN_TITLE_FONT_MIN, _LEFT_PANEL_MAIN_TITLE_FONT_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_INFO_SECTION_TITLE_FONT_MIN, _LEFT_PANEL_INFO_SECTION_TITLE_FONT_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_INFO_LABEL_FONT_MIN, _LEFT_PANEL_INFO_LABEL_FONT_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_INFO_VALUE_FONT_MIN, _LEFT_PANEL_INFO_VALUE_FONT_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_OPERATOR_SECTION_TITLE_FONT_MIN, _LEFT_PANEL_OPERATOR_SECTION_TITLE_FONT_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_OPERATOR_NAME_FONT_MIN, _LEFT_PANEL_OPERATOR_NAME_FONT_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_OPERATOR_IMAGE_WIDTH_MIN, _LEFT_PANEL_OPERATOR_IMAGE_WIDTH_MAX, width_ratio),
            _interpolate_int(_LEFT_PANEL_OPERATOR_IMAGE_HEIGHT_MIN, _LEFT_PANEL_OPERATOR_IMAGE_HEIGHT_MAX, width_ratio),
        )
        if font_signature == self._left_panel_font_signature:
            return

        self._left_panel_font_signature = font_signature
        (
            self._left_panel_main_title_font_size,
            self._left_panel_info_section_title_font_size,
            self._left_panel_info_label_font_size,
            self._left_panel_info_value_font_size,
            self._left_panel_operator_section_title_font_size,
            self._left_panel_operator_name_font_size,
            self._left_panel_operator_image_width,
            self._left_panel_operator_image_height,
        ) = font_signature

        self._main_title_label.setStyleSheet(
            f"font-size: {self._left_panel_main_title_font_size}px; font-weight: bold;"
        )
        self._pdf_title_label.setStyleSheet(
            f"font-size: {self._left_panel_info_section_title_font_size}px; font-weight: bold;"
        )
        self._info_title_label.setStyleSheet(
            f"font-size: {self._left_panel_info_section_title_font_size}px; font-weight: bold;"
        )
        self._operator_title_label.setStyleSheet(
            f"font-size: {self._left_panel_operator_section_title_font_size}px; font-weight: bold;"
        )
        self._info_summary_label.setStyleSheet(
            f"font-size: {self._left_panel_info_value_font_size}px;"
        )
        for title_label in self._info_item_title_labels:
            title_label.setStyleSheet(
                f"font-size: {self._left_panel_info_label_font_size}px; font-weight: bold;"
            )
        for value_label in self._info_item_value_labels:
            value_label.setStyleSheet(f"font-size: {self._left_panel_info_value_font_size}px;")
        for name_label in self._operator_name_labels:
            name_label.setStyleSheet(
                f"font-size: {self._left_panel_operator_name_font_size}px; font-weight: bold;"
            )
        for image_label in self._operator_image_labels:
            image_label.setFixedSize(
                self._left_panel_operator_image_width,
                self._left_panel_operator_image_height,
            )

    def _refresh_right_panel_fonts(self) -> None:
        right_panel = getattr(self, "_right_panel", None)
        if not isinstance(right_panel, QWidget):
            return

        width_range = max(1, _RIGHT_PANEL_WIDTH_MAX - _RIGHT_PANEL_WIDTH_MIN)
        width_ratio = _clamp((right_panel.width() - _RIGHT_PANEL_WIDTH_MIN) / width_range, 0.0, 1.0)
        font_signature = (
            _interpolate_int(_RIGHT_PANEL_MAIN_TITLE_FONT_MIN, _RIGHT_PANEL_MAIN_TITLE_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_STATUS_TITLE_FONT_MIN, _RIGHT_PANEL_STATUS_TITLE_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_STATUS_HEADER_FONT_MIN, _RIGHT_PANEL_STATUS_HEADER_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_STATUS_VALUE_FONT_MIN, _RIGHT_PANEL_STATUS_VALUE_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_TIME_VALUE_FONT_MIN, _RIGHT_PANEL_TIME_VALUE_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_NOTE_FONT_MIN, _RIGHT_PANEL_NOTE_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_SUMMARY_TITLE_FONT_MIN, _RIGHT_PANEL_SUMMARY_TITLE_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_CURRENT_TIME_FONT_MIN, _RIGHT_PANEL_CURRENT_TIME_FONT_MAX, width_ratio),
            _interpolate_int(_RIGHT_PANEL_SUMMARY_VALUE_FONT_MIN, _RIGHT_PANEL_SUMMARY_VALUE_FONT_MAX, width_ratio),
        )
        if font_signature == self._right_panel_font_signature:
            return

        self._right_panel_font_signature = font_signature
        (
            self._right_panel_main_title_font_size,
            self._right_panel_status_title_font_size,
            self._right_panel_status_header_font_size,
            self._right_panel_status_value_font_size,
            self._right_panel_time_value_font_size,
            self._right_panel_note_font_size,
            self._right_panel_summary_title_font_size,
            self._right_panel_current_time_font_size,
            self._right_panel_summary_value_font_size,
        ) = font_signature

        self._furnace_title_label.setStyleSheet(
            f"font-size: {self._right_panel_main_title_font_size}px; font-weight: bold;"
        )
        self._status_note_label.setStyleSheet(f"font-size: {self._right_panel_note_font_size}px;")
        self._current_time_title_label.setStyleSheet(
            f"font-size: {self._right_panel_summary_title_font_size}px; font-weight: bold;"
        )
        self.label_current_time.setStyleSheet(
            f"font-size: {self._right_panel_current_time_font_size}px; font-weight: bold;"
        )
        self._overdue_title_label.setStyleSheet(
            f"font-size: {self._right_panel_summary_title_font_size}px; font-weight: bold;"
        )
        self.label_overdue_furnaces.setStyleSheet(
            f"font-size: {self._right_panel_summary_value_font_size}px; color: #b00020; font-weight: bold;"
        )
        self._refresh_furnace_status_panels(emit_log=False)

    def _create_furnace_status_panel(self, title_text: str, header_texts: tuple[str, ...], furnace_status_rows: list[FurnaceStatusRow], panel_kind: str) -> QWidget:
        panel = QFrame()
        panel.setFrameShape(QFrame.StyledPanel)
        panel.setStyleSheet("background: white;")
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)
        panel_layout.setSpacing(8)
        is_sq_panel = panel_kind == "sq"
        is_pg_panel = panel_kind == "pg"
        header_font_size = self._right_panel_status_header_font_size + (4 if is_sq_panel else 0)
        value_font_size = self._right_panel_status_value_font_size + (4 if is_sq_panel else 0)
        if is_pg_panel:
            header_font_size += 2
            value_font_size += 2
        title_label = QLabel(title_text)
        title_label.setStyleSheet(f"font-size: {self._right_panel_status_title_font_size}px; font-weight: bold;")
        if title_text:
            panel_layout.addWidget(title_label)

        grid_layout = QGridLayout()
        grid_layout.setHorizontalSpacing(8)
        grid_layout.setVerticalSpacing(6)
        for column_index, header_text in enumerate(header_texts):
            header_label = QLabel(header_text)
            header_label.setStyleSheet(
                f"font-size: {header_font_size}px; font-weight: bold;"
            )
            grid_layout.addWidget(header_label, 0, column_index)

        for row_index, furnace_status_row in enumerate(furnace_status_rows, start=1):
            status_text = furnace_status_row.status_text
            countdown_clock_text = ""
            is_countdown_row = is_sq_panel and bool(furnace_status_row.countdown_text)
            if furnace_status_row.status_kind == "overdue":
                status_text = f"⚠ {status_text}"
            elif is_countdown_row:
                status_text = "ソルト上げ"

            if is_countdown_row:
                countdown_clock_text = furnace_status_row.countdown_text.rsplit(" ", 1)[-1]

            if is_sq_panel:
                end_time_or_countdown_text = countdown_clock_text or furnace_status_row.end_time_text
                row_values = [furnace_status_row.furnace_name, status_text, end_time_or_countdown_text]
            else:
                row_values = [
                    furnace_status_row.furnace_name,
                    furnace_status_row.instruction_no_text,
                    furnace_status_row.start_time_text,
                ]

            for column_index, row_value in enumerate(row_values):
                if is_sq_panel and column_index == 1:
                    status_widget = QFrame()
                    status_widget.setStyleSheet("background: transparent;")
                    status_layout = QVBoxLayout(status_widget)
                    status_layout.setContentsMargins(0, 0, 0, 0)
                    status_layout.setSpacing(4)

                    value_label = QLabel(row_value)
                    status_color = _STATUS_COLOR_BY_KIND.get(furnace_status_row.status_kind, "#f1f1f1")
                    status_text_color = _STATUS_TEXT_COLOR_BY_KIND.get(furnace_status_row.status_kind, "#222222")
                    if is_countdown_row:
                        status_color = "rgba(255, 255, 255, 245)"
                        status_text_color = "#c00000"
                    value_label.setStyleSheet(
                        f"background: {status_color}; color: {status_text_color}; padding: 4px 6px; border: {('2px solid #cc2222' if is_countdown_row else '1px solid #9aa4af')}; font-size: {value_font_size}px; font-weight: bold;"
                    )
                    status_layout.addWidget(value_label)

                    if furnace_status_row.countdown_text and not is_countdown_row:
                        countdown_label = QLabel(furnace_status_row.countdown_text)
                        countdown_label.setAlignment(Qt.AlignCenter)
                        countdown_label.setStyleSheet(
                            f"background: rgba(255, 255, 255, 245); color: #c00000; border: 2px solid #cc2222; padding: 2px 4px; font-size: {max(16, value_font_size - 2)}px; font-weight: bold;"
                        )
                        status_layout.addWidget(countdown_label)

                    grid_layout.addWidget(status_widget, row_index, column_index)
                    continue

                value_label = QLabel(row_value)
                if column_index >= 2:
                    time_font_size = value_font_size if is_sq_panel else self._right_panel_time_value_font_size + (2 if is_pg_panel else 0)
                    if is_sq_panel and is_countdown_row and column_index == 2:
                        value_label.setStyleSheet(
                            f"background: rgba(255, 255, 255, 245); color: #c00000; border: 2px solid #cc2222; padding: 2px 4px; font-size: {time_font_size}px; font-weight: bold;"
                        )
                    else:
                        value_label.setStyleSheet(f"font-size: {time_font_size}px;")
                elif not is_sq_panel and column_index == 1:
                    value_label.setStyleSheet(
                        f"background: #f8f8f8; padding: 4px 6px; border: 1px solid #9aa4af; font-size: {value_font_size}px; font-weight: bold;"
                    )
                else:
                    value_label.setStyleSheet(f"font-size: {value_font_size}px;")
                grid_layout.addWidget(value_label, row_index, column_index)
        panel_layout.addLayout(grid_layout)
        return panel

    def _get_sq_header_texts(self) -> tuple[str, str, str]:
        if any(row.countdown_text for row in self._sq_furnace_status_rows):
            return ("炉", "ソルト上げ", "カウントダウン")
        return ("炉", "処理状況", "終了時間")

    def _replace_furnace_status_panel(self, container_layout: QVBoxLayout, panel_widget: QWidget) -> None:
        while container_layout.count() > 0:
            layout_item = container_layout.takeAt(0)
            old_widget = layout_item.widget()
            if old_widget is not None:
                old_widget.deleteLater()
        container_layout.addWidget(panel_widget)

    def _build_sq_countdown_seconds_by_name(self) -> dict[str, int]:
        countdown_seconds_by_name: dict[str, int] = {}
        for furnace_status_row in self._sq_furnace_status_rows:
            countdown_seconds = _resolve_countdown_seconds(furnace_status_row.end_time_text)
            if countdown_seconds is None:
                continue
            countdown_seconds_by_name[furnace_status_row.furnace_name] = countdown_seconds
        return countdown_seconds_by_name

    def _load_oracle_pg_status_by_furnace(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        if now - self._oracle_pg_status_loaded_at < _ORACLE_PG_STATUS_REFRESH_SECONDS:
            return self._oracle_pg_status_by_furnace
        try:
            self._oracle_pg_status_by_furnace = {
                str(pg_status.get("furnace", "")): pg_status
                for pg_status in fetch_current_pg_furnace_statuses()
                if str(pg_status.get("furnace", ""))
            }
            self._oracle_pg_status_loaded_at = now
        except Exception as exc:  # noqa: BLE001
            logger.warning("ORACLE_PG_STATUS_LOAD_FAILED error=%s", exc)
        return self._oracle_pg_status_by_furnace

    def _load_furnace_status_rows_from_ini(self) -> None:
        loaded_furnace_status_rows: list[FurnaceStatusRow] = []
        pg_latest_group_display_by_furnace = load_latest_group_display_by_furnace()
        shiji_status_overrides = load_shiji_furnace_status_overrides()
        oracle_pg_status_by_furnace = self._load_oracle_pg_status_by_furnace()
        for index, default_furnace_name in enumerate(_DEFAULT_FURNACE_NAMES, start=1):
            furnace_name = ini_get(self._ini, "setting", f"rono{index}", default_furnace_name)
            shiji_status_override = shiji_status_overrides.get(furnace_name, {})
            oracle_pg_status = oracle_pg_status_by_furnace.get(furnace_name, {})
            instruction_no_text = ini_get(self._ini, "SECTION_2", f"sijino{index}", "-")
            if furnace_name.startswith("PG-"):
                instruction_no_text = shiji_status_override.get(
                    "instruction_no_text",
                    pg_latest_group_display_by_furnace.get(furnace_name, instruction_no_text),
                )
            status_text = ini_get(self._ini, "SECTION_2", f"staus{index}", "待機")
            temperature_text = ini_get(self._ini, "SECTION_2", f"temperature{index}", "-")
            start_time_text = ini_get(self._ini, "SECTION_2", f"start_time{index}", "-")
            end_time_text = ini_get(self._ini, "SECTION_2", f"end_time{index}", "-")
            if furnace_name.startswith("PG-") and shiji_status_override.get("start_time_text"):
                start_time_text = shiji_status_override["start_time_text"]
            if furnace_name.startswith("PG-") and oracle_pg_status:
                instruction_no_text = str(oracle_pg_status.get("instruction_no_text", instruction_no_text) or instruction_no_text)
                start_time_text = str(oracle_pg_status.get("start_time_text", start_time_text) or start_time_text)
                status_text = str(oracle_pg_status.get("status_text", status_text) or status_text)
                status_kind = str(oracle_pg_status.get("status_kind", _resolve_furnace_status_kind(status_text)) or _resolve_furnace_status_kind(status_text))
            elif furnace_name.startswith("PG-"):
                status_text, status_kind = _resolve_furnace_status_by_time(
                    status_text,
                    start_time_text,
                    end_time_text,
                )
            if furnace_name.startswith("SQ-") and shiji_status_override:
                status_text = shiji_status_override.get("status_text", status_text)
                status_kind = shiji_status_override.get("status_kind", _resolve_furnace_status_kind(status_text))
                end_time_text = shiji_status_override.get("end_time_text", end_time_text)
            elif not furnace_name.startswith("PG-"):
                status_text, status_kind = _resolve_furnace_status_by_time(
                    status_text,
                    start_time_text,
                    end_time_text,
                )
            countdown_seconds = _resolve_countdown_seconds(end_time_text) if furnace_name.startswith("SQ-") else None
            countdown_text = ""
            if countdown_seconds is not None and status_kind != "overdue" and shiji_status_override.get("salt_up_done") != "true":
                countdown_text = _format_countdown_text(countdown_seconds)
            loaded_furnace_status_rows.append(
                FurnaceStatusRow(
                    furnace_name=furnace_name,
                    status_text=status_text,
                    status_kind=status_kind,
                    instruction_no_text=instruction_no_text,
                    temperature_text=temperature_text,
                    start_time_text=start_time_text,
                    end_time_text=end_time_text,
                    countdown_text=countdown_text,
                )
            )
            logger.debug(
                "FURNACE_STATUS_LOADED index=%s furnace=%s status=%s status_kind=%s temperature=%s start_time=%s end_time=%s",
                index,
                furnace_name,
                status_text,
                status_kind,
                temperature_text,
                start_time_text,
                end_time_text,
            )

        self._pg_furnace_status_rows = loaded_furnace_status_rows[:5]
        self._sq_furnace_status_rows = loaded_furnace_status_rows[5:]

    def _refresh_furnace_status_panels(self, emit_log: bool = True) -> None:
        self._replace_furnace_status_panel(
            self._pg_status_panel_container_layout,
            self._create_furnace_status_panel("", ("炉", "作業指示書No", "開始時間"), self._pg_furnace_status_rows, "pg"),
        )
        self._replace_furnace_status_panel(
            self._sq_status_panel_container_layout,
            self._create_furnace_status_panel("", self._get_sq_header_texts(), self._sq_furnace_status_rows, "sq"),
        )
        if emit_log:
            logger.debug(
                "FURNACE_STATUS_REFRESHED pg_rows=%s sq_rows=%s",
                len(self._pg_furnace_status_rows),
                len(self._sq_furnace_status_rows),
            )

    def _refresh_status_summary(self, emit_log: bool = True) -> None:
        overdue_furnace_names = [f"⚠ {row.furnace_name}" for row in [*self._pg_furnace_status_rows, *self._sq_furnace_status_rows] if row.status_kind == "overdue"]
        self.label_overdue_furnaces.setText("\n".join(overdue_furnace_names) if overdue_furnace_names else "-")
        if emit_log:
            logger.debug(
                "FURNACE_SUMMARY_REFRESHED overdue=%s",
                "/".join(overdue_furnace_names) if overdue_furnace_names else "-",
            )

    def _update_current_time_labels(self) -> None:
        if self.label_current_time.isVisible():
            self.label_current_time.setText(datetime.now().strftime("%H:%M"))
        self._load_furnace_status_rows_from_ini()
        self._refresh_furnace_status_panels(emit_log=False)
        self._refresh_status_summary(emit_log=False)

    # ----------------------------
    # Settings / 設定読み込み
    # ----------------------------
    def _load_settings_from_ini(self) -> None:
        # 起動時設定はここでまとめて読み込み、各サブ機能が個別に INI を触らないようにする。
        # [SECTION_3] cameras
        self._cam_urls[0] = ini_get(self._ini, "SECTION_3", "CAM_1", "0")
        self._cam_urls[1] = ini_get(self._ini, "SECTION_3", "CAM_2", "0")
        self._cam_urls[2] = ini_get(self._ini, "SECTION_3", "CAM_3", "0")

        # [setting]
        self._factory_name = ini_get(self._ini, "setting", "FACTORY", "")
        self._ro_name = ini_get(self._ini, "setting", "Ro", "")
        self._ro_no = ini_get(self._ini, "setting", "RoNo", "")
        csv_folder_text = ini_get(self._ini, "setting", "CSV_FOLDER", ".")
        csv_file_text = ini_get(self._ini, "setting", "CSV_FILE", "")
        self._csv_folder, self._csv_file = _resolve_csv_source(csv_folder_text, csv_file_text)
        self._access_file_path = Path(ini_get(self._ini, "setting", "ACCESS_FILE", ""))
        self._pdf_folder = Path(ini_get(self._ini, "setting", "PDF_FOLDER", "."))
        self._face_folder = Path(ini_get(self._ini, "setting", "FACE_FOLDER", "."))
        # 旧設定ファイル互換のため、FACTORY / RO が無ければ PDF パスから補完する。
        if not self._factory_name or not self._ro_name:
            resolved_factory_name, resolved_ro_name = _resolve_factory_selection_from_pdf_folder(self._pdf_folder)
            if not self._factory_name:
                self._factory_name = resolved_factory_name
            if not self._ro_name:
                self._ro_name = resolved_ro_name

        # [SECTION_2]
        self._face_id1 = ini_get(self._ini, "SECTION_2", "FACE_ID1", "0")
        self._face_id2 = ini_get(self._ini, "SECTION_2", "FACE_ID2", "0")
        self._face_id3 = ini_get(self._ini, "SECTION_2", "FACE_ID3", "0")
        self._load_furnace_status_rows_from_ini()
        logger.info(
            "UI_CONFIG_LOADED ini=%s factory=%s ro=%s rono=%s csv_folder=%s csv_file=%s pdf_folder=%s face_folder=%s face_id1=%s face_id2=%s face_id3=%s",
            self._app_config.ini_path,
            self._factory_name or "-",
            self._ro_name or "-",
            self._ro_no or "-",
            self._csv_folder,
            self._csv_file or "-",
            self._pdf_folder,
            self._face_folder,
            self._face_id1,
            self._face_id2,
            self._face_id3,
        )

    def _ensure_camera_definitions_loaded(self) -> bool:
        # カメラ設定は必要になるまで読まず、起動時の失敗箇所を増やさないようにする。
        """Load camera definition JSON once and show a dialog on failure."""
        if self._camera_definitions:
            return True

        camera_data_path = get_camera_data_path(self._app_config.app_dir)

        try:
            self._camera_definitions = _load_camera_definitions(camera_data_path)
            if not self._camera_definitions:
                raise ValueError("camera_data.json does not contain any categories")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load camera definitions: %s", exc)
            QMessageBox.critical(
                self,
                "カメラ設定エラー",
                f"camera_data.json を読み込めませんでした。\n{camera_data_path}\n\n{exc}",
            )
            return False
        return True

    def _find_camera_selection_by_url(self, camera_url: str) -> tuple[str, str]:
        # URL から逆引きしておくと、設定ダイアログを開いたとき現在値を自然に再表示できる。
        """Resolve the current URL to category and equipment for dialog defaults."""
        if not camera_url or camera_url == "0":
            return self._get_default_camera_selection()

        for category in self._camera_definitions:
            for equipment_name, equipment_url in self._camera_definitions.get(category, {}).items():
                if equipment_url == camera_url:
                    return category, equipment_name
        return self._get_default_camera_selection()

    def _get_default_camera_selection(self) -> tuple[str, str]:
        for category in self._camera_definitions:
            equipment_map = self._camera_definitions.get(category, {})
            if equipment_map:
                first_equipment_name = next(iter(equipment_map))
                return category, first_equipment_name
        return "", ""

    def _sync_camera_selection_states(self) -> None:
        # ダイアログ初期値は常に現在の RTSP URL 群から再生成し、設定保存漏れを避ける。
        self._camera_selection_states = [
            self._find_camera_selection_by_url(camera_url) for camera_url in self._cam_urls
        ]

    def _ensure_ro_definitions_loaded(self) -> bool:
        # 工場・炉の選択肢は設定ダイアログでしか使わないため、こちらも遅延読込にする。
        """Load RO definition JSON once and show a dialog on failure."""
        if self._ro_definitions:
            return True

        ro_data_path = get_ro_data_path(self._app_config.app_dir)
        try:
            self._ro_definitions = _load_ro_definitions(ro_data_path)
            if not self._ro_definitions:
                raise ValueError("ro_data.json does not contain any RO values")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load RO definitions: %s", exc)
            QMessageBox.critical(
                self,
                "設定エラー",
                f"ro_data.json を読み込めませんでした。\n{ro_data_path}\n\n{exc}",
            )
            return False
        return True

    def _restart_csv_watcher(self) -> None:
        # CSV 監視先が設定変更で変わるため、watchdog は作り直して状態を単純に保つ。
        if self._csv_watcher is not None:
            self._csv_watcher.stop()
            self._csv_watcher = None
        self._start_csv_watcher()

    # ----------------------------
    # CSV watcher / CSV監視
    # ----------------------------
    def _start_csv_watcher(self) -> None:
        # watchdog と 30 秒周期監視を併用し、共有フォルダ特有の取りこぼしを減らす。
        if not self._csv_file:
            logger.warning("CSV_FILE is empty; watcher not started")
            return

        def on_detected() -> None:
            # watchdogスレッドから呼ばれるため、UIスレッドで実行する
            # Called from watchdog thread; marshal to UI thread
            # watchdog スレッドから直接 UI を触らず、Qt イベントループへ載せ替える。
            QTimer.singleShot(0, self._on_csv_detected)

        watch_config = CsvWatchConfig(folder=self._csv_folder, filename=self._csv_file, debounce_seconds=5.0)
        try:
            self._csv_watcher = CsvWatcher(watch_config, on_detected)
            self._csv_watcher.start()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to start CSV watcher: folder=%s file=%s", self._csv_folder, self._csv_file)
            self._csv_watcher = None
            QMessageBox.warning(
                self,
                "CSV監視エラー",
                f"CSV監視を開始できませんでした。\n{self._csv_folder / self._csv_file}\n\n{exc}",
            )

    def _on_csv_detected(self) -> None:
        self._trigger_csv_import()

    def _periodic_csv_check(self) -> None:
        # 定期確認 / Periodic check
        self._trigger_csv_import()

    def _load_scheduled_update_hour(self) -> Optional[int]:
        update_time_path_text = ini_get(self._ini, MANIFEST_SECTION, UPDATE_TIME_PATH_KEY, "").strip()
        if not update_time_path_text:
            return None

        update_time_path = Path(update_time_path_text)
        try:
            payload = json.loads(update_time_path.read_text(encoding="utf-8-sig"))
        except Exception as exc:  # noqa: BLE001
            logger.warning("SCHEDULED_UPDATE_TIME_LOAD_FAILED path=%s error=%s", update_time_path, exc)
            return None
        if not isinstance(payload, dict):
            logger.warning("SCHEDULED_UPDATE_TIME_INVALID path=%s reason=not_object", update_time_path)
            return None

        try:
            update_hour = int(payload.get("time"))
        except (TypeError, ValueError):
            logger.warning("SCHEDULED_UPDATE_TIME_INVALID path=%s time=%s", update_time_path, payload.get("time"))
            return None

        if not 1 <= update_hour <= 24:
            logger.warning("SCHEDULED_UPDATE_TIME_OUT_OF_RANGE path=%s time=%s", update_time_path, update_hour)
            return None

        return 0 if update_hour == 24 else update_hour

    def _check_scheduled_update(self) -> None:
        scheduled_update_hour = self._load_scheduled_update_hour()
        if scheduled_update_hour is None:
            return

        now = datetime.now()
        if now.hour != scheduled_update_hour:
            return

        checked_key = now.strftime("%Y-%m-%d-%H")
        if self._scheduled_update_checked_key == checked_key:
            return
        self._scheduled_update_checked_key = checked_key

        logger.info("SCHEDULED_UPDATE_CHECK_STARTED hour=%s", scheduled_update_hour)
        update_result = check_for_update(self._app_config.app_dir, self._app_config.ini_path)
        if update_result is None:
            logger.info("SCHEDULED_UPDATE_NOT_AVAILABLE hour=%s", scheduled_update_hour)
            return

        if not update_result.package_path.exists():
            logger.warning("SCHEDULED_UPDATE_PACKAGE_NOT_FOUND path=%s", update_result.package_path)
            return

        logger.info(
            "SCHEDULED_UPDATE_APPLY local=%s latest=%s package=%s",
            update_result.local_version,
            update_result.latest_version,
            update_result.package_path,
        )
        launch_updater(self._app_config.app_dir, update_result, is_frozen=getattr(sys, "frozen", False))
        self.close()
        QApplication.quit()

    def _get_ini_last_modified_at(self) -> float:
        try:
            return self._app_config.ini_path.stat().st_mtime
        except OSError:
            return 0.0

    def _check_ini_updates(self) -> None:
        current_ini_last_modified_at = self._get_ini_last_modified_at()
        if current_ini_last_modified_at <= self._ini_last_modified_at:
            return
        self._ini_last_modified_at = current_ini_last_modified_at
        self._reload_ini_and_refresh_ui()

    def _reload_ini_and_refresh_ui(self) -> None:
        previous_csv_folder = self._csv_folder
        previous_csv_file = self._csv_file
        try:
            self._ini = load_ini(self._app_config.ini_path)
            self._load_settings_from_ini()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to reload INI after external update: %s", exc)
            return

        if self._csv_folder != previous_csv_folder or self._csv_file != previous_csv_file:
            self._restart_csv_watcher()
        self.visi_textbox_ws_timecount()
        logger.info("INI_EXTERNAL_UPDATE_APPLIED path=%s", self._app_config.ini_path)

    def _resolve_current_pg_furnace_name(self) -> str:
        for furnace_source_text in (self._ro_no, self._ro_name, self._csv_file):
            normalized_furnace_name = _normalize_pg_furnace_name(furnace_source_text)
            if normalized_furnace_name:
                return normalized_furnace_name
        return ""

    def _record_pg_shiji_no(self, shiji_no: str) -> None:
        normalized_shiji_no = (shiji_no or "").strip()
        if not normalized_shiji_no or normalized_shiji_no == "0":
            return

        furnace_name = self._resolve_current_pg_furnace_name()
        if not furnace_name:
            logger.info("SHIJI_SAVE_SKIPPED reason=no_pg_furnace shiji_no=%s", normalized_shiji_no)
            return

        saved_data = handle_shiji_scan(furnace_name, normalized_shiji_no)
        logger.info(
            "SHIJI_SCAN_RESULT furnace=%s shiji_no=%s result=%s group_id=%s path=%s",
            furnace_name,
            normalized_shiji_no,
            saved_data.get("result", "-"),
            saved_data.get("group_id", "-"),
            self._shiji_json_path,
        )
        if saved_data.get("result") == "needs_confirm":
            self._shiji_scan_result_ready.emit(saved_data)

    def _handle_shiji_scan_result(self, scan_result: dict[str, Any]) -> None:
        if not isinstance(scan_result, dict):
            return
        if scan_result.get("result") != "needs_confirm":
            return

        message_box = QMessageBox(self)
        message_box.setWindowTitle("作業指示書No確認")
        message_box.setIcon(QMessageBox.Question)
        message_box.setText(str(scan_result.get("message", "確認が必要です。")))
        buttons_by_action: dict[QPushButton, str] = {}
        for action in scan_result.get("choices", []):
            if str(action) == "cancel":
                continue
            action_text = get_confirm_action_label(str(action))
            button = message_box.addButton(action_text, QMessageBox.ActionRole)
            buttons_by_action[button] = str(action)
        cancel_button = message_box.addButton(QMessageBox.Cancel)
        message_box.exec_()

        clicked_button = message_box.clickedButton()
        selected_action = buttons_by_action.get(clicked_button, "cancel")
        if clicked_button == cancel_button:
            selected_action = "cancel"

        resolved_result = resolve_shiji_confirm(str(scan_result.get("confirm_id", "")), selected_action)
        logger.info(
            "SHIJI_CONFIRM_RESOLVED confirm_id=%s action=%s result=%s furnace=%s shiji_no=%s",
            scan_result.get("confirm_id", "-"),
            selected_action,
            resolved_result.get("result", "-"),
            resolved_result.get("furnace", "-"),
            resolved_result.get("shiji_no", "-"),
        )
        self._load_furnace_status_rows_from_ini()
        self._refresh_furnace_status_panels(emit_log=False)

    # ----------------------------
    # Core logic / 中核処理
    # ----------------------------
    def read_csv(self) -> None:
        """
        VB版 Read_CSV() 相当：
        - CSVをcp932で読み取り
        - 最後の行の値で ini [SECTION_2] を更新
        - CSVを削除（1回読んだら消す）
        Equivalent to VB Read_CSV().
        """
        if not self._csv_file:
            return

        # 監視対象は「設定フォルダ + 設定ファイル名」から毎回組み立て、設定変更にも追随させる。
        csv_path = (self._csv_folder / self._csv_file)
        if not csv_path.exists():
            return

        logger.info("CSV detected: %s", csv_path)
        time.sleep(1.0)  # VB版の Thread.Sleep 相当（安定化目的）/ emulate VB sleep for stability

        last_row: Optional[list[str]] = None
        try:
            with csv_path.open("r", encoding="cp932", newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    last_row = row

            if not last_row:
                logger.warning("CSV is empty: %s", csv_path)
                return

            # INI更新 / Update INI
            # VB mapping: [0]=PDF_FILENAME, [1]=SIJINO, [5]=HIN_NAME, [11]=NISUGATA, [4]=LOT, [15]=IN_TIME
            pdf_filename_text = last_row[0] if len(last_row) > 0 else "0"
            shiji_no_text = last_row[1] if len(last_row) > 1 else "0"
            hin_name_text = last_row[5] if len(last_row) > 5 else "0"
            nisugata_text = last_row[11] if len(last_row) > 11 else "0"
            lot_text = last_row[4] if len(last_row) > 4 else "0"
            in_time_text = last_row[15] if len(last_row) > 15 else "0"
            set_value(self._ini, "SECTION_2", "PDF_FILENAME", pdf_filename_text)
            set_value(self._ini, "SECTION_2", "SIJINO", shiji_no_text)
            set_value(self._ini, "SECTION_2", "HIN_NAME", hin_name_text)
            set_value(self._ini, "SECTION_2", "NISUGATA", nisugata_text)
            set_value(self._ini, "SECTION_2", "LOT", lot_text)
            set_value(self._ini, "SECTION_2", "IN_TIME", in_time_text)

            save_ini(self._app_config.ini_path, self._ini)
            logger.info("INI updated from CSV: %s", self._app_config.ini_path)
            self._record_pg_shiji_no(shiji_no_text)

            # Keep CSV file after reading.
            logger.info("CSV read complete; kept file: %s", csv_path)

        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to read CSV: %s (%s)", csv_path, exc)

    def visi_textbox_ws_timecount(self) -> None:
        """
        VB版 Visi_textbox_WS_timecount() 相当：
        - ini [SECTION_2] から表示情報を読み込み
        - PDF表示更新
        - カウントダウン開始判定
        Equivalent to VB Visi_textbox_WS_timecount().
        """
        # reload ini from disk to reflect external edits / 外部編集も拾う
        # 他処理で INI が更新された可能性を前提に、都度ディスクから読み直す。
        try:
            self._ini = load_ini(self._app_config.ini_path)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to reload INI: %s", exc)

        self._in_time = ini_get(self._ini, "SECTION_2", "IN_TIME", "0")
        self._sijino = ini_get(self._ini, "SECTION_2", "SIJINO", "0")
        self._hin_name = ini_get(self._ini, "SECTION_2", "HIN_NAME", "0")
        self._nisugata = ini_get(self._ini, "SECTION_2", "NISUGATA", "0")
        self._lot = ini_get(self._ini, "SECTION_2", "LOT", "0")
        self._pdf_filename = ini_get(self._ini, "SECTION_2", "PDF_FILENAME", "0")
        self._face_id1 = ini_get(self._ini, "SECTION_2", "FACE_ID1", "0")
        self._face_id2 = ini_get(self._ini, "SECTION_2", "FACE_ID2", "0")
        self._face_id3 = ini_get(self._ini, "SECTION_2", "FACE_ID3", "0")

        self.label_sijino.setText("" if self._sijino == "0" else self._sijino)
        self.label_hin.setText("" if self._hin_name == "0" else self._hin_name)
        self.label_nisugata.setText("" if self._nisugata == "0" else self._nisugata)
        self.label_lot.setText("" if self._lot == "0" else self._lot)
        self._info_summary_label.setText(
            f"指示書No：{self.label_sijino.text()} ｜ 品名：{self.label_hin.text()} ｜ 荷姿：{self.label_nisugata.text()} ｜ Lot値：{self.label_lot.text()}"
        )

        # PDF表示 / PDF render
        # PDF は CSV 取込結果に紐づいて変わるため、毎回候補探索からやり直す。
        pdf_path = self._find_pdf_path()
        if pdf_path is None:
            self.pdf_label.setText("PDFが見つかりません / PDF not found")
            self._set_pdf_pixmap(None)
            logger.warning(
                "PDF_RENDER_MISSING pdf_folder=%s rono=%s pdf_filename=%s",
                self._pdf_folder,
                self._ro_no or "-",
                self._pdf_filename or "-",
            )
        else:
            pix = _render_pdf_first_page(pdf_path)
            if pix is None:
                self.pdf_label.setText("PDF表示失敗 / Failed to render PDF")
                self._set_pdf_pixmap(None)
                logger.error("PDF_RENDER_ERROR path=%s", pdf_path)
            else:
                self._set_pdf_pixmap(pix)
                self.pdf_label.setText("")
                logger.debug("PDF_RENDER_SUCCESS path=%s", pdf_path)

        # 顔写真 / Face photos
        # 作業者番号も同じ SECTION_2 から復元し、PDF 更新と同じタイミングで反映する。
        self.show_face_photos()

        self._refresh_furnace_status_panels()
        self._refresh_status_summary()
        logger.debug(
            "UI_REFRESH_APPLIED in_time=%s pdf_filename=%s sijino=%s hin_name=%s lot=%s face_id1=%s face_id2=%s face_id3=%s",
            self._in_time or "-",
            self._pdf_filename or "-",
            self._sijino or "-",
            self._hin_name or "-",
            self._lot or "-",
            self._face_id1 or "-",
            self._face_id2 or "-",
            self._face_id3 or "-",
        )

        # カウントダウン / Countdown
        self._maybe_start_countdown()

    def _find_pdf_path(self) -> Optional[Path]:
        # 最後の `0.pdf` は資料未整備時の共通代替表示として使う。
        """
        PDF表示優先順位：
          1) PDF_FOLDER/RoNo/PDF_FILENAME.pdf
          2) PDF_FOLDER/PDF_FILENAME.pdf
          3) PDF_FOLDER/0.pdf
        Priority-based PDF lookup (same as VB).
        """
        if not self._pdf_folder:
            logger.warning("PDF_SEARCH_SKIPPED pdf_folder_empty=True")
            return None

        candidates: list[Path] = []
        if self._ro_no and self._pdf_filename and self._pdf_filename != "0":
            candidates.append(self._pdf_folder / self._ro_no / f"{self._pdf_filename}.pdf")
        if self._pdf_filename and self._pdf_filename != "0":
            candidates.append(self._pdf_folder / f"{self._pdf_filename}.pdf")
        candidates.append(self._pdf_folder / "0.pdf")
        logger.debug(
            "PDF_SEARCH_STARTED pdf_folder=%s rono=%s pdf_filename=%s candidates=%s",
            self._pdf_folder,
            self._ro_no or "-",
            self._pdf_filename or "-",
            " | ".join(str(candidate) for candidate in candidates),
        )

        for c in candidates:
            if c.exists():
                logger.debug("PDF_SEARCH_HIT path=%s", c)
                return c
        logger.warning(
            "PDF_SEARCH_MISS pdf_folder=%s rono=%s pdf_filename=%s",
            self._pdf_folder,
            self._ro_no or "-",
            self._pdf_filename or "-",
        )
        return None

    # ----------------------------
    # PDF view scaling / PDF全体表示（フィット）
    # ----------------------------
    def _set_pdf_pixmap(self, pixmap: Optional[QPixmap]) -> None:
        # PDF 再読込を避けるため、元画像を保持してズーム時は再スケーリングだけで済ませる。
        """
        PDFの元Pixmapを保持し、表示領域に収まるよう縮小して表示します。
        Keep original pixmap and scale it to fit the view (show whole page).
        """
        self._pdf_pixmap_original = pixmap
        self._update_pdf_view()

    def _update_pdf_view(self) -> None:
        """
        Update the visible PDF pixmap using the current zoom factor.
        """
        if self._pdf_pixmap_original is None:
            self.pdf_label.setPixmap(QPixmap())
            self.pdf_label.resize(self.pdf_label.sizeHint())
            self._sync_pdf_zoom_input()
            return

        scaled_width = max(1, int(self._pdf_pixmap_original.width() * self._pdf_zoom_factor))
        scaled_height = max(1, int(self._pdf_pixmap_original.height() * self._pdf_zoom_factor))
        scaled = self._pdf_pixmap_original.scaled(
            scaled_width,
            scaled_height,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.pdf_label.setPixmap(scaled)
        self.pdf_label.resize(scaled.size())
        self._sync_pdf_zoom_input()

    def _set_pdf_zoom_factor(self, zoom_factor: float) -> None:
        self._pdf_zoom_factor = max(_PDF_ZOOM_MIN_FACTOR, min(_PDF_ZOOM_MAX_FACTOR, zoom_factor))
        self._update_pdf_view()
        self.update_camera_views()

    def _sync_pdf_zoom_input(self) -> None:
        self.input_pdf_zoom.setText(f"{int(round(self._pdf_zoom_factor * 100))}%")

    def _apply_pdf_zoom_input(self) -> None:
        zoom_text = self.input_pdf_zoom.text().strip().replace("%", "")
        try:
            zoom_percent = int(zoom_text)
        except ValueError:
            self._sync_pdf_zoom_input()
            return

        self._set_pdf_zoom_factor(zoom_percent / 100.0)

    def _zoom_in_pdf(self) -> None:
        self._set_pdf_zoom_factor(self._pdf_zoom_factor + _PDF_ZOOM_STEP)

    def _zoom_out_pdf(self) -> None:
        self._set_pdf_zoom_factor(self._pdf_zoom_factor - _PDF_ZOOM_STEP)

    def _reset_pdf_zoom(self) -> None:
        self._set_pdf_zoom_factor(1.0)

    def _update_stop_popup_position(self) -> None:
        self.stop_popup.adjustSize()
        self.stop_popup.move(16, 16)
        self.stop_popup.raise_()

    def _find_sq_countdown_targets(self) -> list[tuple[str, int]]:
        now = datetime.now()
        countdown_targets: list[tuple[str, int]] = []
        for furnace_status_row in self._sq_furnace_status_rows:
            if not furnace_status_row.countdown_text:
                continue
            end_time = _parse_today_time(furnace_status_row.end_time_text)
            if end_time is None:
                continue
            countdown_seconds = int((end_time - now).total_seconds())
            logger.debug(
                "SQ_COUNTDOWN_CHECK furnace=%s end_time=%s seconds_until_end=%s",
                furnace_status_row.furnace_name,
                furnace_status_row.end_time_text,
                countdown_seconds,
            )
            if countdown_seconds <= 0:
                continue
            countdown_targets.append((f"{furnace_status_row.furnace_name} ソルト上げ", countdown_seconds))
            continue
            if nearest_target is None or countdown_seconds < nearest_target[1]:
                nearest_target = (f"{furnace_status_row.furnace_name} ソルト上げ", countdown_seconds)
        countdown_targets.sort(key=lambda countdown_target: countdown_target[1])
        return countdown_targets

    def _update_sq_countdown_labels(self, countdown_targets: list[tuple[str, int]]) -> None:
        self.label_stop.setText("\n".join(countdown_title for countdown_title, _ in countdown_targets))
        self.label_countdown.setText(
            "\n".join(f"{max(0, countdown_seconds) // 60}:{max(0, countdown_seconds) % 60:02d}" for _, countdown_seconds in countdown_targets)
        )

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_stop_popup_position()
        # 画面サイズ変更時にPDFをフィットし直す / Re-fit PDF on resize
        self._update_pdf_view()
        self._refresh_left_panel_fonts()
        self._refresh_right_panel_fonts()

    # ----------------------------
    # Face photos / 顔写真
    # ----------------------------
    def show_face_photos(self) -> None:
        # 設計書に合わせ、常に 2 枠を表示したうえで未設定側だけプレースホルダを出す。
        """
        VB版 Vis_face() 相当。
        Equivalent to VB Vis_face().
        """
        self.face_main_title.show()
        self.face_sub_title.show()
        self.face_main.show()
        self.face_sub.show()

        if _is_numeric(self._face_id1):
            self._set_face_image(self.face_main, self._face_id1)
        else:
            self.face_main.setPixmap(QPixmap())
            self.face_main.setText("未設定 / N/A")
            logger.warning("FACE_IMAGE_SKIPPED slot=1 face_id=%s reason=non_numeric", self._face_id1)

        if _is_numeric(self._face_id2):
            self._set_face_image(self.face_sub, self._face_id2)
        else:
            self.face_sub.setPixmap(QPixmap())
            self.face_sub.setText("未設定 / N/A")
            logger.warning("FACE_IMAGE_SKIPPED slot=2 face_id=%s reason=non_numeric", self._face_id2)

        if _is_numeric(self._face_id3) and self._face_id3 != "0":
            self._operator_third_card.show()
            self.face_third_title.show()
            self.face_third.show()
            self._set_face_image(self.face_third, self._face_id3)
        else:
            self._operator_third_card.hide()
            self.face_third_title.hide()
            self.face_third.hide()
            self.face_third.setPixmap(QPixmap())
            self.face_third.setText("")

    def _set_face_image(self, label: QLabel, face_id: str) -> None:
        # 顔写真が無い場合も社員番号の紐付け不備だと分かるよう、ファイル名付きで表示する。
        path = _resolve_face_image_path(self._face_folder, face_id)
        if path.exists():
            label.setPixmap(QPixmap(str(path)))
            label.setText("")
            logger.debug("FACE_IMAGE_LOADED face_id=%s path=%s", face_id, path)
        else:
            label.setPixmap(QPixmap())
            label.setText(f"画像なし / Missing\n{path.name}")
            logger.warning("FACE_IMAGE_MISSING face_id=%s path=%s", face_id, path)

    def _validate_operator_id_input(self, raw_value: str, title: str, allow_empty: bool) -> Optional[str]:
        # 数字形式だけでなく画像ファイルの存在まで確認し、登録後の空表示を防ぐ。
        value = _normalize_operator_id(raw_value)
        if not value:
            return "" if allow_empty else None
        if not _is_numeric(value):
            QMessageBox.warning(self, "入力エラー", f"{title}は数字のみ入力してください。")
            return None

        image_path = _resolve_face_image_path(self._face_folder, value)
        if not image_path.exists():
            QMessageBox.warning(
                self,
                "顔写真未登録",
                f"{title}の顔写真が見つかりません。\n{image_path}",
            )
            return None

        return value

    def _on_single_operator_change_clicked(self, ini_key: str, input_title: str) -> None:
        current_value = ini_get(self._ini, "SECTION_2", ini_key, "0")
        initial_text = "" if current_value == "0" else current_value
        operator_id, ok = QInputDialog.getText(self, input_title, f"{input_title}を入力してください（数字のみ）", text=initial_text)
        if not ok:
            return

        validated_operator_id = self._validate_operator_id_input(operator_id, input_title, allow_empty=True)
        if validated_operator_id is None:
            return

        set_value(self._ini, "SECTION_2", ini_key, validated_operator_id if validated_operator_id else "0")
        save_ini(self._app_config.ini_path, self._ini)
        self.visi_textbox_ws_timecount()

    def _on_camera_setting_clicked(self) -> None:
        # ダイアログで選んだカテゴリ/設備を RTSP URL に変換し、保存済み接続をまとめて差し替える。
        if not self._ensure_camera_definitions_loaded():
            return

        self._sync_camera_selection_states()
        dialog = CameraSettingDialog(
            self._camera_definitions,
            list(self._camera_definitions.keys()),
            self._camera_selection_states,
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        selected_settings = dialog.get_selected_settings()
        next_camera_urls: list[str] = []
        for category_name, equipment_name in selected_settings:
            camera_url = self._camera_definitions.get(category_name, {}).get(equipment_name, "")
            if not camera_url:
                QMessageBox.warning(
                    self,
                    "カメラ設定エラー",
                    f"設備に対応する RTSP URL が見つかりませんでした。\n{category_name} / {equipment_name}",
                )
                return
            next_camera_urls.append(camera_url)

        self._camera_selection_states = selected_settings
        self._restart_camera_streams(next_camera_urls)

    def _on_operator_setting_clicked(self) -> None:
        """
        「担当設定」ボタン：
          メイン/補助の担当者CDを入力し、INIへ保存します。
        Operator setting button: input operator IDs and save to INI.
        """
        main_id, ok1 = QInputDialog.getText(self, "メイン担当者登録", "担当者コードを入力してください（数字のみ入力）")
        if not ok1:
            return
        sub_id, ok2 = QInputDialog.getText(self, "補助作業者登録", "補助作業者はいますか？担当者コードを入力してください（数字のみ入力）")
        if not ok2:
            return
        third_id, ok3 = QInputDialog.getText(
            self,
            "3人目作業者登録",
            "3人目作業者はいますか？担当者コードを入力してください。（数字のみ）",
        )
        if not ok3:
            return

        validated_main_id = self._validate_operator_id_input(main_id, "メイン担当者コード", allow_empty=True)
        if validated_main_id is None:
            return

        validated_sub_id = self._validate_operator_id_input(sub_id, "補助作業者コード", allow_empty=True)
        if validated_sub_id is None:
            return

        validated_third_id = self._validate_operator_id_input(third_id, "3人目作業者コード", allow_empty=True)
        if validated_third_id is None:
            return

        set_value(self._ini, "SECTION_2", "FACE_ID1", validated_main_id if validated_main_id else "0")
        set_value(self._ini, "SECTION_2", "FACE_ID2", validated_sub_id if validated_sub_id else "0")
        if validated_third_id or self._ini.has_option("SECTION_2", "FACE_ID3"):
            set_value(self._ini, "SECTION_2", "FACE_ID3", validated_third_id if validated_third_id else "0")
        save_ini(self._app_config.ini_path, self._ini)
        logger.info(
            "Operator IDs updated: FACE_ID1=%s FACE_ID2=%s FACE_ID3=%s",
            validated_main_id or "0",
            validated_sub_id or "0",
            validated_third_id or "0",
        )

        self.visi_textbox_ws_timecount()

    def _on_app_setting_clicked(self) -> None:
        # PIT 固定運用のため、変更対象は監視フォルダ系の設定だけに絞る。
        dialog = AppSettingDialog(
            str(self._csv_folder),
            str(self._pdf_folder),
            str(self._face_folder),
            self,
        )
        if dialog.exec_() != QDialog.Accepted:
            return

        csv_folder_text, pdf_folder_text, face_folder_text = dialog.get_selected_settings()
        set_value(self._ini, "setting", "CSV_FOLDER", csv_folder_text)
        set_value(self._ini, "setting", "PDF_FOLDER", pdf_folder_text)
        set_value(self._ini, "setting", "FACE_FOLDER", face_folder_text)
        save_ini(self._app_config.ini_path, self._ini)

        self._csv_folder, self._csv_file = _resolve_csv_source(csv_folder_text, self._csv_file)
        self._pdf_folder = Path(pdf_folder_text)
        self._face_folder = Path(face_folder_text)

        self._restart_csv_watcher()
        self.visi_textbox_ws_timecount()
        self._trigger_csv_import()

    # ----------------------------
    # Countdown / カウントダウン
    # ----------------------------
    def _maybe_start_countdown(self) -> None:
        # `IN_TIME` は CSV から渡る装入時刻で、現在時刻との差を STOP 表示として見せる。
        """
        IN_TIME から目標時刻を作り、1分超ならカウントダウン表示開始。
        Build target datetime from IN_TIME; start countdown if > 1 minute.
        """
        sq_countdown_targets = self._find_sq_countdown_targets()
        if sq_countdown_targets:
            self._countdown_mode = "sq"
            self._update_sq_countdown_labels(sq_countdown_targets)
            self._countdown_seconds = sq_countdown_targets[0][1]
            self._timer_countdown.start()
            logger.info("SQ_COUNTDOWN_STARTED count=%s titles=%s", len(sq_countdown_targets), " | ".join(countdown_title for countdown_title, _ in sq_countdown_targets))
            return

        if not self._in_time or self._in_time == "0":
            self._stop_countdown()
            return

        try:
            # VB版は yyyyMMddHHmmss のうち 分まで使用（秒は0固定）
            # VB uses yyyyMMddHHmmss but constructs DateTime with seconds=0
            # 旧 VB 互換で秒は切り捨て扱いにしており、文字列仕様が変わるとここが影響点になる。
            s = self._in_time
            year = int(s[0:4])
            month = int(s[4:6])
            day = int(s[6:8])
            hour = int(s[8:10])
            minute = int(s[10:12])
            target = datetime(year, month, day, hour, minute, 0)
            diff = (target - datetime.now()).total_seconds()
            if diff > 60:
                self._countdown_mode = "in_time"
                self.label_stop.setText("装入STOP")
                self._countdown_seconds = int(diff)
                self._timer_countdown.start()
                self._update_countdown_label()
            else:
                self._stop_countdown()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to parse IN_TIME=%s (%s)", self._in_time, exc)
            self._stop_countdown()

    def _stop_countdown(self) -> None:
        self._timer_countdown.stop()
        self._countdown_mode = ""
        self._countdown_seconds = 0
        self.stop_popup.hide()
        self.label_stop.hide()
        self.label_stop.setText("装入STOP")
        self.label_countdown.hide()
        self.label_countdown.setText("")

    def _update_countdown_label(self) -> None:
        minutes = max(0, self._countdown_seconds) // 60
        seconds = max(0, self._countdown_seconds) % 60
        self.label_countdown.setText(f"{minutes}:{seconds:02d}")

    def countdown_tick(self) -> None:
        """
        1秒ごとのカウントダウン処理。
        1-second countdown tick.
        """
        if self._countdown_mode == "sq":
            sq_countdown_targets = self._find_sq_countdown_targets()
            if not sq_countdown_targets:
                self._stop_countdown()
                return
            self._countdown_seconds = sq_countdown_targets[0][1]
            self._update_sq_countdown_labels(sq_countdown_targets)
            self._load_furnace_status_rows_from_ini()
            self._refresh_furnace_status_panels(emit_log=False)
            self._refresh_status_summary(emit_log=False)
            return
        self._stop_countdown()

    # ----------------------------
    # Cameras / カメラ
    # ----------------------------
    def start_camera_streams(self) -> None:
        # 起動時設定の CAM_1..3 を元に、使用するカメラだけ受信ループを立ち上げる。
        """
        Read CAM_1..3 from INI and start OpenCV capture threads for non-zero URLs.
        """
        self._restart_camera_streams(self._cam_urls)

    def _restart_camera_streams(self, camera_urls: list[str]) -> None:
        # 設定変更時は既存接続を明示停止してから張り直し、多重接続や解放漏れを避ける。
        """Stop existing capture threads and start them again with new RTSP URLs."""
        if not self._stop_camera_streams():
            QMessageBox.warning(
                self,
                "カメラ設定エラー",
                "既存のカメラスレッド停止待ちでタイムアウトしました。\n少し待ってから再度お試しください。",
            )
            return
        # ここで採用した URL 一覧が以後の再表示・設定再編集の正本になる。
        self._cam_urls = camera_urls.copy()
        self._camera_stop_event.clear()

        for index in range(len(self._camera_frames)):
            with self._camera_locks[index]:
                self._camera_frames[index] = None
                self._camera_failure_counts[index] = 0

        self._camera_threads = []
        for index, url in enumerate(self._cam_urls):
            if url == "0" or not url.strip():
                self._set_camera_placeholder(index, "No Camera")
                continue
            self._set_camera_placeholder(index, "Connecting...")

            thread = threading.Thread(
                target=self._camera_capture_loop,
                args=(index, url),
                daemon=True,
            )
            thread.start()
            self._camera_threads.append(thread)
            logger.info("Camera capture thread started: CAM_%d=%s", index + 1, url)

    def _stop_camera_streams(self) -> bool:
        # 停止しきれない場合は再起動をやめ、半端な接続状態を増やさないことを優先する。
        """Signal all capture threads to stop and wait for each thread to release its own capture."""
        self._camera_stop_event.set()

        all_threads_stopped = True
        for thread in self._camera_threads:
            if thread.is_alive():
                thread.join(timeout=_CAMERA_THREAD_JOIN_TIMEOUT_SECONDS)
            if thread.is_alive():
                all_threads_stopped = False

        if not all_threads_stopped:
            logger.error("Timed out while waiting for camera threads to stop")
            return False

        self._camera_threads = []
        return True

    def _camera_capture_loop(self, index: int, url: str) -> None:
        # UI には常に最新フレームだけを共有し、読取失敗時はこのループ内で再接続を完結させる。
        # Keep only the latest frame for UI display and reconnect on any capture failure.
        consecutive_failure_count = 0
        while not self._camera_stop_event.is_set():
            capture: Optional[cv2.VideoCapture] = None
            reconnect_delay_seconds = _CAMERA_RECONNECT_DELAY_SECONDS
            try:
                # OpenCV 側のデフォルト待ち時間が長いと画面復旧が遅れるため、タイムアウトを短めにする。
                capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                self._camera_captures[index] = capture
                try:
                    capture.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, _CAMERA_IO_TIMEOUT_MILLISECONDS)
                    capture.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, _CAMERA_IO_TIMEOUT_MILLISECONDS)
                except Exception:
                    logger.debug("Camera timeout properties are not supported: CAM_%d", index + 1)
                if not capture.isOpened():
                    consecutive_failure_count += 1
                    if consecutive_failure_count >= _CAMERA_MAX_CONSECUTIVE_FAILURES:
                        self._set_camera_connection_error_state(index)
                        logger.error(
                            "Camera stopped after repeated open failures: CAM_%d=%s (failure_count=%d)",
                            index + 1,
                            url,
                            consecutive_failure_count,
                        )
                        break
                    self._set_camera_reconnect_state(index, consecutive_failure_count, "Failed to open camera")
                    logger.warning(
                        "Failed to open camera %d: %s (failure_count=%d)",
                        index + 1,
                        url,
                        consecutive_failure_count,
                    )
                    reconnect_delay_seconds = _CAMERA_OPEN_RETRY_DELAY_SECONDS
                    continue

                while not self._camera_stop_event.is_set():
                    try:
                        ok, frame = capture.read()
                    except cv2.error:
                        consecutive_failure_count += 1
                        self._set_camera_reconnect_state(index, consecutive_failure_count, "OpenCV read failed")
                        logger.exception(
                            "OpenCV read failed with cv2.error; reconnecting: CAM_%d=%s (failure_count=%d)",
                            index + 1,
                            url,
                            consecutive_failure_count,
                        )
                        break
                    except Exception:
                        consecutive_failure_count += 1
                        self._set_camera_reconnect_state(index, consecutive_failure_count, "Unexpected read failure")
                        logger.exception(
                            "Unexpected camera read failure; reconnecting: CAM_%d=%s (failure_count=%d)",
                            index + 1,
                            url,
                            consecutive_failure_count,
                        )
                        break

                    if not ok or frame is None:
                        consecutive_failure_count += 1
                        self._set_camera_reconnect_state(index, consecutive_failure_count, "Camera read failed")
                        logger.warning(
                            "Camera read failed; reconnecting: CAM_%d=%s (failure_count=%d)",
                            index + 1,
                            url,
                            consecutive_failure_count,
                        )
                        break

                    with self._camera_locks[index]:
                        self._camera_frames[index] = frame
                        self._camera_failure_counts[index] = 0
                        self._camera_status_messages[index] = "Connecting..."
                    consecutive_failure_count = 0
            finally:
                # 再接続前に毎回 release することで、RTSP ソケットの取り残しを防ぐ。
                if capture is not None:
                    try:
                        capture.release()
                    except Exception:
                        logger.exception("Failed to release camera capture: CAM_%d=%s", index + 1, url)
                if self._camera_captures[index] is capture:
                    self._camera_captures[index] = None

            if consecutive_failure_count >= _CAMERA_MAX_CONSECUTIVE_FAILURES:
                self._set_camera_connection_error_state(index)
                logger.error(
                    "Camera stopped after repeated failures: CAM_%d=%s (failure_count=%d)",
                    index + 1,
                    url,
                    consecutive_failure_count,
                )
                break

            if not self._camera_stop_event.wait(reconnect_delay_seconds):
                continue
            break

    def _set_camera_reconnect_state(self, index: int, failure_count: int, reason: str) -> None:
        # 古いフレームを残すと接続断に気づけないため、再接続中は一度プレースホルダへ戻す。
        """Clear the last frame and keep reconnect status in shared state only."""
        with self._camera_locks[index]:
            self._camera_frames[index] = None
            self._camera_failure_counts[index] = failure_count
            self._camera_status_messages[index] = "Connecting..."
        logger.info("Camera reconnect scheduled: CAM_%d reason=%s", index + 1, reason)

    def _set_camera_connection_error_state(self, index: int) -> None:
        """Stop reconnect attempts for a camera after repeated failures."""
        with self._camera_locks[index]:
            self._camera_frames[index] = None
            self._camera_status_messages[index] = _CAMERA_CONNECTION_ERROR_MESSAGE

    def _update_middle_panel_stretch(self) -> None:
        # カメラ未使用時は PDF 領域を広げ、主用途の作業標準を見やすくする。
        middle_split_layout = getattr(self, "_middle_split_layout", None)
        if not isinstance(middle_split_layout, QHBoxLayout):
            return

        no_camera_selected = all(not widget.isVisible() for widget in self.cam_widgets)
        right_panel_stretch = _RIGHT_PANEL_NO_CAMERA_STRETCH if no_camera_selected else _RIGHT_PANEL_STRETCH
        middle_split_layout.setStretch(0, _PDF_PANEL_STRETCH)
        middle_split_layout.setStretch(1, right_panel_stretch)
        self._refresh_right_panel_fonts()

    def _set_camera_widget_visibility(self, index: int, is_visible: bool) -> None:
        self.cam_widgets[index].setVisible(is_visible)
        self._update_middle_panel_stretch()

    def _set_camera_placeholder(self, index: int, message: str) -> None:
        # カメラ無効・接続中・恒久エラーで見た目を切り替え、現場で状態を判別しやすくする。
        with self._camera_locks[index]:
            self._camera_status_messages[index] = message
        widget = self.cam_widgets[index]
        widget.setPixmap(QPixmap())
        widget.setText(message)
        should_show_widget = message != "No Camera"
        self._set_camera_widget_visibility(index, should_show_widget)
        if message == _CAMERA_CONNECTION_ERROR_MESSAGE:
            widget.setStyleSheet(
                "background: black; color: #ff8080; font-size: "
                f"{_CAMERA_CONNECTION_ERROR_FONT_SIZE}px; font-weight: bold;"
            )
        else:
            widget.setStyleSheet("background: black; color: #bbb;")

    def update_camera_views(self) -> None:
        # 受信スレッドと競合しないようコピーしたフレームだけを UI スレッド側で描画する。
        for index, widget in enumerate(self.cam_widgets):
            frame = None
            status_message = "Connecting..."
            with self._camera_locks[index]:
                if self._camera_frames[index] is not None:
                    frame = self._camera_frames[index].copy()
                status_message = self._camera_status_messages[index]

            if frame is None:
                if widget.pixmap() is not None or widget.text() != status_message:
                    self._set_camera_placeholder(index, status_message)
                continue

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, _channels = frame_rgb.shape
            image = QImage(frame_rgb.data, width, height, frame_rgb.strides[0], QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(image.copy())
            scaled = pixmap.scaled(widget.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self._set_camera_widget_visibility(index, True)
            widget.setPixmap(scaled)
            widget.setText("")

    def _show_update_history_dialog(self) -> None:
        # 配布物外の共有テキストを直接読むことで、再配布なしで更新履歴だけ差し替えられる。
        try:
            update_history_text = _read_text_with_fallback_encodings(
                _UPDATE_HISTORY_PATH,
                ["utf-8-sig", "utf-8", "cp932"],
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load update history: %s", exc)
            QMessageBox.warning(
                self,
                "更新履歴表示エラー",
                f"更新履歴を読み込めませんでした。\n{_UPDATE_HISTORY_PATH}\n\n{exc}",
            )
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("更新履歴")
        dialog.resize(720, 560)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        text_edit = QPlainTextEdit(dialog)
        text_edit.setReadOnly(True)
        text_edit.setPlainText(update_history_text)
        layout.addWidget(text_edit)

        close_button = QPushButton("閉じる", dialog)
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, alignment=Qt.AlignRight)

        dialog.exec_()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        # 運用者向けの隠しショートカットとして、Shift+F1 でも更新履歴を開けるようにする。
        if event.key() == Qt.Key_F1 and bool(event.modifiers() & Qt.ShiftModifier):
            self._show_update_history_dialog()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        # watchdog とカメラスレッドを止めてから終了し、共有ファイルや RTSP 接続を残さない。
        logger.info("APP_CLOSE_EVENT_STARTED")
        try:
            self._stop_camera_streams()
            if self._csv_watcher:
                self._csv_watcher.stop()
        except Exception as exc:  # noqa: BLE001
            logger.exception("APP_CLOSE_EVENT_FAILED error=%s", exc)
        finally:
            logger.info("APP_CLOSE_EVENT_FINISHED")
            event.accept()
    _shiji_scan_result_ready = pyqtSignal(object)
    # シグナル（UIスレッドで受信）/ Signal delivered on UI thread
    _csv_import_done = pyqtSignal()
