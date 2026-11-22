#!/usr/bin/env python3
"""Sends phone notifications through ntfy.

  evening : ~7pm Central, tomorrow's kid items + conflicts (skipped if nothing)
  friday  : ~4pm Central Friday, kids' activities for the next 10 days + conflicts
  auto    : picks evening/friday from the clock, does nothing otherwise
            (the workflow fires at both daylight-saving UTC offsets)

Env: NTFY_TOPIC (required unless --dry-run), NTFY_SERVER (default https://ntfy.sh),
     PAGE_URL (optional, makes the notification tappable), plus the calendar feed vars.
Flags: --mode auto|evening|friday  --force  --dry-run  --today YYYY-MM-DD
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

import requests

import famcal
from famcal import fmt_range, is_kid, PEOPLE

LONG_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def day_label(d):
    return "%s %s %d" % (LONG_DAYS[d.weekday()], d.strftime("%b"), d.day)


def line(e, conflicted=False):
    when = "" if e["all_day"] else fmt_range(e) + " "
    txt = "%s: %s%s" % (PEOPLE[e["key"]]["label"], when, e["title"])
    if e["notes"]:
        txt += " (%s)" % e["notes"]
    if e["location"]:
        txt += " @ " + e["location"]
    if e.get("last") and e["last"] != e["date"]:
        txt += " (through %s)" % day_label(e["last"])
    return ("⚠️ " if conflicted else "• ") + txt


def conflict_line(a, b):
    return "⚠️ %s: %s (%s) overlaps %s (%s)" % (
        day_label(a["date"]), a["title"], fmt_range(a), b["title"], fmt_range(b))


def build_message(mode, today, events, conflicts, errors):
    tomorrow = today + timedelta(days=1)
    lines, title, priority, tags = [], "", 3, "calendar"

    if mode == "evening":
        kids = [e for e in events if e["date"] == tomorrow and is_kid(e)]
        clash = [(a, b) for a, b in conflicts if a["date"] == tomorrow]
        if not kids and not clash:
            return None
        ids = {id(x) for pair in clash for x in pair}
        title = "Tomorrow (%s)" % day_label(tomorrow)
        lines += [line(e, id(e) in ids) for e in kids]
        if clash:
            priority, tags = 4, "warning"
            lines += [""] + [conflict_line(a, b) for a, b in clash]
    else:  # friday
        end = today + timedelta(days=10)
        kids = famcal.collapse_runs(
            [e for e in events if is_kid(e) and tomorrow <= e["date"] <= end])
        clash = [(a, b) for a, b in conflicts if tomorrow <= a["date"] <= end]
        title = "Kids: next 10 days"
        if clash:
            priority, tags = 4, "warning"
            lines.append("CONFLICTS")
            lines += [conflict_line(a, b) for a, b in clash]
            lines.append("")
        ids = {id(x) for pair in clash for x in pair}
        last = None
        for e in kids:
            if e["date"] != last:
                if last is not None:
                    lines.append("")
                lines.append(day_label(e["date"]))
                last = e["date"]
            lines.append(line(e, id(e) in ids))
        if not kids:
            lines.append("Nothing planned for the kids yet.")

    if errors:
        lines += ["", "Note: " + "; ".join(errors)]
    body = "\n".join(lines)
    if len(body.encode("utf-8")) > 3800:
        body = body.encode("utf-8")[:3800].decode("utf-8", "ignore") + "\n..."
    return {"title": title, "body": body, "priority": priority, "tags": tags}


def send(msg):
    topic = os.environ["NTFY_TOPIC"].strip()
    server = os.environ.get("NTFY_SERVER", "https://ntfy.sh").rstrip("/")
    headers = {"Title": msg["title"], "Priority": str(msg["priority"]), "Tags": msg["tags"]}
    if os.environ.get("PAGE_URL"):
        headers["Click"] = os.environ["PAGE_URL"]
    r = requests.post("%s/%s" % (server, topic), data=msg["body"].encode("utf-8"),
                      headers=headers, timeout=20)
    r.raise_for_status()


def pick_mode(now, forced):
    if forced:
        return forced
    if now.weekday() == 4 and now.hour == 16:
        return "friday"
    if now.hour == 19:
        return "evening"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", default="auto", choices=["auto", "evening", "friday"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--today")
    ap.add_argument("--events", default=os.environ.get("EVENTS_JSON", "events.json"))
    args = ap.parse_args()

    now = famcal.now_local()
    if args.today:
        now = datetime.fromisoformat(args.today + "T19:00:00").replace(tzinfo=famcal.TZ)
    timed = pick_mode(now, None)  # what the clock says right now
    if args.force or args.today:  # testing / manual run: ignore the clock
        mode = args.mode if args.mode != "auto" else (timed or "evening")
    elif args.mode == "auto":
        mode = timed
    else:  # explicit mode on a schedule still respects the clock
        mode = args.mode if timed == args.mode else None
    if not mode:
        print("Not a notification time (%s Central); nothing to do." % now.strftime("%a %H:%M"))
        return

    today = now.date()
    events, errors, _, ok = famcal.load_all(today, args.events, span_days=14)
    if ok == 0:
        print("All feeds failed; not sending a misleading notification.", file=sys.stderr)
        sys.exit(1)
    msg = build_message(mode, today, events, famcal.find_conflicts(events), errors)
    if msg is None:
        print("Nothing to report for %s." % mode)
        return
    if args.dry_run:
        print("--- %s (priority %d) ---\n%s" % (msg["title"], msg["priority"], msg["body"]))
        return
    send(msg)
    print("Sent %s notification." % mode)


if __name__ == "__main__":
    main()
