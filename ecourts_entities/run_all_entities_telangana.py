r"""
District Courts Parallel Orchestrator (Entities - Telangana / Rangareddy)
========================================================================
Launches all 6 District Court entity search scripts specifically for Telangana (Rangareddy).

HOW TO RUN:
    python run_all_entities_telangana.py
"""

import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    script_path = Path(__file__).parent / "run_all_entities_parallel.py"
    cmd = [sys.executable, str(script_path), "--state", "telangana"] + sys.argv[1:]
    subprocess.run(cmd)
