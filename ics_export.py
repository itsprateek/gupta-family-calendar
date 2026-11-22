#!/usr/bin/env python3
"""Turns events.json (events from school emails) into an .ics calendar file,
with three alerts on every event, so it can be subscribed to or imported in
Apple Calendar / iCloud.

Alerts
  timed events   : 2 days before, 1 day before, 1 hour before
  all-day events : 9am two days before, 9am the day before, 7am that day
                   (all-day events have no start time, so "1 hour before"
                   becomes "7am that morning")
  multi-day items (school breaks) alert before the first day only.

Usage: python ics_export.py [events.json] [out.ics] [--who yuv|ivaan|adults] [--ids id1,id2] [--name NAME]

generate_calendar.py also calls write_feed() on every build, which publishes
the file next to the pages under a hard-to-guess name derived from a feed
secret (so the link isn't guessable and no secret is stored in the repo).
"""
import hashlib
import json
import os
import sys
from datetime import date, datetime, time, timedelta, timezone

from icalendar import Alarm, Calendar, Event

import famcal

CAL_NAME = "Family School Events"
WHO_LABEL = {"yuv": "Yuv", "ivaan": "Ivaan", "kids": "Kids", "adults": "Adults",
             "parents": "Adults", "family": "Family", "both": "Kids", "all": "Family"}

# (trigger relative to the event start, text shown in the alert)
TIMED_ALERTS = [(timedelta(days=-2), "in 2 days"), (timedelta(days=-1), "tomorrow"),
                (timedelta(hours=-1), "in 1 hour")]
# All-day events start at midnight, so offsets are measured from 00:00.
ALLDAY_ALERTS = [(timedelta(hours=-39), "in 2 days"),   # 9am, two days before
                 (timedelta(hours=-15), "tomorrow"),    # 9am, the day before
                 (timedelta(hours=7), "today")]         # 7am, the day itself


def _prefix(who):
    if isinstance(who, str):
        who = [who]
    names = []
    for w in who or ["kids"]:
        label = WHO_LABEL.get(str(w).lower().strip(), str(w).strip().title())
        if label not in names:
            names.append(label)
    return " & ".join(names)


def _hhmm(day, text):
    hh, mm = text.strip().split(":")
    return datetime.combine(day, time(int(hh), int(mm)), tzinfo=famcal.TZ)


def _matches_who(raw_who, who):
    """True if an events.json "who" list belongs to the child/person `who`
    ("yuv", "ivaan" or "adults"). A both-kids item belongs to each kid."""
    if isinstance(raw_who, str):
        raw_who = [raw_who]
    keys = {str(w).lower().strip() for w in (raw_who or ["kids"])}
    if who in ("yuv", "ivaan"):
        return who in keys or bool(keys & {"kids", "both", "all", "family"})
    if who == "adults":
        return bool(keys & {"adults", "parents"})
    return who in keys


def build_calendar(events_path="events.json", only_ids=None, who=None, calname=CAL_NAME):
    """Returns (ics_bytes, event_count, problems). only_ids / who narrow it down
    (used to mail just the new events for one child)."""
    cal = Calendar()
    cal.add("prodid", "-//Gupta family calendar//school events//EN")
    cal.add("version", "2.0")
    cal.add("calscale", "GREGORIAN")
    cal.add("method", "PUBLISH")
    cal.add("x-wr-calname", calname)
    cal.add("x-wr-timezone", "America/Chicago")
    cal.add("refresh-interval", timedelta(hours=1), parameters={"VALUE": "DURATION"})
    cal.add("x-published-ttl", "PT1H")

    problems, count = [], 0
    if not events_path or not os.path.exists(events_path):
        return cal.to_ical(), 0, ["events file not found"]
    with open(events_path, encoding="utf-8") as f:
        data = json.load(f)
    stamp = datetime.now(timezone.utc)

    for raw in data.get("events", []):
        if only_ids is not None and raw.get("id") not in only_ids:
            continue
        if who and not _matches_who(raw.get("who"), who):
            continue
        try:
            d0 = date.fromisoformat(raw["date"])
            d1 = date.fromisoformat(raw.get("end_date") or raw["date"])
            title = raw["title"].strip()
            summary = "%s: %s" % (_prefix(raw.get("who")), title)

            ev = Event()
            ev.add("uid", "%s@gupta-family-calendar" % (raw.get("id") or "%s-%s" % (raw["date"], title)))
            ev.add("dtstamp", stamp)
            ev.add("summary", summary)
            if raw.get("location"):
                ev.add("location", raw["location"])
            desc = [t for t in (raw.get("notes"), ("Source: " + raw["source"]) if raw.get("source") else None) if t]
            if desc:
                ev.add("description", "\n".join(desc))

            if raw.get("start"):
                start = _hhmm(d0, raw["start"]).astimezone(timezone.utc)
                ev.add("dtstart", start)
                if raw.get("end"):
                    ev.add("dtend", _hhmm(d0, raw["end"]).astimezone(timezone.utc))
                alerts = TIMED_ALERTS
            else:
                ev.add("dtstart", d0)
                ev.add("dtend", d1 + timedelta(days=1))  # DTEND is exclusive for all-day
                ev.add("transp", "TRANSPARENT")           # don't mark the whole day "busy"
                alerts = ALLDAY_ALERTS

            for offset, when in alerts:
                al = Alarm()
                al.add("action", "DISPLAY")
                al.add("description", "%s (%s)" % (summary, when))
                al.add("trigger", offset)
                ev.add_component(al)

            cal.add_component(ev)
            count += 1
        except Exception as exc:  # one bad row must not break the feed
            problems.append("ics: skipped %r (%s)" % (raw.get("title", raw), exc))
    return cal.to_ical(), count, problems


def feed_filename(secret):
    """Stable, unguessable file name derived from a secret the repo already has."""
    digest = hashlib.sha256(("school-feed|" + secret).encode("utf-8")).hexdigest()[:24]
    return "school-%s.ics" % digest


def write_feed(out_dir, events_path="events.json", secret=None):
    """Write the feed into out_dir. Returns the file name, or None when there is
    no secret to derive a private name from (then nothing is published)."""
    secret = (secret if secret is not None else os.environ.get("ADULTS_ICS_URL", "")).strip()
    if not secret:
        return None
    data, count, problems = build_calendar(events_path)
    for p in problems:
        print("WARNING: " + p, file=sys.stderr)
    name = feed_filename(secret)
    with open(os.path.join(out_dir, name), "wb") as f:
        f.write(data)
    print("School-events feed: %d events -> %s (add this file name to your Pages address to subscribe)" % (count, name))
    return name


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="events.json -> .ics with alerts")
    ap.add_argument("events", nargs="?", default="events.json")
    ap.add_argument("out", nargs="?", default="school-events.ics")
    ap.add_argument("--ids", help="comma-separated event ids to include (default: all)")
    ap.add_argument("--who", choices=["yuv", "ivaan", "adults"], help="only this person's events")
    ap.add_argument("--name", default=None, help="calendar name inside the file")
    a = ap.parse_args()
    ids = {x.strip() for x in a.ids.split(",") if x.strip()} if a.ids else None
    blob, n, probs = build_calendar(a.events, ids, a.who, a.name or ("%s (%s)" % (CAL_NAME, a.who.title()) if a.who else CAL_NAME))
    for p in probs:
        print("WARNING: " + p, file=sys.stderr)
    with open(a.out, "wb") as f:
        f.write(blob)
    print("Wrote %d events to %s" % (n, a.out))
