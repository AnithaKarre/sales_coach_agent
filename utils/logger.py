
import sys
import os
import logging
from logging import Logger
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from config import credential_manager


# Ensure UTF-8 output for emoji and unicode in console logs
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding='utf-8')


class LogFilter(logging.Filter):
    """
    Log filter to shorten file path in logs relative to the project root.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        file_path = record.pathname
        try:
            project_root_path = Path(__file__).resolve().parents[1]
            record.pathname = os.path.relpath(file_path, project_root_path)
        except Exception:
            record.pathname = file_path
        return True


def get_logger() -> Logger:
    """
    Initializes and returns a logger instance with both console and rotating file handlers.
    """

    logger = logging.getLogger('agent_logger')

    # Prevent duplicate handlers if logger is already set
    if logger.handlers:
        return logger

    # Default level
    logging_level = credential_manager.get_key('LOGGING_LEVEL') or 'INFO'
    logging_level = getattr(logging, logging_level.upper().strip(), logging.INFO)
    logger.setLevel(logging_level)
    logger.propagate = False

    # Common formatter
    log_format = '%(asctime)s %(levelname)s %(pathname)s:%(lineno)d - %(message)s'
    formatter = logging.Formatter(log_format)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(LogFilter())
    logger.addHandler(console_handler)

    # File handler
    log_dir = credential_manager.get_key('LOGGING_FOLDER_PATH') or "./logs"
    log_file = credential_manager.get_key('LOGGING_FILE_NAME') or "application.log"
    log_path = os.path.join(log_dir, log_file)

    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    file_handler = TimedRotatingFileHandler(
        log_path, when="midnight", interval=1, backupCount=30, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(LogFilter())
    logger.addHandler(file_handler)

    # Uncomment if you want confirmation in logs
    # logger.info("Logger initialized with level %s", logging.getLevelName(logging_level))

    return logger


# Global logger instance
log = get_logger()