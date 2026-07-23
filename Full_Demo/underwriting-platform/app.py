import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

import db
import ingestion
import llm
import parsers

st.set_page_config(page_title="Underwriting Analytics Platform", layout="wide")
st.title("Submission Analytics & Underwriting Assistant")

tab_ingest, tab_insights, tab_viz, tab_reco = st.tabs(
    ["1 · Ingestion", "2 · Insights", "3 · Visualisation", "4 · Recommendations & Chat"]
)

# ---------------------------------------------------------------- Ingestion
with tab_ingest:
    st.subheader("Data Processing & Ingestion")
    target = st.selectbox("Target table", db.ALLOWED_TABLES)
    try:
        target_cols = db.run_query(f"SELECT * FROM `{target}` LIMIT 1").columns.tolist()
    except Exception:
        target_cols = []

    up = st.file_uploader("Upload CSV or PDF", type=["csv", "pdf"])
    if up:
        df = pd.DataFrame()
        if up.name.lower().endswith(".csv"):
            df = ingestion.read_csv(up)
        else:
            raw = ingestion.read_pdf_text(up)
            st.text_area("Extracted text (preview)", raw[:2000], height=160)

            if target == "pdf_submission":
                # Fixed-template D&O application -> parse deterministically.
                st.caption("Parsed with the rule-based D&O application parser "
                           "(reliable for this fixed form; no LLM needed).")
                record = parsers.parse_do_application(raw)
                record["source_file"] = up.name
                df = pd.DataFrame([record])
            else:
                fields_str = st.text_input(
                    "Fields to extract (comma-separated, or 'all')",
                    value=", ".join(target_cols),
                    help="List the columns to pull, or type 'all' to let phi3:mini "
                         "find every field. Listed fields are faster and more accurate.",
                )
                fields = [f.strip() for f in fields_str.split(",") if f.strip()]
                if st.button("Extract fields with phi3:mini") and fields:
                    with st.spinner(
                        "Extracting with phi3:mini — the first run loads the model, "
                        "so it can take a minute. Later runs are fast."
                    ):
                        st.session_state["extracted"] = llm.extract_fields(raw, fields)
                if st.session_state.get("extracted"):
                    df = pd.DataFrame([st.session_state["extracted"]])
                    if "source_file" in target_cols and "source_file" not in df.columns:
                        df["source_file"] = up.name

        if not df.empty:
            # Keep only columns that exist in the target table, so an unmapped
            # field can never crash the insert.
            if target_cols:
                dropped = [c for c in df.columns if c not in target_cols]
                if dropped:
                    st.caption("Ignoring fields not in the target table: "
                               + ", ".join(dropped))
                keep = [c for c in df.columns if c in target_cols]
                if keep:
                    df = df[keep]

            st.write("Review & edit before loading")
            df = st.data_editor(df, use_container_width=True, num_rows="dynamic")
            for issue in ingestion.basic_validate(df):
                st.warning(issue)
            mode = st.radio("Load mode", ["append", "replace"], horizontal=True)
            if st.button("Load into MariaDB", type="primary"):
                try:
                    # Single-row extractions (PDFs) also get a key/value CSV audit file.
                    csv_path = None
                    if len(df) == 1:
                        csv_path = ingestion.save_keyvalue_csv(df, up.name)
                    n = ingestion.commit(df, target, mode)
                    msg = f"Loaded {n} row(s) into {target}."
                    if csv_path:
                        msg += f" Key/value CSV saved to {csv_path}."
                    st.success(msg)
                    if csv_path:
                        with open(csv_path, "rb") as fh:
                            st.download_button(
                                "Download key/value CSV", fh,
                                file_name=csv_path.split("/")[-1], mime="text/csv",
                            )
                    st.session_state.pop("extracted", None)
                except Exception as e:
                    st.error(f"Load failed: {e}")

