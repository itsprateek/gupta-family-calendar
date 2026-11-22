#!/usr/bin/env python3
"""
Generates a static weekly family calendar HTML page from iCloud public
calendar (webcal) feeds. Designed to run on a schedule via GitHub Actions
and be deployed to GitHub Pages. The output HTML is intentionally plain
(flexbox, no CSS Grid, no CSS custom properties, no JS) so it renders
correctly on old Safari/Chrome on iOS 9.

Outputs one page per week: index.html is the current week, w-1.html /
w1.html etc. are past/future weeks, linked with prev/next arrows so the
calendar can be browsed without any JavaScript.

v2 adds, on the current-week page only: Today / Tomorrow highlight cards,
a conflicts card, and a "Coming up - kids" strip. Events that the email
intake task put in events.json are merged in and tagged "email". Calendar
loading and conflict logic live in famcal.py (shared with notify.py).
"""

import html as html_mod
import os
import sys
from datetime import date, datetime, timedelta

import requests

import famcal
import ics_export
from famcal import PEOPLE, fmt_range, fmt_time, is_kid

TIMEZONE = famcal.TZ

# How many weeks of pages to generate around the current week.
WEEKS_BACK = 4
WEEKS_FORWARD = 8

# Current-week page layout limits (so everything fits on one iPad mini screen).
MAX_PER_DAY = 6
UPCOMING_DAYS = 14
UPCOMING_GROUPS = 7
UPCOMING_PER_GROUP = 3

# Weather location: Prosper, TX 75078 (page is static, so weather is
# fetched at build time from Open-Meteo — no API key needed).
WEATHER_LAT = 33.2362
WEATHER_LON = -96.8011

# Feed calendars (legend + show/hide toggles), built from famcal.PEOPLE so
# colors and env var names live in one place.
CALENDARS = [
    {"name": PEOPLE[k]["label"], "key": PEOPLE[k]["short"], "color": PEOPLE[k]["color"]}
    for k in famcal.FEED_KEYS
]

# Canonical order for the visible-calendar suffix in page filenames.
KEY_ORDER = "ayi"

HEADER_COLOR = "#1F4E4A"
BG_COLOR = "#EFF3F1"
PANEL_COLOR = "#FFFFFF"
LINE_COLOR = "#DCE4E2"
INK_COLOR = "#1B2B29"
INK_SOFT = "#5C6B68"
ALERT_COLOR = "#B3261E"

# ---------------------------------------------------------------- themes
# Seasonal / holiday look, picked from today's date at build time. Only the
# header, page tint, a thin stripe and a short greeting change; the layout
# is untouched. Emoji are old enough to render on iOS 9.

def _thanksgiving(y):
    first = date(y, 11, 1)
    return date(y, 11, 1 + (3 - first.weekday()) % 7 + 21)  # 4th Thursday


