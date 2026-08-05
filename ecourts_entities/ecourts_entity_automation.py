r"""
eCourts District Courts Case Status Automation for Entities (ecourtindia_v6)
=============================================================================
Site: https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index

HOW TO RUN:
    Individual Entity Runners (Parallel):
        python entity_1_spaceworld_group.py
        python entity_2_spaceworld_datacentre.py
        python entity_3_gvr_electrotechnics.py
        python entity_4_sada_it_parks.py
        python entity_5_tulip_services.py
        python entity_6_tulip_datacentre.py

    Via Command Line / Flags:
        python ecourts_entity_automation.py --entity "Space World Group LLP"
        python ecourts_entity_automation.py --entity-index 1
        python ecourts_entity_automation.py --all

    Run All District Entities in Parallel:
        python run_all_entities_parallel.py

Targets:
- States & Districts:
    1. Delhi     -> District matching 'new delhi'
    2. Rajasthan -> District matching 'jaipur'
    3. Karnataka -> District matching 'bengaluru|bangalore'
- Traversal: State -> District -> Court Complex -> Court Establishment
- Years: 2026 down to 2020
- Search Type: Party Name (Petitioner/Respondent), Case Status: Both
"""

import os, sys, time, re, base64, argparse, random, shutil, tempfile, io
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

try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

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
    print("[INFO] ddddocr loaded — CAPTCHA will be auto-solved with PIL preprocessing")
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

TARGET_DISTRICTS_DELHI = [
    {"state": "Delhi",      "district_pattern": r"new delhi"},
]

TARGET_DISTRICTS_RAJASTHAN = [
    {"state": "Rajasthan",  "district_pattern": r"jaipur"},
]

TARGET_DISTRICTS_BENGALURU = [
    {"state": "Karnataka",  "district_pattern": r"bengaluru|bangalore"},
]

TARGET_DISTRICTS_TELANGANA = [
    {"state": "Telangana",  "district_pattern": r"ranga|rangareddy"},
]