# ---------------------------------------------------------------- Insights
with tab_insights:
    st.subheader("Data Insights")
    table = st.selectbox("Table", db.list_tables(), key="ins_tbl")
    if st.button("Profile table"):
        try:
            ov = db.table_overview(table)
            c1, c2, c3 = st.columns(3)
            c1.metric("Rows sampled", ov["rows_sampled"])
            c2.metric("Columns", len(ov["dtypes"]))
            c3.metric("Cols with nulls", int((ov["nulls"] > 0).sum()))
            st.write("Column types")
            st.dataframe(ov["dtypes"])
            st.write("Null counts")
            st.dataframe(ov["nulls"])
            st.write("Summary")
            st.dataframe(ov["describe"])
        except Exception as e:
            st.error(e)

# ---------------------------------------------------------------- Viz
with tab_viz:
    st.subheader("Visualisation")
    table = st.selectbox("Table", db.list_tables(), key="viz_tbl")
    try:
        df = db.run_query(f"SELECT * FROM `{table}` LIMIT 5000")
        cols = df.columns.tolist()
        if cols:
            cat = st.selectbox("Category / X axis", cols)
            num_cols = df.select_dtypes("number").columns.tolist()
            val = st.selectbox("Value (blank = count)", ["<count>"] + num_cols)
            if val == "<count>":
                plot = df[cat].value_counts().reset_index()
                plot.columns = [cat, "count"]
                fig = px.bar(plot, x=cat, y="count")
            else:
                fig = px.bar(df.groupby(cat)[val].sum().reset_index(), x=cat, y=val)
            st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(e)

    st.divider()
    pbi = st.secrets.get("powerbi", {}).get("embed_url", "")
    if pbi:
        components.iframe(pbi, height=600)
    else:
        st.caption(
            "Add a Power BI 'publish to web' URL under [powerbi] in secrets to embed "
            "it here. Avoid this for confidential submission data — publish-to-web is "
            "public. Use secure embed (Power BI Pro) for real data."
        )

# ---------------------------------------------------- Recommendations & Chat
with tab_reco:
    st.subheader("Business Recommendations")
    if st.button("Generate recommendations (phi3:mini)"):
        try:
            rows = {}
            for t in db.list_tables():
                try:
                    rows[t] = int(
                        db.run_query(f"SELECT COUNT(*) AS n FROM `{t}`").iloc[0, 0]
                    )
                except Exception:
                    pass
            # Add your own domain aggregates here (status mix, hit ratio, broker
            # breakdown, avg limit, quote turnaround) for richer recommendations.
            stats_md = "\n".join(f"- {k}: {v} rows" for k, v in rows.items())
            with st.spinner("Asking phi3:mini..."):
                st.session_state["reco"] = llm.recommend(stats_md)
        except Exception as e:
            st.error(e)
    if st.session_state.get("reco"):
        st.markdown(st.session_state["reco"])

    st.divider()
    st.subheader("Ask the underwriting assistant")

    with st.expander("Schema the assistant can see"):
        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("Refresh schema"):
                db.discover_schema.clear()
                st.rerun()
        with col_b:
            try:
                _schema = db.discover_schema()
            except Exception as e:
                _schema = {}
                st.error(f"Schema discovery failed: {e}")
            if _schema:
                st.success(f"{len(_schema)} tables/views detected.")
                if "vw_submission_analytics" not in _schema:
                    st.warning(
                        "vw_submission_analytics NOT found — run "
                        "create_analytics_view.sql in DBeaver, then Refresh schema."
                    )
                st.write(sorted(_schema.keys()))
            else:
                st.error(
                    "No tables detected. The DB user likely lacks SELECT "
                    "privileges on this database."
                )

    if "chat" not in st.session_state:
        st.session_state.chat = []
    for m in st.session_state.chat:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    q = st.chat_input("e.g. Which broker has the lowest bind rate this quarter?")
    if q:
        st.session_state.chat.append({"role": "user", "content": q})
        with st.chat_message("user"):
            st.markdown(q)
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                res = llm.ask(q)
            if "error" in res and "sql" not in res:
                st.error(res["error"])
                content = res["error"]
            else:
                if res.get("sql"):
                    with st.expander("SQL executed"):
                        st.code(res["sql"], language="sql")
                if res.get("rows") is not None and not res["rows"].empty:
                    st.dataframe(res["rows"].head(50), use_container_width=True)
                content = res.get("answer") or res.get("error", "No answer.")
                st.markdown(content)
        st.session_state.chat.append({"role": "assistant", "content": content})
