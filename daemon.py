"""Headless Pipeline Daemon

Runs the book pipeline as a standalone process, writing status to the
daemon_status table for the Flask API/UI to read.

Usage:
    python daemon.py --status           # Check daemon status
    python daemon.py --run metadata     # Run metadata phase (blocks)
    python daemon.py --run dedup        # Run dedup phase
    python daemon.py --run copy         # Run copy phase
    python daemon.py --run all          # Run all phases
    python daemon.py --run all --source "Z:\books"  # With custom source
"""

import argparse
import os
import sys
import time

import config
from config import DB_PATH
from db import (
    daemon_heartbeat,
    get_connection,
    get_daemon_status,
    init_db,
    load_config_overrides,
)
from log_utils import setup_logger
from pipeline import (
    run_all_phases,
    run_phase_copy,
    run_phase_dedup,
    run_phase_metadata,
    state,
)

logger = setup_logger("daemon", also_stdout=False)


def _run_with_daemon_status(phase_func, job_type, source=None):
    """Run a pipeline phase while writing status to daemon_status table."""
    pid = os.getpid()
    daemon_heartbeat(DB_PATH, job_type, "running", pid=pid)
    progress = [0, 0]
    error = None
    try:
        def progress_cb(done, total):
            nonlocal progress
            progress = [done, total]
            daemon_heartbeat(DB_PATH, job_type, "running", pid=pid,
                             current_file=state.current_file,
                             current_stage=state.current_stage,
                             current_phase=state.current_phase,
                             progress=progress)
        phase_func(source=source)
        daemon_heartbeat(DB_PATH, job_type, "done", pid=pid,
                         current_phase=state.current_phase,
                         progress=progress)
    except Exception as e:
        error = str(e)
        daemon_heartbeat(DB_PATH, job_type, "failed", pid=pid, error=error,
                         progress=progress)
        logger.error(f"Daemon failed: {error}")
        return False
    return True


def cmd_status():
    """Print daemon status to stdout."""
    status = get_daemon_status(DB_PATH)
    logger.info(f"Status:     {status.get('status', 'unknown')}")
    logger.info(f"Job type:   {status.get('job_type', '-')}")
    logger.info(f"PID:        {status.get('pid', '-')}")
    logger.info(f"Phase:      {status.get('current_phase', '-')}")
    logger.info(f"Stage:      {status.get('current_stage', '-')}")
    logger.info(f"File:       {status.get('current_file', '-')}")
    if status.get("progress"):
        p = status["progress"]
        logger.info(f"Progress:   {p[0]}/{p[1]} ({p[1]-p[0]} remaining)")
    if status.get("error"):
        logger.info(f"Error:      {status['error']}")
    logger.info(f"Updated:    {status.get('updated_at', '-')}")
    return 0 if status.get("status") in ("idle", "done") else 1


def cmd_reset():
    """Reset daemon status to idle."""
    conn = get_connection(DB_PATH)
    try:
        conn.execute("DELETE FROM daemon_status")
        conn.commit()
        logger.info("Daemon status reset to idle.")
    finally:
        conn.close()


def cmd_run(args):
    """Run a pipeline phase."""
    init_db(DB_PATH)
    os.makedirs(config.FLAT_DIR, exist_ok=True)

    source = args.source
    phase = args.run

    logger.info(f"Daemon starting phase: {phase} (source: {source})")

    if phase == "all":
        ok = _run_with_daemon_status(run_all_phases, "full_pipeline", source=source)
    elif phase == "metadata":
        ok = _run_with_daemon_status(run_phase_metadata, "metadata", source=source)
    elif phase == "dedup":
        ok = _run_with_daemon_status(run_phase_dedup, "dedup")
    elif phase == "copy":
        ok = _run_with_daemon_status(run_phase_copy, "copy")
    else:
        logger.error(f"Unknown phase: {phase}")
        return 1

    if ok:
        logger.info(f"Daemon: phase '{phase}' completed successfully.")
    else:
        logger.error(f"Daemon: phase '{phase}' FAILED.")
    return 0 if ok else 1


def cmd_watch(args):
    """Watch inbox directory and auto-trigger pipeline."""
    from watcher import start_watcher
    init_db(DB_PATH)
    # Load config overrides from DB (sets config.WATCH_DIR etc.)
    conn = get_connection(DB_PATH)
    load_config_overrides(conn)
    conn.close()
    os.makedirs(config.FLAT_DIR, exist_ok=True)
    watch_dir = getattr(config, "WATCH_DIR", config.INBOX_DIR)
    recursive = getattr(config, "WATCH_RECURSIVE", True)
    logger.info(f"Daemon watching: {watch_dir} (recursive={recursive})")
    logger.info("Press Ctrl+C to stop.")
    daemon_heartbeat(DB_PATH, "watch", "running", pid=os.getpid(),
                     current_phase="watch", current_stage="watching")
    observer = start_watcher(watch_dir, recursive=recursive)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        daemon_heartbeat(DB_PATH, "watch", "done")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Book Organiser Headless Daemon")
    parser.add_argument("--status", action="store_true", help="Check daemon status")
    parser.add_argument("--reset", action="store_true", help="Reset daemon status to idle")
    parser.add_argument("--run", choices=["metadata", "dedup", "copy", "all"],
                        help="Run a specific pipeline phase")
    parser.add_argument("--watch", action="store_true",
                        help="Watch inbox directory and auto-trigger pipeline")
    parser.add_argument("--source", "-s", default=r"Z:\books",
                        help="Source path(s); semicolon-separated for multiple (default: Z:\\books)")
    parser.add_argument("--db", default=DB_PATH, help="Path to SQLite database")

    args = parser.parse_args()

    sources = [s.strip() for s in args.source.split(";") if s.strip()]
    config.SOURCE_DIR = sources[0] if sources else r"Z:\books"
    config.SOURCE_DIRS = sources
    config.DB_PATH = args.db

    if args.status:
        sys.exit(cmd_status())
    elif args.reset:
        cmd_reset()
    elif args.run:
        sys.exit(cmd_run(args))
    elif args.watch:
        cmd_watch(args)
    else:
        parser.print_help()
