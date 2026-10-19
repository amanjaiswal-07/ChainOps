"""
Structured (JSON lines) logging.

Usage: log.info("decision_cycle_completed", extra={"fields": {...}})
Only ids, statuses and timings are logged; never API keys or payload
contents beyond what the audit record already holds.
"""

import json
import logging

import config


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(entry, default=str)


def setup_logging():
    """Idempotent: safe to call from the API, the UI and scripts."""
    root = logging.getLogger("chainops")
    if root.handlers:
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(config.LOG_LEVEL)
    root.propagate = False
