import os
import subprocess
import sys

import config
from log_utils import setup_logger

os.makedirs(config.LOG_DIR, exist_ok=True)
logger = setup_logger("start_app", also_stdout=True)

p = subprocess.Popen([sys.executable, "app.py"], cwd=os.path.dirname(os.path.abspath(__file__)))
logger.info(f"Started PID: {p.pid}")
with open("app_pid.txt", "w") as f:
    f.write(str(p.pid))
