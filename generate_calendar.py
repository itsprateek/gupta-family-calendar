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
"""

import html as html_mod
import os
import sys
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar
import recurring_ical_events

TIMEZONE = ZoneInfo("America/Chicago")

# How many weeks of pages to generate around the current week.
WEEKS_BACK = 4
WEEKS_FORWARD = 8

# Weather location: Prosper, TX 75078 (page is static, so weather is
# fetched at build time from Open-Meteo — no API key needed).
WEATHER_LAT = 33.2362
WEATHER_LON = -96.8011

# Each calendar: display name, accent color (hex), tint (light bg), env var
# holding the public ICS URL (converted from webcal:// to https:// before
# being stored as a GitHub Actions secret).
CALENDARS = [
    {
        "name": "Adults",
        "key": "a",
        "color": "#D9722C",
        "tint": "#FBEEE2",
        "text": "#8A4718",
        "env": "ADULTS_ICS_URL",
    },
    {
        "name": "Yuv",
        "key": "y",
        "color": "#7B5EA7",
        "tint": "#F0EBF7",
        "text": "#503B72",
        "env": "YUV_ICS_URL",
    },
    {
        "name": "Ivaan",
        "key": "i",
        "color": "#4E9A63",
        "tint": "#EBF4EC",
        "text": "#2E5F3B",
        "env": "IVAAN_ICS_URL",
    },
]

# Canonical order for the visible-calendar suffix in page filenames.
KEY_ORDER = "ayi"

HEADER_COLOR = "#1F4E4A"
BG_COLOR = "#EFF3F1"
PANEL_COLOR = "#FFFFFF"
LINE_COLOR = "#DCE4E2"
INK_COLOR = "#1B2B29"
INK_SOFT = "#5C6B68"

DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

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


def fetch_events_for_calendar(url, range_start, range_end):
    """Fetch and expand recurring events for one calendar within the date
    range (inclusive). Returns a list of (date, time_label, summary)
    tuples, or raises on network/parse failure so the caller can handle
    it per-calendar."""
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.text)

    # recurring_ical_events expects naive/aware datetimes; use midnight to
    # midnight across the range, inclusive of the last day.
    start_dt = datetime.combine(range_start, datetime.min.time(), tzinfo=TIMEZONE)
    end_dt = datetime.combine(range_end + timedelta(days=1), datetime.min.time(), tzinfo=TIMEZONE)

    occurrences = recurring_ical_events.of(cal).between(start_dt, end_dt)

    events = []
    for ev in occurrences:
        summary = str(ev.get("summary", "Untitled event"))
        dtstart = ev.get("dtstart").dt

        if isinstance(dtstart, datetime):
            if dtstart.tzinfo is None:
                # Floating time (no TZID) - iCloud typically means this in
                # the calendar's local time already, so attach our target
                # timezone directly rather than assuming UTC.
                local_dt = dtstart.replace(tzinfo=TIMEZONE)
            else:
                local_dt = dtstart.astimezone(TIMEZONE)
            event_date = local_dt.date()
            time_label = local_dt.strftime("%-I:%M %p")
        else:
            # all-day event (date, not datetime)
            event_date = dtstart
            time_label = "All day"

        if range_start <= event_date <= range_end:
            events.append((event_date, time_label, summary))

    return events


def fetch_all_events(range_start, range_end):
    """Fetch every calendar once across the whole page range.
    Returns dict: date -> list of {time, summary, color, tint, text}."""
    by_day = {}

    for cal_info in CALENDARS:
        url = os.environ.get(cal_info["env"])
        if not url:
            print(f"WARNING: no URL set for {cal_info['name']} ({cal_info['env']}), skipping", file=sys.stderr)
            continue
        try:
            events = fetch_events_for_calendar(url, range_start, range_end)
        except Exception as e:
            print(f"WARNING: failed to fetch {cal_info['name']}: {e}", file=sys.stderr)
            continue

        for event_date, time_label, summary in events:
            by_day.setdefault(event_date, []).append({
                "time": time_label,
                "summary": summary,
                "key": cal_info["key"],
                "color": cal_info["color"],
                "tint": cal_info["tint"],
                "text": cal_info["text"],
            })

    # Sort each day's events: all-day first, then chronological
    for d, items in by_day.items():
        items.sort(key=lambda x: (x["time"] != "All day", x["time"]))

    return by_day


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


def render_html(week_start, week_end, by_day, generated_at, offset, weather, visible):
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

    today = datetime.now(TIMEZONE).date()

    day_columns = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        is_today = " today" if d == today else ""
        events_html = ""
        for ev in by_day.get(d, []):
            if ev["key"] not in visible:
                continue
            events_html += (
                f'<div class="event" style="background:{ev["tint"]};'
                f'border-left-color:{ev["color"]};color:{ev["text"]}">'
                f'<span class="time">{ev["time"]}</span>{html_mod.escape(ev["summary"])}</div>'
            )
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

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="{refresh}">
<title>Family Weekly Planner</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: {BG_COLOR};
    font-family: Helvetica, Arial, sans-serif;
    color: {INK_COLOR};
    padding: 20px;
  }}

  .board {{
    background: {PANEL_COLOR};
    border-radius: 4px;
    overflow: hidden;
  }}

  .legend {{
    display: flex;
    -webkit-box-orient: horizontal;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    border-bottom: 1px solid {LINE_COLOR};
    background: {HEADER_COLOR};
  }}
  .legend-left {{ display: flex; align-items: center; }}
  .legend-right {{ display: flex; align-items: center; }}
  .legend-item {{
    display: flex;
    align-items: center;
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    margin-right: 20px;
    padding: 6px 0;
    text-decoration: none;
  }}
  .legend-item.off {{
    opacity: 0.45;
    text-decoration: line-through;
  }}
  .dot {{
    width: 11px;
    height: 11px;
    border-radius: 50%;
    margin-right: 8px;
    display: inline-block;
  }}
  .weather {{
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    margin-right: 14px;
    white-space: nowrap;
  }}
  .week-range {{
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    letter-spacing: 0.5px;
    margin: 0 12px;
    white-space: nowrap;
  }}
  .nav-btn {{
    display: block;
    padding: 4px 16px;
    border: 1px solid #5E807C;
    border-radius: 3px;
    color: #E4EEED;
    font-size: 18px;
    font-weight: bold;
    line-height: 1.2;
    text-decoration: none;
  }}
  .nav-btn.dim {{ opacity: 0.35; }}
  .today-btn {{ font-size: 12px; padding: 7px 12px; margin-left: 12px; letter-spacing: 1px; }}

  .week {{
    display: flex;
  }}
  .day {{
    flex: 1;
    border-right: 1px solid {LINE_COLOR};
    min-height: 560px;
    display: flex;
    flex-direction: column;
  }}
  .day:last-child {{ border-right: none; }}

  .day-head {{
    padding: 14px 8px 10px;
    text-align: center;
    border-bottom: 1px solid {LINE_COLOR};
  }}
  .day-name {{
    font-size: 12px;
    font-weight: bold;
    letter-spacing: 1px;
    color: {INK_SOFT};
  }}
  .day-num {{
    font-size: 24px;
    font-weight: bold;
    margin-top: 2px;
  }}
  .day.today .day-head {{ background: {HEADER_COLOR}; }}
  .day.today .day-name {{ color: #B9CFCC; }}
  .day.today .day-num {{ color: #FFFFFF; }}

  .events {{
    padding: 10px 8px;
    flex: 1;
  }}
  .event {{
    border-radius: 3px;
    padding: 6px 8px;
    font-size: 13px;
    line-height: 1.35;
    font-weight: 500;
    border-left: 3px solid;
    margin-bottom: 6px;
  }}
  .event .time {{
    display: block;
    font-size: 10.5px;
    font-weight: bold;
    margin-bottom: 1px;
  }}
  .empty {{
    color: {LINE_COLOR};
    text-align: center;
    padding-top: 20px;
    font-size: 13px;
  }}

  .footer {{
    padding: 10px 24px;
    font-size: 11px;
    color: {INK_SOFT};
    border-top: 1px solid {LINE_COLOR};
    background: #FAFBFA;
  }}
</style>
</head>
<body>

<div class="board">
  <div class="legend">
    <div class="legend-left">{legend_items}</div>
    <div class="legend-right">{weather_html}{prev_html}<div class="week-range">{week_range_label}</div>{next_html}{today_html}</div>
  </div>

  <div class="week">{days_html}
  </div>

  <div class="footer">Updated {updated_label}</div>
</div>

</body>
</html>
"""
    return html


