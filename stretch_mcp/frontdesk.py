"""Front desk shifts from an iCal feed (Rippling publishes one per schedule)."""

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import config, http


def _unfold(text):
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _parse_dt(params, value):
    if len(value) == 8:  # all-day: not a shift
        return None
    if value.endswith("Z"):
        return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).astimezone(config.TZ)
    tz = config.TZ
    for p in params:
        if p.upper().startswith("TZID="):
            try:
                tz = ZoneInfo(p.split("=", 1)[1].strip('"'))
            except Exception:
                tz = config.TZ
    return datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=tz).astimezone(config.TZ)


def parse_ical(text):
    """Return [{start, end, summary}] for every timed VEVENT. Recurrence rules are not expanded."""
    events, cur = [], None
    for line in _unfold(text):
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT":
            if cur and cur.get("start") and cur.get("end") and cur.get("status") != "CANCELLED":
                events.append({"start": cur["start"], "end": cur["end"], "summary": cur.get("summary", "")})
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            name = name.upper()
            if name == "DTSTART":
                cur["start"] = _parse_dt(params, value)
            elif name == "DTEND":
                cur["end"] = _parse_dt(params, value)
            elif name == "SUMMARY":
                cur["summary"] = value.replace("\\,", ",").replace("\\n", " ").strip()
            elif name == "STATUS":
                cur["status"] = value.strip().upper()
    return sorted(events, key=lambda e: e["start"])


def shifts(start_day: date, days: int = 1):
    text = http.request("GET", config.require("FRONT_DESK_ICAL_URL"), raw=True, headers={"Accept": "text/calendar"})
    lo = datetime(start_day.year, start_day.month, start_day.day, tzinfo=config.TZ)
    hi = lo + timedelta(days=days)
    out = []
    for e in parse_ical(text):
        if e["start"] < hi and e["end"] > lo:
            summary = e["summary"]
            # Rippling titles look like "Front Desk/STRETCH (First Last)"; keep the person.
            named = re.search(r"\(([^)]+)\)\s*$", summary)
            out.append(
                {
                    "who": named.group(1).strip() if named else summary,
                    "open": "open" in summary.lower() or "unassigned" in summary.lower(),
                    "start": e["start"],
                    "end": e["end"],
                }
            )
    return out
