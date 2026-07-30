from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - depends on the runtime environment.
    load_dotenv = None


RUNNING_STATUS_CODE = "running"
STOPPED_STATUS_CODE = "stopped"
RUNNING_STATUS_TEXT = "\u51e6\u7406\u4e2d"
STOPPED_STATUS_TEXT = "\u505c\u6a5f"
PG_FURNACE_STATUS_QUERY = """
WITH pg_furnaces AS (
    SELECT '06' AS RO_NO, 'PG-1' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '07' AS RO_NO, 'PG-2' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '08' AS RO_NO, 'PG-3' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '20' AS RO_NO, 'PG-4' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '32' AS RO_NO, 'PG-5' AS FURNACE_NAME FROM DUAL
),
shiji_distinct AS (
    SELECT DISTINCT
        m.PIT_S_NIPPOU_NO,
        m.S_SIJI_NO
    FROM SANYO.T_PIT_SAGYO_NIPPOU_MEI m
    WHERE m.S_SIJI_NO IS NOT NULL
),
shiji_agg AS (
    SELECT
        PIT_S_NIPPOU_NO,
        LISTAGG(S_SIJI_NO, '/') WITHIN GROUP (ORDER BY S_SIJI_NO) AS S_SIJI_NO_TEXT
    FROM shiji_distinct
    GROUP BY
        PIT_S_NIPPOU_NO
),
running_headers AS (
    SELECT
        n.RO_NO,
        r.RO_NM,
        n.PIT_S_NIPPOU_NO,
        n.SOUNYU_YMD_F,
        n.SOUNYU_YMD_T,
        n.TOUROKU_DATE,
        n.KOUSIN_DATE
    FROM SANYO.T_PIT_SAGYO_NIPPOU n
    LEFT JOIN SANYO.M_RO r
        ON r.RO_NO = n.RO_NO
    WHERE n.RO_NO IN ('06', '07', '08', '20', '32')
      AND n.SOUNYU_YMD_F IS NOT NULL
      AND n.SOUNYU_YMD_T IS NULL
),
running_batches AS (
    SELECT
        h.RO_NO,
        h.RO_NM,
        h.PIT_S_NIPPOU_NO,
        h.SOUNYU_YMD_F,
        h.SOUNYU_YMD_T,
        s.S_SIJI_NO_TEXT,
        h.TOUROKU_DATE,
        h.KOUSIN_DATE
    FROM running_headers h
    LEFT JOIN shiji_agg s
        ON s.PIT_S_NIPPOU_NO = h.PIT_S_NIPPOU_NO
),
ranked_batches AS (
    SELECT
        running_batches.*,
        ROW_NUMBER() OVER (
            PARTITION BY running_batches.RO_NO
            ORDER BY
                running_batches.SOUNYU_YMD_F DESC,
                running_batches.PIT_S_NIPPOU_NO DESC
        ) AS RN
    FROM running_batches
)
SELECT
    p.FURNACE_NAME,
    p.RO_NO,
    COALESCE(b.RO_NM, p.FURNACE_NAME) AS RO_NM,
    CASE
        WHEN b.PIT_S_NIPPOU_NO IS NULL THEN 'stopped'
        ELSE 'running'
    END AS STATUS,
    b.PIT_S_NIPPOU_NO,
    b.S_SIJI_NO_TEXT,
    b.SOUNYU_YMD_F AS STARTED_AT,
    b.SOUNYU_YMD_T AS ENDED_AT,
    b.TOUROKU_DATE,
    b.KOUSIN_DATE
FROM pg_furnaces p
LEFT JOIN ranked_batches b
    ON b.RO_NO = p.RO_NO
   AND b.RN = 1
ORDER BY
    p.RO_NO
"""
PG_FURNACE_ACCESS_MATCH_QUERY = """
WITH pg_furnaces AS (
    SELECT '06' AS RO_NO, 'PG-1' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '07' AS RO_NO, 'PG-2' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '08' AS RO_NO, 'PG-3' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '20' AS RO_NO, 'PG-4' AS FURNACE_NAME FROM DUAL
    UNION ALL
    SELECT '32' AS RO_NO, 'PG-5' AS FURNACE_NAME FROM DUAL
),
shiji_distinct AS (
    SELECT DISTINCT
        m.PIT_S_NIPPOU_NO,
        m.S_SIJI_NO
    FROM SANYO.T_PIT_SAGYO_NIPPOU_MEI m
    WHERE m.S_SIJI_NO IS NOT NULL
),
shiji_agg AS (
    SELECT
        PIT_S_NIPPOU_NO,
        LISTAGG(S_SIJI_NO, '/') WITHIN GROUP (ORDER BY S_SIJI_NO) AS S_SIJI_NO_TEXT
    FROM shiji_distinct
    GROUP BY
        PIT_S_NIPPOU_NO
),
candidate_batches AS (
    SELECT
        p.FURNACE_NAME,
        n.RO_NO,
        r.RO_NM,
        n.PIT_S_NIPPOU_NO,
        s.S_SIJI_NO_TEXT,
        n.SOUNYU_YMD_F AS STARTED_AT,
        n.SOUNYU_YMD_T AS ENDED_AT,
        n.TOUROKU_DATE,
        n.KOUSIN_DATE,
        CASE
            WHEN n.SOUNYU_YMD_F IS NOT NULL AND n.SOUNYU_YMD_T IS NULL THEN 'running'
            ELSE 'finished'
        END AS MATCH_STATUS
    FROM SANYO.T_PIT_SAGYO_NIPPOU n
    INNER JOIN pg_furnaces p
        ON p.RO_NO = n.RO_NO
    LEFT JOIN SANYO.M_RO r
        ON r.RO_NO = n.RO_NO
    LEFT JOIN shiji_agg s
        ON s.PIT_S_NIPPOU_NO = n.PIT_S_NIPPOU_NO
    WHERE n.SOUNYU_YMD_F IS NOT NULL
),
ranked_batches AS (
    SELECT
        candidate_batches.*,
        ROW_NUMBER() OVER (
            PARTITION BY candidate_batches.RO_NO
            ORDER BY
                CASE WHEN candidate_batches.MATCH_STATUS = 'running' THEN 0 ELSE 1 END,
                candidate_batches.KOUSIN_DATE DESC NULLS LAST,
                candidate_batches.ENDED_AT DESC NULLS LAST,
                candidate_batches.STARTED_AT DESC NULLS LAST,
                candidate_batches.TOUROKU_DATE DESC NULLS LAST,
                candidate_batches.PIT_S_NIPPOU_NO DESC
        ) AS RN
    FROM candidate_batches
)
SELECT
    FURNACE_NAME,
    RO_NO,
    RO_NM,
    MATCH_STATUS AS STATUS,
    PIT_S_NIPPOU_NO,
    S_SIJI_NO_TEXT,
    STARTED_AT,
    ENDED_AT,
    TOUROKU_DATE,
    KOUSIN_DATE
FROM ranked_batches
WHERE RN <= 20
ORDER BY
    RO_NO,
    RN
"""
FORBIDDEN_SQL_PATTERNS = (
    r"\bINSERT\b",
    r"\bUPDATE\b",
    r"\bDELETE\b",
    r"\bMERGE\b",
    r"\bALTER\b",
    r"\bDROP\b",
    r"\bCREATE\b",
    r"\bTRUNCATE\b",
    r"\bEXEC\b",
    r"\bCALL\b",
    r"\bCOMMIT\b",
    r"\bFOR\s+UPDATE\b",
)


