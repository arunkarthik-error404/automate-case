r"""
District Courts Parallel Orchestrator (Entities)
=================================================
Launches all 6 District Court entity search scripts in parallel processes across Delhi, Rajasthan (Jaipur), and Karnataka (Bengaluru).

HOW TO RUN:
    python run_all_entities_parallel.py
"""

import sys
import time
import argparse
import subprocess
from pathlib import Path

ENTITY_SCRIPTS = [
    "entity_1_spaceworld_group.py",
    "entity_2_spaceworld_datacentre.py",
    "entity_3_gvr_electrotechnics.py",
    "entity_4_sada_it_parks.py",
    "entity_5_tulip_services.py",
    "entity_6_tulip_datacentre.py",
]

def main():
    parser = argparse.ArgumentParser(description="District Courts Parallel Orchestrator (Entities)")
    parser.add_argument("--state", type=str, choices=["delhi", "rajasthan", "bengaluru", "telangana", "karnataka", "all"], default="all", help="Target state: 'delhi', 'rajasthan', 'bengaluru', or 'telangana'")
    parser.add_argument("--delay", type=float, default=4.0, help="Pacing delay per worker in seconds (default: 4.0)")
    parser.add_argument("--stagger", type=float, default=6.0, help="Launch stagger delay between workers in seconds (default: 6.0)")
    args = parser.parse_args()

    root = Path(__file__).parent
    python_exe = sys.executable

    print("=" * 70)
    print(f"  LAUNCHING ALL 6 DISTRICT COURT ENTITY SEARCHES ({args.state.upper()}) IN PARALLEL")
    print(f"  State filter      : {args.state}")
    print(f"  Pacing per worker : {args.delay}s")
    print(f"  Launch stagger    : {args.stagger}s")
    print("=" * 70 + "\n")

    processes = []
    for idx, script in enumerate(ENTITY_SCRIPTS):
        script_path = root / script
        print(f"  ▶ Launching worker [{idx+1}/{len(ENTITY_SCRIPTS)}]: {script} (state: {args.state})")
        p = subprocess.Popen([python_exe, str(script_path), "--state", args.state, "--delay", str(args.delay)])
        processes.append((script, p))
        if idx < len(ENTITY_SCRIPTS) - 1:
            time.sleep(args.stagger)

    print(f"\n  ✓ All {len(processes)} worker processes started.")
    print("  Waiting for processes to complete...\n")

    for script, p in processes:
        p.wait()
        print(f"  ✓ Process finished: {script} (exit code: {p.returncode})")

    print("\n" + "=" * 70)
    print("  ALL PARALLEL DISTRICT COURT ENTITY SEARCHES COMPLETED")
    print("=" * 70)

if __name__ == "__main__":
    main()
