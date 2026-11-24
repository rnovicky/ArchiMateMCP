"""
D20: the record of what the write tools changed. One JSON line per write, in
CHANGE_LOG (changes.log in the server's folder by default) and in the server's
log: when, which key, which tool, which model and item, what changed. It says
who used the server's key, not which person: that is the multi-user epic's
change log in the API (EPIC_MULTIUSER.md, MU-16).
"""

from __future__ import annotations

import datetime
import json
import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger("app.changes")


def record(settings: Settings, key_name: str, tool: str, model: dict, item: dict[str, Any],
           change: dict[str, Any]) -> dict[str, Any]:
    """Write one line; a file that cannot be written is logged, and the change it records stays made."""
    entry = {
        "time": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "key": key_name or None, "tool": tool,
        "model": {"id": model["id"], "name": model.get("name")},
        "item": item, "change": change,
    }
    line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"), default=str)
    logger.info("change: %s", line)
    path = settings.change_log_path
    if path is not None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            logger.error("Cannot write the record of changes to %s (%s); the change itself is made.", path, e)
    return entry