TARGET_DISTRICTS = TARGET_DISTRICTS_DELHI + TARGET_DISTRICTS_RAJASTHAN + TARGET_DISTRICTS_BENGALURU + TARGET_DISTRICTS_TELANGANA

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
        (DOWNLOAD_DIR / "entity_log.txt").parent.mkdir(exist_ok=True)
        with open(DOWNLOAD_DIR / "entity_log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def make_driver():
    opts = Options()
    profile_dir = tempfile.mkdtemp(prefix="ecourts_entity_chrome_")
    opts.add_argument(f"--user-data-dir={profile_dir}")
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
    dismissed_any = False
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
                log("  ⚠ Server error modal detected! Sleeping 5s for server cooldown...")
                time.sleep(5)

            btns = m.find_elements(By.CSS_SELECTOR, ".btn-close, .close, button[data-bs-dismiss='modal'], button, input[type='button']")
            for b in btns:
                if b.is_displayed():
                    safe_click(driver, b)
                    time.sleep(0.5)
                    dismissed_any = True
                    break
    except Exception:
        pass
    return dismissed_any

def is_captcha_mismatch_visible(driver):
    """Check if a visible error modal or alert explicitly indicates invalid captcha."""
    try:
        try:
            alert = driver.switch_to.alert
            txt = alert.text.lower()
            if "captcha" in txt:
                log(f"      ⚠ JS Alert: '{alert.text.strip()}'")
                alert.accept()
                return True
        except Exception:
            pass

        error_elements = driver.find_elements(By.CSS_SELECTOR, ".modal.show, div.modal[style*='display: block'], #errormsgmodal, #alertmodal, .alert-danger, .error-message, #errormsg")
        for el in error_elements:
            if el.is_displayed():
                txt = el.text.lower()
                if any(w in txt for w in ["invalid captcha", "captcha mismatch", "wrong captcha", "enter valid captcha", "captcha enter"]):
                    return True
    except Exception:
        pass
    return False

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
    """Find select element by role: 'state', 'district', 'complex', 'establishment'."""
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

    for s in visible_selects:
        s_id   = (s.get_attribute("id") or "").lower()
        s_name = (s.get_attribute("name") or "").lower()
        for kw in keywords:
            if kw in s_id or kw in s_name:
                return s

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

def select_option_by_value(select_el, target_value):
    if not select_el:
        return None
    sel = Select(select_el)
    for o in sel.options:
        val = (o.get_attribute("value") or "").strip()
        txt = o.text.strip()
        if val == target_value:
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

# ── CAPTCHA PRE-PROCESSING & SOLVER ─────────────────────────────────

def preprocess_captcha_image(img_bytes):
    """
    Enhances CAPTCHA contrast, removes background noise/wavy lines,
    and upscales 2x to maximize ddddocr recognition accuracy.
    """
    if not PIL_AVAILABLE or not img_bytes:
        return img_bytes
    try:
        image = Image.open(io.BytesIO(img_bytes)).convert("L")
        enhancer = ImageEnhance.Contrast(image)
        image = enhancer.enhance(2.5)
        w, h = image.size
        image = image.resize((w * 2, h * 2), Image.Resampling.LANCZOS)
        threshold = 140
        image = image.point(lambda p: 255 if p > threshold else 0)

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return img_bytes

def refresh_captcha(driver):
    try:
        ref_btns = [el for el in driver.find_elements(By.CSS_SELECTOR, "img[src*='refresh'], a[onclick*='captcha'], #captcha_refresh, .captcha-refresh, i.fa-refresh") if el.is_displayed()]
        if ref_btns:
            safe_click(driver, ref_btns[0])
            time.sleep(1.5)
            return True
    except Exception:
        pass
    return False

def solve_captcha(driver):
    """
    Solves image CAPTCHA using ddddocr with PIL contrast enhancement.
    Automatically refreshes CAPTCHA if prediction length is invalid (<5 characters).
    """
    for cap_attempt in range(3):
        try:
            img_els = [el for el in driver.find_elements(By.CSS_SELECTOR, "img#captcha_image, img[src*='captcha']") if el.is_displayed()]
            if not img_els:
                img_els = driver.find_elements(By.CSS_SELECTOR, "img#captcha_image, img[src*='captcha']")
            if not img_els:
                return ""

            img_el = img_els[0]
            img_src = img_el.get_attribute("src") or ""

            img_bytes = None
            if "base64," in img_src:
                b64_data = img_src.split("base64,")[1]
                img_bytes = base64.b64decode(b64_data)
            else:
                img_bytes = img_el.screenshot_as_png

            if OCR_AVAILABLE and img_bytes:
                # 1. Raw OCR prediction
                code_raw = _ocr.classification(img_bytes).strip()
                clean_raw = re.sub(r'[^a-zA-Z0-9]', '', code_raw)

                # 2. Preprocessed OCR prediction
                proc_bytes = preprocess_captcha_image(img_bytes)
                code_proc = _ocr.classification(proc_bytes).strip()
                clean_proc = re.sub(r'[^a-zA-Z0-9]', '', code_proc)

                alt_keywords = ["enter", "character", "image", "select", "audio", "captcha", "type", "hear"]
                is_alt = any(w in code_raw.lower() or w in code_proc.lower() for w in alt_keywords)

                if is_alt:
                    log("    ⚠ CAPTCHA OCR read alt text / image loading. Refreshing CAPTCHA...")
                    refresh_captcha(driver)
                    time.sleep(1.5)
                    continue

                # Prefer candidate that matches standard 5 or 6 character CAPTCHA length
                candidate = ""
                if len(clean_proc) in (5, 6):
                    candidate = clean_proc
                elif len(clean_raw) in (5, 6):
                    candidate = clean_raw
                elif len(clean_proc) >= 5:
                    candidate = clean_proc
                elif len(clean_raw) >= 5:
                    candidate = clean_raw

                if candidate:
                    log(f"    Auto CAPTCHA ✓: '{candidate}'")
                    return candidate
                else:
                    log(f"    ⚠ CAPTCHA OCR prediction too short ('{clean_raw}' / '{clean_proc}'). Refreshing CAPTCHA...")
                    refresh_captcha(driver)
                    time.sleep(1.5)
                    continue

        except Exception as e:
            log(f"    ⚠ CAPTCHA OCR error: {e}")

    print("\n" + "!"*50)
    user_code = input("  👉 Type CAPTCHA shown in browser: ").strip()
    print("!"*50 + "\n")
    return user_code

def go_back_to_results(driver):
    """Click Back button on case details page to return to search results list."""
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

def extract_and_download_orders_for_case(driver, save_dir, case_lbl):
    """Scrolls down to Final Orders / Judgements section and downloads order PDF."""
    dl_cnt = 0
    try:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(1.0)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(1.0)

        final_order_links = driver.find_elements(By.XPATH,
            "//table[contains(translate(.,'FINAL ORDERS','final orders'),'final order') or contains(translate(.,'JUDGEMENT','judgement'),'judg')]//a[contains(translate(text(),'ORDERS','orders'),'orders') or contains(translate(text(),'VIEW','view'),'view') or contains(translate(text(),'PDF','pdf'),'pdf') or contains(@href,'pdf') or contains(@onclick,'pdf') or contains(@onclick,'display')]"
        )

        if not final_order_links:
            final_order_links = driver.find_elements(By.XPATH,
                "//*[contains(translate(text(),'FINAL ORDER','final order'),'final order') or contains(translate(text(),'JUDGEMENT','judgement'),'judg')]/following::a[contains(translate(text(),'ORDERS','orders'),'orders') or contains(@onclick,'display')]"
            )

        visible_order_links = [l for l in final_order_links if l.is_displayed()]

        if not visible_order_links:
            all_links = driver.find_elements(By.XPATH, "//a[normalize-space(text())='Orders' or normalize-space(text())='Order' or contains(text(),'Orders')]")
            all_visible = [l for l in all_links if l.is_displayed()]
            if all_visible:
                visible_order_links = [all_visible[-1]]
                log("          ℹ No 'Final Orders / Judgements' section — downloading latest single order.")

        if visible_order_links:
            log(f"          Targeting {len(visible_order_links)} Final Order/Judgement link(s)")

        for o_idx, o_link in enumerate(visible_order_links, 1):
            pdf_saved = False
            pdf_target_fp = save_dir / f"{case_lbl}_final_order_{o_idx}.pdf"

            href = (o_link.get_attribute("href") or "").strip()
            onclick = (o_link.get_attribute("onclick") or "").strip()

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

            if not pdf_saved:
                main_window = driver.current_window_handle
                existing_windows = set(driver.window_handles)

                try:
                    safe_click(driver, o_link)
                    time.sleep(2.5)

                    new_windows = set(driver.window_handles) - existing_windows
                    if new_windows:
                        new_win = list(new_windows)[0]
                        driver.switch_to.window(new_win)
                        time.sleep(1.5)
                        tab_url = driver.current_url
                        if dl_via_requests(driver, tab_url, pdf_target_fp):
                            dl_cnt += 1
                            pdf_saved = True
                        driver.close()
                        driver.switch_to.window(main_window)

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
    try:
        tab_locators = [
            "//a[contains(translate(text(),'PARTY NAME','party name'),'party name')]",
            "//li[contains(translate(.,'PARTY NAME','party name'),'party name')]",
            "//button[contains(translate(text(),'PARTY NAME','party name'),'party name')]",
            "//span[contains(translate(text(),'PARTY NAME','party name'),'party name')]",
            "//*[@id='party_name_tab']", "//*[@id='party-tab']", "//*[contains(@data-bs-target, 'party')]", "//*[contains(@href, 'party')]"
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
    try:
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

def fill_district_party_form(driver, entity_name, year, delay=DEFAULT_DELAY):
    try:
        ensure_party_name_tab(driver)
        time.sleep(1.0)

        search_name = entity_name.strip()

        try:
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, "input[name*='petparty'], input[id*='petparty'], input[name*='party']"))
            )
        except Exception:
            pass

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

        inp_year = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[name*='year'], input[id*='year'], input[name*='r_year']") if el.is_displayed()]
        if inp_year:
            target_year_el = inp_year[0]
            try:
                target_year_el.clear()
            except Exception:
                driver.execute_script("arguments[0].value = '';", target_year_el)
            target_year_el.send_keys(str(year))

        radios = [el for el in driver.find_elements(By.CSS_SELECTOR, "input[type='radio'][value='both'], input[type='radio'][value='B'], input[id*='both']") if el.is_displayed()]
        if not radios:
            radios = [el for el in driver.find_elements(By.XPATH, "//label[contains(text(),'Both')]/preceding-sibling::input[@type='radio'] | //label[contains(text(),'Both')]/input") if el.is_displayed()]
        if radios:
            safe_click(driver, radios[0])

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

