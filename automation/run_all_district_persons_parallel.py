r"""
District Courts Parallel Orchestrator (Persons)
================================================
Launches all 6 District Court person search scripts in parallel processes.

HOW TO RUN:
    python run_all_district_persons_parallel.py
"""

import sys
import time
import argparse
import subprocess
from pathlib import Path

PERSON_SCRIPTS = [
    "ecourts_dist_person_1_janardhan_reddy.py",
    "ecourts_dist_person_2_laxmi_reddy.py",
    "ecourts_dist_person_3_vidya_reddy.py",
    "ecourts_dist_person_4_veera_prakash_reddy.py",
    "ecourts_dist_person_5_veera_reddy.py",
    "ecourts_dist_person_6_kanaka_durga.py",
]

def main():
    parser = argparse.ArgumentParser(description="District Courts Parallel Orchestrator (Persons)")
    parser.add_argument("--delay", type=float, default=4.0, help="Pacing delay per worker in seconds (default: 4.0)")
    parser.add_argument("--stagger", type=float, default=6.0, help="Launch stagger delay between workers in seconds (default: 6.0)")
    args = parser.parse_args()

    root = Path(__file__).parent
    python_exe = sys.executable

    print("=" * 70)
    print("  LAUNCHING ALL 6 DISTRICT COURT PERSON SEARCHES IN PARALLEL")
    print(f"  Pacing per worker : {args.delay}s")
    print(f"  Launch stagger    : {args.stagger}s")
    print("=" * 70 + "\n")

    processes = []
    for idx, script in enumerate(PERSON_SCRIPTS):
        script_path = root / script
        print(f"  ▶ Launching worker [{idx+1}/{len(PERSON_SCRIPTS)}]: {script}")
        p = subprocess.Popen([python_exe, str(script_path), "--delay", str(args.delay)])
        processes.append((script, p))
        if idx < len(PERSON_SCRIPTS) - 1:
            time.sleep(args.stagger)

    print(f"\n  ✓ All {len(processes)} worker processes started.")
    print("  Waiting for processes to complete...\n")

    for script, p in processes:
        p.wait()
        print(f"  ✓ Process finished: {script} (exit code: {p.returncode})")

    print("\n" + "=" * 70)
    print("  ALL PARALLEL DISTRICT COURT PERSON SEARCHES COMPLETED")
    print("=" * 70)

if __name__ == "__main__":
    main()

