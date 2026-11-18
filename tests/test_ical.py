from stretch_mcp.frontdesk import parse_ical

FEED = """BEGIN:VCALENDAR\r
BEGIN:VEVENT\r
DTSTART;TZID=America/Vancouver:20261118T170000\r
DTEND;TZID=America/Vancouver:20261118T210000\r
SUMMARY:Alex - Front\r
  Desk\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART:20261118T143000Z\r
DTEND:20261118T163000Z\r
SUMMARY:Boyd\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;VALUE=DATE:20261118\r
DTEND;VALUE=DATE:20261119\r
SUMMARY:Holiday\r
END:VEVENT\r
BEGIN:VEVENT\r
DTSTART;TZID=America/Vancouver:20261118T090000\r
DTEND;TZID=America/Vancouver:20261118T100000\r
STATUS:CANCELLED\r
SUMMARY:Gone\r
END:VEVENT\r
END:VCALENDAR\r
"""


def test_parses_timed_events_in_studio_time():
    events = parse_ical(FEED)
    assert [e["summary"] for e in events] == ["Boyd", "Alex - Front Desk"]
    assert events[1]["start"].hour == 17 and events[1]["end"].hour == 21
    assert events[0]["start"].utcoffset() == events[1]["start"].utcoffset()
