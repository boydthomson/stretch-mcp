from datetime import datetime
from zoneinfo import ZoneInfo

from stretch_mcp.coverage import find_gaps

TZ = ZoneInfo("America/Vancouver")


def t(h, m=0):
    return datetime(2026, 11, 18, h, m, tzinfo=TZ)


def item(name, a, b):
    return {"name": name, "start": a, "end": b}


def shift(who, a, b, open=False):
    return {"who": who, "open": open, "start": a, "end": b}


def test_fully_covered_is_not_a_gap():
    assert find_gaps([item("Flow", t(12), t(13))], [shift("Boyd", t(11, 30), t(13, 30))]) == []


def test_nobody_on_desk():
    (g,) = find_gaps([item("Flow", t(7), t(8))], [shift("Boyd", t(11, 30), t(13, 30))])
    assert g["status"] == "uncovered" and g["uncovered_minutes"] == 60 and g["on_desk"] == []


def test_partial_cover_reports_missing_minutes():
    (g,) = find_gaps([item("Yin", t(19, 30), t(20, 45))], [shift("Sam", t(17), t(20, 30))])
    assert g["status"] == "partial" and g["uncovered_minutes"] == 15 and g["on_desk"] == ["Sam"]


def test_handover_between_two_shifts_counts_as_covered():
    shifts = [shift("Alex", t(9, 30), t(12, 30)), shift("Boyd", t(12, 30), t(14))]
    assert find_gaps([item("Noon", t(12), t(13))], shifts) == []


def test_open_shift_is_not_cover():
    (g,) = find_gaps([item("Early", t(7), t(8))], [shift("Open shift", t(6, 30), t(8, 30), open=True)])
    assert g["status"] == "uncovered"


def test_lead_time_must_be_staffed_too():
    (g,) = find_gaps([item("Flow", t(12), t(13))], [shift("Boyd", t(12), t(13))], lead_minutes=15)
    assert g["status"] == "partial" and g["uncovered_minutes"] == 15
