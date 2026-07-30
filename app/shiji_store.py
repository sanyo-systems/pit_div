from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

_DEFAULT_FILENAME = "shiji.json"
_SHIJI_VERSION = 1
HISTORY_MAX_COUNT = 100
_LOADING_GROUP_STATUSES = {"waiting", "processing", "salt_processing", "cancelled"}
ACCESS_FURNACE_TO_PG = {
    "1": "PG-1",
    "5": "PG-2",
    "2": "PG-3",
    "8": "PG-4",
    "9": "PG-5",
}
PG_TO_ACCESS_FURNACE = {
    "PG-1": "1",
    "PG-2": "5",
    "PG-3": "2",
    "PG-4": "8",
    "PG-5": "9",
}
PG_TO_SQ_FURNACE = {
    "PG-1": "SQ-1",
    "PG-2": "SQ-3",
    "PG-3": "",
    "PG-4": "SQ-2",
    "PG-5": "SQ-2",
}
ACCESS_FURNACE_TO_SQ = {
    access_furnace_no: salt_furnace
    for access_furnace_no, pg_furnace in ACCESS_FURNACE_TO_PG.items()
    for salt_furnace in (PG_TO_SQ_FURNACE.get(pg_furnace, ""),)
    if salt_furnace
}
_DISPLAY_GROUP_STATUS_PRIORITY = {
    "processing": 0,
    "waiting": 1,
    "salt_processing": 2,
    "cancelled": 3,
}
_PENDING_CONFIRM_ACTION_LABELS = {
    "barashi_read": "ばらし読み込み",
    "add_as_new_loading": "新規装入として追加",
    "cancel": "キャンセル",
}
logger = logging.getLogger(__name__)
_shiji_json_path = Path(_DEFAULT_FILENAME)


def configure_shiji_json_path(json_path: Path) -> None:
    global _shiji_json_path
    _shiji_json_path = json_path


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _build_default_data() -> dict[str, Any]:
    return {
        "version": _SHIJI_VERSION,
        "updated_at": "",
        "last_furnace": "",
        "last_group_id": "",
        "last_confirm_seq": 0,
        "furnaces": {},
        "history": [],
        "pending_confirms": {},
        "processed_access_records": [],
    }


def _build_default_group(group_no: int, group_id: str, now_text: str) -> dict[str, Any]:
    return {
        "group_no": group_no,
        "group_id": group_id,
        "furnace": group_id.rsplit("-", 1)[0],
        "created_at": now_text,
        "last_acquired_at": now_text,
        "status": "waiting",
        "salt_furnace": None,
        "salt_up_time": None,
        "access_id": None,
        "access_furnace_no": None,
        "access_shiji_no_text": None,
        "access_recorded_at": None,
        "pg_started_at": None,
        "pg_completed_at": None,
        "salt_up_at": None,
        "salt_up_done": False,
        "barashi_in_progress": False,
        "barashi_done": False,
        "barashi_started_at": None,
        "barashi_completed_at": None,
        "barashi_done_at": None,
        "items": [],
    }


def _normalize_item(item: Any, group_id: str, item_index: int) -> dict[str, Any]:
    normalized_item = dict(item) if isinstance(item, dict) else {}
    normalized_item.setdefault("item_id", f"{group_id}-{item_index:03d}")
    normalized_item["shiji_no"] = str(normalized_item.get("shiji_no", "")).strip()
    normalized_item.setdefault("acquired_at", "")
    normalized_item.setdefault("barashi_checked", False)
    normalized_item.setdefault("barashi_read_at", None)
    normalized_item.setdefault("note", None)
    return normalized_item


def _normalize_group(group: Any, furnace: str, group_index: int) -> dict[str, Any]:
    normalized_group = dict(group) if isinstance(group, dict) else {}
    group_no = int(normalized_group.get("group_no", group_index) or group_index)
    group_id = str(normalized_group.get("group_id", f"{furnace}-{group_no}"))
    normalized_group["group_no"] = group_no
    normalized_group["group_id"] = group_id
    normalized_group["furnace"] = furnace
    normalized_group.setdefault("created_at", "")
    normalized_group.setdefault("last_acquired_at", normalized_group.get("created_at", ""))
    normalized_group["status"] = str(normalized_group.get("status", "waiting") or "waiting")
    if normalized_group["status"] not in _LOADING_GROUP_STATUSES:
        normalized_group["status"] = "waiting"
    normalized_group.setdefault("salt_furnace", None)
    normalized_group.setdefault("salt_up_time", None)
    normalized_group.setdefault("access_id", None)
    normalized_group.setdefault("access_furnace_no", None)
    normalized_group.setdefault("access_shiji_no_text", None)
    normalized_group.setdefault("access_recorded_at", None)
    normalized_group.setdefault("pg_started_at", None)
    normalized_group.setdefault("pg_completed_at", None)
    normalized_group.setdefault("salt_up_at", None)
    normalized_group.setdefault("salt_up_done", False)
    normalized_group.setdefault("barashi_in_progress", False)
    normalized_group.setdefault("barashi_done", False)
    normalized_group.setdefault("barashi_started_at", None)
    normalized_group.setdefault("barashi_completed_at", None)
    normalized_group.setdefault("barashi_done_at", normalized_group.get("barashi_completed_at"))
    items = normalized_group.get("items", [])
    if not isinstance(items, list):
        items = []
    normalized_group["items"] = [
        _normalize_item(item, group_id, item_index)
        for item_index, item in enumerate(items, start=1)
    ]
    _sync_group_state_fields(normalized_group)
    return normalized_group


def _sync_group_state_fields(group: dict[str, Any]) -> None:
    status_text = str(group.get("status", "waiting") or "waiting")
    if status_text not in _LOADING_GROUP_STATUSES:
        status_text = "waiting"
    group["status"] = status_text

    items = group.get("items", [])
    checked_item_count = 0
    total_item_count = 0
    if isinstance(items, list):
        total_item_count = len(items)
        checked_item_count = sum(
            1
            for item in items
            if isinstance(item, dict) and bool(item.get("barashi_checked", False))
        )

    salt_up_done = bool(group.get("salt_up_done", False))
    if group.get("salt_up_at"):
        salt_up_done = True
    group["salt_up_done"] = salt_up_done

    barashi_done = bool(group.get("barashi_done", False))
    if total_item_count > 0 and checked_item_count >= total_item_count:
        barashi_done = True
    group["barashi_done"] = barashi_done

    group["barashi_in_progress"] = bool(not barashi_done and checked_item_count > 0)
    if group["barashi_in_progress"] and not group.get("barashi_started_at"):
        group["barashi_started_at"] = _now_text()
    if not group["barashi_in_progress"] and not barashi_done:
        group["barashi_started_at"] = None

    if barashi_done:
        if not group.get("barashi_done_at"):
            group["barashi_done_at"] = _now_text()
        if not group.get("barashi_completed_at"):
            group["barashi_completed_at"] = group["barashi_done_at"]
    else:
        group["barashi_done_at"] = None
        group["barashi_completed_at"] = None


def _normalize_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized_data = _build_default_data()
    normalized_data.update(data)
    furnaces = normalized_data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        furnaces = {}
    normalized_furnaces: dict[str, Any] = {}
    for furnace, furnace_entry in furnaces.items():
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list):
            groups = []
        normalized_furnaces[str(furnace)] = {
            "groups": [
                _normalize_group(group, str(furnace), group_index)
                for group_index, group in enumerate(groups, start=1)
            ]
        }
    normalized_data["furnaces"] = normalized_furnaces
    history = normalized_data.get("history", [])
    normalized_data["history"] = history if isinstance(history, list) else []
    pending_confirms = normalized_data.get("pending_confirms", {})
    normalized_data["pending_confirms"] = pending_confirms if isinstance(pending_confirms, dict) else {}
    processed_access_records = normalized_data.get("processed_access_records", [])
    normalized_data["processed_access_records"] = processed_access_records if isinstance(processed_access_records, list) else []
    normalized_data["last_confirm_seq"] = int(normalized_data.get("last_confirm_seq", 0) or 0)
    normalized_data["version"] = _SHIJI_VERSION
    return normalized_data


def _load_shiji_data() -> dict[str, Any]:
    if not _shiji_json_path.exists():
        return _build_default_data()
    with _shiji_json_path.open("r", encoding="utf-8") as json_file:
        loaded_data = json.load(json_file)
    if not isinstance(loaded_data, dict):
        raise ValueError("shiji.json root must be an object")
    return _normalize_data(loaded_data)


