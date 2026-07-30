# このファイルの役割：エントリーポイント。単一起動チェックを行い、MainWindow を起動します。
# Purpose: Entry point. Enforce single instance and launch MainWindow.

from __future__ import annotations

"""
アプリケーションの起動エントリポイント。

このファイルは PyQt アプリの初期化だけを担当し、業務画面そのものは `top.py` の
`MainWindow` に委譲する。起動時には以下を順に行う。
1. 実行ディレクトリとログ出力先の確定
2. 多重起動防止
3. `setting.ini` の存在確認
4. 更新マニフェスト確認と必要ならアップデータ起動
5. メインウィンドウ生成
"""

import logging
import os
import sys
import threading
from contextlib import suppress
from pathlib import Path

from PyQt5.QtWidgets import QApplication, QMessageBox

from app.app_metadata import get_setting_path
from app.app_update import check_for_update, launch_updater, show_update_dialog
from app.top import AppConfig, MainWindow


def _get_app_dir() -> Path:
    # 開発実行と PyInstaller 配布版の両方で、相対ファイル参照の基準となるディレクトリを返す。
    """
    実行中の main.py / main.exe と同じフォルダーを返します。
    Return the directory that contains the running main.py or main.exe.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _setup_logging(app_dir: Path) -> None:
    # 現場で画面だけでは追えない障害を調査できるよう、標準出力とファイルへ同時出力する。
    """
    コンソール + ファイル(app.log)へログ出力します。
    Log to console and app.log file.
    """
    log_path = app_dir / "app.log"
    recorder_log_path = app_dir / "data" / "recorder_log.txt"
    recorder_log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(log_path), encoding="utf-8"),
            logging.FileHandler(str(recorder_log_path), encoding="utf-8"),
        ],
    )
    logging.getLogger(__name__).info("Logging started: %s", log_path)
    logging.getLogger(__name__).info("Recorder logging started: %s", recorder_log_path)


def _install_exception_logging() -> None:
    logger = logging.getLogger(__name__)

    def log_unhandled_exception(exc_type, exc_value, exc_traceback) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        logger.critical("UNHANDLED_EXCEPTION", exc_info=(exc_type, exc_value, exc_traceback))

    def log_unhandled_thread_exception(args: threading.ExceptHookArgs) -> None:
        thread_name = args.thread.name if args.thread is not None else "-"
        logger.critical(
            "UNHANDLED_THREAD_EXCEPTION thread=%s",
            thread_name,
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )

    sys.excepthook = log_unhandled_exception
    threading.excepthook = log_unhandled_thread_exception


class SingleInstanceLock:
    # CSV/INI の同時更新を避けるため、起動多重化は OS のファイルロックで防止する。
    """
    ロックファイル(app.lock)で単一起動を実現します。
    Enforce single instance using a lock file (app.lock).

    注意 / Note:
      Windowsで簡易に動かすため、排他は OS のファイルロック(msvcrt)を使用します。
      Use OS file locking via msvcrt on Windows.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fh = None

    def acquire(self) -> bool:
        try:
            self._fh = open(self._lock_path, "a+", encoding="utf-8")
            if sys.platform.startswith("win"):
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except Exception:
            self.release()
            return False

    def release(self) -> None:
        if self._fh is None:
            return
        with suppress(Exception):
            if sys.platform.startswith("win"):
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        with suppress(Exception):
            self._fh.close()
        self._fh = None


def main() -> int:
    app_dir = _get_app_dir()
    _setup_logging(app_dir)
    _install_exception_logging()

    # 画面起動前に多重起動を止め、CSV/INI の同時書き換えを避ける。
    lock = SingleInstanceLock(app_dir / "app.lock")
    if not lock.acquire():
        # 既に起動中 / Already running
        app = QApplication(sys.argv)
        QMessageBox.warning(None, "起動済み", "既にアプリが起動しています。")
        return 1

    try:
        ini_path = get_setting_path(app_dir)
        if not ini_path.exists():
            app = QApplication(sys.argv)
            QMessageBox.critical(None, "設定ファイルなし", f"setting.ini が見つかりません:\n{ini_path}")
            return 2

        app = QApplication(sys.argv)
        # 更新確認は UI 起動直後に行い、業務画面を開いてから差し替える状況を避ける。
        update_result = check_for_update(app_dir, ini_path)
        if update_result is not None:
            if not update_result.package_path.exists():
                QMessageBox.warning(None, "更新確認", f"更新パッケージが見つかりません:\n{update_result.package_path}")
            else:
                should_update = show_update_dialog(None, update_result)
                if should_update:
                    launch_updater(app_dir, update_result, is_frozen=getattr(sys, "frozen", False))
                    return 0

        try:
            # 実運用で設定不備があっても原因が追えるよう、初期化例外はここで明示的に通知する。
            window = MainWindow(AppConfig(ini_path=ini_path, app_dir=app_dir))
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).exception("Failed to initialize main window: %s", exc)
            QMessageBox.critical(
                None,
                "起動エラー",
                f"設定の読み込みまたは画面初期化に失敗しました。\n{exc}",
            )
            return 3
        window.show()
        return app.exec_()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
