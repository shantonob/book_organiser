"""watchdog-based filesystem watcher for the inbox/watch directory."""

import os
import threading
import time

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

import config
from log_utils import setup_logger
from pipeline import run_all_phases

logger = setup_logger("watcher", also_stdout=False)


class InboxHandler(FileSystemEventHandler):
    def __init__(self, watch_dir, debounce=5):
        self.watch_dir = watch_dir
        self.debounce = debounce
        self._last_trigger = 0

    def on_created(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def on_modified(self, event):
        if event.is_directory:
            return
        self._handle(event.src_path)

    def _handle(self, path):
        ext = os.path.splitext(path)[1].lower()
        if ext not in config.EBOOK_EXTS:
            return
        now = time.time()
        if now - self._last_trigger < self.debounce:
            return
        self._last_trigger = now
        fname = os.path.basename(path)
        logger.info(f"New ebook detected: {fname}")
        logger.info(f"Running pipeline (source={self.watch_dir}) ...")
        run_all_phases(source=self.watch_dir)
        logger.info(f"Pipeline complete for {fname}")


def _scan_existing(watch_dir):
    """Background: run pipeline on existing files once."""
    has_files = False
    for root, dirs, files in os.walk(watch_dir):
        for f in files:
            if os.path.splitext(f)[1].lower() in config.EBOOK_EXTS:
                has_files = True
                break
        if has_files:
            break
    if has_files:
        logger.info("Found existing ebooks — running initial pipeline scan...")
        run_all_phases(source=watch_dir)
        logger.info("Initial scan complete.")
    else:
        logger.info("No existing ebooks found in watch directory.")


def start_watcher(watch_dir, recursive=False, scan_existing=True):
    os.makedirs(watch_dir, exist_ok=True)
    event_handler = InboxHandler(watch_dir)
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=recursive)
    observer.start()
    logger.info(f"Watching {watch_dir} for new ebooks (recursive={recursive}, debounce=5s)...")
    if scan_existing:
        threading.Thread(target=_scan_existing, args=(watch_dir,), daemon=True).start()
    return observer
