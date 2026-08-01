r"""
eCourts District Courts Case Status Automation (ecourtindia_v6)
===============================================================
Site: https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index

HOW TO RUN:
    Individual Person Runners (Parallel):
        python ecourts_dist_person_1_janardhan_reddy.py
        python ecourts_dist_person_2_laxmi_reddy.py
        python ecourts_dist_person_3_vidya_reddy.py
        python ecourts_dist_person_4_veera_prakash_reddy.py
        python ecourts_dist_person_5_veera_reddy.py
        python ecourts_dist_person_6_kanaka_durga.py

    Via Command Line / Flags:
        python ecourts_district_automation.py --person "G. Janardhan Reddy"
        python ecourts_district_automation.py --person-index 1
        python ecourts_district_automation.py --all

    Run All District Persons in Parallel:
        python run_all_district_persons_parallel.py

Targets:
- States & Districts:
    1. Karnataka -> District matching 'bengaluru'
    2. Telangana -> District matching 'ranga' / 'rangareddy'
- Traversal: State -> District -> Court Complex -> Court Establishment
- Years: 2026 down to 2020
- Search Type: Party Name (Petitioner/Respondent), Case Status: Both
"""

import os, sys, time, re, base64, argparse, random
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
from selenium.common.exceptions import WebDriverException, NoSuchWindowException
from webdriver_manager.chrome import ChromeDriverManager

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ── CAPTCHA OCR (ddddocr) ────────────────────────────────────────────
try:
    import ddddocr
    _ocr = ddddocr.DdddOcr(show_ad=False)
    OCR_AVAILABLE = True
    print("[INFO] ddddocr loaded — CAPTCHA will be auto-solved")
except ImportError:
    OCR_AVAILABLE = False
    print("[WARN] ddddocr not found — will prompt user for CAPTCHA if needed")

# ── CONFIGURATION ───────────────────────────────────────────────────

BASE_URL      = "https://services.ecourts.gov.in/ecourtindia_v6/"
SEARCH_URL    = "https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index"
DOWNLOAD_DIR  = Path(__file__).parent / "downloads"
START_YEAR    = 2026
END_YEAR      = 2020
DEFAULT_DELAY = 4.0  # seconds pacing delay to avoid IP rate-limiting / blocking

TARGET_DISTRICTS = [
    {"state": "Karnataka",  "district_pattern": r"bengaluru|bangalore"},
    {"state": "Telangana",  "district_pattern": r"ranga|rangareddy"},
]

PERSONS = [
    "G. Janardhan Reddy",
    "G. Laxmi Reddy",
    "G. Vidya Reddy",
    "G. Veera Prakash Reddy",
    "G. Veera Reddy",
    "G. Kanaka Durga",
]

