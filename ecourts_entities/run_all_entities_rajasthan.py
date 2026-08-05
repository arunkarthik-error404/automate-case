r"""
District Courts Parallel Orchestrator (Entities - Rajasthan / Jaipur)
======================================================================
Launches all 6 District Court entity search scripts specifically for Rajasthan (Jaipur).

HOW TO RUN:
    python run_all_entities_rajasthan.py
"""

import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    script_path = Path(__file__).parent / "run_all_entities_parallel.py"
    cmd = [sys.executable, str(script_path), "--state", "rajasthan"] + sys.argv[1:]
    subprocess.run(cmd)
