import logging
import os

from .paths import resource_path


SENSITIVE_KEYS = ("cookie", "jsessionid", "authorization", "token")


def log_dir():
    path = resource_path("settings")
    os.makedirs(path, exist_ok=True)
    return path


def log_path():
    return os.path.join(log_dir(), "plugin.log")


def sanitize(message):
    text = str(message)
    lower = text.lower()
    if any(key in lower for key in SENSITIVE_KEYS):
        return "[redacted sensitive log message]"
    return text


def setup_logging(path=None):
    path = path or log_path()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        filename=path,
        filemode="a",
    )
    return path


def get_logger(name):
    setup_logging()
    return logging.getLogger(name)


def info(logger, message):
    logger.info(sanitize(message))


def error(logger, message):
    logger.error(sanitize(message))
