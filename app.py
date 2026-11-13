"""
Corporate Actions Control Room - Streamlit dashboard.

    streamlit run app.py

Runs the engine on the files in /data and shows the results.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from ca_engine import run_pipeline

HERE = Path(__file__).parent
st.set_page_config(page_title="Corporate Actions Control Room", layout="wide")


@st.cache_data
def load_results():
    r = run_pipeline(HERE / "data", HERE / "outputs")
    return {k: v for k, v in r.items() if isinstance(v, pd.DataFrame)}


def kpi(results, name):
    k = results["kpis"].set_index("metric")["value"]
    return k.get(name, "-")


def colour_status(val):
    colours = {"PASS": "#C6EFCE", "MATCHED": "#C6EFCE", "PROCESSED": "#C6EFCE", "Y": "#C6EFCE",
               "FAIL": "#FFC7CE", "BREAK": "#FFC7CE", "FLAGGED": "#FFC7CE", "N": "#FFC7CE",
               "High": "#FFC7CE", "Medium": "#FFEB9C", "Low": "#DDEBF7"}
    c = colours.get(str(val))
    return f"background-color: {c}; color: black" if c else ""


def show(df, status_cols=()):
    styled = df.style
    cols = [c for c in status_cols if c in df.columns]
    if cols:
        styled = styled.map(colour_status, subset=cols)
    st.dataframe(styled, width="stretch", hide_index=True)


r = load_results()

st.sidebar.title("Corporate Actions")
st.sidebar.caption("Indian equities - FAKE practice data")
page = st.sidebar.radio("Page", ["Control Room", "Event Validation", "Eligibility & Entitlements",
                                 "Instructions & Votes", "Reconciliation", "Exception Queue",
                                 "Audit & Controls", "Positions", "Client Notifications"])
if st.sidebar.button("Re-run engine"):
    load_results.clear()
    st.rerun()

# -------------------------------------------------------------------------
if page == "Control Room":
    st.title("Corporate Actions Control Room")
    st.caption("Reliance · Bharti Airtel · BSE · Sun Pharma · Tata Motors — all events and figures are fictional")
    c = st.columns(5)
    c[0].metric("Events received", kpi(r, "Events received"))
    c[1].metric("Processed (STP)", kpi(r, "Events processed automatically"),
                kpi(r, "Straight-through processing (STP) rate"))
    c[2].metric("Flagged at validation", kpi(r, "Events flagged at validation"))
    c[3].metric("Recon match rate", kpi(r, "Reconciliation match rate"))
    c[4].metric("Open exceptions", kpi(r, "Exceptions - total"), f"{kpi(r, 'Exceptions - High')} High",
                delta_color="inverse")

    left, right = st.columns(2)
    with left:
        st.subheader("Exceptions by reason")
        st.bar_chart(r["exceptions"]["reason_code"].value_counts())
    with right:
        st.subheader("Exceptions by owner team")
        st.bar_chart(r["exceptions"]["owner"].value_counts())

    st.subheader("Event status")
    show(r["validation"][["event_id", "source", "ticker", "event_type", "record_date",
                          "processing_status", "reason_code", "issue"]], ["processing_status"])
    st.subheader("Controls")
    show(r["controls"], ["result"])

elif page == "Event Validation":
    st.title("Event Validation (scrubbing)")
    st.write("Every vendor event is checked before it can touch a client position. "
             "Failed events go to the exception queue.")
    show(r["validation"], ["processing_status"])

elif page == "Eligibility & Entitlements":
    st.title("Eligibility & Entitlements")
    st.write("Eligibility is based on the **settled** holding at end of record date (T+1). "
             "Trades that had not settled by then are shown and excluded.")
    event = st.selectbox("Event", sorted(r["eligibility"]["event_id"].unique()))
    show(r["eligibility"][r["eligibility"]["event_id"] == event], ["eligible"])
    st.subheader("Entitlements")
    ent = r["entitlements"][r["entitlements"]["event_id"] == event].dropna(axis=1, how="all")
    show(ent)
    cash = r["cash"][r["cash"]["event_id"] == event]
    if not cash.empty:
        st.subheader("Cash ledger")
        show(cash)

elif page == "Instructions & Votes":
    st.title("Client Instructions & Votes")
    st.subheader("Rights issue elections (BHARTIARTL)")
    show(r["instructions"])
    st.subheader("AGM e-voting (SUNPHARMA)")
    show(r["votes"])
    if not r["votes"].empty:
        tally = (r["votes"].groupby(["resolution", "vote"])["counted_votes"].sum()
                 .unstack(fill_value=0))
        st.subheader("Vote tally (counted votes)")
        st.bar_chart(tally)

elif page == "Reconciliation":
    st.title("Reconciliation - expected vs received")
    status = st.radio("Show", ["All", "Breaks only"], horizontal=True)
    rec = r["recon"] if status == "All" else r["recon"][r["recon"]["status"] == "BREAK"]
    show(rec, ["status"])

elif page == "Exception Queue":
    st.title("Exception Queue")
    f1, f2 = st.columns(2)
    sev = f1.multiselect("Severity", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    owners = f2.multiselect("Owner", sorted(r["exceptions"]["owner"].unique()),
                            default=sorted(r["exceptions"]["owner"].unique()))
    exc = r["exceptions"][r["exceptions"]["severity"].isin(sev) & r["exceptions"]["owner"].isin(owners)]
    show(exc, ["severity"])
    st.download_button("Download as CSV", exc.to_csv(index=False), "exceptions.csv")

elif page == "Audit & Controls":
    st.title("Audit Trail & Controls")
    show(r["controls"], ["result"])
    st.subheader("Audit log")
    show(r["audit"], ["basis_check"])

elif page == "Positions":
    st.title("Positions - before and after")
    acc = st.selectbox("Account", sorted(r["final_positions"]["account_id"].unique()))
    a, b = st.columns(2)
    a.subheader("Opening")
    a.dataframe(r["opening_positions"][r["opening_positions"]["account_id"] == acc], hide_index=True)
    b.subheader("Final")
    b.dataframe(r["final_positions"][r["final_positions"]["account_id"] == acc], hide_index=True)

elif page == "Client Notifications":
    st.title("Client Notifications")
    notes = r["notifications"]
    choice = st.selectbox("Notice", notes["file"])
    st.code((HERE / "outputs" / "notifications" / choice).read_text(encoding="utf-8"), language=None)