def main():
    now = datetime.now(TIMEZONE)
    today = now.date()
    current_week_start = today - timedelta(days=today.weekday())  # Monday

    range_start = current_week_start - timedelta(weeks=WEEKS_BACK)
    range_end = current_week_start + timedelta(weeks=WEEKS_FORWARD, days=6)

    by_day = fetch_all_events(range_start, range_end)
    weather = fetch_weather()

    # One page per week per show/hide combination (2^3 = 8 combos), so the
    # legend toggles work as plain links with no JavaScript.
    combos = [
        frozenset(k for j, k in enumerate(KEY_ORDER) if bits >> j & 1)
        for bits in range(2 ** len(CALENDARS))
    ]

    os.makedirs("output", exist_ok=True)
    pages = 0
    for offset in range(-WEEKS_BACK, WEEKS_FORWARD + 1):
        week_start = current_week_start + timedelta(weeks=offset)
        week_end = week_start + timedelta(days=6)
        for visible in combos:
            html = render_html(week_start, week_end, by_day, now, offset, weather, visible)
            with open(os.path.join("output", page_name(offset, visible)), "w") as f:
                f.write(html)
            pages += 1

    print(f"Generated {pages} pages ({range_start} to {range_end}), "
          f"weather={'ok' if weather else 'unavailable'}")


if __name__ == "__main__":
    main()
