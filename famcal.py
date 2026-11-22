#!/usr/bin/env python3
"""Shared loading and conflict logic for the family calendar.

Sources:
  * three iCloud public calendar feeds (Adults, Yuv, Ivaan), read from the
    ADULTS_ICS_URL / YUV_ICS_URL / IVAAN_ICS_URL environment variables
  * events.json, which the email-intake task fills from school emails and PDFs

A feed URL may be https://, webcal://, or file:// (file:// is handy for tests).
"""
import json
import os
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from icalendar import Calendar
import recurring_ical_events

TZ = ZoneInfo("America/Chicago")
DEFAULT_LEN_MIN = 30  # used for conflict checks when an event has no real end

PEOPLE = {
    "adults": {"label": "Adults", "short": "a", "color": "#D9722C", "tint": "#FBEEE2", "text": "#8A4718",
               "env": "ADULTS_ICS_URL", "kid": False},
    "yuv": {"label": "Yuv", "short": "y", "color": "#7B5EA7", "tint": "#F0EBF7", "text": "#503B72",
            "env": "YUV_ICS_URL", "kid": True},
    "ivaan": {"label": "Ivaan", "short": "i", "color": "#4E9A63", "tint": "#EBF4EC", "text": "#2E5F3B",
              "env": "IVAAN_ICS_URL", "kid": True},
    # Only used for email items that apply to both kids; not a feed, not in the legend.
    "kids": {"label": "Both kids", "short": "k", "color": "#3B6FB6", "tint": "#E8EFF9", "text": "#274A7D",
             "env": None, "kid": True},
}
FEED_KEYS = ["adults", "yuv", "ivaan"]


def now_local():
    return datetime.now(TZ)


def is_kid(ev):
    return PEOPLE[ev["key"]]["kid"]


# ---------------------------------------------------------------- fetching

def _fetch(url):
    url = url.strip()
    if url.startswith("file://"):
        with open(url[len("file://"):], "rb") as f:
            return f.read()
    if url.startswith("webcals://"):
        url = "https://" + url[len("webcals://"):]
    elif url.startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    last = None
    for _ in range(2):
        try:
            r = requests.get(url, timeout=25)
            r.raise_for_status()
            return r.content
        except requests.RequestException as exc:
            last = exc
    raise last


