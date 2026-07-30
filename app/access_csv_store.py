from __future__ import annotations

from datetime import datetime
import logging
from pathlib import Path
from typing import Any

from app.pg_access_match_batch_store import mark_pg_access_match_batch_salt_moved
from app.shiji_store import ACCESS_FURNACE_TO_PG, process_access_csv_record, process_due_salt_up_times, shiji_no_text_matches

try:
    import pyodbc
except ImportError:  # pragma: no cover - depends on the runtime environment.
    pyodbc = None


_CSV_HISTORY_TABLE = "CSV履歴"
_ACCESS_ID_COLUMN = "ID"
_ACCESS_RECORDED_AT_COLUMN = "記録日時"
_ACCESS_FURNACE_COLUMN = "炉番号"
_ACCESS_SOLT_UP_TIME_COLUMN = "solt_up_time"
_ACCESS_PROCESS_NAME_COLUMN = "\u51e6\u7406\u540d"
_ACCESS_COOLING_NAME_COLUMN = "\u51b7\u5374\u540d"
_ACCESS_SOLT_TIME_COLUMN = "solt_time"
_ACCESS_SHIJI_NO_COLUMN_CANDIDATES = ("指示番号", "作業指示書No", "shiji_no", "SIJINO")
logger = logging.getLogger(__name__)


def _select_pg_access_match_candidate(
    access_record: dict[str, str],
    pg_status: dict[str, Any],
    pg_access_match_batches: list[dict[str, Any]],
) -> dict[str, Any]:
    access_shiji_no_text = str(access_record.get("shiji_no_text", "") or "").strip()
    candidates: list[dict[str, Any]] = []
    candidates.extend({**batch, "match_source": "pg_access_match_batches"} for batch in pg_access_match_batches)

    logger.debug(
        "[access_csv] pg match candidates access_furnace_no=%s pg_furnace=%s access_shiji=%s cached_pending=%s",
        access_record.get("access_furnace_no", ""),
        ACCESS_FURNACE_TO_PG.get(access_record.get("access_furnace_no", ""), ""),
        access_shiji_no_text,
        [
            {
                "pit_s_nippou_no": candidate.get("pit_s_nippou_no"),
                "shiji_no_text": candidate.get("shiji_no_text", ""),
                "salt_moved": candidate.get("salt_moved", False),
            }
            for candidate in candidates
        ],
    )
    for candidate in candidates:
        candidate_shiji_no_text = str(candidate.get("shiji_no_text", "") or candidate.get("instruction_no_text", "") or "").strip()
        matched = shiji_no_text_matches(access_shiji_no_text, candidate_shiji_no_text)
        logger.debug(
            "[access_csv] pg match compare access_shiji=%s candidate_shiji=%s pg_furnace=%s pit_s_nippou_no=%s status_kind=%s source=%s matched=%s",
            access_shiji_no_text,
            candidate_shiji_no_text,
            candidate.get("pg_furnace", candidate.get("furnace", ACCESS_FURNACE_TO_PG.get(access_record.get("access_furnace_no", ""), ""))),
            candidate.get("pit_s_nippou_no"),
            candidate.get("status_kind", ""),
            candidate.get("match_source", ""),
            str(matched).lower(),
        )
        if matched:
            logger.info(
                "[access_csv] pg match selected access_shiji=%s pg_furnace=%s pit_s_nippou_no=%s candidate_shiji=%s status_kind=%s source=%s",
                access_shiji_no_text,
                candidate.get("pg_furnace", candidate.get("furnace", ACCESS_FURNACE_TO_PG.get(access_record.get("access_furnace_no", ""), ""))),
                candidate.get("pit_s_nippou_no"),
                candidate_shiji_no_text,
                candidate.get("status_kind", ""),
                candidate.get("match_source", ""),
            )
            return candidate
    logger.debug(
        "[access_csv] pg match not found access_furnace_no=%s access_shiji=%s",
        access_record.get("access_furnace_no", ""),
        access_shiji_no_text,
    )
    return {}


def _format_access_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    return str(value).strip()


def _build_connection_string(access_file_path: Path) -> str:
    return f"DRIVER={{Microsoft Access Driver (*.mdb, *.accdb)}};DBQ={access_file_path};"