def _remove_barashi_done_groups(data: dict[str, Any], now_text: str) -> list[dict[str, Any]]:
    removed_groups: list[dict[str, Any]] = []
    furnaces = data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        return removed_groups

    for furnace_name, furnace_entry in furnaces.items():
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list):
            continue
        kept_groups: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict):
                continue
            if not bool(group.get("barashi_done", False)):
                kept_groups.append(group)
                continue
            removed_entry = {
                "furnace": str(furnace_name),
                "group_id": str(group.get("group_id", "") or ""),
                "group_no": int(group.get("group_no", 0) or 0),
                "status": str(group.get("status", "waiting") or "waiting"),
                "salt_furnace": group.get("salt_furnace"),
                "salt_up_done": bool(group.get("salt_up_done", False)),
                "barashi_done_at": group.get("barashi_done_at"),
                "removed_at": now_text,
            }
            removed_groups.append(removed_entry)
        if len(kept_groups) != len(groups):
            furnace_entry["groups"] = kept_groups

    if removed_groups:
        removed_group_ids = {str(group.get("group_id", "")) for group in removed_groups}
        if str(data.get("last_group_id", "")) in removed_group_ids:
            data["last_group_id"] = ""
        data["updated_at"] = now_text
        for removed_group in removed_groups:
            _append_history(data, "barashi_done_group_removed", removed_group)
    return removed_groups


def _save_shiji_data(data: dict[str, Any]) -> None:
    removed_groups = _remove_barashi_done_groups(data, _now_text())
    if removed_groups:
        logger.info("[shiji] removed barashi done groups count=%s", len(removed_groups))
    logger.debug("[shiji] save start path=%s", _shiji_json_path)
    try:
        _shiji_json_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = _shiji_json_path.with_suffix(f"{_shiji_json_path.suffix}.tmp")
        with temp_path.open("w", encoding="utf-8", newline="\n") as json_file:
            json.dump(data, json_file, ensure_ascii=False, indent=2)
            json_file.write("\n")
        temp_path.replace(_shiji_json_path)
        logger.debug("[shiji] save ok path=%s", _shiji_json_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[shiji] save failed path=%s error=%s", _shiji_json_path, exc)
        raise


def _append_history(data: dict[str, Any], event: str, payload: dict[str, Any]) -> dict[str, Any]:
    history = data.setdefault("history", [])
    next_seq = int(history[-1].get("seq", 0)) + 1 if history else 1
    history_entry = {"seq": next_seq, "event": event}
    history_entry.update(payload)
    history.append(history_entry)
    if len(history) > HISTORY_MAX_COUNT:
        data["history"] = history[-HISTORY_MAX_COUNT:]
    return history_entry


def _build_access_record_key(access_id: str, access_furnace_no: str, recorded_at: str) -> str:
    if access_id:
        return access_id
    return f"{access_furnace_no}|{recorded_at}"


def _is_access_record_processed(data: dict[str, Any], access_record_key: str) -> bool:
    processed_access_records = data.get("processed_access_records", [])
    if not isinstance(processed_access_records, list):
        return False
    for processed_record in processed_access_records:
        if not isinstance(processed_record, dict):
            continue
        if (
            str(processed_record.get("access_record_key", "")).strip() == access_record_key
            and str(processed_record.get("result", "")).strip() == "ok"
        ):
            return True
    return False


def _append_processed_access_record(
    data: dict[str, Any],
    access_record_key: str,
    access_id: str,
    access_furnace_no: str,
    recorded_at: str,
    result: str,
    group_id: str,
    processed_at: str,
    furnace: str = "",
    shiji_no_text: str = "",
) -> None:
    processed_access_records = data.setdefault("processed_access_records", [])
    if not isinstance(processed_access_records, list):
        processed_access_records = []
        data["processed_access_records"] = processed_access_records
    processed_access_records.append(
        {
            "access_record_key": access_record_key,
            "access_id": access_id,
            "access_furnace_no": access_furnace_no,
            "furnace": furnace,
            "shiji_no_text": shiji_no_text,
            "recorded_at": recorded_at,
            "result": result,
            "group_id": group_id,
            "processed_at": processed_at,
        }
    )


def _get_or_create_furnace_groups(data: dict[str, Any], furnace: str) -> list[dict[str, Any]]:
    furnaces = data.setdefault("furnaces", {})
    furnace_entry = furnaces.setdefault(furnace, {"groups": []})
    groups = furnace_entry.setdefault("groups", [])
    if not isinstance(groups, list):
        raise ValueError(f"groups must be a list: {furnace}")
    return groups


def _create_group_for_furnace(data: dict[str, Any], furnace: str, now_text: str) -> dict[str, Any]:
    groups = _get_or_create_furnace_groups(data, furnace)
    next_group_no = int(groups[-1].get("group_no", 0) or 0) + 1 if groups else 1
    group_id = f"{furnace}-{next_group_no}"
    group = _build_default_group(next_group_no, group_id, now_text)
    groups.append(group)
    return group


def _has_active_processing_group(groups: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(group, dict)
        and str(group.get("status", "waiting") or "waiting") == "processing"
        and not bool(group.get("barashi_done", False))
        for group in groups
    )


def _promote_waiting_group_if_no_processing(
    data: dict[str, Any],
    furnace: str,
    groups: list[dict[str, Any]],
    now_text: str,
) -> bool:
    if furnace not in PG_TO_SQ_FURNACE or _has_active_processing_group(groups):
        return False
    waiting_groups = [
        group
        for group in groups
        if isinstance(group, dict)
        and str(group.get("status", "waiting") or "waiting") == "waiting"
        and not bool(group.get("barashi_done", False))
    ]
    if not waiting_groups:
        return False

    target_group = min(waiting_groups, key=lambda group: int(group.get("group_no", 0) or 0))
    old_status = str(target_group.get("status", "waiting") or "waiting")
    target_group["status"] = "processing"
    if not str(target_group.get("pg_started_at", "") or "").strip():
        target_group["pg_started_at"] = str(target_group.get("created_at", "") or now_text)
    _sync_group_state_fields(target_group)
    data["updated_at"] = now_text
    _append_history(
        data,
        "waiting_group_promoted_to_processing",
        {
            "furnace": furnace,
            "group_id": target_group.get("group_id", ""),
            "group_no": target_group.get("group_no", 0),
            "old_status": old_status,
            "new_status": target_group.get("status", "waiting"),
            "promoted_at": now_text,
        },
    )
    return True


def _get_loading_group(data: dict[str, Any], furnace: str, now_text: str) -> dict[str, Any]:
    groups = _get_or_create_furnace_groups(data, furnace)
    same_furnace_as_last = data.get("last_furnace") == furnace and bool(groups)
    if same_furnace_as_last:
        group = groups[-1]
    else:
        group = _create_group_for_furnace(data, furnace, now_text)
    _promote_waiting_group_if_no_processing(data, furnace, groups, now_text)
    return group


def _create_item(group: dict[str, Any], shiji_no: str, now_text: str, note: str | None = None) -> dict[str, Any]:
    items = group.setdefault("items", [])
    next_item_no = len(items) + 1
    item = {
        "item_id": f"{group['group_id']}-{next_item_no:03d}",
        "shiji_no": shiji_no,
        "acquired_at": now_text,
        "barashi_checked": False,
        "barashi_read_at": None,
        "note": note,
    }
    items.append(item)
    group["last_acquired_at"] = now_text
    _sync_group_state_fields(group)
    return item


def _build_result(
    result: str,
    furnace: str,
    shiji_no: str,
    group: dict[str, Any] | None = None,
    item: dict[str, Any] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    response = {
        "result": result,
        "furnace": furnace,
        "shiji_no": shiji_no,
    }
    if group is not None:
        response["group_id"] = group.get("group_id", "")
        response["group_no"] = group.get("group_no", 0)
        response["status"] = group.get("status", "waiting")
        response["salt_furnace"] = group.get("salt_furnace")
        response["salt_up_time"] = group.get("salt_up_time")
        response["access_recorded_at"] = group.get("access_recorded_at")
        response["pg_started_at"] = group.get("pg_started_at")
        response["salt_up_done"] = bool(group.get("salt_up_done", False))
        response["barashi_in_progress"] = bool(group.get("barashi_in_progress", False))
        response["barashi_done"] = bool(group.get("barashi_done", False))
        response["salt_up_at"] = group.get("salt_up_at")
        response["barashi_started_at"] = group.get("barashi_started_at")
        response["barashi_completed_at"] = group.get("barashi_completed_at")
        response["barashi_done_at"] = group.get("barashi_done_at")
    if item is not None:
        response["item_id"] = item.get("item_id", "")
    response.update(extra)
    return response


def _save_confirm_request(
    data: dict[str, Any],
    furnace: str,
    shiji_no: str,
    confirm_type: str,
    message: str,
    choices: list[str],
    related_group_id: str,
    related_item_id: str,
    duplicate_group_id: str = "",
) -> dict[str, Any]:
    now_text = _now_text()
    next_confirm_seq = int(data.get("last_confirm_seq", 0) or 0) + 1
    confirm_id = f"confirm-{next_confirm_seq:06d}"
    confirm_payload = {
        "confirm_id": confirm_id,
        "confirm_type": confirm_type,
        "message": message,
        "choices": choices,
        "furnace": furnace,
        "shiji_no": shiji_no,
        "group_id": related_group_id,
        "item_id": related_item_id,
        "duplicate_group_id": duplicate_group_id,
        "created_at": now_text,
    }
    pending_confirms = data.setdefault("pending_confirms", {})
    pending_confirms[confirm_id] = confirm_payload
    data["last_confirm_seq"] = next_confirm_seq
    data["updated_at"] = now_text
    _append_history(
        data,
        "needs_confirm",
        {
            "furnace": furnace,
            "shiji_no": shiji_no,
            "confirm_id": confirm_id,
            "confirm_type": confirm_type,
            "choices": choices,
            "group_id": related_group_id,
            "item_id": related_item_id,
            "read_at": now_text,
        },
    )
    _save_shiji_data(data)
    return _build_result(
        "needs_confirm",
        furnace,
        shiji_no,
        confirm_id=confirm_id,
        confirm_type=confirm_type,
        message=message,
        choices=choices,
        group_id=related_group_id,
        item_id=related_item_id,
    )


def _find_barashi_candidates(
    groups: list[dict[str, Any]],
    shiji_no: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    matched_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in groups:
        if not bool(group.get("salt_up_done", False)):
            continue
        if bool(group.get("barashi_done", False)):
            continue
        items = group.get("items", [])
        if not isinstance(items, list):
            continue
        if _group_matches_shiji_no_text(group, shiji_no):
            first_item = next((item for item in items if isinstance(item, dict)), None)
            if first_item is not None:
                matched_candidates.append((group, first_item))
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("shiji_no", "")).strip() != shiji_no:
                continue
            matched_candidates.append((group, item))
    return matched_candidates


def _find_already_barashi_checked_candidates(
    groups: list[dict[str, Any]],
    shiji_no: str,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    matched_candidates: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for group in groups:
        if not bool(group.get("salt_up_done", False)):
            continue
        items = group.get("items", [])
        if not isinstance(items, list):
            continue
        if _group_matches_shiji_no_text(group, normalized_shiji_no):
            first_item = next((item for item in items if isinstance(item, dict)), None)
            if first_item is not None:
                matched_groups.append(group)
                matched_items.append(first_item)
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("shiji_no", "")).strip() != shiji_no:
                continue
            if not bool(item.get("barashi_checked", False)):
                continue
            matched_candidates.append((group, item))
    return matched_candidates


def _find_same_shiji_in_same_furnace(groups: list[dict[str, Any]], shiji_no: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    for group in reversed(groups):
        if bool(group.get("barashi_done", False)):
            continue
        items = group.get("items", [])
        if not isinstance(items, list):
            continue
        if _group_matches_shiji_no_text(group, normalized_shiji_no):
            first_item = next((item for item in items if isinstance(item, dict)), None)
            if first_item is not None:
                matched_groups.append(group)
                matched_items.append(first_item)
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("shiji_no", "")).strip() == shiji_no:
                return group, item
    return None, None


def _build_barashi_action(group_id: str, item_id: str) -> str:
    return f"barashi_read::{group_id}::{item_id}"


def _parse_barashi_action(action: str) -> tuple[str, str] | None:
    if not action.startswith("barashi_read::"):
        return None
    action_parts = action.split("::", 2)
    if len(action_parts) != 3:
        return None
    return action_parts[1], action_parts[2]


def _normalize_shiji_no_parts(shiji_no_text: str) -> list[str]:
    normalized_text = str(shiji_no_text or "").replace("／", "/").strip()
    if not normalized_text:
        return []
    return [
        part.strip()
        for part in normalized_text.split("/")
        if part.strip()
    ]


def _get_group_shiji_no_parts(group: dict[str, Any]) -> list[str]:
    items = group.get("items", [])
    if not isinstance(items, list):
        return []
    return [
        str(item.get("shiji_no", "")).strip()
        for item in items
        if isinstance(item, dict) and str(item.get("shiji_no", "")).strip()
    ]


def _get_group_shiji_no_text(group: dict[str, Any]) -> str:
    return "/".join(_get_group_shiji_no_parts(group))


def _format_time_text(time_text: str) -> str:
    normalized_time_text = (time_text or "").strip()
    if not normalized_time_text:
        return "-"
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(normalized_time_text, date_format).strftime("%H:%M")
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized_time_text).strftime("%H:%M")
    except ValueError:
        return normalized_time_text


def _group_matches_shiji_no_text(group: dict[str, Any], shiji_no_text: str) -> bool:
    shiji_no_parts = _normalize_shiji_no_parts(shiji_no_text)
    if not shiji_no_parts:
        return True
    group_shiji_no_parts = _get_group_shiji_no_parts(group)
    return group_shiji_no_parts == shiji_no_parts or set(group_shiji_no_parts) == set(shiji_no_parts)


def shiji_no_text_matches(left_shiji_no_text: str, right_shiji_no_text: str) -> bool:
    left_shiji_no_parts = _normalize_shiji_no_parts(left_shiji_no_text)
    right_shiji_no_parts = _normalize_shiji_no_parts(right_shiji_no_text)
    if not left_shiji_no_parts or not right_shiji_no_parts:
        return False
    return left_shiji_no_parts == right_shiji_no_parts or set(left_shiji_no_parts) == set(right_shiji_no_parts)


def _select_display_group(groups: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidate_groups = [group for group in groups if isinstance(group, dict)]
    if not candidate_groups:
        return None

    processing_groups = [
        group
        for group in candidate_groups
        if str(group.get("status", "waiting") or "waiting") == "processing"
        and not bool(group.get("barashi_done", False))
    ]
    if processing_groups:
        return min(processing_groups, key=lambda group: int(group.get("group_no", 0) or 0))
    return None


def _find_group_by_id(data: dict[str, Any], group_id: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]] | tuple[None, None, None]:
    furnaces = data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        return None, None, None
    for furnace_name, furnace_entry in furnaces.items():
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("group_id", "")) == group_id:
                return str(furnace_name), groups, group
    return None, None, None


