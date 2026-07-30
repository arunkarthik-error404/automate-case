r"""
NCLT Search Runner: Tulip Data Centre Private Limited
=====================================================
Runs NCLT search automation for Company #6.
"""

from nclt_automation import run_nclt_for_companies

COMPANY_NAME = "Tulip Data Centre Private Limited"

if __name__ == "__main__":
    run_nclt_for_companies(COMPANY_NAME)
