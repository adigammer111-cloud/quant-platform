"""Application-wide logging setup.

Call `configure_logging()` once at process start (CLI entry points and the
Streamlit app both do this). Every module then does `logging.getLogger(__name__)`.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from config import settings

_CONFIGURED = False


def configure_logging() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    root = logging.getLogger()
    root.setLevel(settings.log_level.upper())

    fmt = logging.Formatter(
        fmt="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        settings.logs_dir / "quant_platform.log",
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    # Quiet down noisy third-party loggers.
    for noisy in ("urllib3", "peewee", "yfinance"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True
