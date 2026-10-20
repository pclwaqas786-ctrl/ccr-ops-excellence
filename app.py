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

# Period identity colors — same for day / month / year everywhere in the app
DAY_C = "#f59e0b"    # 24 Hr (amber)
MONTH_C = "#1f4e78"  # MTD (blue)
YEAR_C = "#16a34a"   # YTD (green)

st.set_page_config(page_title="Ops Excellence Dash Board", layout="wide")

# ---------------------------------------------------------------- data ----
@st.cache_data(ttl=900)
def fetch_sheet(buster=None):
    url = "https://raw.githubusercontent.com/pclwaqas786-ctrl/ccr-ops-excellence/data/data.json"
    if buster:
        # Cache-buster: bypass GitHub CDN + ensure fresh fetch on manual refresh
        url += f"?t={buster}"
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
    mt = d.get("month_tab") or {}
    yr = d.get("yearly") or {}
    amt = d.get("all_month_tabs") or {}
    return {"fetched_at": fetched, "rows": rows,
            "month_tab": mt.get("values", []) or [],
            "month_title": mt.get("title", "") or "",
            "all_month_tabs": {k: (v.get("values", []) or [])
                               for k, v in amt.items()},
            "yearly": yr.get("values", []) or []}


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
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return datetime.datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
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


REASON_NAMES = ["Raw Material Shortage", "Power Failure", "Process / Setup",
                "EBD / MBD", "Consumables Shortage", "Planning Advice",
                "Equipment Failure"]


def parse_month_tab(values):
    """Current month tab (e.g. 'Oct 26'): per-day A/B shift MT, Summary text,
    downtime-by-reason minutes (cols 13-19) and status."""
    out = []
    if not values:
        return out
    for r in values[1:]:
        r = list(r) + [None] * (24 - len(r))
        dt = parse_date(r[0])
        if not dt:
            continue
        out.append({"date": dt,
                    "a": num(r[20]), "b": num(r[21]),
                    "summary": str(r[22] or "").strip(),
                    "status": str(r[11] or ""),
                    "reasons": [num(r[i]) for i in range(13, 20)]})
    return out


def downtime_details(month_values):
    """Per-reason downtime with day-wise summary texts.
    Returns [{name, hours, items: [(date_str, summary, hrs), ...]}],
    biggest reason first, zero reasons hidden."""
    parsed = parse_month_tab(month_values)
    out = [{"name": n, "hours": 0.0, "items": []} for n in REASON_NAMES]
    for d in parsed:
        ds = d["date"].strftime("%d-%b")
        for i, mins in enumerate(d["reasons"]):
            if mins > 0:
                h = mins / 60.0
                out[i]["hours"] += h
                out[i]["items"].append((ds, d["summary"], h))
    return sorted([o for o in out if o["hours"] > 0.05],
                  key=lambda x: x["hours"], reverse=True)


def ytd_downtime_details(all_tabs):
    """Aggregate downtime_details across all monthly tabs (Jul-now)."""
    agg = {}
    for title in sorted(all_tabs.keys(), key=month_sort_key):
        for det in downtime_details(all_tabs[title]):
            a = agg.setdefault(det["name"],
                               {"name": det["name"], "hours": 0.0, "items": []})
            a["hours"] += det["hours"]
            a["items"].extend(det["items"])
    return sorted(agg.values(), key=lambda x: x["hours"], reverse=True)


def parse_yearly(values):
    """Yearly tab: YTD downtime-by-reason minutes summed over completed
    month rows (ignores the sheet's own Total row)."""
    names = list(REASON_NAMES)
    sums = [0.0] * 7
    if values and len(values) > 2:
        hdr = list(values[1]) + [None] * 20
        for i in range(7):
            nm = str(hdr[13 + i] or "").strip()
            if nm:
                names[i] = nm
        for r in values[2:]:
            r = list(r) + [None] * 20
            lab = str(r[0] or "").strip()
            if not re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2,4}$",
                            lab, re.I):
                continue
            if num(r[1]) <= 0 and "complet" not in str(r[11] or "").lower():
                continue
            for i in range(7):
                sums[i] += num(r[13 + i])
    return {"names": names, "reasons": sums}