def _find_next_group(groups: list[dict[str, Any]], current_group_no: int) -> dict[str, Any] | None:
    next_groups = [
        group
        for group in groups
        if isinstance(group, dict) and int(group.get("group_no", 0) or 0) > current_group_no
    ]
    if not next_groups:
        return None
    return min(next_groups, key=lambda group: int(group.get("group_no", 0) or 0))


def _select_shiji_sent_target_group(
    groups: list[dict[str, Any]],
    shiji_no_text: str = "",
    furnace_name: str = "",
) -> dict[str, Any] | None:
    access_shiji_parts = _normalize_shiji_no_parts(shiji_no_text)
    if shiji_no_text:
        logger.debug(
            "[access_csv] shiji normalize raw=%s normalized=%s",
            shiji_no_text,
            json.dumps(access_shiji_parts, ensure_ascii=False),
        )
    for group in groups:
        if not isinstance(group, dict):
            continue
        logger.debug(
            "[shiji] candidate check furnace=%s group_id=%s group_no=%s status=%s items=%s",
            furnace_name,
            group.get("group_id", ""),
            group.get("group_no", 0),
            group.get("status", "waiting"),
            json.dumps(_get_group_shiji_no_parts(group), ensure_ascii=False),
        )
        if access_shiji_parts:
            logger.info(
                "[access_csv] compare shiji furnace=%s group_id=%s pg_shiji=%s access_shiji=%s matched=%s",
                furnace_name,
                group.get("group_id", ""),
                _get_group_shiji_no_text(group),
                shiji_no_text,
                str(_group_matches_shiji_no_text(group, shiji_no_text)).lower(),
            )
    selectable_groups = [
        group
        for group in groups
        if isinstance(group, dict)
        and not bool(group.get("salt_up_done", False))
        and not bool(group.get("barashi_done", False))
    ]
    if access_shiji_parts:
        selectable_groups = [
            group
            for group in selectable_groups
            if _group_matches_shiji_no_text(group, shiji_no_text)
        ]
    for status_text in ("processing", "waiting"):
        matched_groups = [
            group
            for group in selectable_groups
            if str(group.get("status", "waiting") or "waiting") == status_text
        ]
        if matched_groups:
            selected_group = min(matched_groups, key=lambda group: int(group.get("group_no", 0) or 0))
            match_reason = " and shiji match" if access_shiji_parts else ""
            logger.info(
                "[shiji] selected group_id=%s reason=status %s%s",
                selected_group.get("group_id", ""),
                status_text,
                match_reason,
            )
            return selected_group
    logger.debug(
        "[shiji] no target group furnace=%s access_shiji=%s",
        furnace_name,
        json.dumps(access_shiji_parts, ensure_ascii=False),
    )
    return None


