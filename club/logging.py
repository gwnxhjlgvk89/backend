"""Scrub query credentials from third-party server logs, including WebSocket URLs."""
import logging
import re


class Redact(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        message = re.sub(r'([?&](?:ticket|token|password)=)[^&\s"\']+', r'\1[redacted]', message, flags=re.I)
        message = re.sub(r'Bearer\s+[^\s"\']+', 'Bearer [redacted]', message, flags=re.I)
        record.msg, record.args = message, ()
        return True


def install():
    for name in ('uvicorn.error', 'uvicorn.access', 'club'):
        logging.getLogger(name).addFilter(Redact())
