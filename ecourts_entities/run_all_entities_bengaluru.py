r"""
District Courts Parallel Orchestrator (Entities - Bengaluru / Karnataka)
========================================================================
Launches all 6 District Court entity search scripts specifically for Bengaluru (Karnataka).

HOW TO RUN:
    python run_all_entities_bengaluru.py
"""

import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    script_path = Path(__file__).parent / "run_all_entities_parallel.py"
    cmd = [sys.executable, str(script_path), "--state", "bengaluru"] + sys.argv[1:]
    subprocess.run(cmd)
