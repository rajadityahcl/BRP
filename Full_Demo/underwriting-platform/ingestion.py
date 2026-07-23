"""Ingestion Layer: documents / CSVs -> validated DataFrame -> MariaDB."""
from __future__ import annotations

import os
from datetime import datetime

import pandas as pd

from db import load_dataframe

CSV_DIR = "csv_exports"


def save_keyvalue_csv(df: pd.DataFrame, source_file: str) -> str:
    """Write the single extracted row as a two-column key/value CSV (audit trail).

    Returns the path to the written file.
    """
    os.makedirs(CSV_DIR, exist_ok=True)
    kv = df.iloc[[0]].T.reset_index()
    kv.columns = ["field", "value"]
    stem = os.path.splitext(os.path.basename(source_file))[0]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(CSV_DIR, f"{stem}_{ts}.csv")
    kv.to_csv(path, index=False)
    return path


def read_csv(file) -> pd.DataFrame:
    return pd.read_csv(file)


def read_pdf_text(file) -> str:
    import pdfplumber

    parts = []
    with pdfplumber.open(file) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def basic_validate(df: pd.DataFrame) -> list[str]:
    issues = []
    if df.empty:
        issues.append("File has no rows.")
    dup = df.columns[df.columns.duplicated()].tolist()
    if dup:
        issues.append(f"Duplicate columns: {dup}")
    empty_cols = [c for c in df.columns if df[c].isna().all()]
    if empty_cols:
        issues.append(f"Fully empty columns: {empty_cols}")
    return issues


def commit(df: pd.DataFrame, table: str, mode: str) -> int:
    return load_dataframe(df, table, if_exists=mode)
