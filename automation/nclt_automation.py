r"""
NCLT Party Name Wise Search Automation
=======================================
Site: https://nclt.gov.in/party-name-wise

HOW TO RUN:
    Individual Company Runners (Parallel):
        python nclt_1_spaceworld_group.py
        python nclt_2_spaceworld_datacentre.py
        python nclt_3_gvr_electrotechnics.py
        python nclt_4_sada_it_parks.py
        python nclt_5_tulip_services.py
        python nclt_6_tulip_datacentre.py

    Via Command Line / Flags:
        python nclt_automation.py --company "Space World Group LLP"
        python nclt_automation.py --company-index 1
        python nclt_automation.py --all

    Run All in Parallel:
        python run_all_nclt_parallel.py

Features:
- Auto-solves text CAPTCHA from DOM (#mainCaptcha)
- Searches company targets across Zonal Benches: New Delhi, Jaipur, Karnataka (Bengaluru)
- Searches years 2017 to 2026
- Automatically handles result tables, PDF/detail captures, and Back button form resets
"""

import os, sys, time, re, shutil, argparse
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── CONFIGURATION ───────────────────────────────────────────────────

BASE_URL     = "https://nclt.gov.in/party-name-wise"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
START_YEAR   = 2026
END_YEAR     = 2017

# (bench_label, bench_option_value)
NCLT_BENCHES = [
    ("New_Delhi", "delhi"),
    ("Jaipur",    "jaipur"),
    ("Karnataka", "bengaluru"),
]

COMPANIES = [
    "Space World Group LLP",
    "Space World Data Centre Private Limited",
    "G.V.R. Electro Technics Private Limited",
    "Sada IT Parks Private Limited",
    "Tulip Data Centre Services Private Limited",
    "Tulip Data Centre Private Limited",
]

# ── UTILITIES ───────────────────────────────────────────────────────

def safe_name(name):
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip()

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def make_driver():
    opts = Options()
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    prefs = {
        "download.default_directory": str(DOWNLOAD_DIR.resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "plugins.always_open_pdf_externally": True,
    }
    opts.add_experimental_option("prefs", prefs)

    service = Service(ChromeDriverManager().install())
    driver  = webdriver.Chrome(service=service, options=opts)
    driver.set_page_load_timeout(45)
    return driver

def safe_click(driver, element):
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", element)
        time.sleep(0.3)
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)

def dl_via_requests(driver, url, filepath):
    try:
        sess = requests.Session()
        for c in driver.get_cookies():
            sess.cookies.set(c["name"], c["value"])
        ua = driver.execute_script("return navigator.userAgent")
        r  = sess.get(url, headers={"User-Agent": ua, "Referer": driver.current_url},
                      timeout=30, stream=True)
        r.raise_for_status()
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        log(f"        ✓ PDF saved: {filepath.name}")
        return True
    except Exception as e:
        log(f"        ✗ DL error: {e}")
        return False

# ── CAPTCHA SOLVER ──────────────────────────────────────────────────

def solve_nclt_captcha(driver):
    """Read plain text digits from #mainCaptcha element."""
    try:
        cap_el = driver.find_element(By.ID, "mainCaptcha")
        cap_text = cap_el.text
        digits = "".join(re.findall(r"\d", cap_text))
        if digits:
            return digits
    except Exception as e:
        log(f"    ⚠ Captcha read error: {e}")
    return None

# ── FORM FILLING ────────────────────────────────────────────────────

