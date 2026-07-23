# Submission Analytics & Underwriting Assistant

A local-only analytics platform for specialty insurance underwriting. Ingests
submission documents, stores them alongside a portfolio warehouse, and lets an
underwriter query everything in plain English.

Built as a case study for a specialty-lines MGU. Nothing leaves the host machine —
the database and the language model both run locally.

![Solution design](solution_design.png)

---

## What it does

| Tab | Purpose |
|---|---|
| **Intake** | Upload a D&O application PDF or CSV. Parsed into structured fields, reviewed by a human, loaded to MariaDB. |
| **Insights** | Profile any table — row counts, null counts, dtypes, summary statistics. |
| **Portfolio** | Charts over the submission warehouse, plus a Power BI embed slot. |
| **Assistant** | Natural-language questions answered with guarded, generated SQL. |

---

## Architecture

```
PDF / CSV  →  Deterministic parser  →  Human review  →  MariaDB
                    (or LLM for                          ├── pdf_submission
                     unstructured text)                  └── warehouse
                                                              raw → stg → qrt
                                                              fact + 7 dims
                                                              ↓
                                                     vw_submission_analytics
                                                              ↓
                                              Streamlit tabs · Power BI
```

### Two extraction strategies, on purpose

The D&O application is a **fixed template**, so `parsers.py` reads it with rules and
regex — 105 of 111 fields on the real test PDF, deterministically. (The six blanks
are genuine: Fiduciary and Crime weren't purchased, so there is no carrier data.)

An LLM was tried first and rejected: it timed out on CPU cold-start, and returned
different answers for the same document across runs. For a fixed form that is the
wrong tool.

- **Fixed forms** → deterministic parser. Repeatable, fast, auditable.
- **Unstructured text** → LLM.
- **Either path** → editable review grid before anything is committed, plus a
  key/value CSV written per load as an audit trail.

### The semantic layer

The warehouse is a Kimball star schema: `fact_submission` (2.5M rows) joined to
seven dimensions. Small language models are unreliable at star-schema joins, so
`create_analytics_view.sql` builds **`vw_submission_analytics`** — the fact table
pre-joined to every dimension as one wide flat table.

Measures are already numeric (`CurrentPremium`, `CurrentLimit`, `AnnualRevenue`,
`Bound`), so aggregates need no casting. Bind rate is `AVG(Bound)`.

Power BI consumes the same view, so one definition serves both.

### How the assistant stays safe

Small local models can't be trusted with native tool-calling, so `llm.ask()` uses a
routed, validated pipeline:

1. **Route to one table.** The question is classified before any SQL is generated,
   and the model is shown a single table's schema. It cannot join tables it never
   saw — this eliminated the largest class of failure.
2. **Generate one `SELECT`.**
3. **Validate.** Rejects non-SELECT statements, forbidden keywords, unknown tables;
   forces a `LIMIT`. Multi-statement output is reduced to the first statement.
4. **Execute as `readonly_user`.** The real backstop: writes are impossible at the
   database level, not merely discouraged in code.
5. **Answer from returned rows only.** On a database error, the actual message is
   fed back for exactly one self-correction attempt.

Schema is discovered at runtime from `information_schema`, so new tables and views
appear automatically — nothing is hardcoded.

---

## Files

| File | Role |
|---|---|
| `app.py` | Streamlit UI, four tabs |
| `theme.py` | Design system — CSS and the Plotly template |
| `db.py` | SQLAlchemy engines (read-write + read-only), schema discovery |
| `llm.py` | Ollama client, routing, text-to-SQL, validation, recommendations |
| `ingestion.py` | CSV/PDF reading, validation, loading, CSV audit export |
| `parsers.py` | Deterministic D&O application parser (111 columns) |
| `create_pdf_submission.sql` | Creates `pdf_submission` |
| `create_analytics_view.sql` | Creates `vw_submission_analytics` |
| `solution_design.svg` / `.png` | Architecture diagram |
| `BUILD_NOTES.txt` | High-level build log |

---

## Setup

### 1. Database

```sql
CREATE USER 'app_user'@'%' IDENTIFIED BY 'change_me';
GRANT SELECT, INSERT, CREATE ON brp_case_study.* TO 'app_user'@'%';

CREATE USER 'readonly_user'@'%' IDENTIFIED BY 'change_me_too';
GRANT SELECT ON brp_case_study.* TO 'readonly_user'@'%';
FLUSH PRIVILEGES;
```

The `GRANT` on `readonly_user` matters more than it looks: `information_schema` only
exposes tables the connecting user can see, so without it schema discovery returns
nothing and every question fails.

Then run, in order:

1. `create_pdf_submission.sql`
2. `create_analytics_view.sql`
3. Verify: `SELECT COUNT(*) FROM vw_submission_analytics;`

### 2. Secrets

Create `.streamlit/secrets.toml` — **exactly one of each section header**. A
duplicated section makes the whole file unparseable and produces a misleading
`KeyError` at startup.

```toml
[mariadb]
host = "127.0.0.1"          # avoids name resolution entirely
port = 3306
database = "brp_case_study"
user = "app_user"
password = "change_me"
ro_user = "readonly_user"
ro_password = "change_me_too"

[ollama]
host = "http://localhost:11434"
sql_model = "qwen2.5-coder:7b"   # optional; omit to use the default model

[powerbi]
embed_url = ""              # must be a publish-to-web URL containing /view?r=
```

Add this file to `.gitignore` before pushing anywhere.

### 3. Models

```bash
ollama pull phi3:mini
ollama pull qwen2.5-coder:7b     # substantially better at SQL
ollama list
```

`sql_model` is used only for SQL generation; conversational replies stay on the
lighter model.

### 4. Python

```bash
python -m venv venv
venv\Scripts\activate            # Windows
pip install -r requirements.txt
```

### 5. Run

```bash
ollama run phi3:mini "ready"     # pre-warm in a separate terminal
streamlit run app.py
```

Pre-warming matters. A cold model loads several GB from disk on first call, which
previously caused request timeouts.

---

## Verifying a deployment

1. Masthead renders navy with a gold rule → theme loaded.
2. **Assistant** tab → expand *Schema the assistant can see* → confirm
   `vw_submission_analytics` is listed and no warning appears.
3. Ask *"Show total premium by operating state."*
4. Ask *"What's the nature of business for the applicant?"* → should produce a plain
   `SELECT` against `pdf_submission` with no join.
5. **Portfolio** tab → build a chart → confirm the themed palette.
6. **Intake** tab → upload the D&O PDF → 105/111 fields → load succeeds.

### Questions that work reliably

Portfolio (`vw_submission_analytics`):
- Show total premium by operating state
- What's the average premium by product?
- Which broker has the lowest bind rate?
- How many submissions bound last quarter?
- What's the bind rate by industry?

Application (`pdf_submission`):
- What's the nature of business for the applicant?
- Which coverages did the applicant purchase?
- Who signed the declaration and on what date?

If a question misfires, naming columns explicitly usually resolves it — e.g.
"average CurrentPremium grouped by ProductCode".

---

## Design

The interface follows a *declarations page* direction drawn from insurance's own
visual language rather than generic dashboard styling: deep navy ground, a gold
accent used only where a seal or rule would appear on a policy document, and
monospace for every figure — because premium and limit schedules are set that way so
digits align in columns. Sections are numbered because the workflow genuinely is a
sequence.

Streamlit does not publish stable CSS class names. `theme.py` targets `data-testid`
and `data-baseweb` attributes, which are the most durable hooks available, but an
upgrade could still break individual rules — degradation is graceful (a single
component reverts to default styling). **Pin your Streamlit version** before any
demo:

```bash
pip freeze > requirements.txt
```

---

## Known limitations

- **Model size.** Routing and the semantic view raise the floor considerably, but a
  3.8B model writing SQL will occasionally produce something odd. `qwen2.5-coder:7b`
  is markedly better and is a one-line config change.
- **CPU inference is slow.** Each answer is two model calls. A GPU or a hosted
  inference API would remove this.
- **`pdf_submission` is entirely VARCHAR** by design — raw document text is preserved
  for audit — so numeric comparisons on that table require casting. The warehouse
  side is properly typed.
- **No authentication.** Acceptable on localhost. Not acceptable if exposed: the
  Intake tab writes to the database.
- **Power BI publish-to-web is public** with no authentication. Fine for synthetic
  demo data; production would require Pro with Entra ID and row-level security, or
  embedding on a Fabric capacity.

---

## Deployment

Streamlit is a stateful, long-lived server holding a WebSocket per session, so
serverless platforms (Vercel, Netlify, Lambda) cannot host it.

| Approach | Trade-off |
|---|---|
| **Cloudflare Tunnel** | `cloudflared tunnel --url http://localhost:8501` — public URL in seconds, nothing to migrate, but your machine must stay awake |
| **Streamlit Community Cloud** | Free and purpose-built, but cannot run Ollama or MariaDB — both must move to hosted services |
| **Oracle Cloud Always Free** | A1.Flex 4 OCPU / 24 GB runs the entire stack 24/7; expect ARM capacity contention |

Add an access gate before exposing any of these publicly, and rotate the default
passwords.

---

## Next steps

- Move `text_to_sql` fully onto `qwen2.5-coder:7b` and re-test the question set
- Replace regex SQL validation with `sqlglot` parsing
- Parsers for further templates (EPL, Cyber, Property)
- `INSERT ... ON DUPLICATE KEY UPDATE` so re-uploads update rather than duplicate
- Richer aggregates in Recommendations — hit ratio, status mix, broker breakdown
- Authentication and `systemd` units for VM deployment
