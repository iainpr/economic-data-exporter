"""Rotating diagnostic logging with secret redaction."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from economic_data_exporter.config import LOG_DIR
from economic_data_exporter.utils.redaction import redact_text


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_text(item) if isinstance(item, str) else item for item in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: redact_text(value) if isinstance(value, str) else value
                for key, value in record.args.items()
            }
        return True


def configure_logging() -> None:
    root = logging.getLogger("economic_data_exporter")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        LOG_DIR / "economic-data-exporter.log",
        maxBytes=2_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.addFilter(RedactionFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
