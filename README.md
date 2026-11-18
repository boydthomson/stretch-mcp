# stretch-mcp

An MCP server that gives an operations agent governed access to the systems that run
[STRETCH Yoga](https://www.stretchvancouver.com), an independent studio at 180 E. Pender St
in Vancouver.

The agent answers "what is going on at the studio today?" from live data, and it can ask
to change a booking, but it cannot change one by itself. A person approves every write in
chat first.

## Why it exists

A studio this size runs on a booking system, a staff scheduler, a shift log and a group
chat, and the owner is the integration layer between them. Before this server, each agent
skill carried its own API recipes and credentials. This puts one typed, audited tool layer
in front of those systems so that any MCP client (Hermes, Claude Code, Claude Desktop) gets
the same tools with the same rules.

## Tools

| Tool | What it returns | Source |
|---|---|---|
| `daily_brief` | The day's classes and rentals, who is on the desk, coverage gaps for the week, yesterday's sales, shift log notes, writes awaiting approval | all of the below |
| `class_schedule` | Classes with teacher, bookings and capacity | Momence API |
| `class_roster` | Who is booked and checked in (first name and last initial only) | Momence API |
| `room_rentals` | Room rentals and private bookings | Momence API |
| `front_desk_shifts` | Who is scheduled on the front desk | iCal feed from the staff scheduler (Rippling) |
| `coverage_gaps` | Classes and rentals with nobody assigned to the desk | Momence + scheduler |
| `sales_summary` | A day's sales by category and payment method, with the same weekday a week earlier | Momence report API |
| `shift_log` | What staff flagged at end of shift: broken things, supplies, incidents | Formbricks |
| `propose_free_booking`, `propose_cancel_booking` | A pending action id. Nothing changes | |
| `execute_action` | Runs a proposed write only after a person approved it | Matrix + Momence |

## How writes are approved

```
agent                     stretch-mcp                    Matrix room            Momence
  | propose_cancel_booking      |                             |                    |
  |---------------------------->| validate against roster     |                    |
  |                             | post "Approval needed A-1f" |                    |
  |                             |---------------------------->|                    |
  |        action id, pending   |                             |  owner reacts ✅   |
  |<----------------------------|                             |                    |
  | execute_action(A-1f)        |                             |                    |
  |---------------------------->| who reacted to that event?  |                    |
  |                             |---------------------------->|                    |
  |                             | approver did: run the write |                    |
  |                             |------------------------------------------------->|
  |             status: done    |                             |                    |
  |<----------------------------|                             |                    |
```

The design points:

- The approval check is made against the homeserver, not against anything the agent
  passes in. The agent holds no token or code that could approve its own proposal.
- A proposal is validated when it is made (the booking has to be on that class's roster),
  and the summary a person approves is written by the server, not by the model.
- Executing is idempotent. A finished action returns its stored result and never runs twice.
- Proposals expire after 24 hours. A ❌ rejects.
- With no Matrix settings, proposals are recorded and can never be executed.

## Tracing

Every tool call appends one line to `audit.jsonl` in the state directory: timestamp, tool,
arguments, duration and success. Results are not logged, so the trace holds no customer
data. Tool failures come back to the agent as `{"ok": false, "error": ...}` rather than as
a stack trace, and `daily_brief` reports a failed section under `unavailable` instead of
failing as a whole.

## Run it

```bash
git clone https://github.com/boydthomson/stretch-mcp && cd stretch-mcp
cp .env.example .env    # fill in; nothing secret is committed
uv sync
uv run pytest
uv run stretch-mcp      # stdio
```

Client config (Hermes `config.yaml`, same shape for other clients):

```yaml
mcp_servers:
  stretch:
    command: /path/to/stretch-mcp/.venv/bin/stretch-mcp
    env:
      STRETCH_MCP_ENV: /path/to/stretch-mcp/.env
```

## Layout

```
stretch_mcp/
  server.py     tool definitions (MCP Python SDK v2)
  momence.py    booking system client
  frontdesk.py  iCal shift feed parser
  coverage.py   pure coverage logic, unit tested
  shiftlog.py   Formbricks responses
  approvals.py  propose / approve / execute state machine
  audit.py      JSONL trace
profile/        the Hermes agent profile that uses this server
tests/
```

## Known limits

- The gate governs the tool path. An agent that also has a shell on the same host and can
  read the server's `.env` could call the booking API directly. The `stretch-ops` profile
  in `profile/` therefore runs without terminal or file tools. Moving the server to its
  own host behind HTTP is the next step.
- Recurring iCal events are not expanded. Rippling publishes one event per shift.
- Sales totals include tax and come from the report API, which allows 100 runs a day;
  finished days are cached.
- There is no evaluation harness yet. The plan is a set of questions with known answers,
  scored nightly against the trace.

## License

MIT