def _to_local(dt):
    """Floating times are treated as Central; aware times are converted."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=TZ)
        return dt.astimezone(TZ)
    return dt


def make_event(key, title, day, all_day, start=None, end=None, location="",
               source="calendar", notes=""):
    return {"key": key, "title": title, "date": day, "all_day": all_day,
            "start": start, "end": end, "location": location,
            "source": source, "notes": notes}


def _expand_component(comp, key, win_start, win_end):
    if str(comp.get("STATUS", "")).upper() == "CANCELLED":
        return []
    title = str(comp.get("SUMMARY", "")).strip() or "(no title)"
    loc = str(comp.get("LOCATION", "")).strip()
    ds = comp.get("DTSTART").dt
    de_prop = comp.get("DTEND")
    de = de_prop.dt if de_prop is not None else None

    if not isinstance(ds, datetime):  # all-day (DTEND is exclusive)
        last = ds
        if isinstance(de, date) and not isinstance(de, datetime):
            last = max(ds, de - timedelta(days=1))
        out, d = [], ds
        while d <= last:
            if win_start <= d <= win_end:
                out.append(make_event(key, title, d, True, location=loc))
            d += timedelta(days=1)
        return out

    start = _to_local(ds)
    end = _to_local(de) if isinstance(de, datetime) else None
    if win_start <= start.date() <= win_end:
        return [make_event(key, title, start.date(), False, start, end, loc)]
    return []


def load_feed(key, raw, win_start, win_end):
    cal = Calendar.from_ical(raw)
    comps = recurring_ical_events.of(cal).between(win_start, win_end + timedelta(days=1))
    out = []
    for comp in comps:
        out.extend(_expand_component(comp, key, win_start, win_end))
    return out


# -------------------------------------------------------------- events.json

def _key_for(who):
    kids = {w for w in who if w in ("yuv", "ivaan")}
    if len(kids) == 2 or any(w in ("kids", "family", "both", "all") for w in who):
        return "kids"
    if len(kids) == 1:
        return kids.pop()
    if any(w in ("adults", "parents") for w in who):
        return "adults"
    return "kids"


def _hhmm(day, text):
    hh, mm = text.strip().split(":")
    return datetime(day.year, day.month, day.day, int(hh), int(mm), tzinfo=TZ)


def load_email_events(path, win_start, win_end):
    events, problems = [], []
    if not path or not os.path.exists(path):
        return events, problems
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for raw in data.get("events", []):
        try:
            d0 = date.fromisoformat(raw["date"])
            d1 = date.fromisoformat(raw.get("end_date") or raw["date"])
            who = raw.get("who") or ["kids"]
            if isinstance(who, str):
                who = [who]
            key = _key_for([w.lower().strip() for w in who])
            title = raw["title"].strip()
            all_day = not raw.get("start")
            d = d0
            while d <= d1:
                if win_start <= d <= win_end:
                    start = end = None
                    if not all_day:
                        start = _hhmm(d, raw["start"])
                        if raw.get("end"):
                            end = _hhmm(d, raw["end"])
                    events.append(make_event(key, title, d, all_day, start, end,
                                             raw.get("location", ""), "email",
                                             raw.get("notes", "")))
                d += timedelta(days=1)
        except Exception as exc:  # one bad row must not break the page
            problems.append("events.json: skipped %r (%s)" % (raw.get("title", raw), exc))
    return events, problems


# --------------------------------------------------------------- everything

def _norm(title):
    return re.sub(r"[^a-z0-9]", "", title.lower())


def _sort_key(e):
    return (e["date"], 0 if e["all_day"] else 1,
            e["start"].timetz().replace(tzinfo=None) if e["start"] else datetime.min.time(),
            e["title"].lower())


def load_range(range_start, range_end, events_path="events.json"):
    """Load all feeds + events.json for [range_start, range_end].
    Returns (events, errors, feeds_ok). A failing feed is reported in errors
    and skipped; the caller decides what to do if feeds_ok is 0."""
    events, errors, ok = [], [], 0
    for key in FEED_KEYS:
        url = os.environ.get(PEOPLE[key]["env"], "").strip()
        label = PEOPLE[key]["label"]
        if not url:
            errors.append("%s calendar: no feed URL set" % label)
            continue
        try:
            events.extend(load_feed(key, _fetch(url), range_start, range_end))
            ok += 1
        except Exception as exc:
            errors.append("%s calendar: %s" % (label, type(exc).__name__))
    extra, problems = load_email_events(events_path, range_start, range_end)
    events.extend(extra)
    errors.extend(problems)

    seen, deduped = set(), []
    for e in sorted(events, key=lambda e: (e["source"] == "email",)):  # calendar wins ties
        sig = (e["date"], _norm(e["title"]), e["key"])
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(e)
    deduped.sort(key=_sort_key)
    return deduped, errors, ok


def load_all(today, events_path="events.json", span_days=21):
    """Returns (events, errors, (win_start, win_end), feeds_ok). Used by notify.py."""
    win_start = today - timedelta(days=today.weekday())
    win_end = max(win_start + timedelta(days=6), today + timedelta(days=span_days))
    events, errors, ok = load_range(win_start, win_end, events_path)
    return events, errors, (win_start, win_end), ok


# ---------------------------------------------------------------- conflicts

def _end(e):
    if e["end"] and e["end"] > e["start"]:
        return e["end"]
    return e["start"] + timedelta(minutes=DEFAULT_LEN_MIN)


def find_conflicts(events):
    """Pairs of overlapping timed events where at least one involves a kid.

    Adult-vs-adult overlaps are ignored on purpose: the Adults calendar is
    merged, so two overlapping entries are usually two different people.
    """
    by_day = {}
    for e in events:
        if not e["all_day"] and e["start"]:
            by_day.setdefault(e["date"], []).append(e)
    out = []
    for day in sorted(by_day):
        evs = sorted(by_day[day], key=lambda e: e["start"])
        for i, a in enumerate(evs):
            a_end = _end(a)
            for b in evs[i + 1:]:
                if b["start"] >= a_end:
                    break
                if not (is_kid(a) or is_kid(b)):
                    continue
                if _norm(a["title"]) == _norm(b["title"]):
                    continue
                out.append((a, b))
    return out


def collapse_runs(events):
    """Merge consecutive all-day events with the same person+title into one
    entry carrying a "last" date (e.g. a school break shown once, not 5 times).
    Timed events are returned untouched (same objects, so conflict ids still match)."""
    out, runs = [], {}
    for e in sorted(events, key=_sort_key):
        if e["all_day"]:
            sig = (e["key"], e["title"])
            run = runs.get(sig)
            if run is not None and e["date"] == run["last"] + timedelta(days=1):
                run["last"] = e["date"]
                continue
            e = dict(e, last=e["date"])
            runs[sig] = e
        out.append(e)
    return out


# ---------------------------------------------------------------- formatting

def fmt_time(dt):
    h = dt.hour % 12 or 12
    suffix = "a" if dt.hour < 12 else "p"
    return "%d%s" % (h, suffix) if dt.minute == 0 else "%d:%02d%s" % (h, dt.minute, suffix)


def fmt_range(e):
    if e["all_day"]:
        return "all day"
    s = fmt_time(e["start"])
    if e["end"] and e["end"] > e["start"]:
        return "%s-%s" % (s, fmt_time(e["end"]))
    return s
