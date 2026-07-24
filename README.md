# Submission Analytics & Underwriting Assistant

A local-only analytics platform for specialty insurance underwriting. Ingests
submission documents, stores them alongside a portfolio warehouse, and answers
underwriting questions in plain English.

Streamlit · MariaDB · Ollama. No data leaves the host.

## Tabs

- **Intake** — upload a D&O application PDF, parsed into 111 fields, reviewed, loaded
- **Insights** — profile any table (rows, nulls, dtypes, stats)
- **Portfolio** — charts over the warehouse, plus a Power BI slot
- **Assistant** — natural-language questions answered with generated SQL

## How it works

**Extraction.** The D&O application is a fixed template, so it's parsed with rules
and regex — 105/111 fields, deterministic and auditable. The LLM is reserved for
unstructured text. Either way a human reviews an editable grid before commit, and
every load writes a key/value CSV as an audit trail.

**Storage.** `pdf_submission` holds the raw application (all VARCHAR, document text
preserved). The warehouse is a star schema — `fact_submission` (2.5M rows) plus seven
dimensions — flattened into `vw_submission_analytics` for querying and Power BI.

**Assistant.** Each question is routed to one table, the model generates a single
`SELECT`, it's validated (SELECT only, forced LIMIT), then executed as a read-only
database user. Answers come only from the returned rows.

## Setup

```sql
-- MariaDB
GRANT SELECT, INSERT, CREATE ON brp_case_study.* TO 'app_user'@'%';
GRANT SELECT ON brp_case_study.* TO 'readonly_user'@'%';
FLUSH PRIVILEGES;
```

Run `create_pdf_submission.sql`, then `create_analytics_view.sql`.

Create `.streamlit/secrets.toml` (one `[mariadb]`, one `[ollama]` section — gitignore it):

```toml
[mariadb]
host = "127.0.0.1"
port = 3306
database = "brp_case_study"
user = "app_user"
password = "..."
ro_user = "readonly_user"
ro_password = "..."

[ollama]
host = "http://localhost:11434"
sql_model = "qwen2.5-coder:7b"
```

Then:

```bash
pip install -r requirements.txt
ollama pull phi3:mini && ollama pull qwen2.5-coder:7b
ollama run phi3:mini "ready"     # pre-warm, separate terminal
streamlit run app.py
```

## Sample questions

Portfolio : *total premium by operating state · average premium by product · which
broker has the lowest bind rate*

Application : *nature of business for the applicant · which coverages were purchased
· who signed the declaration*

## Limitations

- Small local models occasionally write odd SQL; `qwen2.5-coder:7b` is much better
- CPU inference is slow (two model calls per answer)
- `pdf_submission` is all VARCHAR by design — cast for numeric comparisons
- No authentication; the Intake tab writes to the database
- Streamlit is stateful, so serverless hosts (Vercel etc.) can't run it

See `BUILD_NOTES.txt` for the full build log.