def _easter(y):
    a = y % 19
    b, c = divmod(y, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


# name: (greeting, header, page tint, button border, today's day name, stripe A, stripe B)
THEMES = {
    "default":      ("", "#1F4E4A", "#EFF3F1", "#5E807C", "#B9CFCC", "#1F4E4A", "#1F4E4A"),
    "winter":       ("&#10052;&#65039; Winter", "#2B4C6F", "#EDF2F8", "#6F8DB0", "#C3D4E8", "#BBD3EC", "#FFFFFF"),
    "valentines":   ("&#10084;&#65039; Happy Valentine&#8217;s Day", "#8E2F52", "#F8EEF2", "#C07A97", "#EFC6D6", "#E58BAA", "#FFFFFF"),
    "stpatricks":   ("&#9752;&#65039; Happy St. Patrick&#8217;s Day", "#1F5E3B", "#EEF5EF", "#6FA384", "#BEDDC9", "#E0B72E", "#2E8B57"),
    "easter":       ("&#128035; Happy Easter", "#6B5B95", "#F3F0F8", "#9D90C2", "#D6CDEC", "#F6D86B", "#F2A9C8"),
    "spring":       ("&#127800; Spring", "#4A7A5A", "#F0F5EF", "#7FA78D", "#C7DDCF", "#F0A6C4", "#BFE0A8"),
    "july4":        ("&#9733; Happy 4th of July &#9733;", "#1D3557", "#EEF1F6", "#6B84AB", "#C2CFE4", "#C8322B", "#FFFFFF"),
    "summer":       ("&#9728;&#65039; Summer", "#0F6B7A", "#EDF6F7", "#5FA3AE", "#B5DCE2", "#F2B544", "#7ACBD6"),
    "fall":         ("&#127810; Fall", "#7A4416", "#F6F0E8", "#B07C4E", "#E5CBB0", "#D9822B", "#8C5A2B"),
    "halloween":    ("&#127875; Happy Halloween", "#2B1B3D", "#F2EEF5", "#7C66A0", "#CDBFE3", "#F28C28", "#1A1A1A"),
    "thanksgiving": ("&#127809; Happy Thanksgiving", "#6E2A2A", "#F6EEE9", "#B07575", "#E6C3C3", "#D9822B", "#A8431F"),
    "christmas":    ("&#127876; Happy Holidays", "#1F5A3A", "#F1F4EF", "#6FA384", "#BEDDC9", "#C8322B", "#FFFFFF"),
    "newyear":      ("&#127878; Happy New Year", "#1B2440", "#EEF0F6", "#6B77A3", "#C3CAE6", "#C9A227", "#1B2440"),
}


def theme_for(today):
    y = today.year
    md = (today.month, today.day)
    tg, ea = _thanksgiving(y), _easter(y)
    if md >= (12, 27) or md <= (1, 3):
        name = "newyear"
    elif tg < today <= date(y, 12, 26):
        name = "christmas"          # from the day after Thanksgiving
    elif date(y, 11, 1) <= today <= tg:
        name = "thanksgiving"
    elif (10, 18) <= md <= (10, 31):
        name = "halloween"
    elif (6, 28) <= md <= (7, 4):
        name = "july4"
    elif ea - timedelta(days=7) <= today <= ea:
        name = "easter"
    elif (3, 10) <= md <= (3, 17):
        name = "stpatricks"
    elif (2, 7) <= md <= (2, 14):
        name = "valentines"
    elif today.month in (1, 2, 12):
        name = "winter"
    elif today.month in (3, 4, 5):
        name = "spring"
    elif today.month in (6, 7, 8):
        name = "summer"
    else:
        name = "fall"
    greeting, header, bg, btn, dayname, sa, sb = THEMES[name]
    return {"name": name, "greeting": greeting, "header": header, "bg": bg,
            "btn": btn, "dayname": dayname, "stripe_a": sa, "stripe_b": sb}


DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# WMO weather codes -> (emoji, label). Only old-Unicode emoji that render
# on iOS 9 (no iOS 9.1+ additions like the U+1F32x cloud series).
WEATHER_CODES = {
    0: ("☀️", "Clear"),
    1: ("⛅", "Mostly clear"),
    2: ("⛅", "Partly cloudy"),
    3: ("☁️", "Overcast"),
    45: ("☁️", "Fog"),
    48: ("☁️", "Fog"),
    51: ("☔", "Drizzle"),
    53: ("☔", "Drizzle"),
    55: ("☔", "Drizzle"),
    56: ("☔", "Drizzle"),
    57: ("☔", "Drizzle"),
    61: ("☔", "Rain"),
    63: ("☔", "Rain"),
    65: ("☔", "Heavy rain"),
    66: ("☔", "Freezing rain"),
    67: ("☔", "Freezing rain"),
    71: ("❄️", "Snow"),
    73: ("❄️", "Snow"),
    75: ("❄️", "Heavy snow"),
    77: ("❄️", "Snow"),
    80: ("☔", "Showers"),
    81: ("☔", "Showers"),
    82: ("☔", "Heavy showers"),
    85: ("❄️", "Snow showers"),
    86: ("❄️", "Snow showers"),
    95: ("⚡", "Thunderstorm"),
    96: ("⚡", "Thunderstorm"),
    99: ("⚡", "Thunderstorm"),
}


def esc(s):
    return html_mod.escape(s, quote=True)


def fetch_weather():
    """Current conditions from Open-Meteo, or None if the fetch fails
    (the page just renders without the weather chip that cycle)."""
    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": WEATHER_LAT,
                "longitude": WEATHER_LON,
                "current_weather": "true",
            },
            timeout=15,
        )
        resp.raise_for_status()
        cw = resp.json()["current_weather"]
        temp_c = float(cw["temperature"])
        emoji, label = WEATHER_CODES.get(int(cw.get("weathercode", -1)), ("", ""))
        return {
            "temp_c": round(temp_c),
            "temp_f": round(temp_c * 9 / 5 + 32),
            "emoji": emoji,
            "label": label,
        }
    except Exception as e:
        print(f"WARNING: weather fetch failed: {e}", file=sys.stderr)
        return None