def fill_nclt_form(driver, company_name, bench_val, year, status_val="P"):
    """
    Fills NCLT Party Name Wise search form:
    Bench, Party Type (Both=3), Party Name, Case Year, Case Status (Pending=P), Captcha
    """
    try:
        # Wait for form select elements to be available
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.ID, "bench"))
        )

        # 1. Bench
        Select(driver.find_element(By.ID, "bench")).select_by_value(bench_val)
        time.sleep(0.5)

        # 2. Party Type: Both (value 3)
        Select(driver.find_element(By.ID, "party_type")).select_by_value("3")
        time.sleep(0.3)

        # 3. Party Name
        inp_name = driver.find_element(By.ID, "party_name")
        inp_name.clear()
        inp_name.send_keys(company_name)

        # 4. Case Year
        Select(driver.find_element(By.ID, "case_year")).select_by_value(str(year))

        # 5. Case Status: Pending (P)
        Select(driver.find_element(By.ID, "case_status")).select_by_value(status_val)

        # 6. Captcha
        cap_code = solve_nclt_captcha(driver)
        if not cap_code:
            log("    ✗ Could not solve Captcha")
            return False

        log(f"    Captcha read: '{cap_code}'")
        inp_cap = driver.find_element(By.ID, "txtInput")
        inp_cap.clear()
        inp_cap.send_keys(cap_code)
        return True

    except Exception as e:
        log(f"    ✗ Form fill error: {e}")
        return False

# ── SEARCH EXECUTION & RESULTS ──────────────────────────────────────

def search_nclt_company_bench(driver, company_name, bench_label, bench_val):
    save_dir = DOWNLOAD_DIR / f"NCLT_{bench_label}" / safe_name(company_name)
    save_dir.mkdir(parents=True, exist_ok=True)

    log("═"*65)
    log(f"  NCLT SEARCH: {company_name}")
    log(f"  BENCH      : {bench_label}")
    log("═"*65)

    found_any = False
    need_full_load = True

    for year in range(START_YEAR, END_YEAR - 1, -1):
        for status_val, status_label in [("P", "Pending"), ("D", "Disposed")]:
            log(f"\n  ▶ Year {year} ({status_label})")

            if need_full_load or "party-name-wise-search" in driver.current_url:
                try:
                    driver.get(BASE_URL)
                    time.sleep(2)
                except Exception as e:
                    log(f"  ⚠ Failed loading {BASE_URL}: {e}")
                    time.sleep(3)
                    continue

            # Fill form
            if not fill_nclt_form(driver, company_name, bench_val, year, status_val=status_val):
                log("  ✗ Form fill failed — retrying")
                need_full_load = True
                continue

            log(f"  ✓ Form ready: company='{company_name}' bench={bench_label} year={year} status={status_label}")

            # Submit search
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "#search-case-number-form button[type='submit']")
                safe_click(driver, btn)
                time.sleep(3)
            except Exception as e:
                log(f"  ✗ Search button click error: {e}")
                need_full_load = True
                continue

            # Check Results Page
            try:
                WebDriverWait(driver, 10).until(
                    lambda d: "party-name-wise-search" in d.current_url or len(d.find_elements(By.TAG_NAME, "table")) > 0
                )
            except Exception:
                log("  ⚠ Response timeout or page did not load search results")

            # Parse results table
            tables = driver.find_elements(By.TAG_NAME, "table")

            if tables:
                rows = tables[0].find_elements(By.TAG_NAME, "tr")
                # First row is header, check row 2 and beyond
                data_rows = []
                for r in rows[1:]:
                    cells = [td.text.strip() for td in r.find_elements(By.XPATH, "th|td")]
                    row_text = " ".join(cells).lower()
                    if not cells:
                        continue
                    if "please click here for data" in row_text or "no record" in row_text or "no data" in row_text:
                        continue
                    data_rows.append((r, cells))

                if data_rows:
                    found_any = True
                    log(f"  ✓ CASES FOUND for year {year} ({status_label})! Count: {len(data_rows)}")

                    for idx, (r_el, cells) in enumerate(data_rows):
                        case_label = f"{safe_name(company_name)}_{year}_{status_label}_case{idx+1}"
                        log(f"    → Case {idx+1}: {cells[:4]}")

                        # Save text summary of case
                        summary_fp = save_dir / f"{case_label}_summary.txt"
                        summary_fp.write_text(" | ".join(cells), encoding="utf-8")

                        # Check for links or download buttons inside the row
                        action_links = r_el.find_elements(By.TAG_NAME, "a")
                        dl_count = 0
                        for l_idx, lnk in enumerate(action_links):
                            href    = lnk.get_attribute("href") or ""
                            onclick = lnk.get_attribute("onclick") or ""

                            if href and ("pdf" in href.lower() or "display" in href.lower()):
                                pdf_url = href if href.startswith("http") else urljoin(driver.current_url, href)
                                fp = save_dir / f"{case_label}_doc{l_idx+1}.pdf"
                                if dl_via_requests(driver, pdf_url, fp):
                                    dl_count += 1
                            elif onclick or href:
                                try:
                                    safe_click(driver, lnk)
                                    time.sleep(2)
                                    handles = driver.window_handles
                                    if len(handles) > 1:
                                        driver.switch_to.window(handles[-1])
                                        time.sleep(2)
                                        cur_url = driver.current_url
                                        fp = save_dir / f"{case_label}_doc{l_idx+1}.pdf"
                                        if dl_via_requests(driver, cur_url, fp):
                                            dl_count += 1
                                        driver.close()
                                        driver.switch_to.window(handles[0])
                                except Exception as e:
                                    log(f"      ⚠ Link click error: {e}")

                        if dl_count > 0:
                            log(f"      Downloaded {dl_count} document(s)")
                else:
                    log(f"  ℹ  No records for {year} ({status_label})")
            else:
                log(f"  ℹ  No table found for {year} ({status_label})")

            # Click Back button to return to search form for next year/status
            try:
                back_btn = driver.find_elements(By.XPATH, "//button[normalize-space(text())='Back']|//a[normalize-space(text())='Back']")
                if back_btn:
                    safe_click(driver, back_btn[0])
                    time.sleep(2)
                    need_full_load = False
                else:
                    driver.get(BASE_URL)
                    time.sleep(2)
                    need_full_load = True
            except Exception:
                driver.get(BASE_URL)
                time.sleep(2)
                need_full_load = True

    if not found_any:
        log(f"  ℹ  No NCLT cases found for '{company_name}' at {bench_label} across {START_YEAR}-{END_YEAR}")
    return found_any

