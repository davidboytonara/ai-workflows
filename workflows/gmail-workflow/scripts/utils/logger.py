"""Logging configuration for Gmail skill.

Provides consistent logging across all scripts with appropriate log levels and formats.
"""

import logging
import sys
import os
from datetime import datetime
from typing import Optional, Dict, Any


DEFAULT_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logger(name: str, level: Optional[str] = None, log_file: Optional[str] = None) -> logging.Logger:
    """Set up logger with consistent configuration."""
    logger = logging.getLogger(name)

    if level is None:
        level = os.getenv("LOG_LEVEL", "INFO").upper()

    numeric_level = getattr(logging, level, logging.INFO)
    logger.setLevel(numeric_level)

    logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)

    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DATE_FORMAT)
    console_handler.setFormatter(formatter)

    logger.addHandler(console_handler)

    if log_file:
        try:
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"Failed to create file handler: {e}")

    logger.propagate = False
    return logger


def log_error_with_context(logger: logging.Logger, error: Exception, context: Dict[str, Any]):
    """Log error with additional context."""
    logger.error(f"Error: {type(error).__name__}: {str(error)}")
    logger.error("Context:")
    for key, value in context.items():
        logger.error(f"  {key}: {value}")


def log_success(logger: logging.Logger, operation: str, result: Dict[str, Any]):
    """Log successful operation with result details."""
    logger.info(f"✓ {operation} completed successfully")
    if result:
        for key, value in result.items():
            logger.info(f"  {key}: {value}")
