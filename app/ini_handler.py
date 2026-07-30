# このファイルの役割：setting.ini の読み書きを行うヘルパーを提供します。
# Purpose: Provide helper functions to read/write setting.ini.

from __future__ import annotations

"""
`setting.ini` の読込・保存を担当するヘルパー群。

このアプリでは UI 状態と業務データの一部を INI に保持しており、
旧システムとの互換性のため文字コードゆれも吸収する。
"""

import configparser
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _try_read_text(path: Path, encodings: list[str]) -> tuple[str, str]:
    # 配布先ごとに UTF-16 / UTF-8 / cp932 が混在するため、読めるまで順番に試す。
    """
    INIファイルを複数の文字コードで読み込みます。
    Read INI text trying multiple encodings.
    """
    last_exc: Optional[Exception] = None
    for enc in encodings:
        try:
            return path.read_text(encoding=enc), enc
        except Exception as exc:  # noqa: BLE001 - keep going with fallback encodings
            last_exc = exc
    raise last_exc or RuntimeError("Failed to read INI file")


def load_ini(path: Path) -> configparser.ConfigParser:
    # INI の文字コードは固定せず、旧環境から引き継いだファイルもそのまま読めるようにする。
    """
    setting.ini を読み込み ConfigParser を返します。
    Load setting.ini and return ConfigParser.

    注意 / Note:
      現場の ini は UTF-8 / ANSI(cp932) 混在の可能性があるため、複数候補で読み込みます。
      We try multiple encodings because the INI may be UTF-8 or ANSI (cp932).
    """
    config = configparser.ConfigParser()
    if not path.exists():
        raise FileNotFoundError(f"INI not found: {path}")

    # UTF-16LE (BOM: FF FE) の ini が存在するため、utf-16 を最優先で試します。
    # Some deployments use UTF-16LE INI (BOM: FF FE), so try utf-16 first.
    # UTF-16LE の既存配布があるため、BOM を含む形式を優先して読む。
    text, used = _try_read_text(path, ["utf-16", "utf-8-sig", "utf-8", "cp932"])
    config.read_string(text)
    logger.info("INI loaded: %s (encoding=%s)", path, used)
    return config


def save_ini(path: Path, config: configparser.ConfigParser, encoding: Optional[str] = None) -> None:
    # 他ツールや手動編集との差分を減らすため、既存ファイルの文字コードをできるだけ維持する。
    """
    ConfigParser を setting.ini に書き戻します。
    Save ConfigParser back to setting.ini.

    互換性 / Compatibility:
      VB版はWinAPI経由で読み書きしていましたが、Python版は configparser で上書きします。
      VB used WinAPI; Python overwrites using configparser.
    """
    # 既存ファイルの文字コードをなるべく維持します（UTF-16 BOMならUTF-16で保存）。
    # Preserve existing encoding when possible (if UTF-16 BOM, save as UTF-16).
    if encoding is None:
        try:
            with path.open("rb") as fb:
                bom = fb.read(2)
            if bom in (b"\xff\xfe", b"\xfe\xff"):
                encoding = "utf-16"
            else:
                encoding = "utf-8"
        except Exception:  # noqa: BLE001
            encoding = "utf-8"

    with path.open("w", encoding=encoding, newline="\n") as f:
        config.write(f)
    logger.info("INI saved: %s (encoding=%s)", path, encoding)


def get(config: configparser.ConfigParser, section: str, key: str, default: str = "0") -> str:
    # 呼び出し側で毎回存在確認を書かずに済むよう、欠落時は既定値へ寄せる。
    """
    INIから文字列を取得します（未設定なら default）。
    Get string value from INI (default if missing).
    """
    try:
        return config.get(section, key, fallback=default).strip()
    except Exception:  # noqa: BLE001
        return default


def set_value(config: configparser.ConfigParser, section: str, key: str, value: str) -> None:
    # セクション未作成でも使えるようにし、CSV 取込時の更新処理を単純化する。
    """
    INIへ値を設定します（セクションが無ければ作成）。
    Set value in INI (create section if missing).
    """
    if not config.has_section(section):
        config.add_section(section)
    config.set(section, key, str(value))
