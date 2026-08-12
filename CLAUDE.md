# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A static weekly family calendar page for a fridge-mounted old iPad (iOS 9). `generate_calendar.py` fetches 3 iCloud public ICS feeds and renders one self-contained HTML page per week (Mon–Sun) per show/hide combination into `output/`. `index.html` is the current week with all calendars visible; `w-1.html`/`w1.html` etc. cover `WEEKS_BACK` past and `WEEKS_FORWARD` future weeks, and suffixed variants like `w1-ai.html` show only the named calendars (keys `a`/`y`/`i`, `-none` = all hidden). Legend names and week arrows are plain links between these pre-rendered pages — that's how toggling and navigation work with zero JavaScript. A GitHub Actions workflow (`.github/workflows/update-calendar.yml`) runs it every 30 minutes and deploys the output to GitHub Pages.

## Commands

There are no tests or linters. To run the generator locally:

```bash
pip install requests icalendar recurring-ical-events tzdata
ADULTS_ICS_URL=... YUV_ICS_URL=... IVAAN_ICS_URL=... python generate_calendar.py
open output/index.html
```

The three env vars are the iCloud feed URLs (`webcal://` swapped to `https://`). In CI they come from repository secrets of the same names. A missing or failing feed is logged as a warning and skipped — the page still builds with the remaining calendars.

## Hard constraints

- **iOS 9 Safari compatibility** is the reason for everything unusual in the HTML: no JavaScript, no CSS Grid, no CSS custom properties, flexbox only, and a `<meta http-equiv="refresh" content="1800">` tag for auto-reload. Don't modernize the output HTML.
- The output must remain a single self-contained file (inline CSS, no external assets) since it's deployed as-is to Pages.

## Architecture notes

- `CALENDARS` at the top of `generate_calendar.py` defines each calendar's display name, colors (accent/tint/text), and the env var holding its feed URL. Colors must stay in sync with the legend rendered in the header. Adults = orange, Yuv = purple, Ivaan = green.
- All times are rendered in `TIMEZONE` (`America/Chicago`). Floating-time events (no TZID) are treated as already-local, not UTC — this matches iCloud's behavior.
- Each feed is fetched once across the whole multi-week range, then bucketed by day; `recurring_ical_events` expands recurrences. Per-day events sort all-day-first, then chronological.
- The header shows current weather (°F and °C) for the coordinates in `WEATHER_LAT`/`WEATHER_LON` (Prosper, TX), fetched from Open-Meteo at build time with no API key; failure just drops the weather chip. Only old-Unicode emoji are used so they render on iOS 9.
- Non-current-week pages use `<meta refresh>` with a redirect back to `index.html` so the fridge display self-recovers to the current week.

## Operational caveat

GitHub disables scheduled workflows after 60 days of repo inactivity, so the calendar silently stops updating unless a commit or manual workflow run happens every couple of months.
