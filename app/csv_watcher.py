# このファイルの役割：watchdog を使ってCSVの作成/更新を監視し、コールバックを呼び出します。
# Purpose: Watch a CSV file using watchdog and call a callback on create/change events.

from __future__ import annotations

"""
CSV 到着監視を `watchdog` で実装する小さなラッパー。

`top.py` からは「対象フォルダ・ファイル名・検知時コールバック」を渡すだけで使えるようにし、
監視ライブラリ依存を UI 層へ漏らさないようにしている。
"""

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger(__name__)


@dataclass
class CsvWatchConfig:
    # CSV監視フォルダ / CSV watch folder
    folder: Path
    # 監視対象ファイル名 / target filename
    filename: str
    # デバウンス秒数 / debounce seconds
    debounce_seconds: float = 5.0


class _CsvEventHandler(FileSystemEventHandler):
    """`watchdog` のイベントを業務アプリ向けに絞り込む内部ハンドラ。"""

    def __init__(self, config: CsvWatchConfig, on_detected: Callable[[], None]) -> None:
        super().__init__()
        self._config = config
        self._on_detected = on_detected
        self._last_processed_at = 0.0

    def _matches(self, path_str: str) -> bool:
        try:
            p = Path(path_str)
        except Exception:  # noqa: BLE001
            return False
        return p.name.lower() == self._config.filename.lower()

    def _debounced_fire(self) -> None:
        # CSV 保存時は create/modify が連続発火しやすいため、最後の 1 回だけ扱う。
        now = time.time()
        if now - self._last_processed_at <= self._config.debounce_seconds:
            return
        self._last_processed_at = now
        self._on_detected()

    # Created / 作成
    def on_created(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        if self._matches(event.src_path):
            logger.info("CSV detected (created): %s", event.src_path)
            self._debounced_fire()

    # Changed / 更新
    def on_modified(self, event) -> None:  # type: ignore[override]
        if event.is_directory:
            return
        if self._matches(event.src_path):
            logger.info("CSV detected (modified): %s", event.src_path)
            self._debounced_fire()


class CsvWatcher:
    # `watchdog` の詳細を隠し、上位層からは「開始/停止」だけ見えるようにする。
    """
    VBの FileSystemWatcher 相当。
    Equivalent to VB FileSystemWatcher.
    """

    def __init__(self, config: CsvWatchConfig, on_detected: Callable[[], None]) -> None:
        self._config = config
        self._on_detected = on_detected
        self._observer: Optional[Observer] = None

    def start(self) -> None:
        # 設定変更直後でも監視開始できるよう、フォルダが無ければ先に作る。
        self._config.folder.mkdir(parents=True, exist_ok=True)
        handler = _CsvEventHandler(self._config, self._on_detected)
        observer = Observer()
        observer.schedule(handler, str(self._config.folder), recursive=False)
        observer.daemon = True
        observer.start()
        self._observer = observer
        logger.info("CSV watcher started: folder=%s file=%s", self._config.folder, self._config.filename)

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2.0)
        self._observer = None
        logger.info("CSV watcher stopped")

