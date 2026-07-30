from __future__ import annotations

"""
アプリ全体で共有する名前とパス解決ヘルパー。

GitHub 共有しやすいように、設定・定義ファイルを `config/` と `data/` へ分離している。
各モジュールが個別に相対パスを組み立てると移動時の修正漏れが出やすいため、
ファイル配置ルールはこのモジュールへ集約する。
"""

import json
from pathlib import Path

APP_BASENAME = "main"
UPDATER_BASENAME = "updater"

CONFIG_DIRNAME = "config"
DATA_DIRNAME = "data"

SETTING_FILENAME = "setting.ini"
VERSION_FILENAME = "version.json"
CAMERA_DATA_FILENAME = "camera_data.json"
RO_DATA_FILENAME = "ro_data.json"

MANIFEST_SECTION = "UPDATE"
MANIFEST_PATH_KEY = "manifest_path"
UPDATE_TIME_PATH_KEY = "update_time_path"


def get_config_dir(app_dir: Path) -> Path:
    return app_dir / CONFIG_DIRNAME


def get_data_dir(app_dir: Path) -> Path:
    return app_dir / DATA_DIRNAME


def get_setting_path(app_dir: Path) -> Path:
    app_setting_path = app_dir / SETTING_FILENAME
    if app_setting_path.exists():
        return app_setting_path
    parent_setting_path = app_dir.parent / SETTING_FILENAME
    if parent_setting_path.exists():
        return parent_setting_path
    return app_setting_path


def get_version_file_path(app_dir: Path) -> Path:
    return get_config_dir(app_dir) / VERSION_FILENAME


def get_camera_data_path(app_dir: Path) -> Path:
    return get_data_dir(app_dir) / CAMERA_DATA_FILENAME


def get_ro_data_path(app_dir: Path) -> Path:
    return get_data_dir(app_dir) / RO_DATA_FILENAME


def get_shiji_data_path(app_dir: Path) -> Path:
    app_shiji_data_path = app_dir / DATA_DIRNAME / "shiji.json"
    if app_shiji_data_path.exists():
        return app_shiji_data_path
    return app_dir.parent / DATA_DIRNAME / "shiji.json"


def get_local_manifest_path(app_dir: Path) -> Path:
    return get_config_dir(app_dir) / "manifest.json"


def write_version_file(app_dir: Path, version_text: str) -> None:
    # `version.json` は更新判定と配布スクリプトの双方で参照するため、書式をここで統一する。
    version_path = get_version_file_path(app_dir)
    version_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": version_text}
    version_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
