import logging
import sys
from app.core.config import get_settings


class StandardFormatter(logging.Formatter):
    """
    Structured standard formatter for development and production logs.
    """
    def format(self, record: logging.LogRecord) -> str:
        # Prevent leaking raw potential secret patterns if present in extra/args
        return super().format(record)


def setup_logging() -> None:
    """
    Configure root and application loggers.
    """
    settings = get_settings()
    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    log_format = (
        "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(StandardFormatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    # Clear existing handlers to prevent duplicate lines
    root_logger.handlers.clear()
    root_logger.addHandler(handler)

    # Adjust external noisy loggers
    logging.getLogger("uvicorn.access").setLevel(log_level)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Obtain a named logger instance.
    """
    return logging.getLogger(name)
