"""
Logging configuration for Google Slides skill.

Provides consistent logging across all scripts with appropriate log levels and formats.
"""

import logging
import sys
import os
from datetime import datetime
from typing import Optional, Dict, Any


# Default log format
DEFAULT_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
DATE_FORMAT = '%Y-%m-%d %H:%M:%S'


def setup_logger(name: str, level: Optional[str] = None, log_file: Optional[str] = None) -> logging.Logger:
    """
    Set up logger with consistent configuration.

    Args:
        name: Logger name (typically __name__)
        level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        log_file: Optional log file path

    Returns:
        Configured logger instance

    Example:
        >>> logger = setup_logger(__name__)
        >>> logger.info("Script started")
    """
    # Get logger
    logger = logging.getLogger(name)

    # Determine log level
    if level is None:
        # Check environment variable
        level = os.getenv('LOG_LEVEL', 'INFO').upper()

    # Set log level
    numeric_level = getattr(logging, level, logging.INFO)
    logger.setLevel(numeric_level)

    # Remove existing handlers
    logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(numeric_level)

    # Create formatter
    formatter = logging.Formatter(DEFAULT_FORMAT, datefmt=DATE_FORMAT)
    console_handler.setFormatter(formatter)

    # Add console handler
    logger.addHandler(console_handler)

    # Add file handler if specified
    if log_file:
        try:
            # Create log directory if it doesn't exist
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            file_handler = logging.FileHandler(log_file)
            file_handler.setLevel(numeric_level)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

            logger.debug(f"Logging to file: {log_file}")
        except Exception as e:
            logger.warning(f"Failed to create file handler: {e}")

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get logger instance (convenience function).

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def set_debug_mode(enabled: bool = True):
    """
    Enable or disable debug mode for all loggers.

    Args:
        enabled: Whether to enable debug mode
    """
    level = logging.DEBUG if enabled else logging.INFO
    logging.getLogger().setLevel(level)

    for handler in logging.getLogger().handlers:
        handler.setLevel(level)


def log_api_call(logger: logging.Logger, operation: str, details: Dict[str, Any]):
    """
    Log API call details in a structured format.

    Args:
        logger: Logger instance
        operation: API operation name (e.g., 'createSlide', 'insertText')
        details: Dict with operation details
    """
    logger.debug(f"API Call: {operation}")
    for key, value in details.items():
        logger.debug(f"  {key}: {value}")


def log_batch_operation(logger: logging.Logger, batch_num: int, total_batches: int,
                       requests_count: int, operation_type: str = "batch"):
    """
    Log batch operation progress.

    Args:
        logger: Logger instance
        batch_num: Current batch number
        total_batches: Total number of batches
        requests_count: Number of requests in this batch
        operation_type: Type of operation
    """
    progress = (batch_num / total_batches) * 100
    logger.info(
        f"{operation_type.capitalize()} {batch_num}/{total_batches} "
        f"({progress:.1f}%) - {requests_count} requests"
    )


def log_error_with_context(logger: logging.Logger, error: Exception, context: Dict[str, Any]):
    """
    Log error with additional context.

    Args:
        logger: Logger instance
        error: Exception that occurred
        context: Dict with contextual information
    """
    logger.error(f"Error: {type(error).__name__}: {str(error)}")
    logger.error("Context:")
    for key, value in context.items():
        logger.error(f"  {key}: {value}")


def log_success(logger: logging.Logger, operation: str, result: Dict[str, Any]):
    """
    Log successful operation with result details.

    Args:
        logger: Logger instance
        operation: Operation name
        result: Dict with result details
    """
    logger.info(f"✓ {operation} completed successfully")
    if result:
        for key, value in result.items():
            logger.info(f"  {key}: {value}")


def create_log_file_path(script_name: str, log_dir: str = 'logs') -> str:
    """
    Create log file path with timestamp.

    Args:
        script_name: Name of the script
        log_dir: Directory to store logs

    Returns:
        Full path to log file

    Example:
        >>> create_log_file_path('create_slides')
        'logs/create_slides_20250117_143022.log'
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"{script_name}_{timestamp}.log"
    return os.path.join(log_dir, filename)


class APICallLogger:
    """Context manager for logging API call lifecycle."""

    def __init__(self, logger: logging.Logger, operation: str, **kwargs):
        """
        Initialize API call logger.

        Args:
            logger: Logger instance
            operation: Operation name
            **kwargs: Additional context to log
        """
        self.logger = logger
        self.operation = operation
        self.context = kwargs
        self.start_time = None

    def __enter__(self):
        """Start logging API call."""
        self.start_time = datetime.now()
        self.logger.info(f"Starting: {self.operation}")
        if self.context:
            for key, value in self.context.items():
                self.logger.debug(f"  {key}: {value}")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """End logging API call."""
        duration = (datetime.now() - self.start_time).total_seconds()

        if exc_type is None:
            self.logger.info(f"✓ Completed: {self.operation} (took {duration:.2f}s)")
        else:
            self.logger.error(
                f"✗ Failed: {self.operation} (after {duration:.2f}s) - "
                f"{exc_type.__name__}: {exc_val}"
            )

        # Don't suppress exception
        return False


# Create default logger for module
default_logger = setup_logger('google-slide')


if __name__ == '__main__':
    # Test examples
    logger = setup_logger(__name__, level='DEBUG')

    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")

    # Test API call logger
    with APICallLogger(logger, "createSlide", slide_layout="TITLE"):
        logger.info("Creating slide...")
        # Simulate work
        import time
        time.sleep(0.1)

    # Test error logging
    try:
        raise ValueError("Test error")
    except Exception as e:
        log_error_with_context(logger, e, {'presentation_id': '123', 'slide_num': 5})

    # Test success logging
    log_success(logger, "Create Presentation", {
        'presentation_id': '1ABC123',
        'url': 'https://docs.google.com/presentation/d/1ABC123/edit'
    })
