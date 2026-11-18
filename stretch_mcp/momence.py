"""Momence public API v2 client: classes, rosters, rentals, sales, and two writes."""

import base64
import json
import time
from datetime import date, datetime, timedelta, timezone

from . import config, http

API = "https://api.momence.com/api/v2"
_token = {"value": None, "expires": 0.0}


def _auth_header():
    if _token["value"] and time.time() < _token["expires"]:
        return {"Authorization": f"Bearer {_token['value']}"}
    basic = base64.b64encode(
        f"{config.require('MOMENCE_CLIENT_ID')}:{config.require('MOMENCE_CLIENT_SECRET')}".encode()
    ).decode()
    data = http.request(
        "POST",
        f"{API}/auth/token",
        headers={"Authorization": f"Basic {basic}"},
        form={
            "grant_type": "password",
            "username": config.require("MOMENCE_USERNAME"),
            "password": config.require("MOMENCE_PASSWORD"),
        },
    )
    _token["value"] = data["accessToken"]
    _token["expires"] = time.time() + 6 * 3600  # tokens last about a day; refresh well before
    return {"Authorization": f"Bearer {_token['value']}"}


def _call(method, path, **kw):
    return http.request(method, f"{API}{path}", headers=_auth_header(), **kw)


def _paginate(path, params=None, page_size=100, max_items=1000):
    items, page = [], 0
    while len(items) < max_items:
        # `page` is required by every Momence list endpoint and the rows are under `payload`.
        data = _call("GET", path, params={**(params or {}), "page": page, "pageSize": page_size})
        rows = data.get("payload") or []
        items.extend(rows)
        if len(rows) < page_size:
            break
        page += 1
    return items


def day_bounds_utc(day: date):
    start = datetime(day.year, day.month, day.day, tzinfo=config.TZ)
    end = start + timedelta(days=1)
    fmt = "%Y-%m-%dT%H:%M:%S.000Z"
    return start.astimezone(timezone.utc).strftime(fmt), end.astimezone(timezone.utc).strftime(fmt)


def to_local(iso_utc: str) -> datetime:
    return datetime.fromisoformat(iso_utc.replace("Z", "+00:00")).astimezone(config.TZ)


def _teacher_name(session):
    t = session.get("teacher") or {}
    return (" ".join(x for x in (t.get("firstName"), t.get("lastName")) if x)).strip() or None


def sessions(start_day: date, days: int = 1):
    """Classes starting in [start_day, start_day + days), cancelled ones excluded."""
    after, _ = day_bounds_utc(start_day)
    _, before = day_bounds_utc(start_day + timedelta(days=days - 1))
    rows = _paginate(
        "/host/sessions",
        {"startAfter": after, "startBefore": before, "sortBy": "startsAt", "sortOrder": "ASC"},
    )
    out = []
    for s in rows:
        if s.get("isCancelled"):
            continue  # filtered here: includeCancelled=false makes the API return nothing
        start, end = to_local(s["startsAt"]), to_local(s["endsAt"])
        out.append(
            {
                "session_id": s["id"],
                "name": (s.get("name") or "").strip(),
                "teacher": _teacher_name(s),
                "start": start,
                "end": end,
                "booked": s.get("bookingCount") or 0,
                "capacity": s.get("capacity"),
            }
        )
    return out


def roster(session_id: int):
    """Who is booked. Names are reduced to first name plus last initial."""
    s = _call("GET", f"/host/sessions/{int(session_id)}")
    people = []
    # This endpoint rejects page sizes above 50.
    for b in _paginate(f"/host/sessions/{int(session_id)}/bookings", page_size=50, max_items=300):
        if b.get("cancelledAt"):
            continue
        m = b.get("member") or {}
        last = (m.get("lastName") or "").strip()
        people.append(
            {
                "booking_id": b["id"],
                "member_id": m.get("id"),
                "name": f"{(m.get('firstName') or '').strip()} {last[:1] + '.' if last else ''}".strip(),
                "checked_in": bool(b.get("checkedIn")),
            }
        )
    return {
        "session_id": int(session_id),
        "name": (s.get("name") or "").strip(),
        "start": to_local(s["startsAt"]),
        "capacity": s.get("capacity"),
        "people": people,
    }


