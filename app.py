"""Ops Excellence Dash Board — company standard format (separate app).

Implements the Standard_Dashboard format:
  OEE Data Analysis (24hr / MTD / YTD grids)
  24 Hrs Summary | MTD / YTD Summary
Live data from the OEE_Data tab of the Google Sheet (via baked data.json).
Sections without sheet data are marked clearly.
"""
import json
import re
import calendar
import datetime

import requests
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

BLUE = "#1f4e78"
GREEN = "#2e7d32"
AMBER = "#c77700"
RED = "#c0392b"
TEAL = "#0f766e"
PURPLE = "#6d28d9"

st.set_page_config(page_title="Ops Excellence Dash Board", layout="wide")

# ---------------------------------------------------------------- data ----
@st.cache_data(ttl=900)
def fetch_sheet():
    url = "https://pclwaqas786-ctrl.github.io/ccr-oee-dashboard/data.json"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    d = r.json()
    values = d.get("values", [])
    if not values:
        raise RuntimeError("empty baked data")
    try:
        fa = datetime.datetime.fromisoformat(d["fetched_at"])
        fetched = fa.strftime("%d %b %Y, %H:%M")
    except Exception:
        fetched = str(d.get("fetched_at", ""))
    rows = [list(r) + [None] * (16 - len(r)) for r in values]
    return {"fetched_at": fetched, "rows": rows}


def num(v):
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    if s.endswith("%"):
        try:
            return float(s[:-1]) / 100.0
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


MON = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
       "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def parse_date(v):
    if v is None or v == "":
        return None
    s = str(v).strip()
    m0 = re.match(r"Date\((\d+),(\d+),(\d+)\)", s)
    if m0:
        return datetime.datetime(int(m0.group(1)), int(m0.group(2)) + 1,
                                 int(m0.group(3)))
    if re.fullmatch(r"\d{4,6}", s):
        return datetime.datetime(1970, 1, 1) + datetime.timedelta(days=int(s) - 25569)
    m = re.match(r"(\d{1,2})-([A-Za-z]{3})-(\d{2,4})", s)
    if m and m.group(2).lower() in MON:
        y = int(m.group(3))
        if y < 100:
            y += 2000
        return datetime.datetime(y, MON[m.group(2).lower()], int(m.group(1)))
    return None


def parse_model(rows):
    M = {"daily": [], "mtd": {}, "reasons": [], "trend": [], "periods": [],
         "target": 0.0, "shift": []}
    section = None
    for r in rows:
        r = list(r) + [None] * (16 - len(r))
        a = r[0]
        lab = str(r[1] if r[1] is not None else "").strip()
        if a not in (None, "") and str(a).strip().replace(".", "", 1).isdigit() \
                and parse_date(r[1]):
            M["daily"].append({
                "day": float(a), "date": parse_date(r[1]),
                "avail": num(r[2]), "dt": num(r[3]), "run": num(r[4]),
                "availP": num(r[5]), "plan": num(r[6]), "ach": num(r[7]),
                "perfP": num(r[8]), "good": num(r[9]), "qualP": num(r[10]),
                "oee": num(r[11]), "status": str(r[12] or ""),
                "ach_blank": str(r[7] or "").strip() == "",
                "shiftA": num(r[14]), "shiftB": num(r[15])})
            continue
        if re.match(r"^MTD TOTAL", lab, re.I):
            M["mtd"] = {"avail": num(r[2]), "dt": num(r[3]), "run": num(r[4]),
                        "availP": num(r[5]), "plan": num(r[6]), "ach": num(r[7]),
                        "perfP": num(r[8]), "qualP": num(r[10]),
                        "oeeP": num(r[11]), "dtHrs": num(r[13])}
            continue
        if re.match(r"^MTD Downtime by Reason", lab, re.I):
            section = "reasons"; continue
        if re.match(r"^MTD Production by Shift", lab, re.I):
            section = "shift"; continue
        if re.match(r"^Yearly Production Trend", lab, re.I):
            section = "trend"; continue
        if re.match(r"^Period-wise Summary", lab, re.I):
            section = "periods"; continue
        if re.match(r"^Yearly Target", lab, re.I):
            M["target"] = num(r[2]); section = None; continue
        if re.match(r"^(Total|Period|Day|Date)\b", lab, re.I) and section != "daily":
            continue
        if lab == "" and section:
            continue
        if section == "reasons" and lab:
            M["reasons"].append({"name": lab, "hrs": num(r[2])})
        elif section == "shift" and lab and re.match(r"^Shift", lab, re.I):
            M["shift"].append({"name": lab, "prod": num(r[2])})
        elif section == "trend" and lab and re.search(r"-26|-27", lab, re.I):
            M["trend"].append({"m": lab, "prod": num(r[2]), "cum": num(r[3]),
                               "oee": num(r[4]), "avail": num(r[5]),
                               "perf": num(r[6]), "qual": num(r[7])})
        elif section == "periods" and re.match(r"^Week", lab, re.I):
            M["periods"].append({"p": lab, "avail": num(r[2]), "perf": num(r[3]),
                                 "qual": num(r[4]), "oee": num(r[5]),
                                 "plan": num(r[6]), "ach": num(r[7])})
        if lab == "" and (r[2] in (None, "")) and section \
                and not re.match(r"^Week", lab, re.I):
            if section == "reasons":
                section = None
    M["daily"] = [d for d in M["daily"] if re.search(r"final", d["status"], re.I)]
    M["daily"].sort(key=lambda d: d["date"])
    return M