def _mark_group_barashi_done(group: dict[str, Any], now_text: str) -> None:
    group["barashi_done"] = True
    group["barashi_done_at"] = now_text
    group["barashi_completed_at"] = now_text
    items = group.get("items", [])
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("barashi_checked", False)):
                item["barashi_checked"] = True
                item["barashi_read_at"] = now_text
    _sync_group_state_fields(group)


def _acquire_loading_item(data: dict[str, Any], furnace: str, shiji_no: str, event: str, note: str | None = None) -> dict[str, Any]:
    now_text = _now_text()
    group = _get_loading_group(data, furnace, now_text)
    item = _create_item(group, shiji_no, now_text, note=note)
    data["updated_at"] = now_text
    data["last_furnace"] = furnace
    data["last_group_id"] = group["group_id"]
    _append_history(
        data,
        event,
        {
            "furnace": furnace,
            "shiji_no": shiji_no,
            "item_id": item["item_id"],
            "acquired_at": now_text,
            "group_id": group["group_id"],
            "group_no": group["group_no"],
            "status": group.get("status", "waiting"),
            "salt_up_done": bool(group.get("salt_up_done", False)),
            "barashi_in_progress": bool(group.get("barashi_in_progress", False)),
            "barashi_done": bool(group.get("barashi_done", False)),
            "note": note,
        },
    )
    _save_shiji_data(data)
    return _build_result(event, furnace, shiji_no, group=group, item=item)


def handle_shiji_scan(furnace: str, shiji_no: str) -> dict:
    normalized_furnace = (furnace or "").strip()
    normalized_shiji_no = (shiji_no or "").strip()
    if not normalized_furnace:
        return {"result": "error", "message": "Furnace is empty."}
    if not normalized_shiji_no:
        return {"result": "error", "message": "Shiji number is empty."}

    data = _load_shiji_data()
    groups = _get_or_create_furnace_groups(data, normalized_furnace)

    barashi_candidates = _find_barashi_candidates(groups, normalized_shiji_no)
    barashi_candidate_group_ids = {
        str(group.get("group_id", ""))
        for group, _item in barashi_candidates
    }
    if barashi_candidates and len(barashi_candidate_group_ids) == 1:
        barashi_group, barashi_item = barashi_candidates[0]
        now_text = _now_text()
        if _group_matches_shiji_no_text(barashi_group, normalized_shiji_no):
            _mark_group_barashi_done(barashi_group, now_text)
        else:
            barashi_item["barashi_checked"] = True
            barashi_item["barashi_read_at"] = now_text
        if not barashi_group.get("barashi_started_at"):
            barashi_group["barashi_started_at"] = now_text
        _sync_group_state_fields(barashi_group)
        data["updated_at"] = now_text
        barashi_result = "barashi_done" if bool(barashi_group.get("barashi_done", False)) else "barashi_read"
        _append_history(
            data,
            barashi_result,
            {
                "furnace": normalized_furnace,
                "shiji_no": normalized_shiji_no,
                "group_id": barashi_group.get("group_id", ""),
                "group_no": barashi_group.get("group_no", 0),
                "item_id": barashi_item.get("item_id", ""),
                "status": barashi_group.get("status", "waiting"),
                "salt_up_done": bool(barashi_group.get("salt_up_done", False)),
                "barashi_done": bool(barashi_group.get("barashi_done", False)),
                "barashi_done_at": barashi_group.get("barashi_done_at"),
            },
        )
        _save_shiji_data(data)
        return _build_result(barashi_result, normalized_furnace, normalized_shiji_no, group=barashi_group, item=barashi_item)
    if len(barashi_candidate_group_ids) > 1:
        first_group, first_item = barashi_candidates[0]
        candidate_choices = [
            _build_barashi_action(str(group.get("group_id", "")), str(item.get("item_id", "")))
            for group, item in barashi_candidates
        ]
        candidate_group_ids = [str(group.get("group_id", "")) for group, _ in barashi_candidates]
        return _save_confirm_request(
            data,
            normalized_furnace,
            normalized_shiji_no,
            "multiple_barashi_candidates",
            f"Multiple barashi candidate groups were found: {' / '.join(candidate_group_ids)}",
            [*candidate_choices, "add_as_new_loading", "cancel"],
            str(first_group.get("group_id", "")),
            str(first_item.get("item_id", "")),
        )

    return _acquire_loading_item(data, normalized_furnace, normalized_shiji_no, "acquire")


def resolve_shiji_confirm(confirm_id: str, action: str) -> dict:
    normalized_confirm_id = (confirm_id or "").strip()
    normalized_action = (action or "").strip()
    if not normalized_confirm_id:
        return {"result": "error", "message": "confirm_id is empty."}
    if not normalized_action:
        return {"result": "error", "message": "action is empty."}

    data = _load_shiji_data()
    pending_confirms = data.setdefault("pending_confirms", {})
    confirm_payload = pending_confirms.get(normalized_confirm_id)
    if not isinstance(confirm_payload, dict):
        return {"result": "error", "message": f"confirm_id was not found: {normalized_confirm_id}"}

    furnace = str(confirm_payload.get("furnace", "")).strip()
    shiji_no = str(confirm_payload.get("shiji_no", "")).strip()
    confirm_type = str(confirm_payload.get("confirm_type", "")).strip()
    group_id = str(confirm_payload.get("group_id", "")).strip()
    item_id = str(confirm_payload.get("item_id", "")).strip()
    now_text = _now_text()

    if normalized_action == "cancel":
        event_name = "duplicate_cancelled" if confirm_type == "same_shiji_same_furnace" else "cancelled"
        _append_history(
            data,
            event_name,
            {
                "furnace": furnace,
                "shiji_no": shiji_no,
                "group_id": group_id,
                "item_id": item_id,
                "read_at": now_text,
                "confirm_id": normalized_confirm_id,
                "confirm_type": confirm_type,
            },
        )
        data["updated_at"] = now_text
        pending_confirms.pop(normalized_confirm_id, None)
        _save_shiji_data(data)
        return _build_result("cancelled", furnace, shiji_no, confirm_id=normalized_confirm_id, confirm_type=confirm_type)

    barashi_action_target = _parse_barashi_action(normalized_action)
    if normalized_action == "barashi_read" or barashi_action_target is not None:
        target_group_id = group_id
        target_item_id = item_id
        if barashi_action_target is not None:
            target_group_id, target_item_id = barashi_action_target
        groups = _get_or_create_furnace_groups(data, furnace)
        for group in groups:
            if str(group.get("group_id", "")) != target_group_id:
                continue
            items = group.get("items", [])
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                if str(item.get("item_id", "")) != target_item_id:
                    continue
                item["barashi_checked"] = True
                item["barashi_read_at"] = now_text
                if not group.get("barashi_started_at"):
                    group["barashi_started_at"] = now_text
                _sync_group_state_fields(group)
                if bool(group.get("barashi_done", False)) and not group.get("barashi_completed_at"):
                    group["barashi_completed_at"] = now_text
                data["updated_at"] = now_text
                pending_confirms.pop(normalized_confirm_id, None)
                _append_history(
                    data,
                    "barashi_read",
                    {
                        "furnace": furnace,
                        "shiji_no": shiji_no,
                        "item_id": target_item_id,
                        "read_at": now_text,
                        "group_id": target_group_id,
                        "group_no": group.get("group_no", 0),
                        "status": group.get("status", "waiting"),
                        "salt_up_done": bool(group.get("salt_up_done", False)),
                        "barashi_in_progress": bool(group.get("barashi_in_progress", False)),
                        "barashi_done": bool(group.get("barashi_done", False)),
                        "confirm_id": normalized_confirm_id,
                    },
                )
                _save_shiji_data(data)
                return _build_result("barashi_read", furnace, shiji_no, group=group, item=item)
        return {"result": "error", "message": f"Target item was not found: {target_item_id}"}

    if normalized_action == "add_as_new_loading":
        pending_confirms.pop(normalized_confirm_id, None)
        if confirm_type in {"same_shiji_same_furnace", "already_barashi_checked", "barashi_candidate", "multiple_barashi_candidates"}:
            result = _acquire_loading_item(
                data,
                furnace,
                shiji_no,
                "add_same_shiji",
                note="Additional loading with same shiji number",
            )
            result["confirm_id"] = normalized_confirm_id
            result["confirm_type"] = confirm_type
            return result
        return {"result": "error", "message": f"Unsupported confirm_type: {confirm_type}"}

    return {"result": "error", "message": f"Unsupported action: {normalized_action}"}


