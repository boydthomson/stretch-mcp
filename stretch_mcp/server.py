"""STRETCH MCP server.

Read tools answer "what is going on at the studio". Write tools can only propose; a
person approves in chat before anything changes. Run with `stretch-mcp` (stdio).
"""

from datetime import date, datetime, timedelta

from mcp.server.mcpserver import MCPServer

from . import approvals, config, coverage, frontdesk, momence, shiftlog
from .audit import traced

mcp = MCPServer(
    "stretch",
    instructions=(
        "Live operational data for STRETCH Yoga (180 E. Pender St, Vancouver). All times are studio-local. "
        "Dates are YYYY-MM-DD; leave a date empty for today. Start with daily_brief for any general "
        "question about a day. Writes are two steps: a propose_* tool, then execute_action after a person "
        "approves in chat. Never tell anyone a write happened until execute_action returns status done."
    ),
)


def _day(value: str = "") -> date:
    value = (value or "").strip().lower()
    today = datetime.now(config.TZ).date()
    if value in ("", "today"):
        return today
    if value == "tomorrow":
        return today + timedelta(days=1)
    if value == "yesterday":
        return today - timedelta(days=1)
    return date.fromisoformat(value)


def _t(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _class_row(s):
    return {
        "session_id": s["session_id"],
        "time": f"{_t(s['start'])} to {_t(s['end'])}",
        "name": s["name"],
        "teacher": s["teacher"],
        "booked": s["booked"],
        "capacity": s["capacity"],
    }


def _gap_row(g):
    return {
        "date": g["start"].strftime("%a %Y-%m-%d"),
        "time": f"{_t(g['start'])} to {_t(g['end'])}",
        "name": g["name"],
        "status": g["status"],
        "uncovered_minutes": g["uncovered_minutes"],
        "on_desk": g["on_desk"],
    }


@mcp.tool()
@traced
def class_schedule(date: str = "", days: int = 1) -> dict:
    """Classes on a date (or a run of days): time, name, teacher, bookings and capacity. Live from Momence."""
    day = _day(date)
    days = max(1, min(int(days), 14))
    rows = momence.sessions(day, days)
    out = {"from": day.isoformat(), "days": days, "classes": []}
    for s in rows:
        row = _class_row(s)
        if days > 1:
            row["date"] = s["start"].strftime("%a %Y-%m-%d")
        out["classes"].append(row)
    out["total_booked"] = sum(s["booked"] for s in rows)
    return out


@mcp.tool()
@traced
def class_roster(session_id: int) -> dict:
    """Who is booked into one class and who has checked in. Names are first name plus last initial."""
    r = momence.roster(session_id)
    return {
        "session_id": r["session_id"],
        "name": r["name"],
        "start": r["start"].strftime("%a %Y-%m-%d %H:%M"),
        "capacity": r["capacity"],
        "booked": len(r["people"]),
        "checked_in": sum(1 for p in r["people"] if p["checked_in"]),
        "people": r["people"],
    }


@mcp.tool()
@traced
def room_rentals(date: str = "", days: int = 1) -> dict:
    """Room rentals and private bookings on a date (or a run of days)."""
    day = _day(date)
    days = max(1, min(int(days), 31))
    return {
        "from": day.isoformat(),
        "days": days,
        "rentals": [
            {
                "reservation_id": r["reservation_id"],
                "date": r["start"].strftime("%a %Y-%m-%d"),
                "time": f"{_t(r['start'])} to {_t(r['end'])}",
                "name": r["name"],
            }
            for r in momence.rentals(day, days)
        ],
    }


@mcp.tool()
@traced
def front_desk_shifts(date: str = "", days: int = 1) -> dict:
    """Who is scheduled on the front desk, from the published staff schedule."""
    day = _day(date)
    days = max(1, min(int(days), 31))
    return {
        "from": day.isoformat(),
        "days": days,
        "shifts": [
            {
                "date": s["start"].strftime("%a %Y-%m-%d"),
                "time": f"{_t(s['start'])} to {_t(s['end'])}",
                "who": s["who"],
                "open": s["open"],
            }
            for s in frontdesk.shifts(day, days)
        ],
    }


@mcp.tool()
@traced
def coverage_gaps(date: str = "", days: int = 7) -> dict:
    """Classes and rentals with nobody assigned to the front desk for all or part of them.

    Open (unassigned) shifts do not count as cover. Use this to find shifts that need filling.
    """
    day = _day(date)
    days = max(1, min(int(days), 31))
    items = [{"name": s["name"], "start": s["start"], "end": s["end"]} for s in momence.sessions(day, days)]
    items += [{"name": r["name"], "start": r["start"], "end": r["end"]} for r in momence.rentals(day, days)]
    gaps = coverage.find_gaps(items, frontdesk.shifts(day, days))
    return {"from": day.isoformat(), "days": days, "items_checked": len(items), "gaps": [_gap_row(g) for g in gaps]}


@mcp.tool()
@traced
def sales_summary(date: str = "yesterday") -> dict:
    """Total sales for one day, tax included, with the same weekday a week earlier for comparison."""
    day = _day(date)
    this = momence.sales(day)
    prior = momence.sales(day - timedelta(days=7))
    return {**this, "weekday": day.strftime("%A"), "same_weekday_last_week": {"date": prior["date"], "total": prior["total"]}}


@mcp.tool()
@traced
def shift_log(days: int = 2) -> dict:
    """What front desk staff wrote in the shift log: broken things, supplies, follow-ups, incidents, notes."""
    rows = shiftlog.entries(max(1, min(int(days), 30)))
    for r in rows:
        r["submitted"] = r["submitted"].strftime("%a %Y-%m-%d %H:%M")
    return {"days": days, "entries": rows, "needing_attention": sum(1 for r in rows if r["needs_attention"])}


@mcp.tool()
@traced
def daily_brief(date: str = "") -> dict:
    """Everything a studio manager wants first thing: the day's classes and rentals, who is on the
    front desk, coverage gaps today and over the next week, yesterday's sales, recent shift log
    notes and writes waiting for approval. One section failing does not stop the others."""
    day = _day(date)
    brief = {"date": day.strftime("%A %Y-%m-%d"), "unavailable": []}

    def section(name, fn):
        try:
            brief[name] = fn()
        except Exception as e:  # noqa: BLE001
            brief["unavailable"].append({"section": name, "reason": f"{type(e).__name__}: {e}"[:200]})

    week_classes, week_rentals, week_shifts = [], [], []

    def classes():
        week_classes.extend(momence.sessions(day, 7))
        return [_class_row(s) for s in week_classes if s["start"].date() == day]

    def rentals():
        week_rentals.extend(momence.rentals(day, 7))
        return [{"time": f"{_t(r['start'])} to {_t(r['end'])}", "name": r["name"]} for r in week_rentals if r["start"].date() == day]

    def desk():
        week_shifts.extend(frontdesk.shifts(day, 7))
        return [
            {"time": f"{_t(s['start'])} to {_t(s['end'])}", "who": s["who"], "open": s["open"]}
            for s in week_shifts
            if s["start"].date() == day
        ]

    def gaps():
        items = [{"name": x["name"], "start": x["start"], "end": x["end"]} for x in week_classes + week_rentals]
        return [_gap_row(g) for g in coverage.find_gaps(items, week_shifts)]

    section("classes", classes)
    section("rentals", rentals)
    section("front_desk", desk)
    if "classes" in brief and "front_desk" in brief:
        section("coverage_gaps_next_7_days", gaps)
    section("sales_yesterday", lambda: sales_summary.__wrapped__((day - timedelta(days=1)).isoformat()))
    section("shift_log", lambda: shift_log.__wrapped__(2)["entries"])
    section("awaiting_approval", approvals.pending)
    if "classes" in brief:
        brief["booked_today"] = sum(c["booked"] for c in brief["classes"])
    return brief


@mcp.tool()
@traced
def propose_free_booking(member_id: int, session_id: int, reason: str) -> dict:
    """Propose booking a member into a class at no charge. Nothing changes until a person approves.

    Returns an action id. The approval request is posted to the ops chat room by this server.
    """
    s = momence.roster(session_id)
    summary = f"free booking for member {int(member_id)} in {s['name']} on {s['start']:%a %b %d at %H:%M} ({reason.strip()[:120]})"
    return approvals.propose("book_free", {"member_id": int(member_id), "session_id": int(session_id)}, summary)


@mcp.tool()
@traced
def propose_cancel_booking(session_id: int, booking_id: int, reason: str, notify_member: bool = True) -> dict:
    """Propose cancelling one booking (credit refunded). Nothing changes until a person approves.

    The booking must be on the roster of the given class; get both ids from class_roster.
    """
    r = momence.roster(session_id)
    person = next((p for p in r["people"] if p["booking_id"] == int(booking_id)), None)
    if not person:
        return {"ok": False, "error": f"booking {booking_id} is not on the roster of class {session_id}"}
    summary = (
        f"cancel {person['name']}'s booking in {r['name']} on {r['start']:%a %b %d at %H:%M}, "
        f"{'with' if notify_member else 'without'} an email to them ({reason.strip()[:120]})"
    )
    return approvals.propose("cancel_booking", {"booking_id": int(booking_id), "notify_member": bool(notify_member)}, summary)


@mcp.tool()
@traced
def execute_action(action_id: str) -> dict:
    """Run a proposed write, but only if an approver has reacted ✅ to it in chat.

    Safe to call again: a finished action returns its stored result and is never run twice.
    """
    return approvals.execute(action_id.strip())


def main():
    mcp.run()


if __name__ == "__main__":
    main()