def init_portal_navigation(driver, state_name, delay=DEFAULT_DELAY, max_attempts=3):
    """Navigates to search portal and selects State with robust retries."""
    for nav_attempt in range(1, max_attempts + 1):
        try:
            log(f"  Navigating to Case Status portal (Attempt {nav_attempt}/{max_attempts})...")
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

            state_sel = get_dropdown_by_role(driver, "state")
            if not state_sel:
                log("  ✗ State dropdown not found")
                time.sleep(2)
                continue

            res = select_option_by_pattern(state_sel, f"^{state_name}$|{state_name}")
            if not res:
                log(f"  ✗ State '{state_name}' option not found in dropdown")
                return None
            sel_state_val, sel_state_txt = res
            log(f"  ✓ Selected State: {sel_state_txt}")
            time.sleep(delay)
            wait_for_loading(driver)
            close_error_modals(driver)

            # Wait for District dropdown options
            dist_options = wait_for_dropdown_options(driver, "district", min_options=1, timeout=12)
            if dist_options:
                opt_texts = [o[1] for o in dist_options]
                log(f"  ✓ Found {len(dist_options)} District Option(s) for State '{sel_state_txt}': {opt_texts[:6]}...")
                return (sel_state_txt, dist_options)
            else:
                log(f"  ⚠ District dropdown empty for '{sel_state_txt}' — retrying navigation...")
                time.sleep(3)

        except Exception as e:
            log(f"  ⚠ Navigation attempt {nav_attempt} error: {e}")
            time.sleep(3)

    return None