def detect_campaigns(values, min_gap=3):
    """Detect production campaigns from a monthly tab.
    A campaign = consecutive days with Achieved > 0. A gap of min_gap+
    zero-days ends the campaign; the next production day starts a new one.
    Returns list of dicts: {n, d0, d1, ndays, target, achieved}."""
    days = []
    for idx, r in enumerate(values[1:], start=2):
        r = list(r) + [None] * 24
        lab = str(r[0] or "").strip()
        if lab.lower() == "monthly":
            break  # monthly total row
        if not lab:
            continue
        day_no = idx - 1  # row 2 = day 1
        days.append((day_no, num(r[1]), num(r[2])))
    camps, cur, gap = [], [], 0
    for d, t, a in days:
        if a > 0:
            if gap >= min_gap and cur:
                camps.append(cur)
                cur = []
            gap = 0
            cur.append((d, t, a))
        else:
            gap += 1
    if cur:
        camps.append(cur)
    out = []
    for ci, c in enumerate(camps, start=1):
        out.append({"n": ci, "d0": c[0][0], "d1": c[-1][0],
                    "ndays": len(c),
                    "target": sum(x[1] for x in c),
                    "achieved": sum(x[2] for x in c)})
    return out


def month_sort_key(title):
    m = re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
                 r"\s*-?\s*(\d{2,4})$", str(title).strip(), re.I)
    if not m:
        return (0, 0)
    yy = int(m.group(2))
    if yy < 100:
        yy += 2000
    return (yy, MON[m.group(1).lower()])


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
    st.plotly_chart(fig, use_container_width=True, key=key, config={'displayModeBar': False})


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
    st.plotly_chart(fig, use_container_width=True, key=key, config={'displayModeBar': False})


def mini_bar(labels, values, title, color, key, suffix="%", hl=False):
    if "%" in suffix:
        txt = [f"{v:.0f}%" for v in values]
    else:
        txt = [f"{v:,.0f}" for v in values]
    fig = go.Figure(go.Bar(
        x=labels, y=values, marker_color=color,
        text=txt, textposition="outside",
        textfont=dict(size=11, color="#334155"),
        cliponaxis=False,
        hovertemplate="%{x}: %{y:,.1f}" + suffix + "<extra></extra>"))
    kw = dict(title=dict(text=title, font=dict(size=15, family="Arial Black")),
              height=230, margin=dict(l=5, r=5, t=50, b=5))
    if hl:
        kw["shapes"] = [dict(type="rect", xref="paper", yref="paper", x0=0, y0=0,
                             x1=1, y1=1, line=dict(color="#eab308", width=3))]
    fig.update_layout(**kw)
    st.plotly_chart(fig, use_container_width=True, key=key, config={'displayModeBar': False})


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
            border-radius:10px; padding:16px 24px; margin-bottom:8px;
            box-shadow:0 2px 8px rgba(0,0,0,0.15);
            display:flex; align-items:center; gap:18px;">
<img src="data:image/png;base64,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"
     style="width:72px; height:72px; object-fit:contain; background:#ffffff;
            border-radius:8px; padding:6px; flex-shrink:0;">
<div style="flex:1;">
<div style="font-size:28px; font-weight:800; color:#ffffff; text-align:center;
            letter-spacing:0.5px;">CCR &mdash; Ops Excellence Dashboard</div>
