from __future__ import annotations

"""
起動前の更新確認とアップデータ起動を担当するモジュール。

業務画面を直接自己更新するとファイル置換中に実行中プロセスが衝突するため、
更新有無の判定までは本体が行い、実際の差し替えは `updater.py` に委譲する。
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from PyQt5.QtWidgets import QMessageBox, QWidget

from app.app_metadata import (
    APP_BASENAME,
    MANIFEST_PATH_KEY,
    MANIFEST_SECTION,
    UPDATER_BASENAME,
    get_local_manifest_path,
    get_version_file_path,
    write_version_file,
)
from app.ini_handler import get as ini_get
from app.ini_handler import load_ini

logger = logging.getLogger(__name__)


@dataclass
class UpdateCheckResult:
    # 更新確認時に必要な情報を 1 つのオブジェクトにまとめ、UI 表示とアップデータ起動で再利用する。
    local_version: str
    latest_version: str
    package_path: Path
    force_update: bool
    message: str
    manifest_path: Path


def read_local_version(app_dir: Path) -> str:
    version_path = get_version_file_path(app_dir)
    if not version_path.exists():
        logger.warning("version.json not found: %s", version_path)
        return "0.0.0"
    try:
        payload = json.loads(version_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to read local version: %s", exc)
        return "0.0.0"
    version = str(payload.get("version", "0.0.0")).strip()
    return version or "0.0.0"


def write_local_version(app_dir: Path, version: str) -> None:
    write_version_file(app_dir, version)


def parse_version_text(version_text: str) -> tuple[int, ...]:
    # `v1.2` のような表記ゆれでも比較できるよう、各要素から数字だけを取り出す。
    normalized_parts = []
    for raw_part in str(version_text).strip().split("."):
        raw_part = raw_part.strip()
        if not raw_part:
            normalized_parts.append(0)
            continue
        digits = "".join(ch for ch in raw_part if ch.isdigit())
        normalized_parts.append(int(digits or "0"))
    return tuple(normalized_parts or [0])


def is_newer_version(latest_version: str, local_version: str) -> bool:
    return parse_version_text(latest_version) > parse_version_text(local_version)


def load_update_manifest(manifest_path: Path) -> dict[str, Any]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("manifest.json must be an object")
    return payload


def resolve_manifest_path(app_dir: Path, ini_path: Path) -> Optional[Path]:
    # 運用環境ごとに manifest の置き場所が異なるため、INI 指定とローカル配置の両方に対応する。
    config = load_ini(ini_path)
    manifest_path_text = ini_get(config, MANIFEST_SECTION, MANIFEST_PATH_KEY, "")
    if manifest_path_text:
        return Path(manifest_path_text)

    fallback_manifest_path = app_dir.parent / "manifest.json"
    if fallback_manifest_path.exists():
        logger.info("Using fallback manifest path: %s", fallback_manifest_path)
        return fallback_manifest_path

    local_manifest_path = get_local_manifest_path(app_dir)
    if local_manifest_path.exists():
        logger.info("Using local manifest path: %s", local_manifest_path)
        return local_manifest_path

    return None


def check_for_update(app_dir: Path, ini_path: Path) -> Optional[UpdateCheckResult]:
    # ここではダウンロードは行わず、ローカルまたは共有フォルダ上にある更新資材の有無だけ判定する。
    manifest_path = resolve_manifest_path(app_dir, ini_path)
    if manifest_path is None:
        logger.info("Update manifest path is not configured and fallback manifest was not found")
        return None
    if not manifest_path.exists():
        logger.warning("Update manifest not found: %s", manifest_path)
        return None

    try:
        manifest = load_update_manifest(manifest_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load update manifest: %s", exc)
        return None

    local_version = read_local_version(app_dir)
    latest_version = str(manifest.get("latest_version", "")).strip()
    package_path_text = str(manifest.get("package_path", "")).strip()
    if not latest_version or not package_path_text:
        logger.warning("Update manifest is missing latest_version or package_path")
        return None

    if not is_newer_version(latest_version, local_version):
        logger.info("No update available: local=%s latest=%s", local_version, latest_version)
        return None

    package_path = Path(package_path_text)
    if not package_path.is_absolute():
        # 相対パス指定なら manifest 基準で解決し、manifest と package を同じ配布場所に置けるようにする。
        package_path = manifest_path.parent / package_path

    return UpdateCheckResult(
        local_version=local_version,
        latest_version=latest_version,
        package_path=package_path,
        force_update=bool(manifest.get("force_update", False)),
        message=str(manifest.get("message", "")).strip(),
        manifest_path=manifest_path,
    )


def show_update_dialog(parent: Optional[QWidget], update_result: UpdateCheckResult) -> bool:
    # 強制更新時は拒否ボタンを出さず、任意更新時のみユーザーに保留余地を残す。
    message_lines = [
        f"現在の版数: {update_result.local_version}",
        f"最新の版数: {update_result.latest_version}",
    ]
    if update_result.message:
        message_lines.extend(["", update_result.message])
    message_lines.extend(["", "更新を適用しますか？"])

    buttons = QMessageBox.Yes
    if not update_result.force_update:
        buttons |= QMessageBox.No

    response = QMessageBox.question(
        parent,
        "更新確認",
        "\n".join(message_lines),
        buttons,
        QMessageBox.Yes,
    )
    return response == QMessageBox.Yes


def _copy_updater_asset(app_dir: Path, is_frozen: bool) -> tuple[Path, list[str]]:
    # 本体更新中に updater 自身が消えないよう、一時ディレクトリへ複製してから起動する。
    temp_dir = Path(tempfile.mkdtemp(prefix="divwork_updater_"))
    if is_frozen:
        updater_source_path = app_dir / f"{UPDATER_BASENAME}.exe"
        if not updater_source_path.exists():
            raise FileNotFoundError(f"Updater executable not found: {updater_source_path}")
        updater_temp_path = temp_dir / updater_source_path.name
        shutil.copy2(updater_source_path, updater_temp_path)
        return updater_temp_path, [str(updater_temp_path)]

    updater_source_path = app_dir / f"{UPDATER_BASENAME}.py"
    if not updater_source_path.exists():
        raise FileNotFoundError(f"Updater script not found: {updater_source_path}")
    updater_temp_path = temp_dir / updater_source_path.name
    shutil.copy2(updater_source_path, updater_temp_path)
    return updater_temp_path, [sys.executable, str(updater_temp_path)]


def launch_updater(app_dir: Path, update_result: UpdateCheckResult, is_frozen: bool) -> None:
    # 更新後の再起動コマンドもここで組み立て、updater 側は「差し替えて再起動する」ことに専念させる。
    updater_temp_path, base_command = _copy_updater_asset(app_dir, is_frozen)

    if is_frozen:
        restart_command = [str(app_dir / f"{APP_BASENAME}.exe")]
    else:
        restart_command = [sys.executable, str(app_dir / f"{APP_BASENAME}.py")]

    command = base_command + [
        "--app-dir",
        str(app_dir),
        "--package-path",
        str(update_result.package_path),
        "--target-version",
        update_result.latest_version,
    ]
    command.extend(
        [
            "--wait-pid",
            str(os.getpid()),
            "--restart-cmd-json",
            json.dumps(restart_command, ensure_ascii=False),
        ]
    )

    creation_flags = 0
    if sys.platform.startswith("win"):
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    subprocess.Popen(
        command,
        cwd=str(updater_temp_path.parent),
        close_fds=True,
        creationflags=creation_flags,
    )
    logger.info("Updater launched: %s", command)