def _confirm_shiji_sent_group(
    data: dict[str, Any],
    furnace_name: str,
    groups: list[dict[str, Any]],
    target_group: dict[str, Any],
    event: str,
    now_text: str,
    salt_furnace: str | None = None,
    salt_up_time: str | None = None,
    access_recorded_at: str | None = None,
    extra_history: dict[str, Any] | None = None,
) -> dict:
    resolved_salt_furnace = salt_furnace or PG_TO_SQ_FURNACE.get(furnace_name)
    old_status = str(target_group.get("status", "waiting") or "waiting")
    target_group_id = str(target_group.get("group_id", ""))
    logger.info("[shiji] confirm_shiji_sent start group_id=%s old_status=%s", target_group_id, old_status)
    target_group["status"] = "salt_processing"
    target_group["salt_furnace"] = resolved_salt_furnace
    normalized_salt_up_time = (salt_up_time or "").strip()
    normalized_access_recorded_at = (access_recorded_at or "").strip()
    access_payload = extra_history if isinstance(extra_history, dict) else {}
    target_group["pg_completed_at"] = normalized_access_recorded_at or now_text
    if normalized_salt_up_time:
        target_group["salt_up_time"] = normalized_salt_up_time
        logger.info("[shiji] salt_up_time recorded group_id=%s solt_up_time=%s", target_group_id, normalized_salt_up_time)
    else:
        logger.info("[shiji] salt_up_time missing access_id=%s", access_payload.get("access_id", ""))
    if access_payload.get("access_id"):
        target_group["access_id"] = access_payload.get("access_id")
    if access_payload.get("access_furnace_no"):
        target_group["access_furnace_no"] = access_payload.get("access_furnace_no")
    if access_payload.get("shiji_no_text"):
        target_group["access_shiji_no_text"] = access_payload.get("shiji_no_text")
    if normalized_access_recorded_at:
        target_group["access_recorded_at"] = normalized_access_recorded_at
    _sync_group_state_fields(target_group)
    logger.info(
        "[shiji] group status changed group_id=%s %s -> %s",
        target_group_id,
        old_status,
        target_group.get("status", "waiting"),
    )
    logger.info(
        "[access_csv] pg completed and sq started pg_furnace=%s group_id=%s pg_status=%s sq_furnace=%s salt_up_time=%s",
        furnace_name,
        target_group_id,
        target_group.get("status", "waiting"),
        target_group.get("salt_furnace"),
        target_group.get("salt_up_time"),
    )
    updated_groups = [
        {
            "group_id": target_group.get("group_id", ""),
            "status": target_group.get("status", "waiting"),
            "salt_furnace": target_group.get("salt_furnace"),
        }
    ]

    next_group = _find_next_group(groups, int(target_group.get("group_no", 0) or 0))
    updated_next_group_id = ""
    if next_group is not None and str(next_group.get("status", "waiting") or "waiting") == "waiting":
        next_old_status = str(next_group.get("status", "waiting") or "waiting")
        next_group["status"] = "processing"
        next_group["pg_started_at"] = normalized_access_recorded_at or now_text
        _sync_group_state_fields(next_group)
        updated_next_group_id = str(next_group.get("group_id", ""))
        logger.info(
            "[shiji] next group status changed group_id=%s %s -> processing",
            updated_next_group_id,
            next_old_status,
        )
        updated_groups.append(
            {
                "group_id": updated_next_group_id,
                "status": next_group.get("status", "waiting"),
            }
        )
    elif next_group is None:
        logger.info("[shiji] next group not found furnace=%s group_id=%s", furnace_name, target_group_id)
    else:
        logger.info(
            "[shiji] next group skipped group_id=%s status=%s",
            next_group.get("group_id", ""),
            next_group.get("status", "waiting"),
        )

    data["updated_at"] = now_text
    history_payload = {
        "furnace": furnace_name,
        "group_id": target_group.get("group_id", ""),
        "group_no": target_group.get("group_no", 0),
        "old_status": old_status,
        "new_status": target_group.get("status", "waiting"),
        "status": target_group.get("status", "waiting"),
        "salt_furnace": target_group.get("salt_furnace"),
        "next_group_id": updated_next_group_id,
        "updated": updated_groups,
        "confirmed_at": now_text,
        "access_recorded_at": normalized_access_recorded_at,
    }
    if extra_history is not None:
        history_payload.update(extra_history)
    _append_history(data, event, history_payload)
    if updated_next_group_id:
        _append_history(
            data,
            "next_group_processing",
            {
                "furnace": furnace_name,
                "group_id": updated_next_group_id,
                "old_status": next_old_status,
                "new_status": "processing",
                "processed_at": now_text,
            },
        )
    if normalized_salt_up_time:
        _append_history(
            data,
            "salt_up_time_recorded",
            {
                "furnace": furnace_name,
                "group_id": target_group.get("group_id", ""),
                "solt_up_time": normalized_salt_up_time,
                "salt_up_time": normalized_salt_up_time,
                "processed_at": now_text,
            },
        )
    _save_shiji_data(data)
    logger.info(
        "[access_csv] shiji data saved group_id=%s pg_furnace=%s sq_furnace=%s salt_up_time=%s",
        target_group.get("group_id", ""),
        furnace_name,
        target_group.get("salt_furnace"),
        target_group.get("salt_up_time"),
    )
    return _build_result(
        event,
        furnace_name,
        "",
        group=target_group,
        event=event,
        target_group_id=target_group.get("group_id", ""),
        salt_furnace=target_group.get("salt_furnace"),
        salt_up_time=target_group.get("salt_up_time"),
        access_recorded_at=target_group.get("access_recorded_at"),
        next_group_id=updated_next_group_id,
        updated=updated_groups,
    )


def confirm_shiji_sent(
    group_id: str,
    salt_up_time: str | None = None,
    access_recorded_at: str | None = None,
) -> dict:
    normalized_group_id = (group_id or "").strip()
    if not normalized_group_id:
        return {"result": "error", "message": "group_id is empty."}

    data = _load_shiji_data()
    furnace_name, groups, target_group = _find_group_by_id(data, normalized_group_id)
    if furnace_name is None or groups is None or target_group is None:
        return {"result": "error", "message": f"group_id was not found: {normalized_group_id}"}

    now_text = _now_text()
    return _confirm_shiji_sent_group(
        data,
        furnace_name,
        groups,
        target_group,
        "confirm_shiji_sent",
        now_text,
        PG_TO_SQ_FURNACE.get(furnace_name),
        salt_up_time,
        access_recorded_at,
    )


