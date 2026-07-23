"""Phi-3:mini agentic layer via Ollama.

Uses Ollama's native /api/chat endpoint (no extra SDK). Point [ollama].host in
secrets at wherever Ollama runs. To swap to any OpenAI-compatible server, call
its /v1/chat/completions endpoint instead.

The agentic text-to-SQL uses a guarded two-call pattern rather than native tool
calling, which is far more reliable with small local models like phi3:mini:
  1. Ask the model for a single MySQL SELECT.
  2. Validate it (SELECT-only, whitelisted tables, enforced LIMIT).
  3. Execute via the READ-ONLY engine.
  4. Ask the model to answer the question from the returned rows.
"""
from __future__ import annotations

import json
import re

import requests
import streamlit as st

from db import discover_schema, queryable_tables, run_query

def _cfg(key: str, default: str) -> str:
    """Read an optional [ollama] setting from secrets.toml."""
    try:
        return st.secrets["ollama"][key]
    except Exception:
        return default


# Default chat model. Override in secrets.toml:
#   [ollama]
#   model = "phi3:mini"
#   sql_model = "qwen2.5-coder:7b"   # much stronger at text-to-SQL
MODEL = _cfg("model", "phi3:mini")
SQL_MODEL = _cfg("sql_model", MODEL)

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|"
    r"revoke|call|merge|into|load_file|outfile|information_schema|sleep)\b",
    re.IGNORECASE,
)


def _host() -> str:
    return st.secrets.get("ollama", {}).get("host", "http://localhost:11434")


