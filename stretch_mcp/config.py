"""Settings come from the environment only. Nothing secret lives in this repo."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo


def _load_dotenv():
    """Read KEY=value lines from STRETCH_MCP_ENV or ./.env without overriding real env."""
    path = Path(os.environ.get("STRETCH_MCP_ENV", ".env"))
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


_load_dotenv()


def get(name, default=None):
    value = os.environ.get(name, "")
    return value if value else default


def require(name):
    value = get(name)
    if not value:
        raise ConfigError(f"{name} is not set")
    return value


class ConfigError(RuntimeError):
    """A tool was called but the system behind it is not configured."""


TZ = ZoneInfo(get("STUDIO_TZ", "America/Vancouver"))


def state_dir():
    path = Path(get("STRETCH_MCP_STATE_DIR", str(Path.home() / ".local/state/stretch-mcp")))
    path.mkdir(parents=True, exist_ok=True)
    return path