<div style="font-size:14px; color:#ffe9c4; text-align:center; margin-top:6px;">
Copper Casting &amp; Rolling Plant &mdash; Daily OEE, Production &amp; Downtime Performance</div>
</div>
</div>
""", unsafe_allow_html=True)

try:
    data = fetch_sheet(st.session_state.get("_buster"))
except Exception as e:
    st.error("Could not load data from the sheet. Please press Refresh / Rerun. "
             f"({type(e).__name__})")
    st.stop()

M = parse_model(data["rows"])
mtd = M["mtd"]

# ---- join authoritative shift + summary data from the monthly tab ----
# (OEE_Data cols O/P are unreliable; the month tab holds real A/B shift MT
# and the per-day Summary text where the reason is written.)
month_rows = parse_month_tab(data["month_tab"])
_month_by_date = {m["date"].date(): m for m in month_rows}
_final_dates = {d["date"].date() for d in M["daily"]}
for _d in M["daily"]:
    _m = _month_by_date.get(_d["date"].date())
    if _m:
        _d["shiftA"] = _m["a"]
        _d["shiftB"] = _m["b"]
        _d["summary"] = _m["summary"]
# MTD downtime by reason (minutes -> hours), finalized dates only
mtd_reasons = [0.0] * 7
for _m in month_rows:
    if _m["date"].date() in _final_dates:
        for _i in range(7):
            mtd_reasons[_i] += _m["reasons"][_i]
ytd_dt = parse_yearly(data["yearly"])


def _period_pill(text, color):
    st.markdown(
        f"<div style='display:inline-block;background:{color};color:#ffffff;"
        f"font-weight:800;font-size:16px;padding:6px 20px;border-radius:20px;"
        f"margin:16px 0 6px 0;letter-spacing:.5px;'>{text}</div>",
        unsafe_allow_html=True)
st.caption(f"Updated {data['fetched_at']} · auto-refreshes every ~15 min")
if st.button("↻ Refresh data"):
    import time as _time
    # New buster => brand-new cache entry + CDN bypass => guaranteed fresh
    st.session_state["_buster"] = str(int(_time.time()))
    st.rerun()

FY = fy_label()
tgt = M["target"] or 4800
ytd = sum(m["prod"] for m in M["trend"]) if M["trend"] else 0

# ---- targets header: target + achieved for year / month / day ----
# Period identity colors: YEAR = green, MONTH = blue, DAY = amber (same everywhere)
def _target_card(title, target, achieved, pct_note, grad, warn=None):
    warn_html = ""
    if warn:
        w = str(warn).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if len(w) > 160:
            w = w[:157] + "..."
        warn_html = (f'<div style="font-size:12px;color:#fff;background:rgba(0,0,0,.25);'
                     f'border-radius:6px;padding:6px 8px;margin-top:8px;text-align:left;">'
                     f"&#9888; Reason: {w}</div>")
    st.markdown(
        f"""<div style="background:{grad}; border-radius:10px; padding:16px 20px;
             box-shadow:0 2px 8px rgba(0,0,0,0.18); text-align:center;">
        <div style="font-size:13px; font-weight:700; color:#e8f8ef;
             letter-spacing:1px; text-transform:uppercase;">{title}</div>
        <div style="font-size:34px; font-weight:800; color:#ffffff;
             margin:4px 0;">{target}</div>
        <div style="font-size:12px; color:#d5f5e3;">Value tons &middot; target</div>
        <div style="font-size:16px; font-weight:700; color:#ffffff; margin-top:10px;
             border-top:1px solid rgba(255,255,255,.35); padding-top:8px;">Achieved: {achieved}</div>
        <div style="font-size:12px; color:#e8f8ef;">{pct_note}</div>{warn_html}</div>""",
        unsafe_allow_html=True)

_ytd_ach = ytd
_mtd_plan = mtd.get("plan", 0) or 0
_mtd_ach = mtd.get("ach", 0) or 0
_last = M["daily"][-1] if M["daily"] else None

tc = st.columns(3)
with tc[0]:
    _yp = (_ytd_ach / tgt * 100) if tgt else 0
    _target_card("Yearly Target", f"{tgt:,.0f}", f"{_ytd_ach:,.1f} MT",
                 f"{_yp:.1f}% of target",
                 "linear-gradient(135deg, #0d6e3f 0%, #27ae60 100%)")
with tc[1]:
    _mp = (_mtd_ach / _mtd_plan * 100) if _mtd_plan else 0
    _target_card("Monthly Target", f"{_mtd_plan:,.1f}", f"{_mtd_ach:,.1f} MT",
                 f"{_mp:.1f}% of plan",
                 "linear-gradient(135deg, #1f4e78 0%, #2e9bd5 100%)")
with tc[2]:
    if _last:
        _dp = _last["plan"] or 0
        _da = _last["ach"] or 0
        _pct = (_da / _dp * 100) if _dp else 0
        _warn = None
        if _pct < 100:
            # reason comes from the sheet's Summary column (monthly tab)
            _rsn = (_last.get("summary") or "").strip()
            _warn = _rsn if _rsn else "Reason not entered in the sheet yet"
        _target_card("Day Target", f"{_dp:,.1f}", f"{_da:,.1f} MT",
                     f"{_pct:.0f}% of plan \u00b7 {_last['date'].strftime('%d-%b')}",
                     "linear-gradient(135deg, #b45309 0%, #f59e0b 100%)",
                     warn=_warn)
    else:
        _target_card("Day Target", "\u2014", "\u2014", "No finalized day yet",
                     "linear-gradient(135deg, #b45309 0%, #f59e0b 100%)")

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

# ---- 24HR row (amber = day) ----
_period_pill("24 HR", DAY_C)
if last2:
    d2dates = " & ".join(d["date"].strftime("%d-%b") for d in last2)
    st.caption(f"📅 Last 2 finalized days: {d2dates}")
    _oee_row6("24 Hr", [
        ("bar", {"title": "24 Hr OEE", "labels": d2lbl,
                  "values": [d["oee"]*100 for d in last2],
                  "color": DAY_C, "key": "h24-oee"}),
        ("bar", {"title": "24 Hr Efficiency", "labels": d2lbl,
                  "values": [d["perfP"]*100 for d in last2],
                  "color": DAY_C, "key": "h24-eff"}),
        ("bar", {"title": "24 Hr Quality", "labels": d2lbl,
                  "values": [d["qualP"]*100 for d in last2],
                  "color": DAY_C, "key": "h24-qual"}),
        ("bar", {"title": "24 Hr Availability", "labels": d2lbl,
                  "values": [d["availP"]*100 for d in last2],
                  "color": DAY_C, "key": "h24-avail"}),
        ("bar", {"title": "24 Hr Production", "labels": d2lbl,
                  "values": [d["ach"] for d in last2],
                  "color": DAY_C, "key": "h24-prod", "suffix": " MT"}),
        ("bar", {"title": "24 Hr Tonnage", "labels": d2lbl,
                  "values": [d["ach"] for d in last2],
                  "color": DAY_C, "key": "h24-ton", "suffix": " MT"}),
    ])
else:
    st.info("No finalized daily data in the sheet yet.")


_period_pill("MTD", MONTH_C)
_m2 = [m for m in trend2 if m["oee"] > 0]
_m2lbl = [m["m"] for m in _m2] or ["Oct-26"]
st.caption(f"📅 Last 2 months: {' & '.join(_m2lbl)}")
_oee_row6("MTD", [
    ("bar", {"title": "MTD OEE", "labels": _m2lbl,
              "values": [m["oee"]*100 for m in _m2] or [mtd.get("oeeP",0)*100],
              "color": MONTH_C, "key": "mtd-oee"}),
    ("bar", {"title": "MTD Efficiency", "labels": _m2lbl,
              "values": [m["perf"]*100 for m in _m2] or [mtd.get("perfP",0)*100],
              "color": MONTH_C, "key": "mtd-eff"}),
    ("bar", {"title": "MTD Quality", "labels": _m2lbl,
              "values": [m["qual"]*100 for m in _m2] or [mtd.get("qualP",0)*100],
              "color": MONTH_C, "key": "mtd-qual"}),
    ("bar", {"title": "MTD Availability", "labels": _m2lbl,
              "values": [m["avail"]*100 for m in _m2] or [mtd.get("availP",0)*100],
              "color": MONTH_C, "key": "mtd-avail"}),
    ("bar", {"title": "MTD Production", "labels": t2lbl, "values": t2prod,
              "color": MONTH_C, "key": "mtd-prod", "suffix": " MT"}),
    ("bar", {"title": "MTD Tonnage", "labels": ["Oct-26"], "values": [mtd.get("ach",0)],
              "color": MONTH_C, "key": "mtd-ton", "suffix": " MT"}),
])


_period_pill(f"YTD ({FY})", YEAR_C)
_my = [m for m in trendY if m["oee"] > 0]
_mylbl = [m["m"] for m in _my] or ["Oct-26"]
_oee_row6("YTD", [
    ("bar", {"title": "YTD OEE", "labels": _mylbl,
              "values": [m["oee"]*100 for m in _my] or [mtd.get("oeeP",0)*100],
              "color": YEAR_C, "key": "ytd-oee"}),
    ("bar", {"title": "YTD Efficiency", "labels": _mylbl,
              "values": [m["perf"]*100 for m in _my] or [mtd.get("perfP",0)*100],
              "color": YEAR_C, "key": "ytd-eff"}),
    ("bar", {"title": "YTD Quality", "labels": _mylbl,
              "values": [m["qual"]*100 for m in _my] or [mtd.get("qualP",0)*100],
              "color": YEAR_C, "key": "ytd-qual"}),
    ("bar", {"title": "YTD Availability", "labels": _mylbl,
              "values": [m["avail"]*100 for m in _my] or [mtd.get("availP",0)*100],
              "color": YEAR_C, "key": "ytd-avail"}),
    ("bar", {"title": "YTD Production", "labels": tylbl, "values": typrod,
              "color": YEAR_C, "key": "ytd-prod", "suffix": " MT"}),
    ("bar", {"title": "YTD Tonnage", "labels": [FY], "values": [ytd],
              "color": YEAR_C, "key": "ytd-ton", "suffix": " MT"}),
])


# ================= 24 HRS SUMMARY (amber = day) =================
st.markdown('<div class="section-band" style="background:linear-gradient(135deg,#b45309,#f59e0b);">24 Hrs Summary</div>', unsafe_allow_html=True)
if last2:
    L = last2[-1]
    st.caption(f"Latest finalized day: {L['date'].strftime('%d-%b-%Y')}")
    # Day KPI cards row — fills the 24 Hrs Summary header area
    _dc = st.columns(3)
    with _dc[0]:
        kpi_card("Production (24 Hr)", f"{L['ach']:.1f} MT",
                 f"Plan {L['plan']:.1f} MT", DAY_C)
    with _dc[1]:
        kpi_card("OEE (24 Hr)", f"{L['oee'] * 100:.1f}%",
                 "Overall Equipment Effectiveness", DAY_C)
    with _dc[2]:
        kpi_card("Availability", f"{L['availP'] * 100:.1f}%",
                 f"Run {L['run'] / 60:.1f} hrs / Avail {L['avail'] / 60:.1f} hrs",
                 DAY_C)
    _dc2 = st.columns(3)
    with _dc2[0]:
        kpi_card("Performance", f"{L['perfP'] * 100:.1f}%",
                 "Speed vs ideal rate", DAY_C)
    with _dc2[1]:
        kpi_card("Quality", f"{L['qualP'] * 100:.1f}%",
                 f"Good length {L['good']:.1f} MT", DAY_C)
    with _dc2[2]:
        kpi_card("Losses Time (24 Hr)", f"{L['dt'] / 60:.1f} hrs",
                 f"Downtime · Run {L['run'] / 60:.1f} hrs", "#b91c1c")
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
        st.plotly_chart(fig, use_container_width=True, key="s-shift-prod", config={'displayModeBar': False})
        st.caption(f"Sum of finalized daily entries — {d0} to {d1}")
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
            f"<div style='flex:1;background:#b45309;color:white;border-radius:8px;"
            f"padding:12px;text-align:center;'>"
            f"<div style='font-size:12px;'>Shift A</div>"
            f"<div style='font-size:22px;font-weight:bold;'>{la:.1f}</div>"
            f"<div style='font-size:12px;'>MT</div></div>"
            f"<div style='flex:1;background:#f59e0b;color:white;border-radius:8px;"
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
            f"<div style='font-size:12px;color:#64748b'>Sum of finalized daily entries — {d0} to {d1}</div>",
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
    _sa_vals = [d.get("shiftA", 0) for d in real_days]
    _sb_vals = [d.get("shiftB", 0) for d in real_days]
    fig.add_trace(go.Bar(
        x=xs, y=_sa_vals, name="Shift A",
        marker_color="#b45309",
        text=[f"{v:.0f}" for v in _sa_vals],
        textposition="outside", textfont=dict(size=8, color="#334155"),
        cliponaxis=False,
        hovertemplate="%{x}<br>Shift A: %{y:.1f} MT<extra></extra>"))
    fig.add_trace(go.Bar(
        x=xs, y=_sb_vals, name="Shift B",
        marker_color="#fbbf24",
        text=[f"{v:.0f}" for v in _sb_vals],
        textposition="outside", textfont=dict(size=8, color="#334155"),
        cliponaxis=False,
        hovertemplate="%{x}<br>Shift B: %{y:.1f} MT<extra></extra>"))
    fig.update_layout(title=dict(text="Shift-wise Production by Day (MT)", font=dict(family="Arial Black", size=16)),
                      barmode="group", height=340,
                      margin=dict(l=5, r=5, t=40, b=5),
                      legend=dict(orientation="h", y=1.08))
    st.plotly_chart(fig, use_container_width=True, key="u-shift", config={'displayModeBar': False})
    u1 = st.columns(2)
    with u1[0]:
        _oee_vals = [d["oee"] * 100 for d in real_days]
        fig = go.Figure(go.Bar(
            x=xs, y=_oee_vals, marker_color=DAY_C,
            text=[f"{v:.0f}%" for v in _oee_vals],
            textposition="outside", textfont=dict(size=9, color="#334155"),
            cliponaxis=False,
            hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
        fig.update_layout(title=dict(text="Date-wise OEE %", font=dict(family="Arial Black", size=16)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-oee", config={'displayModeBar': False})
    with u1[1]:
        _prod_vals = [d["ach"] for d in real_days]
        fig = go.Figure(go.Bar(
            x=xs, y=_prod_vals, marker_color=DAY_C,
            text=[f"{v:.0f}" for v in _prod_vals],
            textposition="outside", textfont=dict(size=9, color="#334155"),
            cliponaxis=False,
            hovertemplate="%{x}: %{y:.1f} MT<extra></extra>"))
        fig.update_layout(title=dict(text="Date-wise Production (MT)", font=dict(family="Arial Black", size=16)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-prod", config={'displayModeBar': False})
    u2 = st.columns(1)
    with u2[0]:
        # Exclude NPD (Non-Production Days) — days with zero production are not "downtime"
        dt_days = [d for d in real_days if d["ach"] > 0]
        dt_xs = [d["date"].strftime("%d-%b") for d in dt_days]
        # Hover: show reason breakdown + summary text from the monthly tab
        _mt_by_date = {d["date"].strftime("%Y-%m-%d"): d
                       for d in parse_month_tab(data.get("month_tab", []))}
        _hover = []
        for d in dt_days:
            _dk = d["date"].strftime("%Y-%m-%d")
            _m = _mt_by_date.get(_dk)
            _hrs = d["dt"] / 60
            _t = (f"<b>{d['date'].strftime('%d-%b')}</b>"
                  f"<br>Downtime: {_hrs:.1f} hrs")
            if _m:
                _parts = [f"{REASON_NAMES[i]}: {mins/60:.1f}h"
                          for i, mins in enumerate(_m["reasons"]) if mins > 0]
                if _parts:
                    _t += "<br>" + "<br>".join(_parts)
                if _m["summary"]:
                    _t += f"<br><i>{_m['summary']}</i>"
            _hover.append(_t)
        _dt_vals = [d["dt"] / 60 for d in dt_days]
        fig = go.Figure(go.Bar(
            x=dt_xs, y=_dt_vals, marker_color=RED,
            text=[f"{v:.1f}" for v in _dt_vals],
            textposition="outside", textfont=dict(size=9, color="#334155"),
            cliponaxis=False,
            hovertext=_hover, hoverinfo="text"))
        fig.update_layout(title=dict(text="Date-wise Downtime (hrs)", font=dict(family="Arial Black", size=16)),
                          height=300, margin=dict(l=5, r=5, t=40, b=5))
        st.plotly_chart(fig, use_container_width=True, key="u-dt", config={'displayModeBar': False})
        npd_count = len(real_days) - len(dt_days)
        if npd_count > 0:
            st.caption(f"ℹ️ {npd_count} NPD day(s) excluded (no production — not downtime)")
    # ---- downtime by reason: monthly (blue) + yearly (green) ----
    # Downtime detail: wording with day-wise summaries (no bare bars).
    # Each reason expandable to show exactly what happened which day.
    def _reason_detail(title, details, color):
        st.markdown(
            f"<div style='font-size:15px;font-weight:bold;margin-bottom:4px;"
            f"color:{color};'>{title}</div>",
            unsafe_allow_html=True)
        if not details:
            st.info("No downtime recorded in this period.")
            return
        _total_dt = sum(d["hours"] for d in details)
        st.markdown(
            f"<div style='font-size:15px;font-weight:bold;color:#b91c1c;"
            f"margin:2px 0 2px 0;'>Total Downtime: {_total_dt:.1f} hrs</div>",
            unsafe_allow_html=True)
        top = details[0]
        st.markdown(
            f"<div style='font-size:13px;color:#475569;margin:2px 0 8px 0;'>"
            f"&#128736; Top downtime reason: <b>{top['name']}</b> &mdash; "
            f"<b>{top['hours']:.1f} hrs</b></div>",
            unsafe_allow_html=True)
        for det in details:
            with st.expander(f"{det['name']} — {det['hours']:.1f} hrs",
                             expanded=False):
                for ds, summ, h in det["items"]:
                    txt = f"• <b>{ds}</b> ({h:.1f}h)"
                    if summ:
                        txt += f": {summ}"
                    st.markdown(txt, unsafe_allow_html=True)

    u3 = st.columns(1)
    with u3[0]:
        _mtitle = (f" — {data['month_title']}" if data.get("month_title") else "")
        _reason_detail(f"MTD Downtime by Reason{_mtitle}",
                       downtime_details(data.get("month_tab", [])),
                       MONTH_C)
        st.markdown("<br>", unsafe_allow_html=True)
        _reason_detail(f"YTD Downtime by Reason — {FY}",
                       ytd_downtime_details(data.get("all_month_tabs", {})),
                       YEAR_C)

# ================= CAMPAIGN SUMMARY =================
st.markdown('<div class="section-band" style="background:linear-gradient(135deg,#1f4e78,#3b82c4);">Campaign Summary</div>', unsafe_allow_html=True)
st.caption("Auto-detected: consecutive production days = one campaign · 3+ day gap (No Plan) = new campaign.")

_amt = data.get("all_month_tabs", {})
_camp_rows = []
_camp_chart = []  # (label, target, achieved)
for _title in sorted(_amt.keys(), key=month_sort_key):
    _mlab = _title.replace(" ", "")
    for _c in detect_campaigns(_amt[_title]):
        _ap = (_c["achieved"] / _c["target"] * 100) if _c["target"] > 0 else 0.0
        _lab = f"{_mlab} C{_c['n']}"
        _camp_rows.append({
            "Month": _title,
            "Campaign": _c["n"],
            "Days": f"{_c['d0']}–{_c['d1']} ({_c['ndays']}d)",
            "Target (MT)": round(_c["target"], 1),
            "Achieved (MT)": round(_c["achieved"], 1),
            "Achv %": round(_ap, 1),
        })
        _camp_chart.append((_lab, round(_c["target"], 1),
                            round(_c["achieved"], 1), round(_ap, 1)))
if _camp_rows:
    st.dataframe(_camp_rows, use_container_width=True, hide_index=True)
    # Small Target vs Achieved bar chart per campaign
    _clabs = [c[0] for c in _camp_chart]
    _ct = [c[1] for c in _camp_chart]
    _ca = [c[2] for c in _camp_chart]
    _cp = [c[3] for c in _camp_chart]
    fig = go.Figure()
    fig.add_bar(x=_clabs, y=_ct, name="Target",
                marker_color="#93c5fd",
                text=[f"{v:.0f}" for v in _ct], textposition="outside",
                textfont=dict(size=10, color="#334155"), cliponaxis=False,
                hovertemplate="%{x}<br>Target: %{y:.1f} MT<extra></extra>")
    fig.add_bar(x=_clabs, y=_ca, name="Achieved",
                marker_color="#1f4e78",
                text=[f"{v:.0f}" for v in _ca], textposition="outside",
                textfont=dict(size=10, color="#334155"), cliponaxis=False,
                hovertemplate="%{x}<br>Achieved: %{y:.1f} MT<extra></extra>")
    fig.update_layout(
        title=dict(text="Campaign-wise Target vs Achieved (MT)",
                   font=dict(family="Arial Black", size=15)),
        barmode="group", height=320,
        margin=dict(l=5, r=5, t=45, b=5),
        legend=dict(orientation="h", yanchor="bottom", y=1.02,
                    xanchor="right", x=1),
        xaxis=dict(tickangle=-30))
    st.plotly_chart(fig, use_container_width=True, key="camp-chart", config={'displayModeBar': False})
else:
    st.info("No campaigns detected yet.")

st.divider()
st.caption("Source: OEE_Data tab of the Google Sheet — updates appear automatically (cached ~15 min).")
