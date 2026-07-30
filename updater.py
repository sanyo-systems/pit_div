from __future__ import annotations

"""
更新パッケージ適用専用の別プロセス。

本体プロセス終了を待って ZIP を展開し、実行ファイル群を置き換えてから再起動する。
更新元ファイルを上書き中に自分自身が掴まれないよう、本体とは分離している。
"""

import argparse
import ctypes
import json
import logging
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Sequence

from app.app_metadata import (
    CAMERA_DATA_FILENAME,
    CONFIG_DIRNAME,
    DATA_DIRNAME,
    RO_DATA_FILENAME,
    SETTING_FILENAME,
    VERSION_FILENAME,
    write_version_file,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

_PRESERVED_RELATIVE_PATHS = {
    f"{CONFIG_DIRNAME}/{SETTING_FILENAME}".lower(),
    SETTING_FILENAME.lower(),
    ".env",
    f"{DATA_DIRNAME}/shiji.json".lower(),
    f"{DATA_DIRNAME}/pg_access_match_batches.json".lower(),
    f"{DATA_DIRNAME}/recorder_log.txt".lower(),
    "app.lock",
    "app.log",
}
_MANAGED_UPDATE_RELATIVE_PATHS = {
    f"{DATA_DIRNAME}/{CAMERA_DATA_FILENAME}".lower(),
    f"{DATA_DIRNAME}/{RO_DATA_FILENAME}".lower(),
    f"{CONFIG_DIRNAME}/{VERSION_FILENAME}".lower(),
}


def _write_local_version(app_dir: Path, version_text: str) -> None:
    # 差し替え成功後の状態だけを `version.json` へ反映し、途中失敗時に不整合を残さない。
    write_version_file(app_dir, version_text)


def _wait_for_process_exit(pid: int, timeout_seconds: int = 120) -> bool:
    # Windows 配布版を前提にプロセス終了を待ち、更新対象ファイルのロックが外れるのを待機する。
    if pid <= 0:
        return True

    if sys.platform.startswith("win"):
        synchronize = 0x00100000
        process_handle = ctypes.windll.kernel32.OpenProcess(synchronize, False, pid)
        if process_handle:
            try:
                wait_result = ctypes.windll.kernel32.WaitForSingleObject(process_handle, timeout_seconds * 1000)
                return wait_result == 0
            finally:
                ctypes.windll.kernel32.CloseHandle(process_handle)

    end_time = time.time() + timeout_seconds
    while time.time() < end_time:
        try:
            import os

            os.kill(pid, 0)
        except OSError:
            return True
        time.sleep(1.0)
    return False


def _resolve_extracted_root(extract_dir: Path) -> Path:
    # ZIP のルートが 1 階層余分に包まれていても、そのまま配置できるように吸収する。
    children = list(extract_dir.iterdir())
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return extract_dir


def _copy_package_contents(source_dir: Path, target_dir: Path) -> None:
    # 現場固有の設定・ログは保持しつつ、配布管理下の JSON や exe は更新で置き換える。
    for source_path in source_dir.rglob("*"):
        relative_path = source_path.relative_to(source_dir)
        relative_key = relative_path.as_posix().lower()
        target_path = target_dir / relative_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
            continue
        if target_path.exists() and relative_key in _PRESERVED_RELATIVE_PATHS:
            logger.info("Preserved existing file: %s", target_path)
            continue
        if target_path.exists() and relative_key in _MANAGED_UPDATE_RELATIVE_PATHS:
            logger.info("Overwriting managed update file: %s", target_path)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def _restart_application(restart_command: Sequence[str], app_dir: Path) -> None:
    # updater は再起動後の待機をせず、起動を委譲したら役目を終える。
    creation_flags = 0
    if sys.platform.startswith("win"):
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    subprocess.Popen(list(restart_command), cwd=str(app_dir), close_fds=True, creationflags=creation_flags)


def run_update(app_dir: Path, package_path: Path, target_version: str, wait_pid: int, restart_command: Sequence[str]) -> int:
    # 更新処理の順序をこの関数へ集約し、エラーコードで失敗地点を切り分けやすくしている。
    if not package_path.exists():
        logger.error("Update package not found: %s", package_path)
        return 2

    if not _wait_for_process_exit(wait_pid):
        logger.error("Timed out waiting for process exit: pid=%s", wait_pid)
        return 3

    temp_root_dir = Path(tempfile.mkdtemp(prefix="divwork_package_"))
    extract_dir = temp_root_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(package_path, "r") as zip_file:
            zip_file.extractall(extract_dir)

        package_root_dir = _resolve_extracted_root(extract_dir)
        # テンポラリ展開から最終配置へコピーする形にし、部分更新状態の時間を短くする。
        _copy_package_contents(package_root_dir, app_dir)
        _write_local_version(app_dir, target_version)
        _restart_application(restart_command, app_dir)
        logger.info("Update applied successfully: %s", target_version)
        return 0
    finally:
        shutil.rmtree(temp_root_dir, ignore_errors=True)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DivWorkStandard updater")
    parser.add_argument("--app-dir", required=True)
    parser.add_argument("--package-path", required=True)
    parser.add_argument("--target-version", required=True)
    parser.add_argument("--wait-pid", required=True, type=int)
    parser.add_argument("--restart-cmd-json", required=True)
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    restart_command = json.loads(args.restart_cmd_json)
    return run_update(
        app_dir=Path(args.app_dir),
        package_path=Path(args.package_path),
        target_version=args.target_version,
        wait_pid=args.wait_pid,
        restart_command=restart_command,
    )


if __name__ == "__main__":
    raise SystemExit(main())