def get_runtime_env_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / ".env"
    return Path(__file__).resolve().parents[1] / ".env"


def load_environment() -> None:
    if load_dotenv is not None:
        load_dotenv(dotenv_path=get_runtime_env_path())


def ensure_readonly_query(query: str) -> str:
    normalized_query = query.strip()
    upper_query = normalized_query.upper()
    if not (upper_query.startswith("SELECT") or upper_query.startswith("WITH")):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    for pattern in FORBIDDEN_SQL_PATTERNS:
        if re.search(pattern, upper_query):
            raise ValueError("Forbidden SQL detected.")
    return normalized_query


def get_oracle_connection() -> Any:
    import oracledb

    load_environment()
    user = os.getenv("ORACLE_USER")
    password = os.getenv("ORACLE_PASSWORD")
    dsn = os.getenv("ORACLE_DSN")
    if not user or not password or not dsn:
        raise RuntimeError("ORACLE_USER, ORACLE_PASSWORD, ORACLE_DSN are required.")
    return oracledb.connect(user=user, password=password, dsn=dsn)


def format_oracle_time_text(value: Any) -> str:
    if value is None:
        return "-"
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M")
    value_text = str(value).strip()
    if not value_text:
        return "-"
    for date_format in ("%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(value_text, date_format).strftime("%H:%M")
        except ValueError:
            continue
    return value_text


def normalize_pg_status_row(row: dict[str, Any]) -> dict[str, Any]:
    status_code = str(row.get("status", "") or "").strip()
    status_kind = "running" if status_code == RUNNING_STATUS_CODE else "stopped"
    status_text = RUNNING_STATUS_TEXT if status_kind == "running" else STOPPED_STATUS_TEXT
    shiji_no_text = str(row.get("s_siji_no_text", "") or "").strip()
    if status_kind == "stopped":
        instruction_no_text = STOPPED_STATUS_TEXT
        start_time_text = "-"
    else:
        instruction_no_text = shiji_no_text or "-"
        start_time_text = format_oracle_time_text(row.get("started_at"))
    return {
        "furnace": str(row.get("furnace_name", "") or "").strip(),
        "ro_no": str(row.get("ro_no", "") or "").strip(),
        "status_text": status_text,
        "status_kind": status_kind,
        "pit_s_nippou_no": row.get("pit_s_nippou_no"),
        "instruction_no_text": instruction_no_text,
        "shiji_no_text": shiji_no_text,
        "start_time_text": start_time_text,
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "registered_at": row.get("touroku_date"),
        "updated_at": row.get("kousin_date"),
    }


def normalize_pg_access_match_row(row: dict[str, Any]) -> dict[str, Any]:
    status_code = str(row.get("status", "") or "").strip()
    shiji_no_text = str(row.get("s_siji_no_text", "") or "").strip()
    return {
        "furnace": str(row.get("furnace_name", "") or "").strip(),
        "ro_no": str(row.get("ro_no", "") or "").strip(),
        "ro_name": str(row.get("ro_nm", "") or "").strip(),
        "match_status": status_code,
        "status_kind": "running" if status_code == RUNNING_STATUS_CODE else "finished",
        "pit_s_nippou_no": row.get("pit_s_nippou_no"),
        "instruction_no_text": shiji_no_text or "-",
        "shiji_no_text": shiji_no_text,
        "start_time_text": format_oracle_time_text(row.get("started_at")),
        "started_at": row.get("started_at"),
        "ended_at": row.get("ended_at"),
        "registered_at": row.get("touroku_date"),
        "updated_at": row.get("kousin_date"),
    }


def fetch_current_pg_furnace_statuses() -> list[dict[str, Any]]:
    query = ensure_readonly_query(PG_FURNACE_STATUS_QUERY)
    with get_oracle_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            column_names = [column[0].lower() for column in cursor.description]
            rows = [dict(zip(column_names, row)) for row in cursor.fetchall()]
    return [normalize_pg_status_row(row) for row in rows]


def fetch_recent_pg_furnace_batches_for_access_match() -> list[dict[str, Any]]:
    query = ensure_readonly_query(PG_FURNACE_ACCESS_MATCH_QUERY)
    with get_oracle_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(query)
            column_names = [column[0].lower() for column in cursor.description]
            rows = [dict(zip(column_names, row)) for row in cursor.fetchall()]
    return [normalize_pg_access_match_row(row) for row in rows]
