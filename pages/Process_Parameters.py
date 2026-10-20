"""CCR Process Parameters Dashboard — PM2-CR-603 (per-coil process data).

Data: process_data.json on the repo's data branch, baked from the
"CCR Process Parameters - PM2-CR-603" Google Sheet (transcribed register
pages, coil weights matched from the Coiler PM2-CR-609 register by coil #).
"""
import datetime
import json

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

BLUE = "#1f4e78"
GREEN = "#2e7d32"
AMBER = "#c77700"
TEAL = "#0f766e"

st.set_page_config(page_title="CCR Process Parameters", layout="wide")

st.markdown("""
<div style="background:linear-gradient(135deg, #1f4e78 0%, #2e75b6 45%, #0f766e 100%);
            border-radius:10px; padding:16px 24px; margin-bottom:10px;">
<div style="font-size:26px; font-weight:800; color:#ffffff; text-align:center;">
CCR &mdash; Process Parameters Dashboard</div>
<div style="font-size:13px; color:#dbeafe; text-align:center; margin-top:4px;">
Cu CCR Line Process Parameters (PM2-CR-603) &middot; Per-coil data &middot;
Coil weights from Coiler Unit register (PM2-CR-609)</div></div>
""", unsafe_allow_html=True)


@st.cache_data(ttl=900)
def fetch_json(name, buster=None):
    url = ("https://raw.githubusercontent.com/pclwaqas786-ctrl/"
           f"ccr-ops-excellence/data/{name}")
    if buster:
        url += f"?t={buster}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()


