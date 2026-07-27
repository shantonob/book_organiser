import os
import sys
import logging
from logging.handlers import RotatingFileHandler

import config


def setup_logger(name, filename=None, level=logging.INFO, also_stdout=False):
    if filename is None:
        filename = f"{name}.log"
    # Use local log dir to avoid SMB latency
    log_dir = os.path.join(os.path.expanduser("~"), "book_organiser_data", "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, filename)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.handlers.clear()

    handler = RotatingFileHandler(log_path, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(handler)

    if also_stdout:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
        logger.addHandler(console)

    return logger
