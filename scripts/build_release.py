from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
APP_DIR = SCRIPT_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from app.app_metadata import (  # noqa: E402
    CONFIG_DIRNAME,
    DATA_DIRNAME,
    SETTING_FILENAME,
    VERSION_FILENAME,
    get_version_file_path,
)

PACKAGE_BASENAME = "PIT_DIV"
MAIN_BASENAME = "main"
UPDATER_BASENAME = "updater"
REQUIRED_RELEASE_FILES = (
    Path(".env"),
    Path(SETTING_FILENAME),
    Path(CONFIG_DIRNAME) / VERSION_FILENAME,
    Path(DATA_DIRNAME) / "shiji.json",
    Path(DATA_DIRNAME) / "pg_access_match_batches.json",
)


def read_version_name(app_dir: Path) -> str:
    version_path = get_version_file_path(app_dir)
    payload = json.loads(version_path.read_text(encoding="utf-8"))
    version_name = str(payload.get("version", "")).strip()
    if not version_name:
        raise ValueError(f"Version is missing in {version_path}")
    return version_name


def run_pyinstaller(app_dir: Path, entry_name: str) -> None:
    entry_path = app_dir / f"{entry_name}.py"
    if not entry_path.exists():
        raise FileNotFoundError(f"Entry file not found: {entry_path}")
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--windowed",
        "--collect-all",
        "cryptography",
        "--name",
        entry_name,
        str(entry_path.name),
    ]
    subprocess.run(command, cwd=str(app_dir), check=True)


def copy_required_file(app_dir: Path, release_dir: Path, relative_path: Path) -> None:
    source_path = app_dir / relative_path
    if not source_path.exists():
        raise FileNotFoundError(f"Required release file not found: {source_path}")
    target_path = release_dir / relative_path
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, target_path)


def copy_release_files(app_dir: Path, release_dir: Path) -> None:
    release_dir.mkdir(parents=True, exist_ok=True)

    main_exe_path = app_dir / "dist" / f"{MAIN_BASENAME}.exe"
    if not main_exe_path.exists():
        raise FileNotFoundError(f"Required release file not found: {main_exe_path}")
    shutil.copy2(main_exe_path, release_dir / main_exe_path.name)

    updater_exe_path = app_dir / "dist" / f"{UPDATER_BASENAME}.exe"
    if updater_exe_path.exists():
        shutil.copy2(updater_exe_path, release_dir / updater_exe_path.name)

    for relative_path in REQUIRED_RELEASE_FILES:
        copy_required_file(app_dir, release_dir, relative_path)


def write_manifest_file(releases_root_dir: Path, version_name: str) -> Path:
    package_filename = f"{PACKAGE_BASENAME}_{version_name}.zip"
    manifest_payload = {
        "latest_version": version_name,
        "package_type": "zip",
        "package_path": f"packages/{package_filename}",
        "force_update": False,
        "message": "",
    }
    manifest_path = releases_root_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


def create_release_zip(release_dir: Path, package_dir: Path, version_name: str) -> Path:
    package_dir.mkdir(parents=True, exist_ok=True)
    zip_path = package_dir / f"{PACKAGE_BASENAME}_{version_name}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        for source_path in release_dir.rglob("*"):
            if source_path.is_file():
                zip_file.write(source_path, source_path.relative_to(release_dir))
    return zip_path


def main() -> int:
    app_dir = APP_DIR
    version_name = read_version_name(app_dir)

    run_pyinstaller(app_dir, MAIN_BASENAME)
    if (app_dir / f"{UPDATER_BASENAME}.py").exists():
        run_pyinstaller(app_dir, UPDATER_BASENAME)

    releases_root_dir = app_dir / "releases"
    release_dir = releases_root_dir / f"{PACKAGE_BASENAME}_{version_name}"
    package_dir = releases_root_dir / "packages"

    copy_release_files(app_dir, release_dir)
    manifest_path = write_manifest_file(releases_root_dir, version_name)
    zip_path = create_release_zip(release_dir, package_dir, version_name)

    print(f"Release folder: {release_dir}")
    print(f"Release zip: {zip_path}")
    print(f"Manifest: {manifest_path}")
    if not (release_dir / f"{UPDATER_BASENAME}.exe").exists():
        print("Updater exe: skipped because updater.py was not found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