def page_name(offset, visible):
    """visible is the set of calendar keys shown on this page. All-visible
    pages keep the plain names (index.html, w1.html) so existing bookmarks
    still work; other combinations get a suffix like -ai (Yuv hidden) or
    -none (everything hidden)."""
    base = "index" if offset == 0 else f"w{offset}"
    if len(visible) == len(CALENDARS):
        suffix = ""
    else:
        suffix = "-" + ("".join(k for k in KEY_ORDER if k in visible) or "none")
    return f"{base}{suffix}.html"


# ------------------------------------------------------------ visibility

def is_visible(ev, visible):
    """Feed events follow their legend toggle. Email items for both kids show
    while either kid is visible."""
    short = PEOPLE[ev["key"]]["short"]
    if short == "k":
        return "y" in visible or "i" in visible
    return short in visible


def time_label(ev):
    return "All day" if ev["all_day"] else ev["start"].strftime("%-I:%M %p")


def short_date(d):
    return f"{SHORT_DAYS[d.weekday()]} {d.strftime('%b')} {d.day}"


# ------------------------------------------------------- v2 page pieces

def week_chip(ev, conflicted):
    p = PEOPLE[ev["key"]]
    cls = "event cf" if conflicted else "event"
    warn = "&#9888; " if conflicted else ""
    badge = ' <span class="mail">email</span>' if ev["source"] == "email" else ""
    return (
        f'<div class="{cls}" style="background:{p["tint"]};'
        f'border-left-color:{p["color"]};color:{p["text"]}">'
        f'<span class="time">{warn}{time_label(ev)}</span>{esc(ev["title"])}{badge}</div>'
    )


def card_item(ev, conflicted):
    p = PEOPLE[ev["key"]]
    when = "" if ev["all_day"] else fmt_range(ev) + " "
    bits = [
        f'<span class="dot" style="background:{p["color"]}"></span>',
        f'<b style="color:{p["text"]}">{esc(p["label"])}</b> ',
        f'<span class="soft">{when}</span>{esc(ev["title"])}',
    ]
    if ev["notes"]:
        bits.append(f' <i class="note">&mdash; {esc(ev["notes"])}</i>')
    if ev["location"]:
        bits.append(f' <span class="soft">@ {esc(ev["location"])}</span>')
    if conflicted:
        bits.append(' <span class="warn">&#9888; overlaps</span>')
    return f'<li class="{"cf" if conflicted else ""}">{"".join(bits)}</li>'


def day_card(title, day, events, conflicted_ids, visible):
    todays = [e for e in events if e["date"] == day and is_visible(e, visible)]
    kids = [e for e in todays if is_kid(e)]
    adults = [e for e in todays if not is_kid(e)]
    out = [f'<div class="card"><h2>{title} <span>{short_date(day)}</span></h2>']
    if kids:
        out.append("<ul>" + "".join(card_item(e, id(e) in conflicted_ids) for e in kids[:5]) + "</ul>")
        if len(kids) > 5:
            out.append(f'<p class="none">+{len(kids) - 5} more</p>')
    else:
        out.append('<p class="none">Nothing on for the kids.</p>')
    if adults:
        names = "; ".join(
            ("" if e["all_day"] else fmt_time(e["start"]) + " ") + e["title"] for e in adults[:3]
        )
        extra = f" +{len(adults) - 3} more" if len(adults) > 3 else ""
        out.append(f'<p class="adults"><b>Adults:</b> {esc(names)}{extra}</p>')
    out.append("</div>")
    return "".join(out)