ENTITIES = [
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
    line = f"[{ts}] {msg}"
    try:
        print(line)
    except Exception:
        try:
            print(line.encode("ascii", errors="replace").decode("ascii"))
        except Exception:
            pass
    try:
        (DOWNLOAD_DIR / "district_log.txt").parent.mkdir(exist_ok=True)
        with open(DOWNLOAD_DIR / "district_log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

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

def close_error_modals(driver):
    """Dismiss any 'Oops! There is something wrong' modals if present and handle rate-limiting delays."""
    try:
        modals = driver.find_elements(By.CSS_SELECTOR, "div.modal.show, div.modal[style*='display: block'], #errormsgmodal, #alertmodal")
        for m in modals:
            if not m.is_displayed():
                continue
            m_text = m.text.lower()
            if "too many requests" in m_text or "ip blocked" in m_text or "access denied" in m_text:
                log("  ⚠ IP block / rate-limit detected! Sleeping 20s for cooldown...")
                time.sleep(20)
            elif "something wrong" in m_text or "try again" in m_text or "busy" in m_text:
                log("  ⚠ Server error modal detected! Sleeping 10s for server cooldown...")
                time.sleep(10)

            btns = m.find_elements(By.CSS_SELECTOR, ".btn-close, .close, button[data-bs-dismiss='modal'], button, input[type='button']")
            for b in btns:
                if b.is_displayed():
                    safe_click(driver, b)
                    time.sleep(0.5)
                    break
    except Exception:
        pass

def is_error_or_captcha_mismatch(driver):
    """Check if a visible error modal, alert, or banner indicates invalid captcha or submission error."""
    try:
        # 1. Check browser JS Alert dialog
        try:
            alert = driver.switch_to.alert
            txt = alert.text.strip()
            log(f"      ⚠ JS Alert detected: '{txt}'")
            alert.accept()
            return True, f"JS Alert: '{txt}'"
        except Exception:
            pass

        # 2. Check VISIBLE modals or alert elements on page
        error_css = (
            ".modal.show, div.modal[style*='display: block'], #errormsgmodal, #alertmodal, "
            ".alert-danger, .error-message, #errormsg, div[id*='error'], div[class*='error'], "
            ".toast-error, .alert-warning"
        )
        for el in driver.find_elements(By.CSS_SELECTOR, error_css):
            if el.is_displayed():
                txt = el.text.strip()
                txt_lower = txt.lower()
                if any(w in txt_lower for w in [
                    "invalid captcha", "captcha mismatch", "wrong captcha", "enter valid captcha",
                    "captcha enter", "something wrong", "try again", "error", "server error",
                    "too many requests", "access denied", "blocked"
                ]):
                    return True, f"Modal/Error: '{txt[:100]}'"
    except Exception:
        pass
    return False, ""

def is_explicit_no_records_found(driver):
    """Returns True ONLY if the page explicitly states that no records/cases were found for the query."""
    try:
        page_text = driver.find_element(By.TAG_NAME, "body").text.lower()
        no_record_phrases = [
            "no record found", "record not found", "no case found", "case not found",
            "no matching record", "no records found", "no data found", "zero records"
        ]
        if any(phrase in page_text for phrase in no_record_phrases):
            return True
        for tbl in driver.find_elements(By.TAG_NAME, "table"):
            if tbl.is_displayed():
                t_text = tbl.text.lower()
                if any(phrase in t_text for phrase in no_record_phrases):
                    return True
    except Exception:
        pass
    return False

def is_captcha_mismatch_visible(driver):
    is_err, _ = is_error_or_captcha_mismatch(driver)
    return is_err


def wait_for_loading(driver, timeout=15):
    """Wait for loading spinners or overlays to disappear."""
    time.sleep(0.8)
    end_time = time.time() + timeout
    while time.time() < end_time:
        close_error_modals(driver)
        try:
            spinners = driver.find_elements(By.CSS_SELECTOR, "#loading, .modal-backdrop, div.spinner, .loading_img, #loader, div[style*='display: block'][class*='load']")
            visible_spinners = [s for s in spinners if s.is_displayed()]
            if not visible_spinners:
                break
        except Exception:
            break
        time.sleep(0.5)

def get_dropdown_by_role(driver, role):
    """
    Find select element by role: 'state', 'district', 'complex', 'establishment'.
    Tries keyword matching first, then positional index.
    """
    selects = driver.find_elements(By.TAG_NAME, "select")
    visible_selects = [s for s in selects if s.is_displayed()]
    if not visible_selects:
        visible_selects = selects

    role_keywords = {
        "state": ["state", "sess_state"],
        "district": ["dist", "sess_dist"],
        "complex": ["complex", "court_complex"],
        "establishment": ["establishment", "est", "building", "court_code"]
    }
    keywords = role_keywords.get(role, [])

    # 1. Try keyword matching
    for s in visible_selects:
        s_id   = (s.get_attribute("id") or "").lower()
        s_name = (s.get_attribute("name") or "").lower()
        for kw in keywords:
            if kw in s_id or kw in s_name:
                return s

    # 2. Try positional fallback
    position_map = {"state": 0, "district": 1, "complex": 2, "establishment": 3}
    idx = position_map.get(role)
    if idx is not None and len(visible_selects) > idx:
        return visible_selects[idx]

    return None

def get_select_options(select_el):
    """Returns list of (value, text) for valid non-placeholder options."""
    if not select_el:
        return []
    sel = Select(select_el)
    opts = []
    for o in sel.options:
        val  = (o.get_attribute("value") or "").strip()
        txt  = o.text.strip()
        if val and val != "0" and val != "" and "select" not in txt.lower():
            opts.append((val, txt))
    return opts

def wait_for_dropdown_options(driver, role, min_options=1, timeout=12):
    """Wait for dropdown corresponding to `role` to have at least `min_options` valid options."""
    end_time = time.time() + timeout
    while time.time() < end_time:
        close_error_modals(driver)
        s_el = get_dropdown_by_role(driver, role)
        if s_el:
            opts = get_select_options(s_el)
            if len(opts) >= min_options:
                return opts
        time.sleep(0.5)
    return []

def select_option_by_pattern(select_el, pattern):
    if not select_el:
        return None
    sel = Select(select_el)
    for o in sel.options:
        txt = o.text.strip()
        val = (o.get_attribute("value") or "").strip()
        if val and val != "0" and (re.search(pattern, txt, re.IGNORECASE) or re.search(pattern, val, re.IGNORECASE)):
            sel.select_by_value(val)
            return (val, txt)
    return None

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

def refresh_captcha(driver):
    """Click CAPTCHA refresh icon if present."""
    try:
        ref_btns = [el for el in driver.find_elements(By.CSS_SELECTOR, "img[src*='refresh'], a[onclick*='captcha'], #captcha_refresh, .captcha-refresh, i.fa-refresh") if el.is_displayed()]
        if ref_btns:
            safe_click(driver, ref_btns[0])
            time.sleep(1.5)
            return True
    except Exception:
        pass
    return False

def preprocess_captcha_image(img_bytes):
    """Enhance contrast and binarize noisy/distorted CAPTCHA image using PIL."""
    try:
        from PIL import Image, ImageEnhance
        img = Image.open(io.BytesIO(img_bytes)).convert("L")
        enh = ImageEnhance.Contrast(img)
        img = enh.enhance(2.5)
        img = img.point(lambda p: 255 if p > 140 else 0)
        out_buf = io.BytesIO()
        img.save(out_buf, format="PNG")
        return out_buf.getvalue()
    except Exception:
        return img_bytes

def solve_captcha(driver, max_attempts=12):
    """
    Solves image CAPTCHA using ddddocr with PIL preprocessing.
    If the CAPTCHA image is distorted or unrecognizable (<4 chars or noise),
    it automatically clicks refresh_captcha(driver) to request a cleaner CAPTCHA!
    """
    if not OCR_AVAILABLE:
        return ""

    for cap_attempt in range(1, max_attempts + 1):
        try:
            img_els = [el for el in driver.find_elements(By.CSS_SELECTOR, "img#captcha_image, img[src*='captcha']") if el.is_displayed()]
            if not img_els:
                img_els = driver.find_elements(By.CSS_SELECTOR, "img#captcha_image, img[src*='captcha']")
            if not img_els:
                time.sleep(1.0)
                continue

            img_el = img_els[0]
            img_src = img_el.get_attribute("src") or ""

            img_bytes = None
            if "base64," in img_src:
                b64_data = img_src.split("base64,")[1]
                img_bytes = base64.b64decode(b64_data)
            else:
                img_bytes = img_el.screenshot_as_png

            if img_bytes:
                # 1. Raw OCR classification
                code_raw = _ocr.classification(img_bytes).strip()
                code_clean_raw = re.sub(r'[^a-zA-Z0-9]', '', code_raw)
                alt_keywords = ["enter", "character", "image", "select", "audio", "captcha", "type", "hear"]
                is_alt_raw = len(code_clean_raw) > 8 or any(w in code_raw.lower() for w in alt_keywords)

                if not is_alt_raw and 4 <= len(code_clean_raw) <= 7:
                    log(f"    ✓ Auto CAPTCHA solved (raw): '{code_clean_raw}'")
                    return code_clean_raw

                # 2. Preprocessed OCR classification
                prep_bytes = preprocess_captcha_image(img_bytes)
                code_prep = _ocr.classification(prep_bytes).strip()
                code_clean_prep = re.sub(r'[^a-zA-Z0-9]', '', code_prep)
                is_alt_prep = len(code_clean_prep) > 8 or any(w in code_prep.lower() for w in alt_keywords)

                if not is_alt_prep and 4 <= len(code_clean_prep) <= 7:
                    log(f"    ✓ Auto CAPTCHA solved (preprocessed): '{code_clean_prep}'")
                    return code_clean_prep

            # Distorted/unrecognizable image — refresh CAPTCHA for a cleaner image!
            log(f"    ⚠ CAPTCHA unrecognizable / distorted (attempt {cap_attempt}/{max_attempts}) — refreshing CAPTCHA...")
            refresh_captcha(driver)
            time.sleep(1.5)

        except Exception as e:
            log(f"    ⚠ CAPTCHA solve error (attempt {cap_attempt}): {e}")
            refresh_captcha(driver)
            time.sleep(1.5)

    return ""

def go_back_to_results(driver):
    """Click Back button on case details / 2nd page to return to search results list."""
    try:
        back_btns = driver.find_elements(By.XPATH,
            "//input[@value='Back' or @value='BACK' or @value='back'] | "
            "//button[contains(translate(text(),'BACK','back'),'back')] | "
            "//a[contains(translate(text(),'BACK','back'),'back')] | "
            "//*[@id='back_btn'] | //*[contains(@class,'btn-back')]"
        )
        visible_back = [b for b in back_btns if b.is_displayed()]
        if visible_back:
            safe_click(driver, visible_back[0])
            time.sleep(2.0)
            wait_for_loading(driver)
            return True
        else:
            driver.back()
            time.sleep(2.0)
            wait_for_loading(driver)
            return True
    except Exception as e:
        log(f"        ⚠ Go back error: {e}")
        return False

START_YEAR    = 2026
END_YEAR      = 2000  # 2000 to 2026 (20 years / 27 year span)
DEFAULT_DELAY = 4.0  # seconds pacing delay to avoid IP rate-limiting / blocking

def save_page_as_pdf_via_print(driver, filepath):
    """
    Saves the currently rendered page/view to a PDF file using Chrome DevTools Protocol (CDP) Page.printToPDF.
    This provides the Print -> Save to PDF fallback when no clickable links are available.
    """
    try:
        filepath.parent.mkdir(parents=True, exist_ok=True)
        print_options = {
            "printBackground": True,
            "paperWidth": 8.27,    # A4 width in inches
            "paperHeight": 11.69,  # A4 height in inches
            "marginTop": 0.4,
            "marginBottom": 0.4,
            "marginLeft": 0.4,
            "marginRight": 0.4,
        }
        result = driver.execute_cdp_cmd("Page.printToPDF", print_options)
        pdf_bytes = base64.b64decode(result['data'])
        with open(filepath, "wb") as f:
            f.write(pdf_bytes)
        log(f"          ✓ Saved via Print-to-PDF: {filepath.name}")
        return True
    except Exception as e:
        log(f"          ⚠ Print-to-PDF error: {e}")
        return False

def extract_and_download_orders_for_case(driver, save_dir, case_lbl):
    """
    In 2nd page (Case Details view):
    Finds and downloads PDFs strictly from clickable links under the 'Order Details' column 
    in the Interim Orders and Final Orders / Judgements tables (e.g. Orders, Deposition links).
    """
    dl_cnt = 0
    try:
        # Scroll down to load orders section
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(1.0)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)

        # Target ONLY links with text matching Orders, Deposition, Order, Judgement/Judgment under Order Details column
        visible_order_links = []
        raw_order_links = driver.find_elements(By.XPATH,
            "//table//tr[td]//a[normalize-space(text())='Orders' or normalize-space(text())='Deposition' or normalize-space(text())='Order' or normalize-space(text())='Judgement' or normalize-space(text())='Judgment' or contains(translate(text(),'DEPOSITION','deposition'),'depos')] | "
            "//table[contains(translate(.,'INTERIM ORDERS','interim orders'),'interim order') or contains(translate(.,'FINAL ORDERS','final orders'),'final order') or contains(translate(.,'JUDGEMENTS','judgements'),'judg')]//tr[td]/td[position()=3 or position()=last()]//a"
        )
        for a in raw_order_links:
            if a.is_displayed() and a not in visible_order_links:
                link_t = a.text.strip().lower()
                # Filter out hearing history date links or general navigation links
                if link_t in ["orders", "order", "deposition", "judgement", "judgment"] or "depos" in link_t or "order" in link_t:
                    visible_order_links.append(a)

        if visible_order_links:
            log(f"          Targeting {len(visible_order_links)} link(s) under Order Details column")
        else:
            log("          ℹ No order/deposition links listed under Order Details column for this case")
            return 0

        for o_idx, o_link in enumerate(visible_order_links, 1):
            pdf_saved = False
            l_text = (o_link.text or "order").strip()
            pdf_target_fp = save_dir / f"{case_lbl}_order_{o_idx}_{safe_name(l_text)}.pdf"

            href = (o_link.get_attribute("href") or "").strip()
            onclick = (o_link.get_attribute("onclick") or "").strip()

            # 1. Try URL extracted from href or onclick attribute
            pdf_url = ""
            if href and ("pdf" in href.lower() or "display" in href.lower() or "download" in href.lower()):
                pdf_url = href if href.startswith("http") else urljoin(driver.current_url, href)
            elif onclick:
                match = re.search(r"['\"]([^'\"]+\.pdf[^'\"]*|[^'\"]*display[^'\"]*|[^'\"]*download[^'\"]*)['\"]", onclick, re.IGNORECASE)
                if match:
                    rel_path = match.group(1)
                    pdf_url = rel_path if rel_path.startswith("http") else urljoin(driver.current_url, rel_path)

            if pdf_url:
                if dl_via_requests(driver, pdf_url, pdf_target_fp):
                    dl_cnt += 1
                    pdf_saved = True

            # 2. If direct URL GET didn't succeed, click the link element under Order Details
            if not pdf_saved:
                main_window = driver.current_window_handle
                existing_windows = set(driver.window_handles)

                try:
                    safe_click(driver, o_link)
                    time.sleep(2.5)

                    # Check if new tab opened
                    new_windows = set(driver.window_handles) - existing_windows
                    if new_windows:
                        new_win = list(new_windows)[0]
                        driver.switch_to.window(new_win)
                        time.sleep(1.5)
                        tab_url = driver.current_url
                        ct = driver.execute_script("return document.contentType") or ""
                        if "pdf" in tab_url.lower() or "pdf" in ct.lower():
                            if dl_via_requests(driver, tab_url, pdf_target_fp):
                                dl_cnt += 1
                                pdf_saved = True
                        
                        if not pdf_saved:
                            # Save opened order document tab via Print-to-PDF
                            if save_page_as_pdf_via_print(driver, pdf_target_fp):
                                dl_cnt += 1
                                pdf_saved = True

                        driver.close()
                        driver.switch_to.window(main_window)

                    # Check if an in-page modal/iframe/embed PDF viewer opened
                    if not pdf_saved:
                        embeds = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='pdf'], iframe[src*='display'], embed[src*='pdf'], object[data*='pdf'], #pdfviewer iframe, .modal iframe, #modal_pdf iframe")
                        for emb in embeds:
                            emb_src = emb.get_attribute("src") or emb.get_attribute("data") or ""
                            if emb_src:
                                full_emb_url = emb_src if emb_src.startswith("http") else urljoin(driver.current_url, emb_src)
                                if dl_via_requests(driver, full_emb_url, pdf_target_fp):
                                    dl_cnt += 1
                                    pdf_saved = True
                                    break

                    close_error_modals(driver)
                except Exception as ex_click:
                    log(f"          ⚠ Click order link error: {ex_click}")

    except Exception as e:
        log(f"          ⚠ Error processing orders: {e}")

    return dl_cnt

