"""Database access for the underwriting platform.

Two engines:
- app engine (read/write) for ingestion
- read-only engine for the agentic chat / recommendations, so the LLM
  can never mutate data even if a guard is bypassed.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Tables the INGESTION path may WRITE to. Keep this tight — writes are
# dangerous. Reading is governed separately (see discover_schema below), and
# happens only through the read-only engine.
WRITABLE_TABLES = ["raw_submission", "pdf_submission"]

# Backwards-compat alias: older code referenced ALLOWED_TABLES for writes.
ALLOWED_TABLES = WRITABLE_TABLES


@st.cache_data(ttl=300, show_spinner=False)
def discover_schema() -> dict[str, list[str]]:
    """Discover every table and view in the current database, with columns.

    Read-only, one round trip via information_schema. Cached for 5 minutes so
    it isn't re-run on every question. New tables appear automatically.
    """
    db = st.secrets["mariadb"]["database"]
    sql = (
        "SELECT table_name, column_name "
        "FROM information_schema.columns "
        "WHERE table_schema = :db "
        "ORDER BY table_name, ordinal_position"
    )
    def _fetch(readonly: bool) -> pd.DataFrame:
        engine = get_engine(readonly=readonly)
        with engine.connect() as conn:
            return pd.read_sql(text(sql), conn, params={"db": db})

    # Prefer the read-only user. information_schema only exposes tables the
    # connecting user has privileges on, so if that user is under-granted we
    # would silently see an empty database -- fall back to the app engine.
    try:
        df = _fetch(readonly=True)
    except Exception:
        df = pd.DataFrame()
    if df.empty:
        df = _fetch(readonly=False)

    schema: dict[str, list[str]] = {}
    # information_schema may return column names capitalised differently across
    # MariaDB versions; normalise access.
    df.columns = [c.lower() for c in df.columns]
    for _, row in df.iterrows():
        schema.setdefault(row["table_name"], []).append(row["column_name"])
    return schema


def queryable_tables() -> list[str]:
    """All table/view names the read-only assistant may SELECT from."""
    return list(discover_schema().keys())


def _url(user_key: str, pw_key: str) -> str:
    s = st.secrets["mariadb"]
    return (
        f"mysql+pymysql://{s[user_key]}:{s[pw_key]}"
        f"@{s['host']}:{s.get('port', 3306)}/{s['database']}"
    )


@st.cache_resource
def get_engine(readonly: bool = False) -> Engine:
    if readonly:
        return create_engine(_url("ro_user", "ro_password"), pool_pre_ping=True)
    return create_engine(_url("user", "password"), pool_pre_ping=True)


def run_query(sql: str, readonly: bool = True) -> pd.DataFrame:
    engine = get_engine(readonly=readonly)
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


def list_tables() -> list[str]:
    try:
        df = run_query("SHOW TABLES")
        found = df.iloc[:, 0].tolist()
        return [t for t in found if t in ALLOWED_TABLES] or ALLOWED_TABLES
    except Exception:
        return ALLOWED_TABLES


def load_dataframe(df: pd.DataFrame, table: str, if_exists: str = "append") -> int:
    """Load a DataFrame into a table using the read/write engine.

    if_exists: 'append' (default) or 'replace'. For real upserts, load into a
    staging table and run INSERT ... ON DUPLICATE KEY UPDATE (see README).
    """
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Table '{table}' not in ALLOWED_TABLES")
    engine = get_engine(readonly=False)
    df.to_sql(table, engine, if_exists=if_exists, index=False)
    return len(df)


def table_overview(table: str) -> dict:
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Table '{table}' not in ALLOWED_TABLES")
    df = run_query(f"SELECT * FROM `{table}` LIMIT 5000")
    return {
        "sample": df,
        "rows_sampled": len(df),
        "dtypes": df.dtypes.astype(str),
        "nulls": df.isna().sum(),
        "describe": df.describe(include="all").transpose(),
    }