def build_extras(today, events, conflicts, visible):
    """Everything that depends on today's date and the show/hide selection:
    conflict markers, highlight band, and the kids' upcoming strip."""
    shown = [(a, b) for a, b in conflicts if is_visible(a, visible) and is_visible(b, visible)]
    conflicted_ids = {id(x) for pair in shown for x in pair}
    tomorrow = today + timedelta(days=1)

    soon = [(a, b) for a, b in shown if today <= a["date"] <= today + timedelta(days=7)]
    if soon:
        rows = "".join(
            f'<li><b>{short_date(a["date"])}</b> {esc(a["title"])} <i>{fmt_range(a)}</i> '
            f'vs {esc(b["title"])} <i>{fmt_range(b)}</i></li>'
            for a, b in soon[:4]
        )
        more = f'<p class="none">+{len(soon) - 4} more</p>' if len(soon) > 4 else ""
        conflict_card = (
            f'<div class="card alert"><h2>&#9888; Conflicts <span>next 7 days</span></h2>'
            f"<ul>{rows}</ul>{more}</div>"
        )
    else:
        conflict_card = ""  # nothing to warn about: no card, Today/Tomorrow get the room
    band = (
        day_card("Today", today, events, conflicted_ids, visible)
        + day_card("Tomorrow", tomorrow, events, conflicted_ids, visible)
        + conflict_card
    )

    up_start = tomorrow + timedelta(days=1)
    up_end = today + timedelta(days=UPCOMING_DAYS)
    upcoming = famcal.collapse_runs(
        [e for e in events if is_kid(e) and up_start <= e["date"] <= up_end and is_visible(e, visible)]
    )
    groups, order = {}, []
    for e in upcoming:
        if e["date"] not in groups:
            groups[e["date"]] = []
            order.append(e["date"])
        groups[e["date"]].append(e)
    parts = []
    for d in order[:UPCOMING_GROUPS]:
        chips = ""
        for e in groups[d][:UPCOMING_PER_GROUP]:
            p = PEOPLE[e["key"]]
            warn = "&#9888; " if id(e) in conflicted_ids else ""
            when = "" if e["all_day"] else fmt_time(e["start"]) + " "
            thru = ""
            if e.get("last") and e["last"] != e["date"]:
                thru = f' <span class="soft">thru {short_date(e["last"])}</span>'
            badge = ' <span class="mail">email</span>' if e["source"] == "email" else ""
            chips += (
                f'<div class="uchip" style="background:{p["tint"]};border-left-color:{p["color"]};'
                f'color:{p["text"]}"><b>{warn}{when}</b>{esc(e["title"])}{thru}{badge}</div>'
            )
        if len(groups[d]) > UPCOMING_PER_GROUP:
            chips += f'<div class="soft">+{len(groups[d]) - UPCOMING_PER_GROUP} more</div>'
        parts.append(f'<div class="ugroup"><div class="uhead">{short_date(d)}</div>{chips}</div>')
    if not parts:
        parts.append('<p class="none">Nothing planned for the kids yet.</p>')
    strip = '<div class="utitle">Kids<br>coming up</div>' + "".join(parts)

    return {"conflicted_ids": conflicted_ids, "band": band, "strip": strip}


# ---------------------------------------------------------------- render

