"""Human approval for anything that changes a customer's booking.

The agent can only *propose* a write. The server posts the proposal to a Matrix room and
records the event id. `execute` then asks the homeserver who reacted to that event, and
runs the write only if an approver did. The agent never holds anything it could use to
approve its own proposal: the check is made against the homeserver, not against tool input.

With no Matrix settings, proposals are still recorded but can never be executed.
"""

import json
import secrets
import time
import urllib.parse

from . import config, http, momence

APPROVE_KEYS = {"✅", "✔️", "✔", "👍", "👍️"}
REJECT_KEYS = {"❌", "👎", "👎️", "🚫"}
TTL_SECONDS = 24 * 3600

ACTIONS = {
    "book_free": lambda p: momence.book_free(p["member_id"], p["session_id"]),
    "cancel_booking": lambda p: momence.cancel_booking(p["booking_id"], p.get("notify_member", True)),
}


def _path():
    return config.state_dir() / "actions.json"


def _load():
    p = _path()
    return json.loads(p.read_text()) if p.is_file() else {}


def _save(actions):
    tmp = _path().with_suffix(".tmp")
    tmp.write_text(json.dumps(actions, indent=1))
    tmp.replace(_path())


def _matrix():
    hs, token, room = (config.get(k) for k in ("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "APPROVAL_ROOM_ID"))
    if not (hs and token and room):
        return None
    return hs.rstrip("/"), {"Authorization": f"Bearer {token}"}, room


def _approvers():
    return {u.strip() for u in (config.get("APPROVER_USER_IDS", "") or "").split(",") if u.strip()}


def propose(kind, params, summary):
    if kind not in ACTIONS:
        raise ValueError(f"unknown action kind {kind}")
    actions = _load()
    # Same proposal twice while one is still pending: hand back the pending one.
    for a in actions.values():
        if a["kind"] == kind and a["params"] == params and a["status"] == "pending" and a["expires"] > time.time():
            return _public(a)
    action = {
        "id": "A-" + secrets.token_hex(3),
        "kind": kind,
        "params": params,
        "summary": summary,
        "status": "pending",
        "created": time.time(),
        "expires": time.time() + TTL_SECONDS,
        "event_id": None,
    }
    mx = _matrix()
    if mx:
        hs, headers, room = mx
        body = f"Approval needed {action['id']}: {summary}\nReact ✅ to approve or ❌ to reject. Expires in 24 hours."
        resp = http.request(
            "PUT",
            f"{hs}/_matrix/client/v3/rooms/{urllib.parse.quote(room)}/send/m.room.message/{action['id']}-{int(time.time())}",
            headers=headers,
            json_body={"msgtype": "m.text", "body": body},
        )
        action["event_id"] = resp.get("event_id")
    actions[action["id"]] = action
    _save(actions)
    return _public(action)


def _reactions(action):
    hs, headers, room = _matrix()
    data = http.request(
        "GET",
        f"{hs}/_matrix/client/v1/rooms/{urllib.parse.quote(room)}/relations/"
        f"{urllib.parse.quote(action['event_id'])}/m.annotation/m.reaction",
        headers=headers,
        params={"limit": 50},
    )
    approvers = _approvers()
    keys = set()
    for ev in data.get("chunk") or []:
        if ev.get("sender") in approvers:
            keys.add(((ev.get("content") or {}).get("m.relates_to") or {}).get("key"))
    return keys


def execute(action_id):
    actions = _load()
    action = actions.get(action_id)
    if not action:
        return {"ok": False, "error": f"no such action {action_id}"}
    if action["status"] in ("done", "rejected", "failed"):
        return _public(action)  # idempotent: never run a write twice
    if time.time() > action["expires"]:
        action["status"] = "expired"
        _save(actions)
        return _public(action)
    if not _matrix() or not action.get("event_id"):
        return {**_public(action), "ok": False, "error": "approvals are not configured, so this stays a dry run"}
    keys = _reactions(action)
    if keys & REJECT_KEYS:
        action["status"] = "rejected"
    elif keys & APPROVE_KEYS:
        try:
            action["result"] = ACTIONS[action["kind"]](action["params"])
            action["status"] = "done"
        except Exception as e:  # noqa: BLE001
            action["status"] = "failed"
            action["result"] = {"error": f"{type(e).__name__}: {e}"}
        action["finished"] = time.time()
    else:
        return {**_public(action), "ok": False, "error": "not approved yet: waiting for a ✅ from an approver"}
    _save(actions)
    return _public(action)


def pending():
    now = time.time()
    return [_public(a) for a in _load().values() if a["status"] == "pending" and a["expires"] > now]


def _public(a):
    out = {k: a[k] for k in ("id", "kind", "summary", "status")}
    out["approval_requested_in_chat"] = bool(a.get("event_id"))
    if "result" in a:
        out["result"] = a["result"]
    return out
