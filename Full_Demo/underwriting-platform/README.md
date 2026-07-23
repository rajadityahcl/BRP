# Submission Analytics & Underwriting Assistant

A Streamlit MVP with four tabs — Ingestion, Insights, Visualisation, and
Recommendations + agentic chat — over a MariaDB backend, using **phi3:mini via
Ollama** as the local LLM.

## Files
- `app.py` — Streamlit UI, four tabs
- `db.py` — SQLAlchemy engines (read/write + read-only) and helpers
- `llm.py` — phi3:mini via Ollama; guarded text-to-SQL + recommendations
- `ingestion.py` — CSV/PDF parsing, validation, load to MariaDB
- `requirements.txt`, `.streamlit/secrets.toml.example`

## How the agentic chat stays safe
Small local models can't be trusted with native tool-calling, so the chat uses a
guarded two-call pattern in `llm.ask()`:
1. phi3:mini writes one MySQL `SELECT`.
2. `_validate_sql()` rejects anything that isn't a single SELECT, contains a
   forbidden keyword, or touches a table outside `ALLOWED_TABLES`; a `LIMIT` is
   forced if missing.
3. The query runs on a **read-only DB user** (the real backstop).
4. phi3:mini writes the answer from the returned rows only.

## Setup (local)

1. **Install + run Ollama, pull the model**
   ```bash
   # install from https://ollama.com then:
   ollama pull phi3:mini
   ollama serve            # serves on http://localhost:11434
   ```

2. **Create the DB users** (run against your MariaDB)
   ```sql
   CREATE USER 'app_user'@'%'      IDENTIFIED BY 'app_password';
   GRANT SELECT, INSERT, CREATE ON underwriting.* TO 'app_user'@'%';

   CREATE USER 'readonly_user'@'%' IDENTIFIED BY 'readonly_password';
   GRANT SELECT ON underwriting.* TO 'readonly_user'@'%';
   FLUSH PRIVILEGES;
   ```

3. **Configure secrets**
   ```bash
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   # edit with your host, db name, and the two users above
   ```

4. **Install and run**
   ```bash
   pip install -r requirements.txt
   streamlit run app.py
   ```

## Adapting to your data
- Edit `ALLOWED_TABLES` in `db.py` as you add products (`submission_productB`, …).
- The Recommendations tab currently feeds phi3:mini only row counts. Add real
  aggregates (status mix, hit ratio, broker breakdown, avg limit, quote
  turnaround) where the comment marks it in `app.py` for useful suggestions.
- For true upserts instead of append, load into a staging table then:
  ```sql
  INSERT INTO submission_productA (...) SELECT ... FROM staging
  ON DUPLICATE KEY UPDATE col = VALUES(col);
  ```

## Deployment (free MVP)

**Important:** phi3:mini needs ~4 GB RAM to run under Ollama, so Streamlit
Community Cloud (1 GB limit) **cannot host the model**. Two workable free paths:

**Option A — everything local (simplest).** Run Ollama + MariaDB + Streamlit on
your own machine. Zero cost, fully private. Best while building.

**Option B — one free cloud VM.** Oracle Cloud *Always Free* offers an Ampere
ARM instance (up to 4 cores / 24 GB RAM) that comfortably runs Ollama +
phi3:mini + Streamlit + MariaDB together for $0. Caveat: free ARM capacity is
region-dependent and can be hard to grab; retry across availability domains.
   ```bash
   # on the VM
   curl -fsSL https://ollama.com/install.sh | sh && ollama pull phi3:mini
   sudo apt install mariadb-server -y
   pip install -r requirements.txt
   streamlit run app.py --server.port 8501 --server.address 0.0.0.0
   ```

**Split option.** Deploy only the UI on Streamlit Community Cloud and point
`[ollama].host` at an Ollama instance running elsewhere (your VM). Keep the DB
on a free managed MySQL/MariaDB tier (Aiven, TiDB Serverless, or Layerbase).

## Hardening later
- Replace the regex SQL guard with `sqlglot` parsing to verify statement type
  and table references structurally.
- Add auth (Streamlit's native auth or a reverse proxy) before real data.
- Move ingestion to a scheduled GitHub Action or cron worker for unattended runs.