def render_html(week_start, week_end, by_day, generated_at, offset, weather, visible,
                today, extras, errors):
    # Legend names are toggle links: tapping one links to this same week
    # with that calendar's visibility flipped (no JS, works on iOS 9).
    legend_items = ""
    for c in CALENDARS:
        is_on = c["key"] in visible
        flipped = visible - {c["key"]} if is_on else visible | {c["key"]}
        cls = "legend-item" if is_on else "legend-item off"
        legend_items += (
            f'<a class="{cls}" href="{page_name(offset, flipped)}">'
            f'<span class="dot" style="background:{c["color"]}"></span>{c["name"]}</a>'
        )

    week_range_label = f"{week_start.strftime('%b %-d').upper()} – {week_end.strftime('%b %-d, %Y').upper()}"

    compact = offset == 0  # current week gets the highlight band + upcoming strip
    conflicted_ids = extras["conflicted_ids"]

    day_columns = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        is_today = " today" if d == today else ""
        todays = [e for e in by_day.get(d, []) if is_visible(e, visible)]
        shown = todays[:MAX_PER_DAY] if compact else todays
        events_html = "".join(week_chip(e, id(e) in conflicted_ids) for e in shown)
        if compact and len(todays) > MAX_PER_DAY:
            events_html += f'<div class="more">+{len(todays) - MAX_PER_DAY} more</div>'
        if not events_html:
            events_html = '<div class="empty">—</div>'

        day_columns.append(f"""
    <div class="day{is_today}">
      <div class="day-head"><div class="day-name">{DAY_NAMES[i]}</div><div class="day-num">{d.day}</div></div>
      <div class="events">{events_html}</div>
    </div>""")

    days_html = "".join(day_columns)

    # Prev/next week navigation (plain links, no JS). Arrows dim out at
    # the edges of the generated range.
    if offset > -WEEKS_BACK:
        prev_html = f'<a class="nav-btn" href="{page_name(offset - 1, visible)}">&#8249;</a>'
    else:
        prev_html = '<span class="nav-btn dim">&#8249;</span>'
    if offset < WEEKS_FORWARD:
        next_html = f'<a class="nav-btn" href="{page_name(offset + 1, visible)}">&#8250;</a>'
    else:
        next_html = '<span class="nav-btn dim">&#8250;</span>'
    today_html = (
        f'<a class="nav-btn today-btn" href="{page_name(0, visible)}">TODAY</a>' if offset != 0 else ""
    )

    if weather:
        weather_html = (
            f'<div class="weather">{weather["emoji"]} {weather["label"]} '
            f'{weather["temp_f"]}°F / {weather["temp_c"]}°C</div>'
        )
    else:
        weather_html = ""

    # Current week reloads in place every 30 min; browsed weeks snap back
    # to the current week instead, so the fridge never gets stuck on a
    # past/future week. Both keep the current show/hide selection.
    refresh = "1800" if offset == 0 else f"1800;url={page_name(0, visible)}"

    updated_label = generated_at.strftime("%b %-d, %Y · %-I:%M %p %Z")

    warn_html = ""
    band_html = ""
    upcoming_html = ""
    if compact:
        if errors:
            warn_html = f'<div class="warnbar">Heads up: {esc(" | ".join(errors))}</div>'
        band_html = f'<div class="band">{extras["band"]}</div>'
        upcoming_html = f'<div class="upcoming">{extras["strip"]}</div>'

    theme = theme_for(today)
    # Greeting only on the current week (the fridge view); browsed weeks need the
    # header room for the TODAY button.
    festive_html = f'<div class="festive">{theme["greeting"]}</div>' if compact and theme["greeting"] else ""
    css = CSS
    for token, value in {
        "@BG@": theme["bg"], "@PANEL@": PANEL_COLOR, "@INK@": INK_COLOR, "@SOFT@": INK_SOFT,
        "@LINE@": LINE_COLOR, "@HEADER@": theme["header"], "@ALERT@": ALERT_COLOR,
        "@BTN@": theme["btn"], "@DAYNAME@": theme["dayname"],
        "@STRIPE_A@": theme["stripe_a"], "@STRIPE_B@": theme["stripe_b"],
    }.items():
        css = css.replace(token, value)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="{refresh}">
<title>Family Weekly Planner</title>
<style>{css}</style>
</head>
<body class="{"compact" if compact else ""}">

<div class="board">
  <div class="legend">
    <div class="legend-left">{legend_items}</div>
    {festive_html}
    <div class="legend-right">{weather_html}{prev_html}<div class="week-range">{week_range_label}</div>{next_html}{today_html}</div>
  </div>
  <div class="stripe"></div>
  {warn_html}
  {band_html}
  <div class="week">{days_html}
  </div>
  {upcoming_html}
  <div class="footer">Updated {updated_label}</div>
</div>