def _fetch_access_columns(cursor: Any) -> set[str]:
    try:
        return {
            str(row.column_name)
            for row in cursor.columns(table=_CSV_HISTORY_TABLE)
            if getattr(row, "column_name", None)
        }
    except Exception:  # noqa: BLE001
        return set()


def _fetch_latest_csv_records(access_file_path: Path, limit: int) -> list[dict[str, str]]:
    if pyodbc is None:
        raise RuntimeError("pyodbc is required to read ACCESS_FILE.")

    try:
        connection = pyodbc.connect(_build_connection_string(access_file_path), timeout=3)
        logger.debug("[access_csv] connected ACCESS_FILE=%s", access_file_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("[access_csv] connect failed ACCESS_FILE=%s error=%s", access_file_path, exc)
        raise
    try:
        cursor = connection.cursor()
        access_columns = _fetch_access_columns(cursor)
        shiji_no_column = next(
            (
                column_name
                for column_name in _ACCESS_SHIJI_NO_COLUMN_CANDIDATES
                if column_name in access_columns
            ),
            "",
        )
        selected_columns: list[tuple[str, str]] = [
            ("access_id", _ACCESS_ID_COLUMN),
            ("recorded_at", _ACCESS_RECORDED_AT_COLUMN),
            ("access_furnace_no", _ACCESS_FURNACE_COLUMN),
            ("solt_up_time", _ACCESS_SOLT_UP_TIME_COLUMN),
        ]
        if shiji_no_column:
            selected_columns.append(("shiji_no_text", shiji_no_column))
        for record_key, column_name in (
            ("process_name", _ACCESS_PROCESS_NAME_COLUMN),
            ("cooling_name", _ACCESS_COOLING_NAME_COLUMN),
            ("solt_time", _ACCESS_SOLT_TIME_COLUMN),
        ):
            if column_name in access_columns:
                selected_columns.append((record_key, column_name))
        column_sql = ", ".join(f"[{column_name}]" for _record_key, column_name in selected_columns)
        query = (
            f"SELECT TOP {int(limit)} "
            f"{column_sql} "
            f"FROM [{_CSV_HISTORY_TABLE}] "
            f"ORDER BY [{_ACCESS_ID_COLUMN}] DESC"
        )
        rows = cursor.execute(query).fetchall()
        logger.debug("[access_csv] fetched records count=%s", len(rows))
    finally:
        connection.close()

    records: list[dict[str, str]] = []
    seen_access_furnace_numbers: set[str] = set()
    for row in rows:
        record = {
            "access_id": _format_access_value(row[0]),
            "recorded_at": _format_access_value(row[1]),
            "access_furnace_no": _format_access_value(row[2]),
            "solt_up_time": _format_access_value(row[3]),
            "shiji_no_text": _format_access_value(row[4]) if len(row) > 4 and selected_columns[4][0] == "shiji_no_text" else "",
        }
        for column_index, (record_key, _column_name) in enumerate(selected_columns):
            if record_key in record:
                continue
            record[record_key] = _format_access_value(row[column_index])
        record.setdefault("process_name", "")
        record.setdefault("cooling_name", "")
        record.setdefault("solt_time", "")
        access_furnace_no = record["access_furnace_no"]
        if access_furnace_no in seen_access_furnace_numbers:
            logger.debug(
                "[access_csv] skip older furnace record id=%s furnace_no=%s shiji_no=%s",
                record["access_id"],
                access_furnace_no,
                record["shiji_no_text"],
            )
            continue
        seen_access_furnace_numbers.add(access_furnace_no)
        logger.debug(
            "[access_csv] record detail id=%s recorded_at=%s furnace_no=%s shiji_no=%s process_name=%s cooling_name=%s solt_time=%s solt_up_time=%s",
            record["access_id"],
            record["recorded_at"],
            record["access_furnace_no"],
            record["shiji_no_text"],
            record["process_name"],
            record["cooling_name"],
            record["solt_time"],
            record["solt_up_time"],
        )
        logger.debug(
            "[access_csv] record id=%s 登録日時=%s 炉番号=%s 指示番号=%s solt_up_time=%s",
            record["access_id"],
            record["recorded_at"],
            record["access_furnace_no"],
            record["shiji_no_text"],
            record["solt_up_time"],
        )
        records.append(record)
    return records


def process_new_access_file_entries(
    access_file_path: Path,
    limit: int = 50,
    pg_status_by_furnace: dict[str, dict[str, Any]] | None = None,
    pg_access_match_batches_by_furnace: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    logger.debug(
        "[access_csv] start process_new_access_csv_history ACCESS_FILE=%s table=%s now=%s",
        access_file_path,
        _CSV_HISTORY_TABLE,
        _format_access_value(datetime.now()),
    )
    if not access_file_path:
        return {"result": "skipped", "message": "ACCESS_FILE is empty."}
    if not access_file_path.exists():
        return {"result": "skipped", "message": f"ACCESS_FILE was not found: {access_file_path}"}

    records = _fetch_latest_csv_records(access_file_path, limit)
    logger.debug("[access_csv] fetched records count=%s ACCESS_FILE=%s", len(records), access_file_path)
    processed_results: list[dict[str, Any]] = []
    for record in records:
        pg_furnace = ACCESS_FURNACE_TO_PG.get(record.get("access_furnace_no", ""), "")
        pg_status = (pg_status_by_furnace or {}).get(pg_furnace, {})
        pg_match_candidate = _select_pg_access_match_candidate(
            record,
            pg_status,
            (pg_access_match_batches_by_furnace or {}).get(pg_furnace, []),
        )
        if not pg_match_candidate:
            processed_results.append(
                {
                    "result": "skipped",
                    "event": "access_csv_record_detected",
                    "access_id": record.get("access_id", ""),
                    "access_furnace_no": record.get("access_furnace_no", ""),
                    "shiji_no_text": record.get("shiji_no_text", ""),
                    "message": "No pending PG access match batch was found.",
                }
            )
            continue
        process_result = process_access_csv_record(
            record.get("access_id", ""),
            record.get("access_furnace_no", ""),
            record.get("solt_up_time", ""),
            recorded_at=record.get("recorded_at", ""),
            shiji_no_text=record.get("shiji_no_text", ""),
            process_name=record.get("process_name", ""),
            cooling_name=record.get("cooling_name", ""),
            solt_time=record.get("solt_time", ""),
            pg_shiji_no_text=str(pg_match_candidate.get("shiji_no_text", "") or pg_match_candidate.get("instruction_no_text", "") or ""),
            pg_pit_s_nippou_no=str(pg_match_candidate.get("pit_s_nippou_no", "") or ""),
            pg_match_status=str(pg_match_candidate.get("status_kind", "") or ""),
        )
        if process_result.get("result") == "ok" and pg_match_candidate:
            salt_moved_marked = mark_pg_access_match_batch_salt_moved(
                str(pg_match_candidate.get("pg_furnace", pg_furnace) or pg_furnace),
                str(pg_match_candidate.get("shiji_no_text", "") or pg_match_candidate.get("instruction_no_text", "") or ""),
                str(pg_match_candidate.get("pit_s_nippou_no", "") or ""),
            )
            process_result["pg_access_match_salt_moved"] = salt_moved_marked
        processed_results.append(process_result)
    salt_up_result = process_due_salt_up_times()

    changed_results = [
        result
        for result in processed_results
        if str(result.get("result", "")) not in {"skipped"}
    ]
    salt_up_updated_count = int(salt_up_result.get("updated_count", 0) or 0)
    result_counts: dict[str, int] = {}
    for result in processed_results:
        result_name = str(result.get("result", "unknown") or "unknown")
        result_counts[result_name] = result_counts.get(result_name, 0) + 1
    summary_log = logger.info if changed_results or salt_up_updated_count else logger.debug
    summary_log(
        "[access_csv] summary records=%s changed=%s salt_up_updated=%s results=%s",
        len(records),
        len(changed_results),
        salt_up_updated_count,
        result_counts,
    )
    return {
        "result": "ok",
        "record_count": len(records),
        "changed_count": len(changed_results) + salt_up_updated_count,
        "results": processed_results,
        "salt_up_result": salt_up_result,
    }
