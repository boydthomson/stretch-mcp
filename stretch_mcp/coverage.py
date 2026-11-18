"""Does somebody staff the front desk for every class and rental? Pure logic, no I/O."""

from datetime import timedelta


def _merge(windows):
    merged = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def find_gaps(items, shifts, lead_minutes=0):
    """Compare bookable items against assigned front desk shifts.

    items:  [{name, start, end}]            classes and rentals
    shifts: [{who, open, start, end}]       open (unassigned) shifts do not count as cover
    lead_minutes: how long before the start the desk must already be staffed

    Back-to-back shifts are merged first, so a class that straddles a handover is covered.
    Returns [{name, start, end, status, uncovered_minutes, on_desk}] for every item that is
    not fully covered. status is "uncovered" (nobody at all) or "partial".
    """
    staffed = [s for s in shifts if not s.get("open")]
    merged = _merge([(s["start"], s["end"]) for s in staffed])
    gaps = []
    for it in items:
        need_start = it["start"] - timedelta(minutes=lead_minutes)
        need_end = it["end"]
        covered = timedelta()
        for start, end in merged:
            lo, hi = max(start, need_start), min(end, need_end)
            if hi > lo:
                covered += hi - lo
        missing = (need_end - need_start) - covered
        if missing <= timedelta():
            continue
        on_desk = [s["who"] for s in staffed if s["start"] < need_end and s["end"] > need_start]
        gaps.append(
            {
                "name": it["name"],
                "start": it["start"],
                "end": it["end"],
                "status": "partial" if covered else "uncovered",
                "uncovered_minutes": int(missing.total_seconds() // 60),
                "on_desk": on_desk,
            }
        )
    return gaps
