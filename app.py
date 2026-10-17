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
    url = "https://raw.githubusercontent.com/pclwaqas786-ctrl/ccr-ops-excellence/data/data.json"
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


DONUT_COLOR = "#1f4e78"

def mini_donut(title, value, prev_text, color, key):
    """Round donut: latest % big in center, prev period % smaller inside too."""
    v = max(0, min(100, round(value, 1)))
    fig = go.Figure(go.Pie(values=[v, 100 - v], hole=0.72,
                           marker_colors=[DONUT_COLOR, "#e8edf3"],
                           textinfo="none", hoverinfo="skip",
                           sort=False, direction="clockwise"))
    ann = [dict(text=f"<b>{v:.1f}%</b>", x=0.5, y=0.55,
                font_size=26, showarrow=False)]
    if prev_text:
        ann.append(dict(text=prev_text, x=0.5, y=0.38,
                        font_size=13, showarrow=False, font_color="#64748b"))
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, family="Arial Black")),
        annotations=ann,
        height=220, margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=key)


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
        textposition="outside", textfont=dict(size=14, family="Arial Black"),
        hovertemplate="%{x}: %{y:,.1f}" + suffix + "<extra></extra>"))
    kw = dict(title=dict(text=title, font=dict(size=15, family="Arial Black")),
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
<div style="background:linear-gradient(135deg, #1f4e78 0%, #2e75b6 45%, #f5a623 100%);
            border-radius:10px; padding:20px 24px; margin-bottom:8px;
            box-shadow:0 2px 8px rgba(0,0,0,0.15);">
<div style="font-size:28px; font-weight:800; color:#ffffff; text-align:center;
            letter-spacing:0.5px;">CCR &mdash; Ops Excellence Dashboard</div>
<div style="font-size:14px; color:#ffe9c4; text-align:center; margin-top:6px;">
Copper Casting &amp; Rolling Plant &mdash; Daily OEE, Production &amp; Downtime Performance</div>
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

# ---- targets header (attractive green gradient cards) ----
def _target_card(title, value, unit, grad):
    st.markdown(
        f"""<div style="background:{grad}; border-radius:10px; padding:16px 20px;
             box-shadow:0 2px 8px rgba(0,0,0,0.18); text-align:center;">
        <div style="font-size:13px; font-weight:700; color:#e8f8ef;
             letter-spacing:1px; text-transform:uppercase;">{title}</div>
        <div style="font-size:34px; font-weight:800; color:#ffffff;
             margin:4px 0;">{value}</div>
        <div style="font-size:12px; color:#d5f5e3;">{unit}</div></div>""",
        unsafe_allow_html=True)

tc = st.columns(2)
with tc[0]:
    _target_card("Yearly Target", f"{tgt:,.0f}", "Value tons",
                 "linear-gradient(135deg, #0d6e3f 0%, #27ae60 100%)")
with tc[1]:
    _target_card("Monthly Target", f"{mtd.get('plan', 0):,.1f}", "Value tons",
                 "linear-gradient(135deg, #0e7c6b 0%, #1abc9c 100%)")

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

def _oee_row6(prefix, charts):
    """6 charts in ONE row (template layout). charts = list of (kind, args)."""
    cols = st.columns(6)
    for col, (kind, a) in zip(cols, charts):
        with col:
            if kind == "donut":
                mini_donut(a["title"], a["value"], a.get("prev", ""), a["color"], a["key"])
            else:
                mini_bar(a["labels"], a["values"], a["title"], a["color"], a["key"],
                         suffix=a.get("suffix", ""))


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
st.markdown("#### 24 Hr")
if last2:
    d2dates = " & ".join(d["date"].strftime("%d-%b") for d in last2)
    st.caption(f"📅 Last 2 finalized days: {d2dates}")
    _oee_row6("24 Hr", [
        ("bar", {"title": "24 Hr OEE", "labels": d2lbl,
                  "values": [d["oee"]*100 for d in last2],
                  "color": BLUE, "key": "h24-oee"}),
        ("bar", {"title": "24 Hr Efficiency", "labels": d2lbl,
                  "values": [d["perfP"]*100 for d in last2],
                  "color": GREEN, "key": "h24-eff"}),
        ("bar", {"title": "24 Hr Quality", "labels": d2lbl,
                  "values": [d["qualP"]*100 for d in last2],
                  "color": TEAL, "key": "h24-qual"}),
        ("bar", {"title": "24 Hr Availability", "labels": d2lbl,
                  "values": [d["availP"]*100 for d in last2],
                  "color": PURPLE, "key": "h24-avail"}),
        ("bar", {"title": "24 Hr Production", "labels": d2lbl,
                  "values": [d["ach"] for d in last2],
                  "color": AMBER, "key": "h24-prod", "suffix": " MT"}),
        ("bar", {"title": "24 Hr Tonnage", "labels": d2lbl,
                  "values": [d["ach"] for d in last2],
                  "color": AMBER, "key": "h24-ton", "suffix": " MT"}),
    ])
else:
    st.info("No finalized daily data in the sheet yet.")


st.markdown("#### MTD")
_m2 = [m for m in trend2 if m["oee"] > 0]
_m2lbl = [m["m"] for m in _m2] or ["Oct-26"]
st.caption(f"📅 Last 2 months: {' & '.join(_m2lbl)}")
_oee_row6("MTD", [
    ("bar", {"title": "MTD OEE", "labels": _m2lbl,
              "values": [m["oee"]*100 for m in _m2] or [mtd.get("oeeP",0)*100],
              "color": BLUE, "key": "mtd-oee"}),
    ("bar", {"title": "MTD Efficiency", "labels": _m2lbl,
              "values": [m["perf"]*100 for m in _m2] or [mtd.get("perfP",0)*100],
              "color": GREEN, "key": "mtd-eff"}),
    ("bar", {"title": "MTD Quality", "labels": _m2lbl,
              "values": [m["qual"]*100 for m in _m2] or [mtd.get("qualP",0)*100],
              "color": TEAL, "key": "mtd-qual"}),
    ("bar", {"title": "MTD Availability", "labels": _m2lbl,
              "values": [m["avail"]*100 for m in _m2] or [mtd.get("availP",0)*100],
              "color": PURPLE, "key": "mtd-avail"}),
    ("bar", {"title": "MTD Production", "labels": t2lbl, "values": t2prod,
              "color": AMBER, "key": "mtd-prod", "suffix": " MT"}),
    ("bar", {"title": "MTD Tonnage", "labels": ["Oct-26"], "values": [mtd.get("ach",0)],
              "color": AMBER, "key": "mtd-ton", "suffix": " MT"}),
])


st.markdown(f"#### YTD ({FY})")
_my = [m for m in trendY if m["oee"] > 0]
_mylbl = [m["m"] for m in _my] or ["Oct-26"]
_oee_row6("YTD", [
    ("bar", {"title": "YTD OEE", "labels": _mylbl,
              "values": [m["oee"]*100 for m in _my] or [mtd.get("oeeP",0)*100],
              "color": BLUE, "key": "ytd-oee"}),
    ("bar", {"title": "YTD Efficiency", "labels": _mylbl,
              "values": [m["perf"]*100 for m in _my] or [mtd.get("perfP",0)*100],
              "color": GREEN, "key": "ytd-eff"}),
    ("bar", {"title": "YTD Quality", "labels": _mylbl,
              "values": [m["qual"]*100 for m in _my] or [mtd.get("qualP",0)*100],
              "color": TEAL, "key": "ytd-qual"}),
    ("bar", {"title": "YTD Availability", "labels": _mylbl,
              "values": [m["avail"]*100 for m in _my] or [mtd.get("availP",0)*100],
              "color": PURPLE, "key": "ytd-avail"}),
    ("bar", {"title": "YTD Production", "labels": tylbl, "values": typrod,
              "color": AMBER, "key": "ytd-prod", "suffix": " MT"}),
    ("bar", {"title": "YTD Tonnage", "labels": [FY], "values": [ytd],
              "color": AMBER, "key": "ytd-ton", "suffix": " MT"}),
])


# ================= 24 HRS SUMMARY =================
st.markdown('<div class="section-band">24 Hrs Summary</div>', unsafe_allow_html=True)
if last2:
    L = last2[-1]
    st.caption(f"Latest finalized day: {L['date'].strftime('%d-%b-%Y')}")
    # losses time (template: "only add losses time")
    kpi_card("Losses Time (24 Hr)", f"{L['dt'] / 60:.1f}",
             f"hrs downtime · run {L['run'] / 60:.1f} hrs / available {L['avail'] / 60:.1f} hrs",
             "#b91c1c")
    s1 = st.columns(2)
    with s1[0]:
        sa = sum(d.get("shiftA", 0) for d in M["daily"])
        sb = sum(d.get("shiftB", 0) for d in M["daily"])
        d0 = M["daily"][0]["date"].strftime("%d-%b")
        d1 = M["daily"][-1]["date"].strftime("%d-%b")
        fig = go.Figure(go.Pie(
            labels=["Shift A", "Shift B"], values=[sa, sb], hole=0.55,
            marker_colors=[BLUE, "#5b9bd5"],
            textinfo="label+percent", textfont=dict(size=14, family="Arial Black"),
            hovertemplate="%{label}: %{value:.1f} MT (%{percent})<extra></extra>"))
        fig.update_layout(
            title=dict(text="Shift-wise Production (MTD)", font=dict(family="Arial Black", size=15)),
            height=250, margin=dict(l=5, r=5, t=35, b=5),
            legend=dict(orientation="h", y=-0.05),
            annotations=[dict(text=f"{sa + sb:.1f}<br>MT", x=0.5, y=0.5,
                              font_size=16, showarrow=False)])
        st.plotly_chart(fig, use_container_width=True, key="s-shift-prod")
        st.caption(f"Sum of daily entries — {d0} to {d1}")
    with s1[1]:
        # 24hr shift-wise for latest day
        la, lb = L.get('shiftA', 0), L.get('shiftB', 0)
        ld = L['date'].strftime('%d-%b')
        st.markdown(
            f"<div style='background:white;border-radius:12px;padding:16px;"
            f"box-shadow:0 2px 8px rgba(0,0,0,0.08);'>"
            f"<div style='font-size:14px;font-weight:bold;margin-bottom:12px;'>"
            f"🌅 Shift-wise Production (24 Hr)<br>"
            f"<span style='font-size:12px;color:#64748b;font-weight:normal;'>{ld}</span></div>"
            f"<div style='display:flex;gap:12px;'>"
            f"<div style='flex:1;background:#1f4e78;color:white;border-radius:8px;"
            f"padding:12px;text-align:center;'>"
            f"<div style='font-size:12px;'>Shift A</div>"
            f"<div style='font-size:22px;font-weight:bold;'>{la:.1f}</div>"
            f"<div style='font-size:12px;'>MT</div></div>"
            f"<div style='flex:1;background:#5b9bd5;color:white;border-radius:8px;"
            f"padding:12px;text-align:center;'>"
            f"<div style='font-size:12px;'>Shift B</div>"
            f"<div style='font-size:22px;font-weight:bold;'>{lb:.1f}</div>"
            f"<div style='font-size:12px;'>MT</div></div>"
            f"</div>"
            f"<div style='text-align:center;margin-top:10px;font-size:13px;color:#64748b;'>"
            f"Total: <b>{la+lb:.1f} MT</b></div>"
            f"</div>",
            unsafe_allow_html=True)
    s2 = st.columns(3)
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
        # Production status: clear message like "Production Completed — Target Achieved"
        ach_pct = (L['ach'] / L['plan'] * 100 if L['plan'] else 0)
        if ach_pct >= 100:
            status_msg = "✅ Production Completed — Target Achieved"
            status_color = "#16a34a"
        elif ach_pct >= 90:
            status_msg = f"⚠️ Near Target — {ach_pct:.0f}% Achieved"
            status_color = "#c77700"
        elif L['ach'] > 0:
            status_msg = f"⚠️ Below Target — {ach_pct:.0f}% Achieved"
            status_color = "#c0392b"
        else:
            status_msg = "⏸️ No Production"
            status_color = "#64748b"
        kpi_card("Day Production", f"{L['ach']:,.1f}",
                 f"MT · plan {L['plan']:,.1f} MT "
                 f"({ach_pct:.0f}% of plan)",
                 AMBER)
        st.markdown(
            f"<div style='background:{status_color}; color:white; padding:10px 16px; "
            f"border-radius:8px; font-weight:bold; text-align:center; margin-top:8px;'>"
            f"{status_msg}</div>",
            unsafe_allow_html=True)
        # Shift-wise for the latest day (24hr)
        la, lb = L.get('shiftA', 0), L.get('shiftB', 0)
        st.markdown(
            f"<div style='border:1px solid #ccc; border-radius:8px; padding:10px; margin-top:8px;'>"
            f"<b>Shift-wise (24 Hr)</b><br>"
            f"Shift A: <b>{la:,.1f} MT</b> | Shift B: <b>{lb:,.1f} MT</b></div>",
            unsafe_allow_html=True)


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
        textposition="outside", textfont=dict(size=14, family="Arial Black"),
        hovertemplate="%{x}<br>Shift A: %{y:.1f} MT<extra></extra>"))
    fig.add_trace(go.Bar(
        x=xs, y=[d.get("shiftB", 0) for d in real_days], name="Shift B",
        marker_color="#5b9bd5",
        text=[f"{d.get('shiftB', 0):.1f}" for d in real_days],
        textposition="outside", textfont=dict(size=14, family="Arial Black"),
        hovertemplate="%{x}<br>Shift B: %{y:.1f} MT<extra></extra>"))
    fig.update_layout(title=dict(text="Shift-wise Production by Day (MT)", font=dict(family="Arial Black", size=16)),
                      barmode="group", height=340,
                      margin=dict(l=5, r=5, t=40, b=5),
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True, key="u-shift")
    u1 = st.columns(2)
    with u1[0]:
        fig = go.Figure(go.Bar(
            x=xs, y=[d["oee"] * 100 for d in real_days], marker_color=BLUE,
            text=[f"{d['oee'] * 100:.1f}%" for d in real_days],
            textposition="outside", textfont=dict(size=14, family="Arial Black")))
        fig.update_layout(title=dict(text="Date-wise OEE %", font=dict(family="Arial Black", size=16)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-oee")
    with u1[1]:
        fig = go.Figure(go.Bar(
            x=xs, y=[d["ach"] for d in real_days], marker_color=AMBER,
            text=[f"{d['ach']:.1f}" for d in real_days],
            textposition="outside", textfont=dict(size=14, family="Arial Black")))
        fig.update_layout(title=dict(text="Date-wise Production (MT)", font=dict(family="Arial Black", size=16)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-prod")
    u2 = st.columns(2)
    with u2[0]:
        # Exclude NPD (Non-Production Days) — days with zero production are not "downtime"
        dt_days = [d for d in real_days if d["ach"] > 0]
        dt_xs = [d["date"].strftime("%d-%b") for d in dt_days]
        fig = go.Figure(go.Bar(
            x=dt_xs, y=[d["dt"] / 60 for d in dt_days], marker_color=RED,
            text=[f"{d['dt'] / 60:.1f}h" for d in dt_days],
            textposition="outside", textfont=dict(size=14, family="Arial Black")))
        fig.update_layout(title=dict(text="Date-wise Downtime (hrs)", font=dict(family="Arial Black", size=16)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-dt")
        npd_count = len(real_days) - len(dt_days)
        if npd_count > 0:
            st.caption(f"ℹ️ {npd_count} NPD day(s) excluded (no production — not downtime)")
    with u2[1]:
        by_oee = sorted(real_days, key=lambda d: d["oee"], reverse=True)
        best = by_oee[:3]
        worst = by_oee[-3:][::-1]
        medals = ["🥇", "🥈", "🥉"]
        best_cards = "".join(
            f"<div style='background:linear-gradient(135deg,#16a34a,#22c55e);"
            f"color:white;border-radius:10px;padding:10px 14px;margin:6px 0;"
            f"display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-size:18px;'>{medals[i]} <b>{d['date'].strftime('%d-%b')}</b></span>"
            f"<span><b>{d['oee']*100:.1f}%</b> OEE · {d['ach']:.1f} MT</span></div>"
            for i, d in enumerate(best))
        worst_cards = "".join(
            f"<div style='background:linear-gradient(135deg,#dc2626,#ef4444);"
            f"color:white;border-radius:10px;padding:10px 14px;margin:6px 0;"
            f"display:flex;justify-content:space-between;align-items:center;'>"
            f"<span style='font-size:18px;'>⚠️ <b>{d['date'].strftime('%d-%b')}</b></span>"
            f"<span><b>{d['oee']*100:.1f}%</b> OEE · {d['ach']:.1f} MT</span></div>"
            for d in worst)
        st.markdown(
            f"<div style='font-size:15px;font-weight:bold;margin-bottom:4px;'>"
            f"🏆 Best 3 Days (by OEE)</div>{best_cards}",
            unsafe_allow_html=True)
        st.markdown(
            f"<div style='font-size:15px;font-weight:bold;margin:12px 0 4px;'>"
            f"📉 Weakest 3 Days (by OEE)</div>{worst_cards}",
            unsafe_allow_html=True)
        st.caption("Single CCR line — day-wise ranking shown instead of machine-wise.")

# ================= WEEKLY SUMMARY =================
st.markdown('<div class="section-band">Weekly Summary</div>', unsafe_allow_html=True)
_WEEK_DATES = {"Week 1": "28 Sep–04 Oct", "Week 2": "05–11 Oct",
                "Week 3": "12–18 Oct", "Week 4": "19–25 Oct",
                "Week 5": "26 Oct–01 Nov"}
if M["periods"]:
    wp = M["periods"]
    def _plabel(p):
        base = p['p'].strip()
        return f"{base} ({_WEEK_DATES.get(base, '')})" if base in _WEEK_DATES else base
    def _oee_color(v):
        if v >= 85: return "#16a34a"
        if v >= 70: return "#c77700"
        if v > 0: return "#dc2626"
        return "#94a3b8"
    rows = "".join(
        f"<tr style='border-bottom:1px solid #e2e8f0;'>"
        f"<td style='padding:10px;font-weight:bold;'>📅 {_plabel(p)}</td>"
        f"<td style='text-align:right;padding:10px;'>{p['avail']*100:.1f}%</td>"
        f"<td style='text-align:right;padding:10px;'>{p['perf']*100:.1f}%</td>"
        f"<td style='text-align:right;padding:10px;'>{p['qual']*100:.1f}%</td>"
        f"<td style='text-align:right;padding:10px;'>"
        f"<span style='background:{_oee_color(p['oee']*100)};color:white;"
        f"padding:4px 12px;border-radius:12px;font-weight:bold;'>"
        f"{p['oee']*100:.1f}%</span></td>"
        f"<td style='text-align:right;padding:10px;'>{p['plan']:.0f}</td>"
        f"<td style='text-align:right;padding:10px;font-weight:bold;'>{p['ach']:.1f}</td></tr>"
        for p in wp)
    st.markdown(
        f"<div style='background:white;border-radius:12px;padding:8px;"
        f"box-shadow:0 2px 8px rgba(0,0,0,0.08);overflow-x:auto;'>"
        f"<table style='width:100%;border-collapse:collapse;'>"
        f"<tr style='background:#1f4e78;color:white;'>"
        f"<th style='padding:12px;text-align:left;border-radius:8px 0 0 0;'>Period</th>"
        f"<th style='padding:12px;text-align:right;'>Avail</th>"
        f"<th style='padding:12px;text-align:right;'>Perf</th>"
        f"<th style='padding:12px;text-align:right;'>Qual</th>"
        f"<th style='padding:12px;text-align:right;'>OEE</th>"
        f"<th style='padding:12px;text-align:right;'>Plan (MT)</th>"
        f"<th style='padding:12px;text-align:right;border-radius:0 8px 0 0;'>Ach (MT)</th></tr>"
        f"{rows}</table></div>",
        unsafe_allow_html=True)
else:
    st.info("No weekly summary in the sheet yet.")

st.divider()
st.caption("Source: OEE_Data tab of the Google Sheet — updates appear automatically (cached ~15 min).")
