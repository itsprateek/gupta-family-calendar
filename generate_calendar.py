#!/usr/bin/env python3
"""
Generates a static weekly family calendar HTML page from iCloud public
calendar (webcal) feeds. Designed to run on a schedule via GitHub Actions
and be deployed to GitHub Pages. The output HTML is intentionally plain
(flexbox, no CSS Grid, no CSS custom properties, no JS) so it renders
correctly on old Safari/Chrome on iOS 9.
"""

import os
import sys
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar
import recurring_ical_events

TIMEZONE = ZoneInfo("America/Chicago")

# Each calendar: display name, accent color (hex), tint (light bg), env var
# holding the public ICS URL (converted from webcal:// to https:// before
# being stored as a GitHub Actions secret).
CALENDARS = [
    {
        "name": "Adults",
        "color": "#2C3E66",
        "tint": "#EAEDF4",
        "text": "#24344F",
        "env": "ADULTS_ICS_URL",
    },
    {
        "name": "Yuv",
        "color": "#E8A33D",
        "tint": "#FCF2E1",
        "text": "#7A5620",
        "env": "YUV_ICS_URL",
    },
    {
        "name": "Ivaan",
        "color": "#4E9A63",
        "tint": "#EBF4EC",
        "text": "#2E5F3B",
        "env": "IVAAN_ICS_URL",
    },
]

HEADER_COLOR = "#1F4E4A"
BG_COLOR = "#EFF3F1"
PANEL_COLOR = "#FFFFFF"
LINE_COLOR = "#DCE4E2"
INK_COLOR = "#1B2B29"
INK_SOFT = "#5C6B68"

DAY_NAMES = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def fetch_events_for_calendar(url, week_start, week_end):
    """Fetch and expand recurring events for one calendar within the week.
    Returns a list of (date, time_label, summary) tuples, or raises on
    network/parse failure so the caller can handle it per-calendar."""
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.text)

    # recurring_ical_events expects naive/aware datetimes; use midnight to
    # midnight across the week, inclusive of the last day.
    start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=TIMEZONE)
    end_dt = datetime.combine(week_end + timedelta(days=1), datetime.min.time(), tzinfo=TIMEZONE)

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

        if week_start <= event_date <= week_end:
            events.append((event_date, time_label, summary))

    return events


def build_week_events(week_start, week_end):
    """Returns dict: date -> list of (time_label, summary, color, tint, text)"""
    by_day = {week_start + timedelta(days=i): [] for i in range(7)}

    for cal_info in CALENDARS:
        url = os.environ.get(cal_info["env"])
        if not url:
            print(f"WARNING: no URL set for {cal_info['name']} ({cal_info['env']}), skipping", file=sys.stderr)
            continue
        try:
            events = fetch_events_for_calendar(url, week_start, week_end)
        except Exception as e:
            print(f"WARNING: failed to fetch {cal_info['name']}: {e}", file=sys.stderr)
            continue

        for event_date, time_label, summary in events:
            by_day[event_date].append({
                "time": time_label,
                "summary": summary,
                "color": cal_info["color"],
                "tint": cal_info["tint"],
                "text": cal_info["text"],
            })

    # Sort each day's events: all-day first, then chronological
    for d, items in by_day.items():
        items.sort(key=lambda x: (x["time"] != "All day", x["time"]))

    return by_day


def render_html(week_start, week_end, by_day, generated_at):
    legend_items = "".join(
        f'<div class="legend-item"><span class="dot" style="background:{c["color"]}"></span>{c["name"]}</div>'
        for c in CALENDARS
    )

    week_range_label = f"{week_start.strftime('%b %-d').upper()} \u2013 {week_end.strftime('%b %-d, %Y').upper()}"

    today = datetime.now(TIMEZONE).date()

    day_columns = []
    for i in range(7):
        d = week_start + timedelta(days=i)
        is_today = " today" if d == today else ""
        events_html = ""
        for ev in by_day[d]:
            events_html += (
                f'<div class="event" style="background:{ev["tint"]};'
                f'border-left-color:{ev["color"]};color:{ev["text"]}">'
                f'<span class="time">{ev["time"]}</span>{ev["summary"]}</div>'
            )
        if not events_html:
            events_html = '<div class="empty">\u2014</div>'

        day_columns.append(f"""
    <div class="day{is_today}">
      <div class="day-head"><div class="day-name">{DAY_NAMES[i]}</div><div class="day-num">{d.day}</div></div>
      <div class="events">{events_html}</div>
    </div>""")

    days_html = "".join(day_columns)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="1800">
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
  .legend-left {{ display: flex; }}
  .legend-item {{
    display: flex;
    align-items: center;
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    margin-right: 20px;
  }}
  .dot {{
    width: 11px;
    height: 11px;
    border-radius: 50%;
    margin-right: 8px;
    display: inline-block;
  }}
  .week-range {{
    font-size: 14px;
    font-weight: bold;
    color: #E4EEED;
    letter-spacing: 0.5px;
  }}

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
    <div class="week-range">{week_range_label}</div>
  </div>

  <div class="week">{days_html}
  </div>

  <div class="footer">Updated {generated_at.strftime('%b %-d, %Y \u00b7 %-I:%M %p %Z')}</div>
</div>

</body>
</html>
"""
    return html


def main():
    now = datetime.now(TIMEZONE)
    today = now.date()
    week_start = today - timedelta(days=today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)  # Sunday

    by_day = build_week_events(week_start, week_end)
    html = render_html(week_start, week_end, by_day, now)

    os.makedirs("output", exist_ok=True)
    with open("output/index.html", "w") as f:
        f.write(html)

    print(f"Generated calendar for {week_start} to {week_end}")


if __name__ == "__main__":
    main()
