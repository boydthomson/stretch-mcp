"""Staff shift log: responses to a Formbricks survey filled in at the end of each shift."""

from datetime import datetime, timedelta, timezone

from . import config, http

# Fields worth a manager's attention, in the order they are reported.
FIELDS = ("staff", "shift_type", "broken", "supplies", "followup", "incident_details", "notes")


def entries(days: int = 2, limit: int = 50):
    host = config.require("FORMBRICKS_HOST").rstrip("/")
    data = http.request(
        "GET",
        f"{host}/api/v1/management/responses",
        headers={"x-api-key": config.require("FORMBRICKS_API_KEY")},
        params={"surveyId": config.require("SHIFT_LOG_SURVEY_ID"), "limit": limit},
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    out = []
    for r in data.get("data") or []:
        created = datetime.fromisoformat(r["createdAt"].replace("Z", "+00:00"))
        if created < cutoff:
            continue
        answers = r.get("data") or {}
        entry = {"submitted": created.astimezone(config.TZ)}
        for f in FIELDS:
            v = answers.get(f)
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            if v not in (None, "", []):
                entry[f] = str(v).strip()
        entry["needs_attention"] = any(entry.get(k) for k in ("broken", "supplies", "followup", "incident_details"))
        out.append(entry)
    return sorted(out, key=lambda e: e["submitted"], reverse=True)