def pct(x):
    return f"{x * 100:.1f}%"


def fy_label():
    p5 = datetime.timezone(datetime.timedelta(hours=5))
    now = datetime.datetime.now(p5)
    if now.month >= 7:
        return f"FY {now.year}-{str(now.year + 1)[2:]}"
    return f"FY {now.year - 1}-{str(now.year)[2:]}"


def kpi_card(lbl, val, note="", ac=BLUE):
    st.markdown(
        f'<div class="kpi-card" style="--ac:{ac}">'
        f'<div class="lbl">{lbl}</div><div class="val">{val}</div>'
        + (f'<div class="note">{note}</div>' if note else '') +
        '</div>', unsafe_allow_html=True)


def na_card(lbl, note="Not tracked in the Google Sheet yet"):
    st.markdown(
        f'<div class="kpi-card na-card">'
        f'<div class="lbl">{lbl}</div>'
        f'<div class="na-val">—</div>'
        f'<div class="note">{note}</div></div>', unsafe_allow_html=True)


def mini_donut(title, value, prev_text, color, key):
    """Round donut: value in 0-100, big % in center, prev period as caption."""
    v = max(0, min(100, round(value, 1)))
    fig = go.Figure(go.Pie(values=[v, 100 - v], hole=0.72,
                           marker_colors=[color, "#e8edf3"],
                           textinfo="none", hoverinfo="skip",
                           sort=False, direction="clockwise"))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13)),
        annotations=[dict(text=f"<b>{v:.1f}%</b>", x=0.5, y=0.5,
                          font_size=26, showarrow=False)],
        height=220, margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=key)
    if prev_text:
        st.caption(prev_text)


def mini_gauge(title, value, ref, color, key):
    """Round gauge for a % metric. value/ref in 0-100; ref=None => no delta."""
    ind = dict(mode="gauge+number" + ("+delta" if ref is not None else ""),
               value=round(value, 1),
               number={"suffix": "%", "font": {"size": 22}},
               title={"text": title, "font": {"size": 12}},
               gauge={"axis": {"range": [0, max(100, value * 1.15)], "tickwidth": 1,
                               "tickcolor": "#64748b"},
                      "bar": {"color": color, "thickness": 0.75},
                      "bgcolor": "#e8edf3"})
    if ref is not None:
        ind["delta"] = {"reference": round(ref, 1), "suffix": " pts"}
    fig = go.Figure(go.Indicator(**ind))
    fig.update_layout(height=210, margin=dict(l=15, r=15, t=40, b=10))
    st.plotly_chart(fig, use_container_width=True, key=key)


