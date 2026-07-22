"""watchdog-based filesystem watcher for the inbox/watch directory."""

import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import config
from pipeline import run_all_phases
from log_utils import setup_logger

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


def start_watcher(watch_dir, recursive=False):
    os.makedirs(watch_dir, exist_ok=True)
    event_handler = InboxHandler(watch_dir)
    observer = Observer()
    observer.schedule(event_handler, watch_dir, recursive=recursive)
    observer.start()
    logger.info(f"Watching {watch_dir} for new ebooks (recursive={recursive}, debounce=5s)...")
    return observer
