from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.shiji_store import shiji_no_text_matches

PG_ACCESS_MATCH_BATCHES_MAX_COUNT = 50
PG_ACCESS_MATCH_BATCHES_FILENAME = "pg_access_match_batches.json"
logger = logging.getLogger(__name__)
_pg_access_match_batches_path = Path("data") / PG_ACCESS_MATCH_BATCHES_FILENAME


def configure_pg_access_match_batches_path(json_path: Path) -> None:
    global _pg_access_match_batches_path
    _pg_access_match_batches_path = json_path


def _load_pg_access_match_batches() -> list[dict[str, Any]]:
    if not _pg_access_match_batches_path.exists():
        return []
    try:
        loaded_data = json.loads(_pg_access_match_batches_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pg_access_match] load failed path=%s error=%s", _pg_access_match_batches_path, exc)
        return []
    if isinstance(loaded_data, list):
        return [batch for batch in loaded_data if isinstance(batch, dict)]
    return []


def _save_pg_access_match_batches(batches: list[dict[str, Any]]) -> None:
    _pg_access_match_batches_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _pg_access_match_batches_path.with_suffix(_pg_access_match_batches_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(batches, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(_pg_access_match_batches_path)


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_batch(batch: dict[str, Any]) -> dict[str, Any] | None:
    pit_s_nippou_no = _normalize_text(batch.get("pit_s_nippou_no"))
    pg_furnace = _normalize_text(batch.get("pg_furnace") or batch.get("furnace"))
    ro_no = _normalize_text(batch.get("ro_no"))
    shiji_no_text = _normalize_text(batch.get("shiji_no_text") or batch.get("instruction_no_text"))
    if not pit_s_nippou_no or not pg_furnace or not shiji_no_text:
        return None
    return {
        "pit_s_nippou_no": pit_s_nippou_no,
        "pg_furnace": pg_furnace,
        "ro_no": ro_no,
        "shiji_no_text": shiji_no_text,
        "salt_moved": bool(batch.get("salt_moved", False)),
    }


def _batch_key(batch: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        _normalize_text(batch.get("pit_s_nippou_no")),
        _normalize_text(batch.get("pg_furnace")),
        _normalize_text(batch.get("ro_no")),
        _normalize_text(batch.get("shiji_no_text")),
    )


def _pit_s_nippou_sort_value(batch: dict[str, Any], index: int) -> tuple[int, int]:
    pit_s_nippou_no = _normalize_text(batch.get("pit_s_nippou_no"))
    if pit_s_nippou_no.isdigit():
        return (int(pit_s_nippou_no), index)
    return (index, index)


def _trim_pg_access_match_batches(batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(batches) <= PG_ACCESS_MATCH_BATCHES_MAX_COUNT:
        return batches
    indexed_batches = list(enumerate(batches))
    kept_indexes = {
        index
        for index, _batch in sorted(
            indexed_batches,
            key=lambda item: _pit_s_nippou_sort_value(item[1], item[0]),
        )[-PG_ACCESS_MATCH_BATCHES_MAX_COUNT:]
    }
    return [batch for index, batch in indexed_batches if index in kept_indexes]


def update_pg_access_match_batches(oracle_batches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    batches = []
    batch_indexes: dict[tuple[str, str, str, str], int] = {}
    for loaded_batch in _load_pg_access_match_batches():
        normalized_batch = _normalize_batch(loaded_batch)
        if normalized_batch is None:
            continue
        batch_indexes[_batch_key(normalized_batch)] = len(batches)
        batches.append(normalized_batch)

    for oracle_batch in oracle_batches:
        normalized_batch = _normalize_batch(oracle_batch)
        if normalized_batch is None:
            continue
        batch_key = _batch_key(normalized_batch)
        existing_index = batch_indexes.get(batch_key)
        if existing_index is None:
            batch_indexes[batch_key] = len(batches)
            batches.append(normalized_batch)
            continue
        normalized_batch["salt_moved"] = bool(batches[existing_index].get("salt_moved", False))
        batches[existing_index] = normalized_batch

    batches = _trim_pg_access_match_batches(batches)
    _save_pg_access_match_batches(batches)
    return batches


def load_pending_pg_access_match_batches_by_furnace() -> dict[str, list[dict[str, Any]]]:
    batches_by_furnace: dict[str, list[dict[str, Any]]] = {}
    pending_batches: list[dict[str, Any]] = []
    for loaded_batch in _load_pg_access_match_batches():
        normalized_batch = _normalize_batch(loaded_batch)
        if normalized_batch is None or normalized_batch.get("salt_moved") is True:
            continue
        pending_batches.append(normalized_batch)
    for normalized_batch in sorted(
        enumerate(pending_batches),
        key=lambda item: _pit_s_nippou_sort_value(item[1], item[0]),
        reverse=True,
    ):
        _index, batch = normalized_batch
        batches_by_furnace.setdefault(batch["pg_furnace"], []).append(batch)
    return batches_by_furnace


def mark_pg_access_match_batch_salt_moved(
    pg_furnace: str,
    shiji_no_text: str,
    pit_s_nippou_no: str = "",
) -> bool:
    normalized_pg_furnace = _normalize_text(pg_furnace)
    normalized_shiji_no_text = _normalize_text(shiji_no_text)
    normalized_pit_s_nippou_no = _normalize_text(pit_s_nippou_no)
    if not normalized_pg_furnace or not normalized_shiji_no_text:
        return False

    changed = False
    batches: list[dict[str, Any]] = []
    for loaded_batch in _load_pg_access_match_batches():
        normalized_batch = _normalize_batch(loaded_batch)
        if normalized_batch is None:
            continue
        if (
            not changed
            and normalized_batch.get("salt_moved") is False
            and normalized_batch.get("pg_furnace") == normalized_pg_furnace
            and shiji_no_text_matches(normalized_batch.get("shiji_no_text", ""), normalized_shiji_no_text)
            and (
                not normalized_pit_s_nippou_no
                or normalized_batch.get("pit_s_nippou_no") == normalized_pit_s_nippou_no
            )
        ):
            normalized_batch["salt_moved"] = True
            changed = True
        batches.append(normalized_batch)

    if changed:
        _save_pg_access_match_batches(_trim_pg_access_match_batches(batches))
    return changed
