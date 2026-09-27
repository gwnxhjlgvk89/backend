"""Scrub query credentials from third-party server logs, including WebSocket URLs."""

import logging
import json
from datetime import datetime, timezone
import re


class Redact(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        message = re.sub(r'([?&](?:ticket|token|password)=)[^&\s"\']+', r"\1[redacted]", message, flags=re.I)
        message = re.sub(r'Bearer\s+[^\s"\']+', "Bearer [redacted]", message, flags=re.I)
        record.msg, record.args = message, ()
        return True


class Structured(logging.Formatter):
    def format(self, record):
        message = record.getMessage()
        try:
            payload = json.loads(message)
            if not isinstance(payload, dict):
                payload = {"event": message}
        except ValueError:
            payload = {"event": message}
        return json.dumps(
            {"time": datetime.now(timezone.utc).isoformat(), "level": record.levelname, **payload},
            ensure_ascii=False,
        )


def install():
    for name in ("uvicorn.error", "uvicorn.access", "club"):
        logging.getLogger(name).addFilter(Redact())

    app_logger = logging.getLogger("club")
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.addFilter(Redact())
        handler.setFormatter(Structured())
        app_logger.addHandler(handler)
        app_logger.setLevel(logging.INFO)
        app_logger.propagate = False
