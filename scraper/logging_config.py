import json
import logging
import sys
from datetime import datetime
from typing import Optional
from functools import wraps


class StructuredFormatter(logging.Formatter):
    """Custom formatter that outputs structured JSON logs"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """Custom formatter for human-readable logs"""

    def format(self, record: logging.LogRecord) -> str:
        base_format = f"[{record.levelname:8}] {record.name}: {record.getMessage()}"

        # Add extra fields if present
        if hasattr(record, "extra_data"):
            extra_str = " | ".join(
                f"{k}={v}" for k, v in record.extra_data.items()
            )
            base_format += f" | {extra_str}"

        if record.exc_info:
            base_format += f"\n{self.formatException(record.exc_info)}"

        return base_format


def setup_logging(
    level: str = "INFO",
    log_format: str = "json",
    log_file: Optional[str] = None,
) -> logging.Logger:
    """
    Configure structured logging for the application

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_format: Format type ('json' or 'text')
        log_file: Optional file path for logging

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger("scraper")
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create formatter
    if log_format.lower() == "json":
        formatter = StructuredFormatter()
    else:
        formatter = TextFormatter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def logged(logger: logging.Logger, level: str = "INFO"):
    """
    Decorator to log function calls with arguments and results

    Args:
        logger: Logger instance
        level: Logging level
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            log_level = getattr(logging, level.upper())

            # Log function call
            logger.log(
                log_level,
                f"Calling {func.__name__}",
                extra={"extra_data": {"function": func.__name__, "args": str(args)[:100], "kwargs": str(kwargs)[:100]}},
            )

            try:
                result = func(*args, **kwargs)
                logger.log(
                    log_level,
                    f"Completed {func.__name__}",
                    extra={"extra_data": {"function": func.__name__}},
                )
                return result
            except Exception as e:
                logger.error(
                    f"Error in {func.__name__}: {str(e)}",
                    extra={"extra_data": {"function": func.__name__, "error": str(e)}},
                    exc_info=True,
                )
                raise

        return wrapper

    return decorator