def confirm_shiji_sent_by_access_furnace(
    access_furnace_no: str,
    shiji_no_text: str = "",
    salt_up_time: str | None = None,
    access_id: str = "",
    access_recorded_at: str = "",
    process_name: str = "",
    cooling_name: str = "",
    solt_time: str = "",
    pg_shiji_no_text: str = "",
    pg_pit_s_nippou_no: str = "",
    pg_match_status: str = "",
) -> dict:
    normalized_access_furnace_no = (access_furnace_no or "").strip()
    if not normalized_access_furnace_no:
        return {"result": "error", "message": "access_furnace_no is empty."}

    furnace_name = ACCESS_FURNACE_TO_PG.get(normalized_access_furnace_no)
    salt_furnace = ACCESS_FURNACE_TO_SQ.get(normalized_access_furnace_no)
    if not furnace_name:
        return {
            "result": "error",
            "event": "access_file_confirm_shiji_sent",
            "access_furnace_no": normalized_access_furnace_no,
            "message": f"Unsupported access_furnace_no: {normalized_access_furnace_no}",
        }

    data = _load_shiji_data()
    groups = _get_or_create_furnace_groups(data, furnace_name)
    target_group = _select_shiji_sent_target_group(groups, shiji_no_text, furnace_name)
    pg_shiji_matched = shiji_no_text_matches(pg_shiji_no_text, shiji_no_text)
    logger.info(
        "[access_csv] oracle pg compare furnace=%s pg_shiji=%s access_shiji=%s matched=%s",
        furnace_name,
        pg_shiji_no_text,
        shiji_no_text,
        str(pg_shiji_matched).lower(),
    )
    if target_group is None and pg_shiji_matched:
        target_group = _create_group_for_furnace(data, furnace_name, _now_text())
        target_group["status"] = "processing"
        target_group["pg_started_at"] = access_recorded_at
        for shiji_no_part in _normalize_shiji_no_parts(shiji_no_text):
            _create_item(target_group, shiji_no_part, _now_text(), note="Created from Access CSV history and Oracle PG status")
        _sync_group_state_fields(target_group)
        logger.info(
            "[access_csv] created access matched group furnace=%s group_id=%s shiji_no=%s",
            furnace_name,
            target_group.get("group_id", ""),
            shiji_no_text,
        )
    if target_group is None:
        return {
            "result": "no_target",
            "event": "access_file_confirm_shiji_sent",
            "access_furnace_no": normalized_access_furnace_no,
            "furnace": furnace_name,
            "shiji_no_text": shiji_no_text,
            "pg_shiji_no_text": pg_shiji_no_text,
            "pg_pit_s_nippou_no": pg_pit_s_nippou_no,
            "pg_match_status": pg_match_status,
            "message": "No group is available for shiji sent confirmation.",
        }

    now_text = _now_text()
    result = _confirm_shiji_sent_group(
        data,
        furnace_name,
        groups,
        target_group,
        "confirm_shiji_sent",
        now_text,
        salt_furnace,
        salt_up_time,
        access_recorded_at,
        extra_history={
            "access_id": access_id,
            "access_furnace_no": normalized_access_furnace_no,
            "salt_furnace": salt_furnace,
            "shiji_no_text": shiji_no_text,
            "process_name": process_name,
            "cooling_name": cooling_name,
            "solt_time": solt_time,
            "pg_shiji_no_text": pg_shiji_no_text,
            "pg_pit_s_nippou_no": pg_pit_s_nippou_no,
            "pg_match_status": pg_match_status,
        },
    )
    result["access_furnace_no"] = normalized_access_furnace_no
    result["access_id"] = access_id
    result["access_recorded_at"] = access_recorded_at
    result["salt_furnace"] = salt_furnace
    result["shiji_no_text"] = shiji_no_text
    result["pg_shiji_no_text"] = pg_shiji_no_text
    result["pg_pit_s_nippou_no"] = pg_pit_s_nippou_no
    result["pg_match_status"] = pg_match_status
    result["result"] = "ok"
    return result


def process_access_csv_record(
    access_id: str,
    access_furnace_no: str,
    solt_up_time: str,
    recorded_at: str = "",
    shiji_no_text: str = "",
    process_name: str = "",
    cooling_name: str = "",
    solt_time: str = "",
    pg_shiji_no_text: str = "",
    pg_pit_s_nippou_no: str = "",
    pg_match_status: str = "",
) -> dict:
    normalized_access_id = str(access_id or "").strip()
    normalized_access_furnace_no = str(access_furnace_no or "").strip()
    normalized_solt_up_time = str(solt_up_time or "").strip()
    normalized_recorded_at = str(recorded_at or "").strip()
    normalized_shiji_no_text = str(shiji_no_text or "").strip()
    normalized_process_name = str(process_name or "").strip()
    normalized_cooling_name = str(cooling_name or "").strip()
    normalized_solt_time = str(solt_time or "").strip()
    normalized_pg_shiji_no_text = str(pg_shiji_no_text or "").strip()
    normalized_pg_pit_s_nippou_no = str(pg_pit_s_nippou_no or "").strip()
    normalized_pg_match_status = str(pg_match_status or "").strip()
    logger.debug(
        "[access_csv] process record start access_id=%s furnace_no=%s shiji_no=%s pg_shiji_no=%s pg_pit_s_nippou_no=%s pg_match_status=%s process_name=%s cooling_name=%s solt_time=%s solt_up_time=%s recorded_at=%s",
        normalized_access_id,
        normalized_access_furnace_no,
        normalized_shiji_no_text,
        normalized_pg_shiji_no_text,
        normalized_pg_pit_s_nippou_no,
        normalized_pg_match_status,
        normalized_process_name,
        normalized_cooling_name,
        normalized_solt_time,
        normalized_solt_up_time,
        normalized_recorded_at,
    )
    if not normalized_access_furnace_no:
        return {"result": "error", "message": "access_furnace_no is empty."}

    access_record_key = _build_access_record_key(
        normalized_access_id,
        normalized_access_furnace_no,
        normalized_recorded_at,
    )
    data = _load_shiji_data()
    already_processed = _is_access_record_processed(data, access_record_key)
    logger.debug(
        "[access_csv] processed check access_id=%s already_processed=%s",
        normalized_access_id or access_record_key,
        str(already_processed).lower(),
    )
    if already_processed:
        logger.debug("[access_csv] skip processed access_id=%s", normalized_access_id or access_record_key)
        return {
            "result": "skipped",
            "event": "access_csv_record_detected",
            "access_record_key": access_record_key,
            "access_id": normalized_access_id,
            "access_furnace_no": normalized_access_furnace_no,
            "message": "Access CSV record was already processed.",
        }

    furnace_name = ACCESS_FURNACE_TO_PG.get(normalized_access_furnace_no, "")
    if not furnace_name:
        logger.info("[access_csv] furnace map failed access_furnace_no=%s", normalized_access_furnace_no)
        return {
            "result": "error",
            "event": "access_csv_record_detected",
            "access_record_key": access_record_key,
            "access_id": normalized_access_id,
            "access_furnace_no": normalized_access_furnace_no,
            "message": f"Unsupported access_furnace_no: {normalized_access_furnace_no}",
        }
    logger.debug(
        "[access_csv] furnace map access_furnace_no=%s -> furnace=%s",
        normalized_access_furnace_no,
        furnace_name,
    )
    logger.debug(
        "[access_csv] target furnace resolved access_furnace_no=%s pg_furnace=%s sq_furnace=%s",
        normalized_access_furnace_no,
        furnace_name,
        ACCESS_FURNACE_TO_SQ.get(normalized_access_furnace_no, ""),
    )

    processed_at = _now_text()
    _append_history(
        data,
        "access_csv_history_detected",
        {
            "access_record_key": access_record_key,
            "access_id": normalized_access_id,
            "access_furnace_no": normalized_access_furnace_no,
            "furnace": furnace_name,
            "group_id": "",
            "shiji_no_text": normalized_shiji_no_text,
            "pg_shiji_no_text": normalized_pg_shiji_no_text,
            "pg_pit_s_nippou_no": normalized_pg_pit_s_nippou_no,
            "pg_match_status": normalized_pg_match_status,
            "process_name": normalized_process_name,
            "cooling_name": normalized_cooling_name,
            "solt_time": normalized_solt_time,
            "solt_up_time": normalized_solt_up_time,
            "recorded_at": normalized_recorded_at,
            "processed_at": processed_at,
        },
    )
    data["updated_at"] = processed_at
    _save_shiji_data(data)

    confirm_result = confirm_shiji_sent_by_access_furnace(
        normalized_access_furnace_no,
        normalized_shiji_no_text,
        normalized_solt_up_time,
        normalized_access_id,
        normalized_recorded_at,
        normalized_process_name,
        normalized_cooling_name,
        normalized_solt_time,
        normalized_pg_shiji_no_text,
        normalized_pg_pit_s_nippou_no,
        normalized_pg_match_status,
    )
    confirm_log = logger.info if confirm_result.get("result") == "ok" else logger.debug
    confirm_log(
        "[access_csv] confirm result access_id=%s result=%s pg_furnace=%s sq_furnace=%s group_id=%s salt_up_time=%s",
        normalized_access_id or access_record_key,
        confirm_result.get("result", ""),
        furnace_name,
        confirm_result.get("salt_furnace", ACCESS_FURNACE_TO_SQ.get(normalized_access_furnace_no, "")),
        confirm_result.get("target_group_id", "") or confirm_result.get("group_id", ""),
        normalized_solt_up_time,
    )
    target_group_id = str(confirm_result.get("target_group_id", "") or confirm_result.get("group_id", "")).strip()
    if confirm_result.get("result") != "ok" or not target_group_id:
        data = _load_shiji_data()
        _append_processed_access_record(
            data,
            access_record_key,
            normalized_access_id,
            normalized_access_furnace_no,
            normalized_recorded_at,
            str(confirm_result.get("result", "error")),
            target_group_id,
            _now_text(),
            furnace_name,
            normalized_shiji_no_text,
        )
        _save_shiji_data(data)
        confirm_result["access_record_key"] = access_record_key
        confirm_result["access_id"] = normalized_access_id
        return confirm_result

    data = _load_shiji_data()
    _append_processed_access_record(
        data,
        access_record_key,
        normalized_access_id,
        normalized_access_furnace_no,
        normalized_recorded_at,
        "ok",
        target_group_id,
        _now_text(),
        furnace_name,
        normalized_shiji_no_text,
    )
    _save_shiji_data(data)
    return {
        "result": "ok",
        "event": "access_csv_record_processed",
        "access_record_key": access_record_key,
        "access_id": normalized_access_id,
        "access_furnace_no": normalized_access_furnace_no,
        "furnace": furnace_name,
        "group_id": target_group_id,
        "target_group_id": target_group_id,
        "shiji_no_text": normalized_shiji_no_text,
        "pg_shiji_no_text": normalized_pg_shiji_no_text,
        "pg_pit_s_nippou_no": normalized_pg_pit_s_nippou_no,
        "pg_match_status": normalized_pg_match_status,
        "process_name": normalized_process_name,
        "cooling_name": normalized_cooling_name,
        "solt_time": normalized_solt_time,
        "solt_up_time": normalized_solt_up_time,
        "confirm_result": confirm_result,
    }


