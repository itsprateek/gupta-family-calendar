# Family Fridge Calendar

Generates a static weekly calendar page from 3 iCloud calendar feeds
(Adults, Yuv, Ivaan), auto-refreshing every 30 minutes, hosted free on
GitHub Pages. Designed to be viewed on an old iPad (even iOS 9) mounted
on the fridge.

## One-time setup

1. **Create a new GitHub repository** (public — required for Pages on the
   free plan). Name it whatever you like, e.g. `family-calendar`.

2. **Upload these 3 files**, keeping the folder structure:
   - `generate_calendar.py`
   - `.github/workflows/update-calendar.yml`
   - `README.md` (optional, just for reference)

3. **Add your 3 calendar feed URLs as repository secrets** (this keeps
   the actual links out of your code, since anyone with the link can
   view the calendar):
   - Go to your repo → **Settings → Secrets and variables → Actions**
   - Click **New repository secret** three times, creating:
     - `ADULTS_ICS_URL` → your Adults webcal link, with `webcal://` changed to `https://`
     - `YUV_ICS_URL` → Yuv's link, same swap
     - `IVAAN_ICS_URL` → Ivaan's link, same swap

4. **Enable GitHub Pages via Actions:**
   - Go to repo → **Settings → Pages**
   - Under "Build and deployment" → **Source**, choose **GitHub Actions**

5. **Run it once manually** to confirm it works:
   - Go to the **Actions** tab → "Update Family Calendar" workflow →
     **Run workflow** button
   - Wait ~30-60 seconds, then check the **Pages** section in Settings
     for your live URL (something like
     `https://yourusername.github.io/family-calendar/`)

6. From then on, it auto-runs every 30 minutes on its own.

## On the iPad

1. Open the GitHub Pages URL in Safari or Chrome.
2. Add it to the Home Screen (Share → Add to Home Screen) so it opens
   full-screen without browser chrome.
3. The page has a `<meta http-equiv="refresh">` tag baked in, so it
   reloads itself every 30 minutes automatically — just leave it open.
4. Optional: use **Guided Access** (Settings → Accessibility → Guided
   Access) to lock the screen into this one page so nothing else can be
   tapped by accident.

## Important caveat: GitHub Actions on inactive repos

GitHub automatically **disables scheduled workflows after 60 days with
no repository activity** (commits, etc.). If you don't touch the repo
for 2 months, the calendar will silently stop updating. Fix: either
check in occasionally and click "Run workflow" manually, or make any
small commit every couple months to reset the clock.

## Notes

- Times shown assume `America/Chicago` — edit `TIMEZONE` at the top of
  `generate_calendar.py` if that ever changes.
- If one calendar feed fails to load (bad link, iCloud hiccup), that
  calendar's events just won't appear that cycle — the page still
  builds fine with the other two. Check the Actions tab logs if a
  calendar seems to be missing consistently.
- Colors: Adults = orange, Yuv = purple, Ivaan = green — matches the
  legend in the header bar.
- The ‹ › arrows in the header browse past/future weeks (4 back, 8
  forward). Browsed weeks auto-return to the current week after 30
  minutes, so the fridge never gets stuck on the wrong week.
- The header shows current weather for Prosper, TX (75078) in both °F
  and °C, fetched from Open-Meteo at build time — edit `WEATHER_LAT` /
  `WEATHER_LON` in `generate_calendar.py` to change the location. It
  only refreshes when the page rebuilds (every 30 minutes).
