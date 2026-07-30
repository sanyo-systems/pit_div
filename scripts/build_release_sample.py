from __future__ import annotations

"""
配布用ビルドとリリース ZIP 生成をまとめたスクリプト。

`main.spec` / `updater.spec` で exe を作り、配布に必要な設定・定義ファイルを同梱し、
更新判定側が読む `manifest.json` まで同時に更新する。
"""

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app.app_metadata import (
    APP_BASENAME,
    CAMERA_DATA_FILENAME,
    CONFIG_DIRNAME,
    DATA_DIRNAME,
    RO_DATA_FILENAME,
    SETTING_FILENAME,
    UPDATER_BASENAME,
    VERSION_FILENAME,
    get_version_file_path,
)


def read_version_name(app_dir: Path) -> str:
    # リリース名と更新判定の双方で同じバージョン値を使うため、version.json を単一の正本にする。
    version_path = get_version_file_path(app_dir)
    payload = json.loads(version_path.read_text(encoding="utf-8"))
    version_name = str(payload.get("version", "")).strip()
    if not version_name:
        raise ValueError(f"Version is missing in {version_path}")
    return version_name


def run_pyinstaller(app_dir: Path, spec_name: str) -> None:
    # 本体と updater を別々に固め、自己更新時に updater だけ独立して動けるようにする。
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--noconfirm", spec_name],
        cwd=str(app_dir),
        check=True,
    )


def copy_release_files(app_dir: Path, release_dir: Path) -> None:
    # exe だけでなく各種定義ファイルも同梱し、初回配布先で最低限起動できる状態を作る。
    dist_dir = app_dir / "dist"
    release_dir.mkdir(parents=True, exist_ok=True)

    for relative_path in (
        Path(f"{APP_BASENAME}.exe"),
        Path(f"{UPDATER_BASENAME}.exe"),
        Path(CONFIG_DIRNAME) / SETTING_FILENAME,
        Path(DATA_DIRNAME) / CAMERA_DATA_FILENAME,
        Path(DATA_DIRNAME) / RO_DATA_FILENAME,
        Path(CONFIG_DIRNAME) / VERSION_FILENAME,
    ):
        source_path = dist_dir / relative_path.name if relative_path.suffix.lower() == ".exe" else app_dir / relative_path
        if not source_path.exists():
            raise FileNotFoundError(f"Required release file not found: {source_path}")
        target_path = release_dir / relative_path
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)


def write_manifest_file(manifest_dir: Path, version_name: str) -> Path:
    # 更新確認は manifest を見るだけで済むよう、ZIP 名や強制更新フラグもここへまとめる。
    manifest_payload = {
        "latest_version": version_name,
        "package_type": "zip",
        "package_path": f"packages/{APP_BASENAME}_{version_name}.zip",
        "force_update": False,
        "message": "",
    }
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def create_release_zip(release_dir: Path, zip_dir: Path, version_name: str) -> Path:
    # updater はこの ZIP を展開して差し替えるため、リリースフォルダの構造をそのまま保存する。
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / f"{APP_BASENAME}_{version_name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for source_path in release_dir.rglob("*"):
            if source_path.is_file():
                zip_file.write(source_path, source_path.relative_to(release_dir))
    return zip_path


def main() -> int:
    # 手作業を減らすため、ビルドから manifest 更新まで一括で完了させる。
    app_dir = APP_DIR
    version_name = read_version_name(app_dir)

    run_pyinstaller(app_dir, "packaging/main.spec")
    run_pyinstaller(app_dir, "packaging/updater.spec")

    releases_root_dir = app_dir / "releases"
    release_dir = releases_root_dir / version_name
    if release_dir.exists():
        shutil.rmtree(release_dir)

    copy_release_files(app_dir, release_dir)
    manifest_path = write_manifest_file(releases_root_dir, version_name)
    package_dir = releases_root_dir / "packages"
    zip_path = create_release_zip(release_dir, package_dir, version_name)

    print(f"Release folder: {release_dir}")
    print(f"Release zip: {zip_path}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