def mark_salt_up_done(
    group_id: str,
    salt_up_at: str | None = None,
    event: str = "salt_up_done",
    extra_history: dict[str, Any] | None = None,
) -> dict:
    normalized_group_id = (group_id or "").strip()
    if not normalized_group_id:
        return {"result": "error", "message": "group_id is empty."}

    data = _load_shiji_data()
    furnace_name, _groups, target_group = _find_group_by_id(data, normalized_group_id)
    if furnace_name is None or target_group is None:
        return {"result": "error", "message": f"group_id was not found: {normalized_group_id}"}

    if str(target_group.get("status", "waiting") or "waiting") != "salt_processing":
        return _build_result(
            "error",
            furnace_name,
            "",
            group=target_group,
            message="Salt-up can be marked only for salt_processing groups.",
        )

    now_text = _now_text()
    salt_up_at_text = (salt_up_at or "").strip() or now_text
    target_group["salt_up_done"] = True
    target_group["salt_up_at"] = salt_up_at_text
    _sync_group_state_fields(target_group)
    data["updated_at"] = now_text
    history_payload = {
        "furnace": furnace_name,
        "group_id": normalized_group_id,
        "group_no": target_group.get("group_no", 0),
        "status": target_group.get("status", "waiting"),
        "salt_up_done": True,
        "salt_up_at": salt_up_at_text,
        "processed_at": now_text,
    }
    if extra_history is not None:
        history_payload.update(extra_history)
    _append_history(data, event, history_payload)
    _save_shiji_data(data)
    return _build_result("salt_up_done", furnace_name, "", group=target_group)


def _parse_salt_up_time(salt_up_time: str) -> datetime | None:
    normalized_salt_up_time = (salt_up_time or "").strip()
    if not normalized_salt_up_time:
        return None
    for date_format in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(normalized_salt_up_time, date_format)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized_salt_up_time)
    except ValueError:
        return None


def process_due_salt_up_times() -> dict[str, Any]:
    data = _load_shiji_data()
    now = datetime.now()
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    updated_groups: list[dict[str, Any]] = []
    furnaces = data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        return {"result": "skipped", "updated_count": 0, "updated": updated_groups}

    for furnace_name, furnace_entry in furnaces.items():
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("status", "waiting") or "waiting") != "salt_processing":
                continue
            if bool(group.get("salt_up_done", False)):
                continue
            salt_up_time_text = str(group.get("salt_up_time", "") or "").strip()
            salt_up_time = _parse_salt_up_time(salt_up_time_text)
            if salt_up_time is None or salt_up_time > now:
                continue
            group["salt_up_done"] = True
            group["salt_up_at"] = now_text
            _sync_group_state_fields(group)
            updated_entry = {
                "furnace": str(furnace_name),
                "group_id": group.get("group_id", ""),
                "group_no": group.get("group_no", 0),
                "salt_up_time": salt_up_time_text,
                "salt_up_done": True,
                "salt_up_at": now_text,
            }
            updated_groups.append(updated_entry)
            _append_history(
                data,
                "salt_up_done",
                {
                    **updated_entry,
                    "processed_at": now_text,
                },
            )

    if not updated_groups:
        return {"result": "ok", "updated_count": 0, "updated": updated_groups}
    data["updated_at"] = now_text
    _save_shiji_data(data)
    return {"result": "ok", "updated_count": len(updated_groups), "updated": updated_groups}


def mark_barashi_done_by_scan(furnace: str, shiji_no: str) -> dict:
    normalized_furnace = (furnace or "").strip()
    normalized_shiji_no = (shiji_no or "").strip()
    if not normalized_furnace:
        return {"result": "error", "message": "Furnace is empty."}
    if not normalized_shiji_no:
        return {"result": "error", "message": "Shiji number is empty."}

    data = _load_shiji_data()
    groups = _get_or_create_furnace_groups(data, normalized_furnace)
    matched_groups: list[dict[str, Any]] = []
    matched_items: list[dict[str, Any]] = []
    for group in groups:
        if not bool(group.get("salt_up_done", False)):
            continue
        if bool(group.get("barashi_done", False)):
            continue
        items = group.get("items", [])
        if not isinstance(items, list):
            continue
        if _group_matches_shiji_no_text(group, normalized_shiji_no):
            first_item = next((item for item in items if isinstance(item, dict)), None)
            if first_item is not None:
                matched_groups.append(group)
                matched_items.append(first_item)
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("shiji_no", "")).strip() != normalized_shiji_no:
                continue
            matched_groups.append(group)
            matched_items.append(item)
            break

    if not matched_groups:
        return {"result": "not_found", "furnace": normalized_furnace, "shiji_no": normalized_shiji_no}

    if len(matched_groups) > 1:
        candidate_group_ids = [str(group.get("group_id", "")) for group in matched_groups]
        return {
            "result": "needs_confirm",
            "confirm_type": "multiple_barashi_done_candidates",
            "furnace": normalized_furnace,
            "shiji_no": normalized_shiji_no,
            "group_ids": candidate_group_ids,
            "message": f"Multiple barashi groups were found: {' / '.join(candidate_group_ids)}",
        }

    target_group = matched_groups[0]
    target_item = matched_items[0]
    now_text = _now_text()
    target_item["barashi_checked"] = True
    target_item["barashi_read_at"] = now_text
    if not target_group.get("barashi_started_at"):
        target_group["barashi_started_at"] = now_text
    if _group_matches_shiji_no_text(target_group, normalized_shiji_no):
        _mark_group_barashi_done(target_group, now_text)
    else:
        _sync_group_state_fields(target_group)
    data["updated_at"] = now_text
    barashi_result = "barashi_done" if bool(target_group.get("barashi_done", False)) else "barashi_read"
    _append_history(
        data,
        barashi_result,
        {
            "furnace": normalized_furnace,
            "shiji_no": normalized_shiji_no,
            "group_id": target_group.get("group_id", ""),
            "group_no": target_group.get("group_no", 0),
            "item_id": target_item.get("item_id", ""),
            "status": target_group.get("status", "waiting"),
            "salt_up_done": bool(target_group.get("salt_up_done", False)),
            "barashi_done": bool(target_group.get("barashi_done", False)),
            "barashi_done_at": target_group.get("barashi_done_at"),
        },
    )
    _save_shiji_data(data)
    return _build_result(barashi_result, normalized_furnace, normalized_shiji_no, group=target_group, item=target_item)