def search_district_for_entity(driver_or_ref, entity_name, target_cfg, delay=DEFAULT_DELAY):
    state_name       = target_cfg["state"]
    district_pattern = target_cfg["district_pattern"]

    log("\n" + "═"*65)
    log(f"  DISTRICT ENTITY SEARCH: {entity_name}")
    log(f"  TARGET STATE        : {state_name}")
    log(f"  DIST PATTERN        : {district_pattern}")
    log(f"  PACING DELAY        : {delay}s")
    log("═"*65)

    driver_ref = driver_or_ref if isinstance(driver_or_ref, list) else [driver_or_ref]
    driver = driver_ref[0]

    try:
        nav_res = init_portal_navigation(driver, state_name, delay=delay)
        if not nav_res:
            log(f"  ✗ Failed to initialize portal for State '{state_name}'")
            return False
        sel_state_txt, all_dist_options = nav_res

        # Filter matching districts
        matching_districts = []
        for val, txt in all_dist_options:
            if district_pattern == ".*" or re.search(district_pattern, txt, re.IGNORECASE) or re.search(district_pattern, val, re.IGNORECASE):
                matching_districts.append((val, txt))

        if not matching_districts:
            log(f"  ✗ No district matched pattern '{district_pattern}' in State '{sel_state_txt}'")
            log(f"  Available districts in '{sel_state_txt}': {[d[1] for d in all_dist_options]}")
            return False

        log(f"  ✓ Matched {len(matching_districts)} District(s) in {sel_state_txt}: {[d[1] for d in matching_districts]}")
        total_cases_found_for_entity = 0

        for d_idx, (dist_val, dist_txt) in enumerate(matching_districts, 1):
            log(f"\n  ═════════════════════════════════════════════════════════")
            log(f"  DISTRICT [{d_idx}/{len(matching_districts)}]: {dist_txt} ({sel_state_txt})")
            log(f"  ═════════════════════════════════════════════════════════")

            if len(matching_districts) > 1 and d_idx > 1:
                init_portal_navigation(driver, state_name, delay=delay)
                time.sleep(1)

            dist_sel = get_dropdown_by_role(driver, "district")
            if dist_sel:
                select_option_by_value(dist_sel, dist_val)
                time.sleep(delay)
                wait_for_loading(driver)
                close_error_modals(driver)

            complex_options = wait_for_dropdown_options(driver, "complex", min_options=1, timeout=10)
            if not complex_options:
                complex_sel = get_dropdown_by_role(driver, "complex")
                complex_options = get_select_options(complex_sel) if complex_sel else []

            if not complex_options:
                complex_options = [("0", "Main Court Complex")]

            city_civil_opts = [c for c in complex_options if re.search(r"city civil|civil", c[1], re.IGNORECASE)]
            other_opts      = [c for c in complex_options if not re.search(r"city civil|civil", c[1], re.IGNORECASE)]
            complex_options = city_civil_opts + other_opts

            log(f"  ✓ Found {len(complex_options)} Court Complex(es) in {dist_txt}")

            for c_idx, (comp_val, comp_txt) in enumerate(complex_options, 1):
                log(f"\n  ► [{c_idx}/{len(complex_options)}] COURT COMPLEX: {comp_txt}")
                time.sleep(delay + random.uniform(0.5, 1.5))

                if comp_val != "0":
                    try:
                        complex_sel = get_dropdown_by_role(driver, "complex")
                        if complex_sel:
                            Select(complex_sel).select_by_value(comp_val)
                            time.sleep(delay)
                            wait_for_loading(driver)
                            close_error_modals(driver)
                    except Exception as e:
                        log(f"    ⚠ Complex select error: {e}")

                est_options = wait_for_dropdown_options(driver, "establishment", min_options=1, timeout=5)
                if not est_options:
                    est_sel = get_dropdown_by_role(driver, "establishment")
                    est_options = get_select_options(est_sel) if est_sel else []

                if not est_options:
                    est_options = [("0", "Main Establishment")]

                city_civil_est = [e for e in est_options if re.search(r"city civil|civil|prl", e[1], re.IGNORECASE)]
                other_est      = [e for e in est_options if not re.search(r"city civil|civil|prl", e[1], re.IGNORECASE)]
                est_options    = city_civil_est + other_est

                log(f"    Found {len(est_options)} Court Establishment(s)")

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
                                safe_name(dist_txt) / safe_name(comp_txt) / safe_name(est_txt) / safe_name(entity_name))
                    save_dir.mkdir(parents=True, exist_ok=True)

                    establishment_cases = 0

                    for year in range(START_YEAR, END_YEAR - 1, -1):
                        log(f"      ▶ Year {year} for '{entity_name}'")
                        time.sleep(delay)

                        for attempt in range(1, 4):
                            try:
                                if not fill_district_party_form(driver, entity_name, year, delay=delay):
                                    time.sleep(delay / 2)
                                    continue

                                time.sleep(1.0)
                                if not find_and_click_go_button(driver):
                                    log("      ✗ Submit 'Go' button not found")
                                    time.sleep(delay)
                                    break

                                wait_for_loading(driver)
                                time.sleep(delay + random.uniform(0.5, 1.5))
                                close_error_modals(driver)

                                if is_captcha_mismatch_visible(driver):
                                    log(f"      ⚠ CAPTCHA mismatch (attempt {attempt}/3) — retrying with fresh CAPTCHA")
                                    refresh_captcha(driver)
                                    time.sleep(2)
                                    continue

                                tables = driver.find_elements(By.TAG_NAME, "table")
                                visible_tables = [t for t in tables if t.is_displayed()]
                                if not visible_tables:
                                    visible_tables = tables

                                records_found = False
                                case_rows_info = []

                                for tbl in visible_tables:
                                    rows = tbl.find_elements(By.TAG_NAME, "tr")
                                    if len(rows) <= 1:
                                        continue

                                    for r in rows[1:]:
                                        cells = [td.text.strip() for td in r.find_elements(By.XPATH, "th|td")]
                                        r_text = " ".join(cells).lower()
                                        if not cells or "no record" in r_text or "not found" in r_text or "no case" in r_text:
                                            continue

                                        view_btns = r.find_elements(By.XPATH, ".//a[contains(translate(text(),'VIEW','view'),'view')] | .//input[@value='View' or @value='view'] | .//button[contains(translate(text(),'VIEW','view'),'view')]")
                                        if view_btns:
                                            case_rows_info.append((cells, view_btns[0]))
                                        elif len(cells) >= 3:
                                            case_rows_info.append((cells, None))

                                if case_rows_info:
                                    records_found = True
                                    establishment_cases += len(case_rows_info)
                                    total_cases_found_for_entity += len(case_rows_info)
                                    log(f"      ✓ {len(case_rows_info)} CASE(S) FOUND for {year}!")

                                    for r_idx in range(len(case_rows_info)):
                                        cells, view_btn = case_rows_info[r_idx]
                                        if r_idx > 0:
                                            tbls = [t for t in driver.find_elements(By.TAG_NAME, "table") if t.is_displayed()]
                                            cur_btns = []
                                            for t in tbls:
                                                for tr in t.find_elements(By.TAG_NAME, "tr")[1:]:
                                                    v_b = tr.find_elements(By.XPATH, ".//a[contains(translate(text(),'VIEW','view'),'view')] | .//input[@value='View' or @value='view'] | .//button[contains(translate(text(),'VIEW','view'),'view')]")
                                                    if v_b:
                                                        c_text = [td.text.strip() for td in tr.find_elements(By.XPATH, "th|td")]
                                                        cur_btns.append((c_text, v_b[0]))
                                            if r_idx < len(cur_btns):
                                                cells, view_btn = cur_btns[r_idx]

                                        case_lbl = f"{safe_name(entity_name)}_{year}_case{r_idx + 1}"
                                        log(f"        → Case {r_idx + 1}: {' | '.join(cells[:3])}")

                                        sum_fp = save_dir / f"{case_lbl}_summary.txt"
                                        sum_fp.write_text(" | ".join(cells), encoding="utf-8")

                                        if view_btn:
                                            log("          Opening Case Details (View)...")
                                            safe_click(driver, view_btn)
                                            time.sleep(3.0)
                                            wait_for_loading(driver)
                                            close_error_modals(driver)

                                            dl_cnt = extract_and_download_orders_for_case(driver, save_dir, case_lbl)
                                            if dl_cnt > 0:
                                                log(f"          ✓ Downloaded {dl_cnt} document(s) for Case {r_idx + 1}")
                                            else:
                                                log(f"          ℹ No downloadable PDF orders found for Case {r_idx + 1}")

                                            log("          Returning to search results list...")
                                            go_back_to_results(driver)
                                            time.sleep(2.0)
                                        else:
                                            log(f"          ⚠ View button not found for Case {r_idx + 1}")

                                if not records_found:
                                    log(f"      ℹ  No records for year {year}")

                                break

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
                                init_res = init_portal_navigation(driver, state_name, delay=delay)
                                if init_res:
                                    sel_state_txt, all_dist_options = init_res
                                time.sleep(delay)
                                continue

        log(f"\n  ✓ Completed district search for {entity_name} in {sel_state_txt}. Total cases: {total_cases_found_for_entity}")
        return True

    except Exception as e:
        log(f"  ✗ Fatal search error for {entity_name} in {state_name}: {e}")
        import traceback; traceback.print_exc()
        return False

