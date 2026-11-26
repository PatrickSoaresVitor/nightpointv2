import json
import logging
import re
from app.platform.telemetry import FAILURES


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        # Deliberate allowlist: no raw URL/query, headers, body, exceptions or SQL.
        correlation = getattr(record, "correlation_id", None)
        correlation = correlation if isinstance(correlation, str) and re.fullmatch(r"[0-9a-f]{32}", correlation) else None
        status = getattr(record, "status", None)
        status = status if isinstance(status, int) and 100 <= status <= 599 else None
        category = getattr(record,"failure_category",None)
        category = category if isinstance(category,str) and category in FAILURES else None
        return json.dumps({
            "level": record.levelname if record.levelname in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"} else "UNKNOWN",
            "event": "http_request" if record.msg == "http_request" else "redacted_event",
            "correlation_id": correlation,
            "status": status,
            "failure_category": category,
        })


def configure_logging() -> None:
    logger = logging.getLogger("nightpoint")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