def _find_access_recorded_at_by_group_id(data: dict[str, Any], group_id: str) -> str:
    normalized_group_id = str(group_id or "").strip()
    if not normalized_group_id:
        return ""

    furnaces = data.get("furnaces", {})
    if isinstance(furnaces, dict):
        for furnace_entry in furnaces.values():
            if not isinstance(furnace_entry, dict):
                continue
            groups = furnace_entry.get("groups", [])
            if not isinstance(groups, list):
                continue
            for group in groups:
                if not isinstance(group, dict):
                    continue
                if str(group.get("group_id", "")) != normalized_group_id:
                    continue
                recorded_at = str(group.get("access_recorded_at", "") or "").strip()
                if recorded_at:
                    return recorded_at
                completed_at = str(group.get("pg_completed_at", "") or "").strip()
                if completed_at:
                    return completed_at
                return ""

    processed_access_records = data.get("processed_access_records", [])
    if not isinstance(processed_access_records, list):
        return ""
    for processed_record in reversed(processed_access_records):
        if not isinstance(processed_record, dict):
            continue
        if str(processed_record.get("group_id", "")) != normalized_group_id:
            continue
        return str(processed_record.get("recorded_at", "") or "").strip()
    return ""


def _find_previous_group(groups: list[dict[str, Any]], current_group_no: int) -> dict[str, Any] | None:
    previous_groups = [
        group
        for group in groups
        if isinstance(group, dict) and int(group.get("group_no", 0) or 0) < current_group_no
    ]
    if not previous_groups:
        return None
    return max(previous_groups, key=lambda group: int(group.get("group_no", 0) or 0))


def load_shiji_furnace_status_overrides() -> dict[str, dict[str, str]]:
    data = _load_shiji_data()
    overrides: dict[str, dict[str, str]] = {}
    furnaces = data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        return overrides

    sq_candidates: dict[str, dict[str, Any]] = {}
    pg_furnace_names = set(PG_TO_SQ_FURNACE)
    sq_furnace_names = set(PG_TO_SQ_FURNACE.values())
    seen_pg_furnace_names: set[str] = set()
    removed_barashi_done_groups = _remove_barashi_done_groups(data, _now_text())
    promoted_waiting_group = False
    for furnace_name, furnace_entry in furnaces.items():
        furnace_name_text = str(furnace_name)
        if furnace_name_text in pg_furnace_names:
            seen_pg_furnace_names.add(furnace_name_text)
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list):
            continue
        if _promote_waiting_group_if_no_processing(data, furnace_name_text, groups, _now_text()):
            promoted_waiting_group = True

        processing_group = _select_display_group(groups)
        if isinstance(processing_group, dict):
            started_at = str(processing_group.get("pg_started_at", "") or "").strip()
            if not started_at:
                previous_group = _find_previous_group(groups, int(processing_group.get("group_no", 0) or 0))
                if previous_group is not None:
                    started_at = str(previous_group.get("access_recorded_at", "") or "").strip()
                    if not started_at:
                        started_at = _find_access_recorded_at_by_group_id(data, str(previous_group.get("group_id", "")))
            overrides[str(furnace_name)] = {
                "instruction_no_text": _get_group_shiji_no_text(processing_group),
                "start_time_text": _format_time_text(started_at),
            }
        elif furnace_name_text in pg_furnace_names:
            overrides[furnace_name_text] = {
                "instruction_no_text": "停機",
                "start_time_text": "-",
            }

        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("status", "waiting") or "waiting") != "salt_processing":
                continue
            salt_furnace = str(group.get("salt_furnace", "") or "").strip()
            if not salt_furnace:
                continue
            salt_up_time = str(group.get("salt_up_time", "") or "").strip()
            parsed_salt_up_time = _parse_salt_up_time(salt_up_time)
            salt_up_time_elapsed = parsed_salt_up_time is not None and parsed_salt_up_time <= datetime.now()
            salt_up_done = bool(group.get("salt_up_done", False))
            if salt_up_done or parsed_salt_up_time is None or salt_up_time_elapsed:
                continue
            sq_stopped = salt_up_done and salt_up_time_elapsed
            candidate = {
                "status_text": "停機" if sq_stopped else "処理中",
                "status_kind": "stopped" if sq_stopped else "running",
                "end_time_text": _format_time_text(salt_up_time),
                "salt_up_done": salt_up_done,
                "salt_up_time": salt_up_time,
                "sq_stopped": sq_stopped,
                "group_no": int(group.get("group_no", 0) or 0),
            }
            current_candidate = sq_candidates.get(salt_furnace)
            if current_candidate is None:
                sq_candidates[salt_furnace] = candidate
                continue
            current_stopped = bool(current_candidate.get("sq_stopped", False))
            candidate_stopped = bool(candidate.get("sq_stopped", False))
            if current_stopped and not candidate_stopped:
                sq_candidates[salt_furnace] = candidate
                continue
            if current_stopped == candidate_stopped and str(candidate.get("salt_up_time", "")) < str(current_candidate.get("salt_up_time", "")):
                sq_candidates[salt_furnace] = candidate

    for sq_furnace_name in sq_furnace_names:
        overrides[sq_furnace_name] = {
            "status_text": "停機",
            "status_kind": "stopped",
            "end_time_text": "-",
            "salt_up_done": "true",
        }
    for salt_furnace, candidate in sq_candidates.items():
        overrides[salt_furnace] = {
            "status_text": str(candidate.get("status_text", "処理中")),
            "status_kind": str(candidate.get("status_kind", "running")),
            "end_time_text": str(candidate.get("end_time_text", "-")),
            "salt_up_done": "true" if bool(candidate.get("salt_up_done", False)) else "false",
        }
    for pg_furnace_name in sorted(pg_furnace_names - seen_pg_furnace_names):
        overrides[pg_furnace_name] = {
            "instruction_no_text": "停機",
            "start_time_text": "-",
        }
    if promoted_waiting_group or removed_barashi_done_groups:
        _save_shiji_data(data)
    return overrides


def load_latest_group_display_by_furnace() -> dict[str, str]:
    data = _load_shiji_data()
    display_by_furnace: dict[str, str] = {}
    furnaces = data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        return display_by_furnace

    for furnace_name, furnace_entry in furnaces.items():
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list) or not groups:
            continue
        display_group = _select_display_group(groups)
        if not isinstance(display_group, dict):
            continue
        items = display_group.get("items", [])
        if not isinstance(items, list) or not items:
            continue
        shiji_numbers = [
            str(item.get("shiji_no", "")).strip()
            for item in items
            if isinstance(item, dict) and str(item.get("shiji_no", "")).strip()
        ]
        if shiji_numbers:
            display_by_furnace[str(furnace_name)] = " / ".join(shiji_numbers)
    return display_by_furnace


def load_access_completed_shiji_no_texts_by_furnace() -> dict[str, set[str]]:
    data = _load_shiji_data()
    completed_by_furnace: dict[str, set[str]] = {}
    furnaces = data.get("furnaces", {})
    if not isinstance(furnaces, dict):
        return completed_by_furnace

    for furnace_name, furnace_entry in furnaces.items():
        if not isinstance(furnace_entry, dict):
            continue
        groups = furnace_entry.get("groups", [])
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            if str(group.get("status", "waiting") or "waiting") == "processing":
                continue
            if not str(group.get("access_id", "") or "").strip() and not str(group.get("access_shiji_no_text", "") or "").strip():
                continue
            shiji_no_texts = completed_by_furnace.setdefault(str(furnace_name), set())
            group_shiji_no_text = _get_group_shiji_no_text(group)
            access_shiji_no_text = str(group.get("access_shiji_no_text", "") or "").strip()
            if group_shiji_no_text:
                shiji_no_texts.add(group_shiji_no_text)
            if access_shiji_no_text:
                shiji_no_texts.add(access_shiji_no_text)
    return completed_by_furnace


def get_confirm_action_label(action: str) -> str:
    barashi_action_target = _parse_barashi_action(action)
    if barashi_action_target is not None:
        group_id, _item_id = barashi_action_target
        return f"ばらし読み込み ({group_id})"
    return _PENDING_CONFIRM_ACTION_LABELS.get(action, action)