def mini_bar(labels, values, title, color, key, suffix="%", hl=False):
    fig = go.Figure(go.Bar(
        x=labels, y=values, marker_color=color,
        text=[f"{v:,.1f}{suffix}" for v in values],
        textposition="outside", textfont=dict(size=11),
        hovertemplate="%{x}: %{y:,.1f}" + suffix + "<extra></extra>"))
    kw = dict(title=dict(text=title, font=dict(size=12)),
              height=230, margin=dict(l=5, r=5, t=35, b=5))
    if hl:
        kw["shapes"] = [dict(type="rect", xref="paper", yref="paper", x0=0, y0=0,
                             x1=1, y1=1, line=dict(color="#eab308", width=3))]
    fig.update_layout(**kw)
    st.plotly_chart(fig, use_container_width=True, key=key)


# ------------------------------------------------------------------ UI ----
st.markdown("""
<style>
  .kpi-card { background:#ffffff; border:1px solid #d9e1ea; border-left:5px solid var(--ac,#1f4e78);
    border-radius:10px; padding:12px 14px; box-shadow:0 1px 3px rgba(16,42,67,.08); }
  .kpi-card .lbl { font-size:11px; color:#64748b; text-transform:uppercase; letter-spacing:.6px; }
  .kpi-card .val { font-size:28px; font-weight:700; color:#1c2733; }
  .kpi-card .note { font-size:12px; color:#64748b; }
  .na-card { border-left-color:#cbd5e1 !important; background:#f8fafc !important; }
  .na-card .na-val { font-size:28px; font-weight:700; color:#94a3b8; }
  h1, h2, h3 { color:#1c2733; }
  .title-accent { height:4px; border-radius:2px; margin:-6px 0 14px 0; background:#1f4e78; }
  .section-band { background:#1f4e78; color:#fff; border-radius:6px; padding:8px 14px;
    font-weight:700; margin:18px 0 10px 0; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="background:#f5a623; border-radius:8px; padding:14px 18px; margin-bottom:6px;">
<div style="font-size:24px; font-weight:800; color:#1c2733; text-align:center;">Ops Excellence Dash Board</div>
</div>
""", unsafe_allow_html=True)

try:
    data = fetch_sheet()
except Exception as e:
    st.error("Could not load data from the sheet. Please press Refresh / Rerun. "
             f"({type(e).__name__})")
    st.stop()

M = parse_model(data["rows"])
mtd = M["mtd"]
st.caption(f"Updated {data['fetched_at']} · auto-refreshes every ~15 min")
if st.button("↻ Refresh data"):
    fetch_sheet.clear()
    st.rerun()

FY = fy_label()
tgt = M["target"] or 4800
ytd = sum(m["prod"] for m in M["trend"]) if M["trend"] else 0

# ---- targets header (as per standard format) ----
tc = st.columns(2)
with tc[0]:
    kpi_card("Yearly Target", f"{tgt:,.0f}", "Value tons", BLUE)
with tc[1]:
    kpi_card("Monthly Target", f"{mtd.get('plan', 0):,.1f}", "Value tons", BLUE)

# ================= OEE DATA ANALYSIS =================
st.markdown('<div class="section-band">OEE Data Analysis</div>', unsafe_allow_html=True)

real_days = [d for d in M["daily"] if not d.get("ach_blank")]
last2 = real_days[-2:] if len(real_days) >= 2 else real_days
d2lbl = [d["date"].strftime("%d-%b") for d in last2]
# last 2 months with production (for MTD comparison bars)
trend2 = [m for m in M["trend"] if m["prod"] > 0][-2:]
t2lbl = [m["m"] for m in trend2]
t2prod = [m["prod"] for m in trend2]
# full YTD trend (months with production)
trendY = [m for m in M["trend"] if m["prod"] > 0]
tylbl = [m["m"] for m in trendY]
typrod = [m["prod"] for m in trendY]