# ── RUNNER FUNCTION ─────────────────────────────────────────────────

def run_nclt_for_companies(target_companies):
    if isinstance(target_companies, str):
        target_companies = [target_companies]

    print("="*70)
    print("  NCLT Company Case Search Automation")
    print(f"  Target URL : {BASE_URL}")
    print(f"  Downloads  : {DOWNLOAD_DIR.resolve()}")
    print(f"  Targets    : {len(target_companies)} company(ies)")
    for c in target_companies:
        print(f"               - {c}")
    print("="*70 + "\n")

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    driver = make_driver()
    summary = []

    try:
        print("\n" + "★"*70)
        print("  NCLT COMPANY SEARCHES")
        print("★"*70)

        for company in target_companies:
            for (bench_label, bench_val) in NCLT_BENCHES:
                found = search_nclt_company_bench(driver, company, bench_label, bench_val)
                summary.append(("Company", company, bench_label, found))

        # ── SUMMARY ──
        print("\n" + "="*70)
        print("  NCLT SEARCH FINAL SUMMARY")
        print("="*70)
        hits = 0
        for (typ, name, bench, found) in summary:
            icon = "✓" if found else "✗"
            print(f"  {icon}  {typ:7}  {bench:15}  {name}")
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

# ── MAIN ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NCLT Party Name Wise Search Automation")
    parser.add_argument("--company", type=str, help="Specific company name to search")
    parser.add_argument("--company-index", type=int, choices=range(1, len(COMPANIES) + 1),
                        help="Index of company to search (1 to 6)")
    parser.add_argument("--all", action="store_true", help="Search all companies sequentially")

    args = parser.parse_args()

    if args.company:
        targets = [args.company]
    elif args.company_index:
        targets = [COMPANIES[args.company_index - 1]]
    else:
        targets = COMPANIES

    run_nclt_for_companies(targets)

if __name__ == "__main__":
    main()
