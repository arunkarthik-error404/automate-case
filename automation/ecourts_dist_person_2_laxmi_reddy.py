r"""
District Court Search Runner: G. Laxmi Reddy
============================================
Runs District Court search automation for Person #2.
"""

import argparse
from ecourts_district_automation import run_district_for_persons

PERSON_NAME = "G. Laxmi Reddy"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"District Court Search Runner: {PERSON_NAME}")
    parser.add_argument("--delay", type=float, default=4.0, help="Pacing delay in seconds (default: 4.0)")
    args = parser.parse_args()

    run_district_for_persons(PERSON_NAME, delay=args.delay)