def _oee_bars(prefix, pct_lists, pct_labels, prod_labels, prod_vals,
                ton_label, ton_val, keys):
    """4 % charts in ONE row + Production/Tonnage bars below."""
    titles = ["OEE", "Efficiency", "Quality", "Availability"]
    colors = [BLUE, GREEN, TEAL, PURPLE]
    cols = st.columns(4)
    for col, i in zip(cols, range(4)):
        with col:
            mini_bar(pct_labels, pct_lists[i], f"{prefix} {titles[i]}",
                     colors[i], keys[i])
    bcols = st.columns(2)
    with bcols[0]:
        mini_bar(prod_labels, prod_vals, f"{prefix} Production", AMBER,
                 keys[4], suffix=" MT", hl=True)
    with bcols[1]:
        mini_bar([ton_label], [ton_val], f"{prefix} Tonnage", AMBER,
                 keys[5], suffix=" MT", hl=True)


def _oee_gauges(prefix, pct_vals, pct_refs, prod_labels, prod_vals,
                ton_label, ton_val, keys):
    """4 round gauges (% metrics) + 2 bar charts (Production, Tonnage)."""
    titles = ["OEE", "Efficiency", "Quality", "Availability"]
    colors = [BLUE, GREEN, TEAL, PURPLE]
    gcols = st.columns(4)
    for col, t, v, r, c, k in zip(gcols, titles, pct_vals, pct_refs, colors, keys[:4]):
        with col:
            mini_gauge(f"{prefix} {t}", v, r, c, k)
    bcols = st.columns(2)
    with bcols[0]:
        mini_bar(prod_labels, prod_vals, f"{prefix} Production", AMBER,
                 keys[4], suffix=" MT", hl=True)
    with bcols[1]:
        mini_bar([ton_label], [ton_val], f"{prefix} Tonnage", AMBER,
                 keys[5], suffix=" MT", hl=True)

# ---- YTD row (template: 6 bar graphs, last 2 years) ----
st.markdown(f"#### YTD ({FY})")
moee = [m for m in trendY if m["oee"] > 0]
mlbl = [m["m"] for m in moee] or ["Oct-26"]
_oee_bars("YTD",
         [[m["oee"] * 100 for m in moee] or [mtd.get("oeeP", 0) * 100],
          [m["perf"] * 100 for m in moee] or [mtd.get("perfP", 0) * 100],
          [m["qual"] * 100 for m in moee] or [mtd.get("qualP", 0) * 100],
          [m["avail"] * 100 for m in moee] or [mtd.get("availP", 0) * 100]],
         mlbl,
         tylbl, typrod, FY, ytd,
         ["ytd-oee", "ytd-eff", "ytd-qual", "ytd-avail", "ytd-prod", "ytd-ton"])
st.caption("OEE breakdown from Oct-26 only — earlier months have production totals, no OEE history in sheet.")

# ---- MTD row (template: 6 bar graphs, last 2 months) ----
st.markdown("#### MTD")
m2oee = [m for m in trend2 if m["oee"] > 0]
m2lbl = [m["m"] for m in m2oee] or ["Oct-26"]
_oee_bars("MTD",
         [[m["oee"] * 100 for m in m2oee] or [mtd.get("oeeP", 0) * 100],
          [m["perf"] * 100 for m in m2oee] or [mtd.get("perfP", 0) * 100],
          [m["qual"] * 100 for m in m2oee] or [mtd.get("qualP", 0) * 100],
          [m["avail"] * 100 for m in m2oee] or [mtd.get("availP", 0) * 100]],
         m2lbl,
         t2lbl, t2prod, "Oct-26", mtd.get("ach", 0),
         ["mtd-oee", "mtd-eff", "mtd-qual", "mtd-avail", "mtd-prod", "mtd-ton"])

# ---- 24 Hr row (template: 6 bar graphs, last 2 days) ----