def chat(
    messages: list[dict],
    temperature: float = 0.2,
    num_predict: int | None = None,
    timeout: int = 600,
    model: str | None = None,
) -> str:
    options = {"temperature": temperature}
    if num_predict:
        options["num_predict"] = num_predict
    r = requests.post(
        f"{_host()}/api/chat",
        json={
            "model": model or MODEL,
            "messages": messages,
            "stream": False,
            "keep_alive": "30m",  # keep model in RAM so later calls are fast
            "options": options,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["message"]["content"].strip()


FEATURED_TABLES = ["vw_submission_analytics", "stg_submission", "pdf_submission"]

# Words that mean "the uploaded application" rather than "the portfolio".
_PDF_HINTS = (
    "applicant", "application", "nature of business", "declaration", "signed",
    "mailing", "website", "nonprofit", "chapters", "handbook", "policy manual",
    "coverage desired", "purchased", "requested limit", "phi", "pii",
    "fiscal year", "total assets", "total revenue", "cyber", "fiduciary",
    "crime", "epl", "d&o", "do coverage", "board", "volunteers", "encrypted",
)


def _route(question: str) -> str:
    """Pick the ONE table that should answer this question.

    Routing beats prompting here: by showing the model a single table we make
    an invalid cross-table JOIN structurally impossible.
    """
    schema = discover_schema()
    q = question.lower()
    if "pdf_submission" in schema and any(h in q for h in _PDF_HINTS):
        return "pdf_submission"
    for candidate in ("vw_submission_analytics", "stg_submission"):
        if candidate in schema:
            return candidate
    return "pdf_submission" if "pdf_submission" in schema else next(iter(schema), "")


def _columns_for(table: str) -> str:
    cols = discover_schema().get(table, [])
    return f"{table}({', '.join(cols)})"


def _schema_hint() -> str:
    """Curated hint: feature the two surfaces the assistant should actually use
    (with full columns), and list the remaining ETL/dimension tables by name so
    the small model isn't overwhelmed but can still reach them if asked."""
    schema = discover_schema()
    if not schema:
        return "(no tables available)"
    lines = []
    featured = [t for t in FEATURED_TABLES if t in schema]
    for t in featured:
        lines.append(f"- {t}({', '.join(schema[t])})")
    others = sorted(t for t in schema if t not in featured)
    if others:
        lines.append(
            "Other tables (raw/staging/dimension layers; usually NOT needed — "
            "only query them if the question names them): " + ", ".join(others)
        )
    return "\n".join(lines)


def _extract_sql(text_out: str) -> str:
    # Drop markdown fences.
    text_out = re.sub(r"```(?:sql)?", "", text_out, flags=re.IGNORECASE).strip()
    # Start at the first SELECT (skip any preamble the model added).
    m = re.search(r"select\b", text_out, re.IGNORECASE)
    sql = text_out[m.start():] if m else text_out
    # Keep only the FIRST statement: cut at the first semicolon. This collapses
    # "SELECT ...; SELECT ..." or "SELECT ...; explanation" down to one query,
    # so the multiple-statements guard never trips on a small-model quirk.
    sql = sql.split(";", 1)[0]
    # Small models often append a prose explanation on a new paragraph with no
    # semicolon. Drop anything after the first blank line.
    sql = re.split(r"\n\s*\n", sql, 1)[0]
    return sql.strip()


def _validate_sql(sql: str) -> str:
    low = sql.lower()
    if not low.startswith("select"):
        raise ValueError("Only SELECT queries are allowed.")
    if ";" in sql:
        raise ValueError("Multiple statements are not allowed.")
    if FORBIDDEN.search(sql):
        raise ValueError("Query contains a forbidden keyword.")
    tables = queryable_tables()
    if not tables:
        raise ValueError(
            "Schema discovery returned NO tables. The read-only DB user likely "
            "has no SELECT privilege on this database (information_schema only "
            "shows tables the user can access). Check [mariadb] ro_user in "
            "secrets.toml and run: GRANT SELECT ON <db>.* TO 'readonly_user'@'%'; "
            "FLUSH PRIVILEGES;"
        )
    if not any(t.lower() in low for t in tables):
        raise ValueError(
            f"Query does not reference a known table.\n"
            f"Model wrote: {sql}\n"
            f"Known tables: {', '.join(sorted(tables))}"
        )
    if "limit" not in low:
        sql += " LIMIT 500"
    return sql


def text_to_sql(question: str, error_hint: str = "") -> str:
    """Generate ONE SELECT against a SINGLE routed table.

    Routing to one table (rather than describing the whole warehouse) is what
    makes this reliable with a small local model: it cannot join tables it
    was never shown.
    """
    table = _route(question)
    if not table:
        raise ValueError("No tables available to query.")

    if table == "pdf_submission":
        context = (
            "This table holds ONE uploaded insurance application (a single row). "
            "Questions about 'the applicant' are answered by selecting the "
            "relevant columns with NO WHERE clause and NO aggregation."
        )
    else:
        context = (
            "This is the submission portfolio, one row per submission, already "
            "denormalised. Bound = 1 if bound else 0, so bind rate = AVG(Bound) "
            "and bound count = SUM(Bound). Money and count columns are already "
            "numeric — aggregate directly, never CAST."
        )

    sys = (
        "You translate an underwriter's question into ONE MySQL SELECT query.\n"
        "Output ONLY the SQL: no explanation, no markdown fences, no semicolon.\n\n"
        f"You may query EXACTLY ONE table:\n{_columns_for(table)}\n\n"
        f"{context}\n\n"
        "Hard rules:\n"
        f"1. FROM must be `{table}`. It is the only table that exists for you.\n"
        "2. NEVER write JOIN. NEVER reference any other table.\n"
        "3. Use column names EXACTLY as listed. Never invent or abbreviate them.\n"
        "4. Do NOT invent WHERE filters or literal values not in the question.\n"
        "5. For 'by X' use GROUP BY; for 'top/highest/lowest' use ORDER BY + LIMIT.\n"
        "6. Valid MySQL only — no prose inside the query. Max 500 rows."
    )
    msgs = [{"role": "system", "content": sys},
            {"role": "user", "content": question}]
    if error_hint:
        msgs.append({
            "role": "user",
            "content": (
                f"Your previous query failed with this database error:\n"
                f"{error_hint}\n"
                f"Rewrite it. Use only `{table}` and only its listed columns."
            ),
        })
    raw = chat(msgs, temperature=0.0, model=SQL_MODEL)
    return _validate_sql(_extract_sql(raw))


def answer_from_data(question: str, sql: str, rows_md: str) -> str:
    sys = (
        "You are an analytics assistant for specialty-insurance underwriters. "
        "Answer the question using ONLY the data rows provided. Be concise and "
        "quantitative, and tie findings to underwriting outcomes (hit ratio, "
        "risk selection, turnaround, loss ratio). If the data is insufficient, "
        "say so plainly."
    )
    user = f"Question: {question}\n\nSQL used:\n{sql}\n\nResult rows:\n{rows_md}"
    return chat(
        [{"role": "system", "content": sys},
         {"role": "user", "content": user}],
    )


def ask(question: str) -> dict:
    """Full agentic turn. Returns dict with sql, rows (df), answer, or error.

    If the database rejects the generated SQL, the error is fed back to the
    model for exactly one correction attempt before giving up.
    """
    try:
        sql = text_to_sql(question)
    except Exception as e:
        return {"error": f"Could not build a safe query: {e}"}

    try:
        df = run_query(sql, readonly=True)
    except Exception as first_error:
        # One self-correction attempt using the real database error.
        try:
            sql = text_to_sql(question, error_hint=str(first_error)[:500])
            df = run_query(sql, readonly=True)
        except Exception as e:
            return {"sql": sql, "error": f"Query failed after retry: {e}"}

    rows_md = df.head(50).to_markdown(index=False) if not df.empty else "(no rows)"
    answer = answer_from_data(question, sql, rows_md)
    return {"sql": sql, "rows": df, "answer": answer}


def recommend(stats_md: str) -> str:
    sys = (
        "You are an analytics advisor to specialty-insurance underwriters and "
        "management. Given portfolio statistics, produce 3-5 concrete, "
        "prioritised recommendations. Each: one bold headline plus one sentence "
        "of rationale tied to a business outcome (loss ratio, hit ratio, "
        "appetite, turnaround). Do NOT invent numbers not present in the data."
    )
    return chat(
        [{"role": "system", "content": sys},
         {"role": "user", "content": f"Portfolio statistics:\n{stats_md}"}],
        temperature=0.3,
    )


def _parse_json(out: str) -> dict:
    out = re.sub(r"```(?:json)?", "", out).strip()
    try:
        return json.loads(out[out.find("{"): out.rfind("}") + 1])
    except Exception:
        return {}


def extract_all(raw_text: str) -> dict:
    """Open extraction: let phi3:mini find every labelled field it can."""
    sys = (
        "Extract every labelled field and its value from this submission "
        "document. Return ONLY a JSON object mapping snake_case field names to "
        "values. Use null where a value is missing. No prose, no markdown."
    )
    out = chat(
        [{"role": "system", "content": sys},
         {"role": "user", "content": raw_text[:6000]}],
        temperature=0.0,
        num_predict=1024,
    )
    return _parse_json(out)


def extract_fields(raw_text: str, fields: list[str]) -> dict:
    """Pull named fields from a document. Pass ['all'] to extract everything."""
    if not fields or [f.lower() for f in fields] == ["all"]:
        return extract_all(raw_text)
    sys = (
        "Extract the requested fields from the document text. "
        "Return ONLY a JSON object with exactly these keys: "
        f"{fields}. Use null if a field is absent. No prose, no markdown."
    )
    out = chat(
        [{"role": "system", "content": sys},
         {"role": "user", "content": raw_text[:6000]}],
        temperature=0.0,
        num_predict=512,
    )
    return _parse_json(out) or {f: None for f in fields}