# ── SEARCH FORM ACTIONS ─────────────────────────────────────────────

def ensure_party_name_tab(driver):
    """Select Party Name tab if not active and wait for form to be visible."""
    try:
        tab_locators = [
            "//a[contains(translate(text(),'PARTY NAME','party name'),'party name')]",
            "//li[contains(translate(.,'PARTY NAME','party name'),'party name')]",
            "//button[contains(translate(text(),'PARTY NAME','party name'),'party name')]",
            "//span[contains(translate(text(),'PARTY NAME','party name'),'party name')]",
            "//*[@id='party_name_tab']",
            "//*[@id='party-tab']",
            "//*[contains(@data-bs-target, 'party')]",
            "//*[contains(@href, 'party')]"
        ]
        for loc in tab_locators:
            tabs = [el for el in driver.find_elements(By.XPATH, loc) if el.is_displayed()]
            if tabs:
                safe_click(driver, tabs[0])
                time.sleep(1.0)
                break
    except Exception:
        pass

def find_and_click_go_button(driver):
    """Finds and clicks the Go / Submit button on the search form and calls submit_party_name() if needed."""
    try:
        # 1. Targeted locators matching <button type="button" class="btn btn-primary" value="Go" onclick="submit_party_name();">Go</button>
        locators = [
            "//button[contains(@onclick,'submit_party_name')]",
            "//button[contains(@onclick,'party') and (contains(text(),'Go') or contains(text(),'GO') or @value='Go')]",
            "//button[contains(translate(text(),'GO','go'),'go')]",
            "//input[@value='Go' or @value='GO' or @value='Submit']",
            "//button[@type='submit' or @type='button'][contains(text(),'Go') or contains(text(),'GO') or @value='Go']",
            "//input[contains(@onclick,'validate') or contains(@onclick,'party')]",
            ".btn-primary", "button.btn-primary"
        ]

        clicked = False
        for loc in locators:
            if loc.startswith("//"):
                btns = [el for el in driver.find_elements(By.XPATH, loc) if el.is_displayed()]
            else:
                btns = [el for el in driver.find_elements(By.CSS_SELECTOR, loc) if el.is_displayed()]

            if btns:
                safe_click(driver, btns[0])
                clicked = True
                break

        # 2. JS Fallback to trigger submit_party_name() directly
        if not clicked:
            js_res = driver.execute_script("""
                var btns = document.querySelectorAll("button, input[type='button'], input[type='submit']");
                for (var i = 0; i < btns.length; i++) {
                    var b = btns[i];
                    var txt = (b.innerText || b.value || '').trim();
                    var onc = (b.getAttribute('onclick') || '');
                    if ((txt === 'Go' || txt === 'GO' || onc.indexOf('submit_party_name') !== -1) && b.offsetWidth > 0 && b.offsetHeight > 0) {
                        b.click();
                        return 'clicked:' + txt;
                    }
                }
                if (typeof submit_party_name === 'function') {
                    submit_party_name();
                    return 'js_function_call';
                }
                return false;
            """)
            if js_res:
                clicked = True

        return clicked

    except Exception as e:
        log(f"    ⚠ Error clicking Go button: {e}")
        return False