st.markdown(f"#### YTD ({FY})")
moee = [m for m in trendY if m["oee"] > 0]
mlbl = [m["m"] for m in moee] or ["Oct-26"]
_oee_bars("YTD",
         [[m["oee"] * 100 for m in moee] or [mtd.get("oeeP", 0) * 100],
          [m["perf"] * 100 for m in moee] or [mtd.get("perfP", 0) * 100],
          [m["qual"] * 100 for m in moee] or [mtd.get("qualP", 0) * 100],
          [m["avail"] * 100 for m in moee] or [mtd.get("availP", 0) * 100]],
         mlbl,
         tylbl, typrod, FY, ytd,
         ["ytd-oee", "ytd-eff", "ytd-qual", "ytd-avail", "ytd-prod", "ytd-ton"])
st.caption("OEE breakdown from Oct-26 only — earlier months have production totals, no OEE history in sheet.")

# ---- MTD row (template: 6 bar graphs, last 2 months) ----
st.markdown("#### MTD")
m2oee = [m for m in trend2 if m["oee"] > 0]
m2lbl = [m["m"] for m in m2oee] or ["Oct-26"]
_oee_bars("MTD",
         [[m["oee"] * 100 for m in m2oee] or [mtd.get("oeeP", 0) * 100],
          [m["perf"] * 100 for m in m2oee] or [mtd.get("perfP", 0) * 100],
          [m["qual"] * 100 for m in m2oee] or [mtd.get("qualP", 0) * 100],
          [m["avail"] * 100 for m in m2oee] or [mtd.get("availP", 0) * 100]],
         m2lbl,
         t2lbl, t2prod, "Oct-26", mtd.get("ach", 0),
         ["mtd-oee", "mtd-eff", "mtd-qual", "mtd-avail", "mtd-prod", "mtd-ton"])

# ---- 24 Hr row (template: 6 bar graphs, last 2 days) ----
st.markdown("#### 24 Hr")
if last2:
    _yd = last2[-1]
    _ypct = (_yd["ach"] / _yd["plan"] * 100) if _yd["plan"] else 0
    sc = st.columns(4)
    with sc[0]:
        kpi_card("Date", _yd["date"].strftime("%d-%b-%Y"), "Yesterday", BLUE)
    with sc[1]:
        kpi_card("Target", f'{_yd["plan"]:.1f}', "MT", PURPLE)
    with sc[2]:
        kpi_card("Production", f'{_yd["ach"]:.1f}', "MT", AMBER)
    with sc[3]:
        kpi_card("Plan Achieved", f"{_ypct:.0f}%", "of target", GREEN)

    dcols = st.columns(4)
    _d = [("OEE", "oee", BLUE, "h24-oee"),
          ("Efficiency", "perfP", GREEN, "h24-eff"),
          ("Quality", "qualP", TEAL, "h24-qual"),
          ("Availability", "availP", PURPLE, "h24-avail")]
    for col, (t, k, c, key) in zip(dcols, _d):
        with col:
            prev = f"{d2lbl[0]}: {last2[0][k]*100:.1f}%" if len(last2) > 1 else ""
            mini_donut(f"24 Hr {t}", last2[-1][k] * 100, prev, c, key)
    bcols = st.columns(2)
    with bcols[0]:
        mini_bar(d2lbl, [d["ach"] for d in last2], "24 Hr Production",
                 AMBER, "h24-prod", suffix=" MT", hl=True)
    with bcols[1]:
        mini_bar(d2lbl, [d["ach"] for d in last2], "24 Hr Tonnage",
                 AMBER, "h24-ton", suffix=" MT", hl=True)
else:
    st.info("No finalized daily data in the sheet yet.")

