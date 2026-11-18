"""Append-only JSONL trace of every tool call: what was asked, how long it took, whether it worked.

Arguments are logged, results are not, so the trace never holds customer data.
"""

import functools
import json
import time
from datetime import datetime

from . import config


def record(tool, args, ok, ms, error=None):
    line = {
        "ts": datetime.now(config.TZ).isoformat(timespec="seconds"),
        "tool": tool,
        "args": args,
        "ok": ok,
        "ms": ms,
    }
    if error:
        line["error"] = error[:300]
    try:
        with open(config.state_dir() / "audit.jsonl", "a") as f:
            f.write(json.dumps(line, default=str) + "\n")
    except OSError:
        pass  # tracing must never break a tool


def traced(fn):
    """Wrap a tool: trace it, and turn failures into a structured error the agent can read."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        started = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - the agent needs the reason, not a stack trace
            ms = int((time.monotonic() - started) * 1000)
            record(fn.__name__, kwargs or list(args), False, ms, f"{type(e).__name__}: {e}")
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        record(fn.__name__, kwargs or list(args), True, int((time.monotonic() - started) * 1000))
        return result

    return wrapper