def fill_district_party_form(driver, person_name, year, delay=DEFAULT_DELAY):
    """Fills Petitioner name, Registration year, Both radio button, and Captcha."""
    try:
        ensure_party_name_tab(driver)
        time.sleep(1.0)

        # Sanitize search name (e.g., 'G. Janardhan Reddy' -> 'G Janardhan Reddy' to match eCourts DB formatting without periods)
        search_name = person_name.replace("G.", "G").replace(".", "").strip()

        # Wait up to 5 seconds for party name input to be interactable
        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name*='petparty'], input[id*='petparty'], input[name*='party']"))
            )
        except Exception:
            pass

        # 1. Petitioner/Respondent Name (only visible inputs)
        inp_name = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[name*='petparty'], input[id*='petparty'], input[name*='party']") if el.is_displayed()]
        if not inp_name:
            inp_name = [el for el in driver.find_elements(By.XPATH, "//input[@type='text' and not(contains(@name,'captcha')) and not(contains(@name,'year'))]") if el.is_displayed()]

        if not inp_name:
            # Re-trigger party tab activation in case form returned to a different view
            ensure_party_name_tab(driver)
            time.sleep(1.5)
            inp_name = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[name*='petparty'], input[id*='petparty'], input[name*='party']") if el.is_displayed()]
            if not inp_name:
                inp_name = [el for el in driver.find_elements(By.XPATH, "//input[@type='text' and not(contains(@name,'captcha')) and not(contains(@name,'year'))]") if el.is_displayed()]

        if not inp_name:
            log("    ✗ Petitioner name input field not found")
            return False

        target_name_el = inp_name[0]
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", target_name_el)
        time.sleep(0.4)
        try:
            target_name_el.clear()
        except Exception:
            driver.execute_script("arguments[0].value = '';", target_name_el)
        target_name_el.send_keys(search_name)

        # 2. Registration Year (only visible inputs)
        inp_year = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[name*='year'], input[id*='year'], input[name*='r_year']") if el.is_displayed()]
        if inp_year:
            target_year_el = inp_year[0]
            try:
                target_year_el.clear()
            except Exception:
                driver.execute_script("arguments[0].value = '';", target_year_el)
            target_year_el.send_keys(str(year))

        # 3. Radio button Both (only visible inputs)
        radios = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][value='both'], input[type='radio'][value='B'], input[id*='both']") if el.is_displayed()]
        if not radios:
            radios = [el for el in driver.find_elements(By.XPATH, "//label[contains(text(),'Both')]/preceding-sibling::input[@type='radio'] | //label[contains(text(),'Both')]/input") if el.is_displayed()]
        if radios:
            safe_click(driver, radios[0])

        # 4. Captcha (only visible inputs)
        cap_code = solve_captcha(driver)
        if not cap_code:
            log("    ✗ CAPTCHA could not be solved")
            return False

        inp_cap = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[name*='captcha'], input[id*='captcha'], input[id='txtInput']") if el.is_displayed()]
        if inp_cap:
            target_cap_el = inp_cap[0]
            try:
                target_cap_el.clear()
            except Exception:
                driver.execute_script("arguments[0].value = '';", target_cap_el)
            target_cap_el.send_keys(cap_code)
            time.sleep(0.5)
            return True
        else:
            log("    ✗ Captcha input field not found")
            return False

    except Exception as e:
        log(f"    ✗ Error filling form: {e}")
        return False