</body>
</html>
"""


CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: @BG@;
    font-family: Helvetica, Arial, sans-serif;
    color: @INK@;
    padding: 20px;
  }
  body.compact { padding: 10px; }

  .board {
    background: @PANEL@;
    border-radius: 4px;
    overflow: hidden;
  }

  .legend {
    display: flex;
    -webkit-box-orient: horizontal;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    border-bottom: 1px solid @LINE@;
    background: @HEADER@;
  }
  body.compact .legend { padding: 8px 20px; }
  .legend-left { display: flex; align-items: center; }
  .festive {
    flex: 1;
    text-align: center;
    font-size: 15px;
    font-weight: bold;
    color: #FFFFFF;
    letter-spacing: 0.3px;
    padding: 0 10px;
    white-space: nowrap;
  }
  .stripe {
    height: 5px;
    background: @STRIPE_A@;
    background-image: repeating-linear-gradient(135deg, @STRIPE_A@ 0, @STRIPE_A@ 8px, @STRIPE_B@ 8px, @STRIPE_B@ 16px);
  }
  .legend-right { display: flex; align-items: center; }
  .legend-item {
    display: flex;
    align-items: center;
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    margin-right: 20px;
    padding: 6px 0;
    text-decoration: none;
  }
  .legend-item.off {
    opacity: 0.45;
    text-decoration: line-through;
  }
  .dot {
    width: 11px;
    height: 11px;
    border-radius: 50%;
    margin-right: 8px;
    display: inline-block;
  }
  .weather {
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    margin-right: 14px;
    white-space: nowrap;
  }
  .week-range {
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    letter-spacing: 0.5px;
    margin: 0 12px;
    white-space: nowrap;
  }
  .nav-btn {
    display: block;
    padding: 4px 16px;
    border: 1px solid @BTN@;
    border-radius: 3px;
    color: #E4EEED;
    font-size: 18px;
    font-weight: bold;
    line-height: 1.2;
    text-decoration: none;
  }
  .nav-btn.dim { opacity: 0.35; }
  .today-btn { font-size: 12px; padding: 7px 12px; margin-left: 12px; letter-spacing: 1px; }

  .warnbar { background: #FFF3CD; color: #7A5A00; padding: 4px 20px; font-size: 12px; }

  /* v2: highlight band (current week only) */
  .band { display: flex; padding: 8px 8px 4px 8px; border-bottom: 1px solid @LINE@; }
  .card {
    flex: 1;
    min-width: 0;
    margin: 0 4px;
    padding: 7px 10px;
    border: 1px solid @LINE@;
    border-radius: 4px;
    height: 150px;
    overflow: hidden;
    background: #FAFBFA;
  }
  .card h2 { font-size: 13px; color: @HEADER@; margin-bottom: 4px; }
  .card h2 span { font-weight: normal; color: @SOFT@; font-size: 12px; }
  .card ul { list-style: none; }
  .card li { font-size: 12.5px; line-height: 1.25; margin-bottom: 3px; }
  .card li.cf { background: #FDECEA; border-radius: 3px; }
  .card .dot { width: 8px; height: 8px; margin-right: 4px; }
  .soft { color: @SOFT@; font-size: 11.5px; }
  .note { color: #8A4B00; }
  .warn { color: @ALERT@; font-weight: bold; font-size: 11.5px; }
  .none { font-size: 12.5px; color: @SOFT@; margin: 2px 0; }
  .adults { font-size: 11.5px; margin-top: 4px; padding-top: 3px; border-top: 1px solid @LINE@; }
  .card.alert { background: #FFF6F5; border-color: #E8B4AF; }
  .card.alert h2 { color: @ALERT@; }

  .week {
    display: flex;
  }
  .day {
    flex: 1;
    border-right: 1px solid @LINE@;
    min-height: 560px;
    display: flex;
    flex-direction: column;
  }
  body.compact .day { min-height: 0; }
  .day:last-child { border-right: none; }

  .day-head {
    padding: 14px 8px 10px;
    text-align: center;
    border-bottom: 1px solid @LINE@;
  }
  body.compact .day-head { padding: 6px 8px 5px; }
  .day-name {
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
    color: @SOFT@;
  }
  .day-num {
    font-size: 24px;
    font-weight: bold;
    margin-top: 2px;
  }
  body.compact .day-num { font-size: 20px; margin-top: 0; }
  .day.today .day-head { background: @HEADER@; }
  .day.today .day-name { color: @DAYNAME@; }
  .day.today .day-num { color: #FFFFFF; }

  .events {
    padding: 10px 8px;
    flex: 1;
  }
  body.compact .events { padding: 6px 6px; height: 292px; overflow: hidden; flex: none; }
  .event {
    border-radius: 3px;
    padding: 6px 8px;
    font-size: 13px;
    line-height: 1.35;
    font-weight: 500;
    border-left: 3px solid;
    margin-bottom: 6px;
  }
  body.compact .event { padding: 4px 6px; margin-bottom: 4px; font-size: 12.5px; line-height: 1.25; }
  .event.cf { outline: 2px solid #D93025; }
  .event .time {
    display: block;
    font-size: 10.5px;
    font-weight: bold;
    margin-bottom: 1px;
  }
  .mail {
    font-size: 9px;
    text-transform: uppercase;
    color: @SOFT@;
    border: 1px solid #B8C4C1;
    border-radius: 3px;
    padding: 0 2px;
  }
  .more { font-size: 11px; color: @SOFT@; padding: 1px 3px; }
  .empty {
    color: @LINE@;
    text-align: center;
    padding-top: 20px;
    font-size: 13px;
  }

  /* v2: kids' upcoming strip (current week only) */
  .upcoming {
    display: flex;
    padding: 6px 8px;
    height: 112px;
    overflow: hidden;
    border-top: 1px solid @LINE@;
    background: #FAFBFA;
  }
  .utitle { width: 72px; font-size: 12px; font-weight: bold; color: @HEADER@; padding-top: 2px; }
  .ugroup { width: 138px; margin-right: 8px; }
  .uhead { font-size: 10.5px; font-weight: bold; color: @SOFT@; text-transform: uppercase; margin-bottom: 2px; }
  .uchip {
    border-left: 3px solid;
    border-radius: 3px;
    padding: 2px 5px;
    margin-bottom: 3px;
    font-size: 11.5px;
    line-height: 1.2;
  }

  .footer {
    padding: 10px 24px;
    font-size: 11px;
    color: @SOFT@;
    border-top: 1px solid @LINE@;
    background: #FAFBFA;
  }
  body.compact .footer { padding: 5px 20px; }
"""


