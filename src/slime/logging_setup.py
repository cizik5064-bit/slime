"""Logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import Paths


def setup_logging(paths: Paths, *, verbose: bool = False) -> logging.Logger:
    """Configure the ``slime`` logger once per process."""
    logger = logging.getLogger("slime")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return logger

    paths.logs.mkdir(parents=True, exist_ok=True)
    try:
        handler: logging.Handler = RotatingFileHandler(
            paths.logs / "slime.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.NullHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    )
    logger.addHandler(handler)

    if verbose:
        stream = logging.StreamHandler()
        stream.setLevel(logging.DEBUG)
        stream.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
        logger.addHandler(stream)
    return logger