# ── MAIN DISTRICT SEARCH ITERATOR ────────────────────────────────────

def init_portal_navigation(driver, state_name, district_pattern, delay=DEFAULT_DELAY):
    """Navigates to search portal and selects State and District."""
    try:
        driver.get(BASE_URL)
        time.sleep(3.0)
        wait_for_loading(driver)

        case_status_menu = [el for el in driver.find_elements(
            By.XPATH,
            "//a[contains(translate(text(), 'CASE STATUS', 'case status'), 'case status')] | "
            "//li[contains(translate(., 'CASE STATUS', 'case status'), 'case status')] | "
            "//*[@id='c_status_id'] | //a[contains(@href, 'casestatus')]"
        ) if el.is_displayed()]

        if case_status_menu:
            safe_click(driver, case_status_menu[0])
            time.sleep(3.0)
            wait_for_loading(driver)
        else:
            driver.get(SEARCH_URL)
            time.sleep(3.0)
            wait_for_loading(driver)

        close_error_modals(driver)

        # Select State
        state_sel = get_dropdown_by_role(driver, "state")
        if not state_sel:
            log("  ✗ State dropdown not found")
            return None

        res = select_option_by_pattern(state_sel, f"^{state_name}$|{state_name}")
        if not res:
            log(f"  ✗ State '{state_name}' option not found in dropdown")
            return None
        sel_state_val, sel_state_txt = res
        log(f"  ✓ Selected State: {sel_state_txt}")
        time.sleep(delay)
        wait_for_loading(driver)
        close_error_modals(driver)

        # Select District
        dist_options = wait_for_dropdown_options(driver, "district", min_options=1, timeout=10)
        dist_sel = get_dropdown_by_role(driver, "district")
        if not dist_sel:
            log("  ✗ District dropdown not found")
            return None

        res = select_option_by_pattern(dist_sel, district_pattern)
        if not res:
            log(f"  ✗ District matching '{district_pattern}' not found in dropdown")
            return None
        sel_dist_val, sel_dist_txt = res
        log(f"  ✓ Selected District: {sel_dist_txt}")
        time.sleep(delay)
        wait_for_loading(driver)
        close_error_modals(driver)

        return (sel_state_txt, sel_dist_txt)

    except Exception as e:
        log(f"  ⚠ Navigation initialization error: {e}")
        return None

