"""Shared logging configuration for PJSK Auto Player."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _resolve_level(level: Any) -> int:
    if isinstance(level, int):
        return level

    if isinstance(level, str):
        normalized = level.strip().upper()
        if normalized.isdigit():
            return int(normalized)
        resolved = getattr(logging, normalized, None)
        if isinstance(resolved, int):
            return resolved

    return logging.INFO


def setup_logging(
    config: dict | None = None,
    *,
    level: str | int | None = None,
    log_file: str | None = None,
    max_bytes: int | None = None,
    backup_count: int | None = None,
) -> int:
    """Configure the root logger for console and rotating file output."""
    logging_cfg = (config or {}).get("logging", {}) if isinstance(config, dict) else {}

    configured_level = level if level is not None else logging_cfg.get("level", "INFO")
    log_level = _resolve_level(configured_level)
    log_path = log_file if log_file is not None else logging_cfg.get("file", "")
    file_size = int(max_bytes if max_bytes is not None else logging_cfg.get("max_bytes", 10_485_760))
    file_backups = int(backup_count if backup_count is not None else logging_cfg.get("backup_count", 5))

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt="%H:%M:%S")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    if log_path:
        try:
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path,
                maxBytes=file_size,
                backupCount=file_backups,
                encoding="utf-8",
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except OSError as exc:
            print(f"Failed to initialize log file {log_path}: {exc}", file=sys.stderr)

    logging.captureWarnings(True)
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    return log_level