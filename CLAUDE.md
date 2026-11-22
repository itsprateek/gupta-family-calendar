# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A static weekly family calendar page for a fridge-mounted old iPad (iOS 9). `generate_calendar.py` fetches 3 iCloud public ICS feeds (plus `events.json`, see below) and renders one self-contained HTML page per week (Mon–Sun) per show/hide combination into `output/`. `index.html` is the current week with all calendars visible; `w-1.html`/`w1.html` etc. cover `WEEKS_BACK` past and `WEEKS_FORWARD` future weeks, and suffixed variants like `w1-ai.html` show only the named calendars (keys `a`/`y`/`i`, `-none` = all hidden). Legend names and week arrows are plain links between these pre-rendered pages — that's how toggling and navigation work with zero JavaScript. A GitHub Actions workflow (`.github/workflows/update-calendar.yml`) runs it every 30 minutes and deploys the output to GitHub Pages.

The current-week pages (`index*.html`) also show a highlight band (Today, Tomorrow, Conflicts) above the week grid and a "Kids coming up" strip below it. Browsed weeks keep the plain layout. The Conflicts card only appears when there is a conflict in the next 7 days; otherwise Today and Tomorrow share the band.

The look follows the season/holiday (`THEMES` and `theme_for(today)` in `generate_calendar.py`): header color, page tint, a thin stripe under the header, and a short greeting on the current-week page only. Christmas runs from the day after Thanksgiving to Dec 26; other holidays are New Year, Valentine's Day, St. Patrick's Day, Easter week, July 4th, Halloween and Thanksgiving. To add one, add a `THEMES` row and a date rule in `theme_for`. Keep headers dark enough for white text, and keep emoji iOS 9-safe.

A second workflow, `.github/workflows/notify.yml`, runs `notify.py`, which sends ntfy phone notifications: the evening before (7pm Central, only if the kids have something or there is a conflict) and a Friday 4pm digest of the kids' next 10 days with conflicts.

## Commands

There are no linters. To run the generator locally:

```bash
pip install -r requirements.txt
ADULTS_ICS_URL=... YUV_ICS_URL=... IVAAN_ICS_URL=... python generate_calendar.py
open output/index.html
```

The three env vars are the iCloud feed URLs (`webcal://` swapped to `https://`; `file://` paths also work). In CI they come from repository secrets of the same names. A missing or failing feed is logged as a warning and skipped, and the current-week page shows a yellow "Heads up" bar. If ALL feeds fail the script exits 1 so the previously deployed page stays up.

Offline test with sample data (week of Nov 23, 2026 contains an overlap, an all-day break, email events and a bad row on purpose):

```bash
export ADULTS_ICS_URL=file://$PWD/sample/adults.ics YUV_ICS_URL=file://$PWD/sample/yuv.ics IVAAN_ICS_URL=file://$PWD/sample/ivaan.ics EVENTS_JSON=sample/events.json
CAL_TODAY=2026-11-24 python generate_calendar.py /tmp/out
python notify.py --mode friday --today 2026-11-20 --dry-run
```

`CAL_TODAY` and `--today` are test-only date overrides. Notifications need the `NTFY_TOPIC` secret (workflow) or env var; `--dry-run` prints instead of sending.

`ics_export.py` turns `events.json` into a calendar-app feed with three alerts per event (timed: 2 days, 1 day, 1 hour before; all-day: 9am two days before, 9am the day before, 7am that day). Each build writes it to the Pages output as `school-<24 hex>.ics`, where the hex is derived from the `ADULTS_ICS_URL` secret, so the link is unguessable and nothing secret is stored in the repo. The build log prints the file name; subscribe to `<Pages address>/<that name>` in Apple Calendar. `python ics_export.py events.json out.ics` makes a one-time import file; add `--who yuv|ivaan|adults` and/or `--ids a,b` to export just one person's or just the new events (the intake task mails these, one file per child). Only email events are exported, not the iCloud feed events (those already live in iCloud).

## Hard constraints

- **iOS 9 Safari compatibility** is the reason for everything unusual in the HTML: no JavaScript, no CSS Grid, no CSS custom properties, flexbox only, and a `<meta http-equiv="refresh" content="1800">` tag for auto-reload. Don't modernize the output HTML.
- The output must remain a single self-contained file (inline CSS, no external assets) since it's deployed as-is to Pages.
- The current-week page must fit one iPad mini screen (1024x768): the day columns have a fixed event height and show "+N more" past `MAX_PER_DAY`; the highlight cards and upcoming strip are fixed height. Re-check with a 1024x768 screenshot after layout changes.

## Architecture notes

- `famcal.py` is shared by `generate_calendar.py` and `notify.py`. `PEOPLE` there is the single source for names, colors (accent/tint/text), short keys and env var names: Adults = orange (`a`), Yuv = purple (`y`), Ivaan = green (`i`), plus a blue "Both kids" style (`k`) used only for email items that apply to both kids (not a feed, not in the legend; shown while Yuv or Ivaan is visible). `CALENDARS` in `generate_calendar.py` is built from it.
- All times are rendered in `famcal.TZ` (`America/Chicago`). Floating-time events (no TZID) are treated as already-local, not UTC — this matches iCloud's behavior.
- Each feed is fetched once across the whole multi-week range; `recurring_ical_events` expands recurrences. Events are sorted all-day-first, then by real start time.
- `events.json` (repo root) holds events extracted from school emails/PDFs. It is written by a Claude scheduled task (prompt in `INTAKE_TASK.md`) that reads the family Gmail inbox and commits to `main`. Shape: `{"last_checked": ..., "events": [{"id","title","date","end_date"?,"start"?,"end"?,"who":["yuv"|"ivaan"|"kids"|"adults"],"location"?,"notes"?,"source"}]}`. A bad row is skipped with a warning, never fatal. An email item is dropped when a feed event exists the same day for the same person (a both-kids item matches either kid) with a similar title (`famcal._is_duplicate`: equal, one contained in the other, or ~80% similar) and a compatible time; its notes are kept on the surviving event. They show an "EMAIL" tag.
- Conflicts (`famcal.find_conflicts`) = overlapping timed events where at least one belongs to a kid; adult-vs-adult overlaps are ignored because the Adults calendar is merged. Conflicts involving a hidden calendar are not shown on that page.
- The header shows current weather (°F and °C) for the coordinates in `WEATHER_LAT`/`WEATHER_LON` (Prosper, TX), fetched from Open-Meteo at build time with no API key; failure just drops the weather chip. Only old-Unicode emoji are used so they render on iOS 9.
- Non-current-week pages use `<meta refresh>` with a redirect back to `index.html` so the fridge display self-recovers to the current week.
- `notify.yml` fires at both daylight-saving UTC offsets; `notify.py` only sends when the Central-time clock is in the right hour (evening = 19:xx, Friday = 16:xx).

## Operational caveat

GitHub disables scheduled workflows after 60 days of repo inactivity. The daily `events.json` commit from the intake task keeps the repo active; if that task is ever turned off, push a commit or run a workflow manually every couple of months.