def search_district_for_person(driver_or_ref, person_name, target_cfg, delay=DEFAULT_DELAY):
    state_name       = target_cfg["state"]
    district_pattern = target_cfg["district_pattern"]

    log("\n" + "═"*65)
    log(f"  DISTRICT SEARCH: {person_name}")
    log(f"  TARGET STATE  : {state_name}")
    log(f"  DIST PATTERN  : {district_pattern}")
    log(f"  PACING DELAY  : {delay}s")
    log("═"*65)

    driver_ref = driver_or_ref if isinstance(driver_or_ref, list) else [driver_or_ref]
    driver = driver_ref[0]

    try:
        nav_res = init_portal_navigation(driver, state_name, district_pattern, delay=delay)
        if not nav_res:
            return False
        sel_state_txt, sel_dist_txt = nav_res

        # Court Complex options
        complex_options = wait_for_dropdown_options(driver, "complex", min_options=1, timeout=10)
        if not complex_options:
            complex_sel = get_dropdown_by_role(driver, "complex")
            complex_options = get_select_options(complex_sel)

        # Prioritize 'City Civil' court complex first
        city_civil_opts = [c for c in complex_options if re.search(r"city civil|civil", c[1], re.IGNORECASE)]
        other_opts      = [c for c in complex_options if not re.search(r"city civil|civil", c[1], re.IGNORECASE)]
        complex_options = city_civil_opts + other_opts

        log(f"  ✓ Found {len(complex_options)} Court Complex(es) in {sel_dist_txt}")
        total_cases_found = 0
        all_identified_cases = []

        for c_idx, (comp_val, comp_txt) in enumerate(complex_options, 1):
            log(f"\n  ► [{c_idx}/{len(complex_options)}] COURT COMPLEX: {comp_txt}")
            time.sleep(delay + random.uniform(0.5, 1.5))

            try:
                complex_sel = get_dropdown_by_role(driver, "complex")
                if complex_sel:
                    Select(complex_sel).select_by_value(comp_val)
                    time.sleep(delay)
                    wait_for_loading(driver)
                    close_error_modals(driver)
            except Exception as e:
                log(f"    ⚠ Complex select error: {e}")

            # Court Establishments
            est_options = wait_for_dropdown_options(driver, "establishment", min_options=1, timeout=5)
            if not est_options:
                est_sel = get_dropdown_by_role(driver, "establishment")
                est_options = get_select_options(est_sel) if est_sel else []

            if not est_options:
                est_options = [("0", "Main Establishment")]

            # Prioritize 'City Civil' / 'PRL' establishments first
            city_civil_est = [e for e in est_options if re.search(r"city civil|civil|prl", e[1], re.IGNORECASE)]
            other_est      = [e for e in est_options if not re.search(r"city civil|civil|prl", e[1], re.IGNORECASE)]
            est_options    = city_civil_est + other_est

            log(f"    Found {len(est_options)} Court Establishment(s)")

            person_done_in_district = False

            for e_idx, (est_val, est_txt) in enumerate(est_options, 1):
                log(f"\n    ▷ [{e_idx}/{len(est_options)}] ESTABLISHMENT: {est_txt}")
                time.sleep(delay + random.uniform(0.5, 1.5))

                if est_val != "0":
                    try:
                        est_sel = get_dropdown_by_role(driver, "establishment")
                        if est_sel:
                            Select(est_sel).select_by_value(est_val)
                            time.sleep(delay)
                            wait_for_loading(driver)
                            close_error_modals(driver)
                    except Exception as e:
                        log(f"      ⚠ Establishment select error: {e}")

                save_dir = (DOWNLOAD_DIR / "District_Courts" / safe_name(sel_state_txt) /
                            safe_name(sel_dist_txt) / safe_name(comp_txt) / safe_name(est_txt) / safe_name(person_name))
                save_dir.mkdir(parents=True, exist_ok=True)

                establishment_cases = 0

                # Step 6: Iterate Years (2026 -> 2000)
                for year in range(START_YEAR, END_YEAR - 1, -1):
                    log(f"      ▶ Year {year} for '{person_name}'")
                    time.sleep(delay)

                    year_completed = False
                    attempt = 0
                    while not year_completed:
                        attempt += 1
                        if attempt > 1:
                            log(f"        [Attempt {attempt} for Year {year} — retrying due to error/mismatch]")

                        try:
                            if not fill_district_party_form(driver, person_name, year, delay=delay):
                                log("        ✗ Form fill failed — refreshing fields & retrying year")
                                refresh_captcha(driver)
                                time.sleep(2.0)
                                continue

                            time.sleep(1.0)
                            if not find_and_click_go_button(driver):
                                log("        ✗ Submit 'Go' button not found — refreshing fields & retrying year")
                                refresh_captcha(driver)
                                time.sleep(2.0)
                                continue

                            wait_for_loading(driver)
                            time.sleep(delay + random.uniform(0.5, 1.5))

                            # 1. Check for VISIBLE error modal or CAPTCHA mismatch
                            is_err, err_msg = is_error_or_captcha_mismatch(driver)
                            if is_err:
                                log(f"        ⚠ {err_msg} — refreshing CAPTCHA & retrying SAME year {year}")
                                close_error_modals(driver)
                                refresh_captcha(driver)
                                time.sleep(2.0)
                                continue

                            # 2. Check for explicit "No Record Found" message FIRST
                            if is_explicit_no_records_found(driver):
                                log(f"      ℹ  Confirmed: No records found for year {year}")
                                year_completed = True
                                break

                            # 3. Parse Results table (ONLY rows with clickable View buttons)
                            tables = driver.find_elements(By.TAG_NAME, "table")
                            visible_tables = [t for t in tables if t.is_displayed()]
                            if not visible_tables:
                                visible_tables = tables

                            case_rows_info = []
                            for tbl in visible_tables:
                                rows = tbl.find_elements(By.TAG_NAME, "tr")
                                if len(rows) <= 1:
                                    continue

                                for r in rows[1:]:
                                    cells = [td.text.strip() for td in r.find_elements(By.XPATH, "th|td")]
                                    r_text = " ".join(cells).lower()
                                    if not cells or "no record" in r_text or "not found" in r_text or "no case" in r_text or "select establishment" in r_text or "registration year" in r_text:
                                        continue

                                    view_btns = [b for b in r.find_elements(By.XPATH, ".//a[contains(translate(text(),'VIEW','view'),'view')] | .//input[@value='View' or @value='view'] | .//button[contains(translate(text(),'VIEW','view'),'view')]") if b.is_displayed()]
                                    if view_btns:
                                        case_rows_info.append((cells, view_btns[0]))

                            if case_rows_info:
                                establishment_cases += len(case_rows_info)
                                total_cases_found += len(case_rows_info)
                                log(f"      ✓ {len(case_rows_info)} CASE(S) IDENTIFIED for {year} in [{est_txt}]!")

                                for r_idx, (cells, view_btn) in enumerate(case_rows_info, 1):
                                    clean_cells = [c for c in cells if c and c.lower() != "view"]
                                    summary_str = " | ".join(clean_cells)
                                    log(f"        → Case {r_idx}: {summary_str}")

                                    all_identified_cases.append({
                                        "person": person_name,
                                        "state": sel_state_txt,
                                        "district": sel_dist_txt,
                                        "complex": comp_txt,
                                        "establishment": est_txt,
                                        "year": year,
                                        "case_idx": r_idx,
                                        "summary_str": summary_str,
                                        "details": clean_cells
                                    })

                                year_completed = True
                                break

                            # 3. Check for explicit "No Record Found"
                            if is_explicit_no_records_found(driver):
                                log(f"      ℹ  Confirmed: No records found for year {year}")
                                year_completed = True
                                break

                            # 4. Inconclusive result (neither case rows nor explicit 'no record' found)
                            log(f"      ⚠ Inconclusive result for year {year} (no case table & no explicit 'No Record' message) — retrying SAME year")
                            close_error_modals(driver)
                            refresh_captcha(driver)
                            time.sleep(2.0)

                        except (WebDriverException, NoSuchWindowException) as wde:
                            log(f"      ⚠ Browser session issue ({wde.__class__.__name__}): {wde}")
                            log("      Re-initializing browser driver session and resuming...")
                            time.sleep(10)
                            try:
                                driver.quit()
                            except Exception:
                                pass
                            driver = make_driver()
                            driver_ref[0] = driver
                            init_res = init_portal_navigation(driver, state_name, district_pattern, delay=delay)
                            if init_res:
                                sel_state_txt, sel_dist_txt = init_res
                            time.sleep(delay)
                            continue

                if establishment_cases > 0:
                    log(f"      ✓ Found {establishment_cases} case(s) for '{person_name}' in establishment '{est_txt}'")

        log(f"\n  ✓ Completed district search for {person_name} in {sel_state_txt}/{sel_dist_txt}. Total cases identified: {total_cases_found}")

        # ── PRINT FULL IDENTIFIED CASES CATALOG IN TERMINAL ─────────────
        print("\n" + "═"*90)
        print(f"  DISTRICT COURTS - IDENTIFIED CASES CATALOG FOR: '{person_name}'")
        print(f"  LOCATION: {sel_state_txt} -> {sel_dist_txt}")
        print(f"  TOTAL CASES IDENTIFIED: {len(all_identified_cases)}")
        print("═"*90)

        if all_identified_cases:
            report_lines = []
            header_str = f"DISTRICT COURTS IDENTIFIED CASES REPORT - {person_name}\nLocation: {sel_state_txt} -> {sel_dist_txt}\nTotal Cases Identified: {len(all_identified_cases)}\n" + "─"*80
            report_lines.append(header_str)

            for idx, c in enumerate(all_identified_cases, 1):
                item_str = (
                    f"[{idx}] COURT COMPLEX:   {c['complex']}\n"
                    f"    ESTABLISHMENT:   {c['establishment']}\n"
                    f"    YEAR:            {c['year']}\n"
                    f"    CASE DETAILS:    {c['summary_str']}"
                )
                print(f"\n{item_str}")
                report_lines.append(item_str)

            # Save report to text file
            try:
                cat_dir = DOWNLOAD_DIR / "District_Courts" / safe_name(sel_state_txt) / safe_name(sel_dist_txt) / safe_name(person_name)
                cat_dir.mkdir(parents=True, exist_ok=True)
                cat_fp = cat_dir / f"{safe_name(person_name)}_identified_cases_catalog.txt"
                cat_fp.write_text("\n\n".join(report_lines), encoding="utf-8")
                print(f"\n  ✓ Catalog report saved to file: {cat_fp.resolve()}")
            except Exception as ex_file:
                log(f"  ⚠ Could not save catalog file: {ex_file}")
        else:
            print(f"  ℹ No cases found for '{person_name}' across searched years.")

        print("═"*90 + "\n")
        return True

    except Exception as e:
        log(f"  ✗ Fatal search error for {person_name} in {state_name}: {e}")
        import traceback; traceback.print_exc()
        return False