# ================= MTD / YTD SUMMARY =================
st.markdown('<div class="section-band">MTD / YTD Summary</div>', unsafe_allow_html=True)
if real_days:
    xs = [d["date"].strftime("%d-%b") for d in real_days]
    # daily shift-wise production (Shift A vs Shift B)
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=xs, y=[d.get("shiftA", 0) for d in real_days], name="Shift A",
        marker_color=BLUE,
        text=[f"{d.get('shiftA', 0):.1f}" for d in real_days],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="%{x}<br>Shift A: %{y:.1f} MT<extra></extra>"))
    fig.add_trace(go.Bar(
        x=xs, y=[d.get("shiftB", 0) for d in real_days], name="Shift B",
        marker_color="#5b9bd5",
        text=[f"{d.get('shiftB', 0):.1f}" for d in real_days],
        textposition="outside", textfont=dict(size=10),
        hovertemplate="%{x}<br>Shift B: %{y:.1f} MT<extra></extra>"))
    fig.update_layout(title=dict(text="Shift-wise Production by Day (MT)", font=dict(size=13)),
                      barmode="group", height=340,
                      margin=dict(l=5, r=5, t=40, b=5),
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True, key="u-shift")
    u1 = st.columns(2)
    with u1[0]:
        fig = go.Figure(go.Bar(
            x=xs, y=[d["oee"] * 100 for d in real_days], marker_color=BLUE,
            text=[f"{d['oee'] * 100:.1f}%" for d in real_days],
            textposition="outside", textfont=dict(size=10)))
        fig.update_layout(title=dict(text="Date-wise OEE %", font=dict(size=13)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-oee")
    with u1[1]:
        fig = go.Figure(go.Bar(
            x=xs, y=[d["ach"] for d in real_days], marker_color=AMBER,
            text=[f"{d['ach']:.1f}" for d in real_days],
            textposition="outside", textfont=dict(size=10)))
        fig.update_layout(title=dict(text="Date-wise Production (MT)", font=dict(size=13)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-prod")
    u2 = st.columns(2)
    with u2[0]:
        fig = go.Figure(go.Bar(
            x=xs, y=[d["dt"] / 60 for d in real_days], marker_color=RED,
            text=[f"{d['dt'] / 60:.1f}h" for d in real_days],
            textposition="outside", textfont=dict(size=10)))
        fig.update_layout(title=dict(text="Date-wise Downtime (hrs)", font=dict(size=13)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-dt")
    with u2[1]:
        by_oee = sorted(real_days, key=lambda d: d["oee"], reverse=True)
        best = by_oee[:3]
        worst = by_oee[-3:][::-1]
        bt = "<br>".join(
            f"{d['date'].strftime('%d-%b')}: {d['oee'] * 100:.1f}% OEE, {d['ach']:.1f} MT"
            for d in best)
        wt = "<br>".join(
            f"{d['date'].strftime('%d-%b')}: {d['oee'] * 100:.1f}% OEE, {d['ach']:.1f} MT"
            for d in worst)
        st.markdown(f"**Best 3 days (by OEE)**<br>{bt}", unsafe_allow_html=True)
        st.markdown(f"**Weakest 3 days (by OEE)**<br>{wt}", unsafe_allow_html=True)
        st.caption("Single CCR line — day-wise ranking shown instead of machine-wise.")

# ================= WEEKLY SUMMARY =================
st.markdown('<div class="section-band">Weekly Summary</div>', unsafe_allow_html=True)
if M["periods"]:
    wp = M["periods"]
    rows = "".join(
        f"<tr><td>{p['p']}</td><td style='text-align:right'>{p['avail']*100:.1f}%</td>"
        f"<td style='text-align:right'>{p['perf']*100:.1f}%</td>"
        f"<td style='text-align:right'>{p['qual']*100:.1f}%</td>"
        f"<td style='text-align:right'>{p['oee']*100:.1f}%</td>"
        f"<td style='text-align:right'>{p['plan']:.0f}</td>"
        f"<td style='text-align:right'>{p['ach']:.1f}</td></tr>"
        for p in wp)
    st.markdown(
        f"<table style='width:100%'><tr><th>Period</th>"
        f"<th style='text-align:right'>Avail</th><th style='text-align:right'>Perf</th>"
        f"<th style='text-align:right'>Qual</th><th style='text-align:right'>OEE</th>"
        f"<th style='text-align:right'>Plan (MT)</th><th style='text-align:right'>Ach (MT)</th></tr>{rows}</table>",
        unsafe_allow_html=True)
else:
    st.info("No weekly summary in the sheet yet.")

# ================= 24 HRS SUMMARY =================
st.markdown('<div class="section-band">24 Hrs Summary</div>', unsafe_allow_html=True)
if last2:
    L = last2[-1]
    st.caption(f"Latest finalized day: {L['date'].strftime('%d-%b-%Y')}")
    # losses time (template: "only add losses time")
    kpi_card("Losses Time (24 Hr)", f"{L['dt'] / 60:.1f}",
             f"hrs downtime · run {L['run'] / 60:.1f} hrs / available {L['avail'] / 60:.1f} hrs",
             "#b91c1c")
    s1 = st.columns(3)
    with s1[0]:
        sa = sum(d.get("shiftA", 0) for d in M["daily"])
        sb = sum(d.get("shiftB", 0) for d in M["daily"])
        d0 = M["daily"][0]["date"].strftime("%d-%b")
        d1 = M["daily"][-1]["date"].strftime("%d-%b")
        fig = go.Figure(go.Pie(
            labels=["Shift A", "Shift B"], values=[sa, sb], hole=0.55,
            marker_colors=[BLUE, "#5b9bd5"],
            textinfo="label+percent", textfont=dict(size=12),
            hovertemplate="%{label}: %{value:.1f} MT (%{percent})<extra></extra>"))
        fig.update_layout(
            title=dict(text="Shift-wise Production (MTD)", font=dict(size=12)),
            height=250, margin=dict(l=5, r=5, t=35, b=5),
            legend=dict(orientation="h", y=-0.05),
            annotations=[dict(text=f"{sa + sb:.1f}<br>MT", x=0.5, y=0.5,
                              font_size=16, showarrow=False)])
        st.plotly_chart(fig, use_container_width=True, key="s-shift-prod")
        st.caption(f"Sum of daily entries — {d0} to {d1}")
    with s1[1]:
        na_card("Shift-wise OEE", "Shift-wise OEE not tracked in the Google Sheet yet")
    with s1[2]:
        na_card("Shift-wise Downtime", "Shift-wise downtime not tracked in the Google Sheet yet")
    s2 = st.columns(3)
    with s2[0]:
        na_card("Shift-wise Breakdown", "Shift-wise breakdown not tracked in the Google Sheet yet")
    with s2[1]:
        sa = sum(d.get("shiftA", 0) for d in M["daily"])
        sb = sum(d.get("shiftB", 0) for d in M["daily"])
        d0 = M["daily"][0]["date"].strftime("%d-%b")
        d1 = M["daily"][-1]["date"].strftime("%d-%b")
        st.markdown(
            f"**Production Report — Shift-wise (MTD)**<br>"
            f"<table style='width:100%'><tr><th>Shift</th>"
            f"<th style='text-align:right'>Production (MT)</th></tr>"
            f"<tr><td>Shift A</td><td style='text-align:right'>{sa:,.1f}</td></tr>"
            f"<tr><td>Shift B</td><td style='text-align:right'>{sb:,.1f}</td></tr>"
            f"<tr><td><b>Total</b></td><td style='text-align:right'><b>{sa + sb:,.1f}</b></td></tr>"
            f"</table>"
            f"<div style='font-size:12px;color:#64748b'>Sum of daily entries — {d0} to {d1}</div>",
            unsafe_allow_html=True)
    with s2[2]:
        kpi_card("Day Production", f"{L['ach']:,.1f}",
                 f"MT · plan {L['plan']:,.1f} MT "
                 f"({(L['ach'] / L['plan'] * 100 if L['plan'] else 0):.0f}% of plan)",
                 AMBER)

st.divider()
st.caption("Source: OEE_Data tab of the Google Sheet — updates appear automatically (cached ~15 min).")
