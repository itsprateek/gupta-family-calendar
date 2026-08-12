# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A static weekly family calendar page for a fridge-mounted old iPad (iOS 9). `generate_calendar.py` fetches 3 iCloud public ICS feeds, renders the current week (Mon–Sun) as a single self-contained HTML file at `output/index.html`, and a GitHub Actions workflow (`.github/workflows/update-calendar.yml`) runs it every 30 minutes and deploys the output to GitHub Pages.

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

- `CALENDARS` at the top of `generate_calendar.py` defines each calendar's display name, colors (accent/tint/text), and the env var holding its feed URL. Colors must stay in sync with the legend rendered in the header. Adults = navy, Yuv = marigold, Ivaan = green.
- All times are rendered in `TIMEZONE` (`America/Chicago`). Floating-time events (no TZID) are treated as already-local, not UTC — this matches iCloud's behavior.
- `recurring_ical_events` expands recurrences within the week window; events are grouped by day and sorted all-day-first, then chronological.

## Operational caveat

GitHub disables scheduled workflows after 60 days of repo inactivity, so the calendar silently stops updating unless a commit or manual workflow run happens every couple of months.