# ── RUNNER FUNCTION ─────────────────────────────────────────────────

def run_district_for_persons(target_persons, delay=DEFAULT_DELAY):
    if isinstance(target_persons, str):
        target_persons = [target_persons]

    print("="*70)
    print("  eCourts District Courts Automation (ecourtindia_v6)")
    print(f"  Target URL : {BASE_URL}")
    print(f"  Downloads  : {DOWNLOAD_DIR.resolve()}")
    print(f"  Targets    : {len(target_persons)} Person(s)")
    print(f"  Pacing     : {delay}s delay between requests")
    for p in target_persons:
        print(f"               - {p}")
    print("="*70 + "\n")

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    driver = make_driver()
    driver_ref = [driver]

    try:
        for person in target_persons:
            for dist_cfg in TARGET_DISTRICTS:
                search_district_for_person(driver_ref, person, dist_cfg, delay=delay)

    except KeyboardInterrupt:
        print("\n  ⚠  Stopped by user.")
    except Exception as e:
        print(f"\n  ✗ Execution error: {e}")
    finally:
        try:
            if sys.stdin and sys.stdin.isatty():
                input("\n  Press ENTER to close browser...")
        except (EOFError, KeyboardInterrupt):
            pass
        try:
            driver_ref[0].quit()
        except Exception:
            pass

# ── MAIN ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="eCourts District Courts Automation (ecourtindia_v6)")
    parser.add_argument("--person", type=str, help="Specific person or entity name to search")
    parser.add_argument("--person-index", type=int, choices=range(1, len(PERSONS) + 1),
                        help="Index of person to search (1 to 6)")
    parser.add_argument("--entities", action="store_true", help="Search all entities instead of persons")
    parser.add_argument("--all", action="store_true", help="Search all persons and entities sequentially")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Pacing delay in seconds (default 4.0)")

    args = parser.parse_args()

    if args.person:
        targets = [args.person]
    elif args.person_index:
        targets = [PERSONS[args.person_index - 1]]
    elif args.entities:
        targets = ENTITIES
    elif args.all:
        targets = PERSONS + ENTITIES
    else:
        targets = PERSONS

    run_district_for_persons(targets, delay=args.delay)

if __name__ == "__main__":
    main()