def rentals(start_day: date, days: int = 1):
    """Room rentals and private bookings (Momence appointment reservations).

    The endpoint ignores date filters, so walk it newest first and stop at the window start.
    """
    lo = datetime(start_day.year, start_day.month, start_day.day, tzinfo=config.TZ)
    hi = lo + timedelta(days=days)
    out, page = [], 0
    while page < 40:
        data = _call(
            "GET",
            "/host/appointments/reservations",
            params={"page": page, "pageSize": 100, "sortBy": "startsAt", "sortOrder": "DESC"},
        )
        rows = data.get("payload") or []
        for r in rows:
            if r.get("cancelledAt") or not r.get("startsAt"):
                continue
            start = to_local(r["startsAt"])
            if lo <= start < hi:
                service = (r.get("service") or {}).get("name") or "Rental"
                board = (r.get("board") or {}).get("name")
                out.append(
                    {
                        "reservation_id": r.get("id"),
                        "name": f"{service.strip()} [{board.strip()}]" if board else service.strip(),
                        "start": start,
                        "end": to_local(r.get("endsAt") or r["startsAt"]),
                    }
                )
        if len(rows) < 100 or (rows and rows[-1].get("startsAt") and to_local(rows[-1]["startsAt"]) < lo):
            break
        page += 1
    return sorted(out, key=lambda x: x["start"])


def _amount(item):
    for key in ("paymentValue", "amount", "total", "value"):
        v = item.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def sales(day: date, wait_seconds: int = 90):
    """Total sales for one studio-local day from the Momence report API.

    Finished days are cached on disk because the report API allows 100 runs a day.
    """
    cache = config.state_dir() / f"sales-{day.isoformat()}.json"
    today = datetime.now(config.TZ).date()
    if day < today and cache.is_file():
        return json.loads(cache.read_text())
    start, end = day_bounds_utc(day)
    run = _call(
        "POST",
        "/host/reports",
        json_body={
            "parameters": {
                "reportType": "total-sales",
                "hostId": int(config.require("MOMENCE_HOST_ID")),
                "dateRange": {"from": start, "to": end},
                "includeRefunds": True,
            }
        },
    )
    run_id = run.get("id") or (run.get("payload") or {}).get("id")
    deadline = time.time() + wait_seconds
    payload = {}
    while time.time() < deadline:
        data = _call("GET", f"/host/reports/{run_id}", timeout=60)
        payload = data.get("payload", data)
        if payload.get("status") == "completed":
            break
        time.sleep(3)
    else:
        raise TimeoutError("Momence sales report did not finish in time")
    items = (payload.get("data") or {}).get("items") or payload.get("items") or []
    by_category, by_method, refunded = {}, {}, 0.0
    for it in items:
        amount = _amount(it)
        refunded += float(it.get("refunded") or 0)
        for bucket, key in ((by_category, "paymentCategory"), (by_method, "paymentMethod")):
            label = str(it.get(key) or "other")
            bucket[label] = round(bucket.get(label, 0.0) + amount, 2)
    rank = lambda d: dict(sorted(d.items(), key=lambda kv: -kv[1]))  # noqa: E731
    result = {
        "date": day.isoformat(),
        "total": round(sum(_amount(it) for it in items), 2),
        "refunded": round(refunded, 2),
        "transactions": len(items),
        "by_category": rank(by_category),
        "by_payment_method": rank(by_method),
        "includes_tax": True,
    }
    if day < today:
        cache.write_text(json.dumps(result))
    return result


# ---- writes: only ever called by approvals.execute after a human said yes ----

def book_free(member_id: int, session_id: int):
    resp = _call("POST", f"/host/sessions/{int(session_id)}/bookings/free", json_body={"memberId": int(member_id)})
    return {"booking_id": resp.get("sessionBookingId")}


def cancel_booking(booking_id: int, notify_member: bool):
    _call(
        "DELETE",
        f"/host/session-bookings/{int(booking_id)}",
        json_body={"refund": True, "disableNotifications": not notify_member, "isLateCancellation": False},
    )
    return {"cancelled": int(booking_id)}