def main():
    now = famcal.now_local()
    override = os.environ.get("CAL_TODAY")  # YYYY-MM-DD, for local testing only
    if override:
        now = datetime.fromisoformat(override + "T08:00:00").replace(tzinfo=TIMEZONE)
    today = now.date()
    current_week_start = today - timedelta(days=today.weekday())  # Monday

    range_start = current_week_start - timedelta(weeks=WEEKS_BACK)
    range_end = current_week_start + timedelta(weeks=WEEKS_FORWARD, days=6)

    events, errors, feeds_ok = famcal.load_range(
        range_start, range_end, os.environ.get("EVENTS_JSON", "events.json")
    )
    for e in errors:
        print(f"WARNING: {e}", file=sys.stderr)
    if feeds_ok == 0:
        print("ERROR: all calendar feeds failed; keeping the previously deployed page.", file=sys.stderr)
        sys.exit(1)

    by_day = {}
    for ev in events:
        by_day.setdefault(ev["date"], []).append(ev)
    conflicts = famcal.find_conflicts(events)
    weather = fetch_weather()

    # One page per week per show/hide combination (2^3 = 8 combos), so the
    # legend toggles work as plain links with no JavaScript.
    combos = [
        frozenset(k for j, k in enumerate(KEY_ORDER) if bits >> j & 1)
        for bits in range(2 ** len(CALENDARS))
    ]
    extras_by_combo = {v: build_extras(today, events, conflicts, v) for v in combos}

    out_dir = sys.argv[1] if len(sys.argv) > 1 else "output"
    os.makedirs(out_dir, exist_ok=True)
    pages = 0
    for offset in range(-WEEKS_BACK, WEEKS_FORWARD + 1):
        week_start = current_week_start + timedelta(weeks=offset)
        week_end = week_start + timedelta(days=6)
        for visible in combos:
            page = render_html(week_start, week_end, by_day, now, offset, weather, visible,
                               today, extras_by_combo[visible], errors)
            with open(os.path.join(out_dir, page_name(offset, visible)), "w") as f:
                f.write(page)
            pages += 1

    # Calendar-app feed of the email events (with alerts). Never fatal.
    try:
        ics_export.write_feed(out_dir, os.environ.get("EVENTS_JSON", "events.json"))
    except Exception as exc:
        print(f"WARNING: school-events feed skipped ({exc})", file=sys.stderr)

    print(f"Generated {pages} pages ({range_start} to {range_end}), "
          f"weather={'ok' if weather else 'unavailable'}, "
          f"{sum(1 for e in events if e['source'] == 'email')} email events, "
          f"{len(conflicts)} conflicts")


if __name__ == "__main__":
    main()
