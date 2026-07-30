r"""
eCourts Person Search Automation (Parallel Worker)
==================================================
Site: https://hcservices.ecourts.gov.in/hcservices/main.php
      https://districts.ecourts.gov.in/india.php

HOW TO RUN:
    d:\automate-case\venv\Scripts\python.exe ecourts_persons.py

Runs Person searches (Karnataka High Court & Telangana Rangareddy District Court)
independently so it can execute in parallel with ecourts_entities.py / ecourts_automation.py.
"""

import sys
from pathlib import Path

# Import all shared functions and configuration from ecourts_automation
from ecourts_automation import (
    DOWNLOAD_DIR, PERSONS, PERSON_HC_COURTS,
    make_driver, search_hc, search_telangana_rangareddy
)

def main():
    print("="*70)
    print("  eCourts PERSON Search Automation (Parallel)")
    print(f"  Downloads → {DOWNLOAD_DIR.resolve()}")
    print("  You will be asked to type each CAPTCHA in this window.")
    print("="*70 + "\n")

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    driver = make_driver()
    summary = []

    try:
        print("\n" + "★"*70)
        print("  PERSON SEARCHES (Karnataka HC + Telangana District Court)")
        print("★"*70)
        
        for person in PERSONS:
            if person == "G. Janardhan Reddy":
                print(f"  ℹ  Skipping {person} (already completed)")
                continue

            # High Court searches (Karnataka Bengaluru & Telangana)
            for (label, court_p, bench_p) in PERSON_HC_COURTS:
                found = search_hc(driver, person, label, court_p, bench_p)
                summary.append(("Person", person, label, found))

        # ── SUMMARY ──
        print("\n" + "="*70)
        print("  PERSONS SEARCH FINAL SUMMARY")
        print("="*70)
        hits = 0
        for (typ, name, court, found) in summary:
            icon = "✓" if found else "✗"
            print(f"  {icon}  {typ:6}  {court:25}  {name}")
            if found: hits += 1
        print(f"\n  {hits}/{len(summary)} searches returned results.")
        print(f"  Files saved to: {DOWNLOAD_DIR.resolve()}")

    except KeyboardInterrupt:
        print("\n  ⚠  Stopped by user.")
    except Exception as e:
        print(f"\n  ✗ Fatal: {e}")
        import traceback; traceback.print_exc()
    finally:
        try:
            input("\n  Press ENTER to close browser...")
        except (EOFError, KeyboardInterrupt):
            pass
        driver.quit()

if __name__ == "__main__":
    main()
