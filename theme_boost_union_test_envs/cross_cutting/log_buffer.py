"""In-memory ring buffer that captures server log output.

Both the application's own loguru logs (e.g. provisioning info / errors) and
uvicorn's standard-library logging (startup, reload, access logs) are funneled
into a bounded deque so the frontend can display the same output a developer
would otherwise only see in the terminal running ``uvicorn``.

The buffer is process-local and resets on restart; it is intended for live
debugging, not long-term persistence.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any

# Keep at most this many log lines in memory.
_MAX_LINES = 2000

_buffer: deque[dict[str, Any]] = deque(maxlen=_MAX_LINES)
_lock = threading.Lock()
_seq = 0


def _append(timestamp: str, level: str, message: str, source: str) -> None:
    global _seq
    with _lock:
        _seq += 1
        _buffer.append(
            {
                "id": _seq,
                "timestamp": timestamp,
                "level": level,
                "message": message,
                "source": source,
            }
        )


def get_logs(limit: int = 1000, after_id: int | None = None) -> list[dict[str, Any]]:
    """Return buffered log lines, oldest first.

    Args:
        limit: maximum number of lines to return (most recent ones).
        after_id: when given, only lines with a higher id are returned. Lets
            the frontend poll incrementally without re-fetching everything.
    """
    with _lock:
        items = list(_buffer)
    if after_id is not None:
        items = [item for item in items if item["id"] > after_id]
    return items[-limit:]


def clear_logs() -> None:
    with _lock:
        _buffer.clear()


def _loguru_sink(message: Any) -> None:
    """loguru sink: stores each emitted record in the buffer."""
    record = message.record
    _append(
        timestamp=record["time"].astimezone(timezone.utc).isoformat(),
        level=record["level"].name,
        message=record["message"],
        source=f"{record['name']}:{record['function']}:{record['line']}",
    )


class _BufferLogHandler(logging.Handler):
    """stdlib logging handler: captures uvicorn / library logs."""

    def emit(self, record: logging.LogRecord) -> None:
        # The same record can reach this handler multiple times because it is
        # attached to several loggers in the propagation chain (root + the
        # uvicorn loggers). Guard against recording duplicates.
        if getattr(record, "_buffered", False):
            return
        record._buffered = True  # type: ignore[attr-defined]
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - never let logging crash the app
            message = str(record.msg)
        _append(
            timestamp=datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            level=record.levelname,
            message=message,
            source=record.name,
        )


_installed = False
_install_lock = threading.Lock()


def install_log_capture() -> None:
    """Attach the buffer to loguru and the standard logging system (idempotent)."""
    global _installed
    with _install_lock:
        if _installed:
            return
        _installed = True

    import loguru

    loguru.logger.add(_loguru_sink, level="DEBUG", enqueue=False)

    handler = _BufferLogHandler()
    handler.setLevel(logging.INFO)
    # Root catches most library logging; uvicorn loggers are attached
    # explicitly because they do not always propagate to root.
    logging.getLogger().addHandler(handler)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).addHandler(handler)