# ── RUNNER FUNCTION ─────────────────────────────────────────────────

def run_district_for_entities(target_entities, state_filter=None, delay=DEFAULT_DELAY):
    if isinstance(target_entities, str):
        target_entities = [target_entities]

    dist_cfg_list = TARGET_DISTRICTS
    if state_filter:
        sf = str(state_filter).lower().strip()
        if sf in ["delhi", "new delhi"]:
            dist_cfg_list = TARGET_DISTRICTS_DELHI
        elif sf in ["rajasthan", "jaipur"]:
            dist_cfg_list = TARGET_DISTRICTS_RAJASTHAN
        elif sf in ["bengaluru", "bangalore", "karnataka", "ka"]:
            dist_cfg_list = TARGET_DISTRICTS_BENGALURU
        elif sf in ["telangana", "ts", "ranga", "rangareddy"]:
            dist_cfg_list = TARGET_DISTRICTS_TELANGANA

    print("="*70)
    print("  eCourts District Courts Automation for Entities (ecourtindia_v6)")
    print(f"  Target URL : {BASE_URL}")
    print(f"  Downloads  : {DOWNLOAD_DIR.resolve()}")
    print(f"  Targets    : {len(target_entities)} Entity/Entities")
    print(f"  Regions    : {[d['state'] for d in dist_cfg_list]}")
    print(f"  Pacing     : {delay}s delay between requests")
    for e in target_entities:
        print(f"               - {e}")
    print("="*70 + "\n")

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    try:
        for entity in target_entities:
            for dist_cfg in dist_cfg_list:
                log(f"\n🚀 Launching fresh Chrome browser for '{entity}' in state '{dist_cfg['state']}'...")
                driver = make_driver()
                driver_ref = [driver]
                try:
                    search_district_for_entity(driver_ref, entity, dist_cfg, delay=delay)
                except Exception as ex_search:
                    log(f"  ⚠ Search error for '{entity}' in {dist_cfg['state']}: {ex_search}")
                finally:
                    log(f"  Closing Chrome browser for '{entity}' in state '{dist_cfg['state']}'...")
                    try:
                        driver_ref[0].quit()
                    except Exception:
                        pass
                    time.sleep(2)

    except KeyboardInterrupt:
        print("\n  ⚠  Stopped by user.")
    except Exception as e:
        print(f"\n  ✗ Execution error: {e}")

# ── MAIN ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="eCourts District Courts Automation for Entities (ecourtindia_v6)")
    parser.add_argument("--entity", type=str, help="Specific entity name to search")
    parser.add_argument("--entity-index", type=int, choices=range(1, len(ENTITIES) + 1),
                        help="Index of entity to search (1 to 6)")
    parser.add_argument("--all", action="store_true", help="Search all entities sequentially")
    parser.add_argument("--state", type=str, choices=["delhi", "rajasthan", "bengaluru", "telangana", "karnataka", "all"], default="all",
                        help="Target state/region: 'delhi', 'rajasthan', 'bengaluru', or 'telangana'")
    parser.add_argument("--delay", type=float, default=DEFAULT_DELAY, help="Pacing delay in seconds (default 4.0)")

    args = parser.parse_args()

    if args.entity:
        targets = [args.entity]
    elif args.entity_index:
        targets = [ENTITIES[args.entity_index - 1]]
    else:
        targets = ENTITIES

    run_district_for_entities(targets, state_filter=args.state, delay=args.delay)

if __name__ == "__main__":
    main()
