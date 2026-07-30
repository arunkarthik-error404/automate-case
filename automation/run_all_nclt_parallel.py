r"""
NCLT Parallel Orchestrator
===========================
Launches all 6 NCLT company search scripts in parallel processes.

HOW TO RUN:
    python run_all_nclt_parallel.py
"""

import sys
import time
import subprocess
from pathlib import Path

COMPANY_SCRIPTS = [
    "nclt_1_spaceworld_group.py",
    "nclt_2_spaceworld_datacentre.py",
    "nclt_3_gvr_electrotechnics.py",
    "nclt_4_sada_it_parks.py",
    "nclt_5_tulip_services.py",
    "nclt_6_tulip_datacentre.py",
]

def main():
    root = Path(__file__).parent
    python_exe = sys.executable

    print("=" * 70)
    print("  LAUNCHING ALL 6 NCLT COMPANY SEARCHES IN PARALLEL")
    print("=" * 70 + "\n")

    processes = []
    for script in COMPANY_SCRIPTS:
        script_path = root / script
        print(f"  ▶ Launching parallel process: {script}")
        p = subprocess.Popen([python_exe, str(script_path)])
        processes.append((script, p))
        time.sleep(1)  # Stagger browser launches slightly to avoid initial driver clash

    print(f"\n  ✓ All {len(processes)} worker processes started.")
    print("  Waiting for processes to complete...\n")

    for script, p in processes:
        p.wait()
        print(f"  ✓ Process finished: {script} (exit code: {p.returncode})")

    print("\n" + "=" * 70)
    print("  ALL PARALLEL NCLT SEARCHES COMPLETED")
    print("=" * 70)

if __name__ == "__main__":
    main()
