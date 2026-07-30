r"""
District Court Search Runner: Tulip Data Centre Services Private Limited
========================================================================
Runs District Court search automation for Entity #5 across Delhi, Rajasthan (Jaipur), Karnataka (Bengaluru).
"""

import argparse
from ecourts_entity_automation import run_district_for_entities

ENTITY_NAME = "Tulip Data Centre Services Private Limited"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=f"District Court Search Runner: {ENTITY_NAME}")
    parser.add_argument("--delay", type=float, default=4.0, help="Pacing delay in seconds (default: 4.0)")
    args = parser.parse_args()

    run_district_for_entities(ENTITY_NAME, delay=args.delay)