try:
    import time as _t
    _bucket = str(int(_t.time() // 900) * 900)
    _buster = st.session_state.get("_pbuster") or _bucket
    man = fetch_json("process_months.json", _buster)
    months = man.get("months", [])
    sel = st.selectbox("Month", months, index=len(months) - 1)
    D = fetch_json(f"process_data_{sel}.json", _buster)
except Exception as e:
    st.error(f"Could not load process data. ({type(e).__name__})")
    st.stop()

proc = pd.DataFrame(D.get("process", []))
coil = pd.DataFrame(D.get("coiler", []))
if proc.empty and coil.empty:
    st.info("No process data yet.")
    st.stop()

for df in (proc, coil):
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["month"] = df["date"].dt.strftime("%Y-%m")

p = proc
c = coil

def kpi_card(col, lbl, val, note="", ac=BLUE):
    with col:
        st.markdown(
            f'<div style="background:#fff;border:1px solid #d9e1ea;'
            f'border-left:5px solid {ac};border-radius:10px;padding:12px 14px;">'
            f'<div style="font-size:11px;color:#64748b;text-transform:uppercase;">{lbl}</div>'
            f'<div style="font-size:26px;font-weight:700;color:#1c2733;">{val}</div>'
            + (f'<div style="font-size:12px;color:#64748b;">{note}</div>' if note else "")
            + "</div>", unsafe_allow_html=True)

total_mt = c["net_kg"].sum() / 1000 if not c.empty else 0.0
a_mt = c[c["shift"] == "A"]["net_kg"].sum() / 1000 if not c.empty else 0.0
b_mt = c[c["shift"] == "B"]["net_kg"].sum() / 1000 if not c.empty else 0.0
ndays = c["date"].nunique() if not c.empty else 0
cols = st.columns(4)
kpi_card(cols[0], "Total Production", f"{total_mt:,.1f} MT", f"{sel} - Coiler register", BLUE)
kpi_card(cols[1], "Shift A / Shift B", f"{a_mt:,.1f} / {b_mt:,.1f} MT", "Shift-wise tons", GREEN)
kpi_card(cols[2], "Coils (Process sheet)", f"{len(p):,}", f"Coiler rows: {len(c):,}", TEAL)
kpi_card(cols[3], "Production Days", f"{ndays}", f"Avg {total_mt/ndays:,.1f} MT/day" if ndays else "", AMBER)

# ---- daily A/B production ----
st.markdown("### Daily Production by Shift (MT)")
if not c.empty:
    daily = (c.groupby([c["date"].dt.strftime("%d-%b"), "shift"])["net_kg"]
             .sum().unstack(fill_value=0) / 1000)
    fig = go.Figure()
    for sh, color in (("A", BLUE), ("B", AMBER)):
        if sh in daily.columns:
            fig.add_bar(x=daily.index, y=daily[sh], name=f"Shift {sh}",
                        marker_color=color)
    fig.update_layout(barmode="stack", height=320, margin=dict(l=10, r=10, t=10, b=10),
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ---- parameter trends (daily averages, per shift) ----
st.markdown("### Process Parameters - Daily Averages")
PARAMS = [("castbar", "Cast Bar Temp (C)"), ("speed", "Casting Speed (RPM/Hz)"),
          ("rm", "RM Speed (RPM/Hz)"), ("cc_out_t", "CC Outlet Temp (C)"),
          ("em_t", "Emulsion Temp (C)"), ("q_t", "Quenching Temp (C)")]
if not p.empty:
    pc = st.columns(3)
    for i, (key, label) in enumerate(PARAMS):
        if key not in p.columns:
            continue
        d = (p.dropna(subset=[key])
             .groupby([p["date"].dt.strftime("%d-%b"), "shift"])[key].mean()
             .unstack())
        if d.empty:
            continue
        fig = go.Figure()
        for sh, color in (("A", BLUE), ("B", AMBER)):
            if sh in d.columns:
                fig.add_scatter(x=d.index, y=d[sh], mode="lines+markers",
                                name=f"Shift {sh}", line=dict(color=color))
        fig.update_layout(title=label, height=240, margin=dict(l=10, r=10, t=36, b=10),
                          legend=dict(orientation="h", y=1.18), title_font_size=13)
        with pc[i % 3]:
            st.plotly_chart(fig, use_container_width=True,
                            config={"displayModeBar": False}, key=f"pp-{key}")

# ---- campaigns ----
st.markdown("### Campaigns (this month)")
if not c.empty:
    day_tot = c.groupby(c["date"].dt.date)["net_kg"].sum() / 1000
    camps, cur, last = [], [day_tot.index[0]], day_tot.index[0]
    for d in day_tot.index[1:]:
        if (d - last).days > 2:
            camps.append(cur); cur = []
        cur.append(d); last = d
    camps.append(cur)
    rows = []
    for i, camp in enumerate(camps, 1):
        rows.append({"Campaign": i, "From": str(camp[0]), "To": str(camp[-1]),
                     "Days": len(camp),
                     "Production (MT)": round(sum(day_tot[d] for d in camp), 1)})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

# ---- cross-check vs main dashboard ----
st.markdown("### Cross-check vs Main Dashboard")
main_mt = D.get("main_dashboard_mt")
if main_mt:
    diff = total_mt - main_mt
    st.markdown(
        f"Is sheet ka total: **{total_mt:,.2f} MT** &middot; Main dashboard: "
        f"**{main_mt:,.1f} MT** &middot; Farq: **{diff:+,.2f} MT** "
        f"({(diff/main_mt*100 if main_mt else 0):+.2f}%)")
else:
    st.caption("Is month ka main-dashboard figure abhi cross-check table me nahi hai.")

if st.button("Refresh data"):
    import time as _time
    st.session_state["_pbuster"] = str(int(_time.time()))
    st.rerun()

with st.expander("Per-coil data (Process sheet)"):
    if not p.empty:
        show = p.sort_values(["date", "shift", "coil"])[
            ["date", "shift", "supervisor", "coil", "weight_kg", "time",
             "castbar", "speed", "cc_in_p", "cc_out_t", "rm", "em_t", "q_t", "remarks"]]
        show["date"] = show["date"].dt.strftime("%Y-%m-%d")
        def _sv_red(v):
            try:
                x = float(v)
            except (TypeError, ValueError):
                return ""
            return "background-color:#fee2e2;color:#b91c1c;font-weight:700" if (x < 780 or x > 820) else ""
        _cb = pd.to_numeric(show["castbar"], errors="coerce")
        _n_out = int(((_cb < 780) | (_cb > 820)).sum())
        st.caption(f"Cast Bar SV: 800 ±20 (780-820) — {_n_out} coil(s) in this view are outside the SV (shown in red). Other printed SVs: SF 1200 ±50, HF 1120-1150, Tundish 1130 ±20 (these three are recorded as '-' in the register).")
        st.dataframe(show.style.map(_sv_red, subset=["castbar"]), use_container_width=True, hide_index=True)
