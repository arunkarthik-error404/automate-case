r"""
eCourts High Court Case Status Automation
==========================================
Site: https://hcservices.ecourts.gov.in/hcservices/main.php

HOW TO RUN:
    d:\automate-case\venv\Scripts\python.exe ecourts_automation.py

CAPTCHA: Auto-solved using ddddocr OCR. Falls back to manual input if OCR fails.
PDFs   : Saved to .\downloads\<court>\<name>\
"""

import os, sys, time, re, shutil, io, base64
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
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException
)
from webdriver_manager.chrome import ChromeDriverManager

# ── CAPTCHA OCR (ddddocr) ────────────────────────────────────────────
try:
    import ddddocr
    _ocr = ddddocr.DdddOcr(show_ad=False)
    OCR_AVAILABLE = True
    print("[INFO] ddddocr loaded — CAPTCHA will be auto-solved")
except ImportError:
    OCR_AVAILABLE = False
    print("[WARN] ddddocr not found — will ask you to type CAPTCHA manually")
    print("       Install with: venv\\Scripts\\python.exe -m pip install ddddocr")

# ─────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────

BASE_URL    = "https://hcservices.ecourts.gov.in/hcservices/main.php"
DIST_URL    = "https://services.ecourts.gov.in/ecourtindia_v6/"
DOWNLOAD_DIR = Path(__file__).parent / "downloads"
MAX_YEARS   = 27  # 2026 down to 2000 (20 years / 27 year span)
START_YEAR  = 2026
WAIT        = 20   # element wait timeout seconds
SHORT_WAIT  = 6

# ─────────────────────────────────────────────────────────────────────
#  SEARCH TARGETS
# ─────────────────────────────────────────────────────────────────────

# (court_label,  court_name_partial,          bench_name_partial)
ENTITY_COURTS = [
    ("Delhi",             "Delhi",           "Principal Bench"),
    ("Rajasthan_Jaipur",  "Rajasthan",       "Jaipur"),
    ("Karnataka",         "Karnataka",       "Bengaluru"),
]

PERSON_HC_COURTS = [
    ("Karnataka_Bengaluru", "Karnataka",     "Bengaluru"),
    ("Telangana",           "Telangana",     "Principal Bench"),
]

ENTITIES = [
    "Space World Group LLP",               # ← run first
    "Space World Data Centre Private Limited",
    "G.V.R. Electro Technics Private Limited",
    "Sada IT Parks Private Limited",
    "Tulip Data Centre Services Private Limited",
    "Tulip Data Centre Private Limited",
]

PERSONS = [
    "G. Janardhan Reddy",
    "G. Laxmi Reddy",
    "G. Vidya Reddy",
    "G. Veera Prakash Reddy",
    "G. Veera Reddy",
    "G. Kanaka Durga",
]

# ─────────────────────────────────────────────────────────────────────
#  UTILITIES
# ─────────────────────────────────────────────────────────────────────

def safe_name(name):
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, "_")
    return name.strip()

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(DOWNLOAD_DIR / "log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def wait_for(driver, by, value, t=WAIT):
    return WebDriverWait(driver, t).until(EC.presence_of_element_located((by, value)))

def wait_click(driver, by, value, t=WAIT):
    return WebDriverWait(driver, t).until(EC.element_to_be_clickable((by, value)))

# ─────────────────────────────────────────────────────────────────────
#  BROWSER
# ─────────────────────────────────────────────────────────────────────

def _raw_make_driver():
    abs_dl = str(DOWNLOAD_DIR.resolve())
    opts = Options()
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_experimental_option("prefs", {
        "download.default_directory":  abs_dl,
        "download.prompt_for_download": False,
        "download.directory_upgrade":   True,
        "plugins.always_open_pdf_externally": True,
    })
    svc = Service(ChromeDriverManager().install())
    d   = webdriver.Chrome(service=svc, options=opts)
    d.execute_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
    return d


class DriverWrapper:
    """Wrapper around Selenium WebDriver to support full browser restarts on persistent network errors."""
    def __init__(self, driver):
        self.d = driver

    def restart(self):
        log("  🔄 Restarting Chrome browser due to persistent network / connection error...")
        try:
            self.d.quit()
        except Exception as e:
            log(f"    ⚠ Error quitting old driver: {e}")
        time.sleep(2)
        self.d = _raw_make_driver()
        log("  ✓ New Chrome browser instance launched successfully.")
        return self.d

    def quit(self):
        try:
            self.d.quit()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self.d, name)


def make_driver():
    return DriverWrapper(_raw_make_driver())

# ─────────────────────────────────────────────────────────────────────
#  DROPDOWN HELPERS
# ─────────────────────────────────────────────────────────────────────

def select_by_partial(sel_elem, partial):
    """Select first option whose text contains `partial` (case-insensitive)."""
    sel = Select(sel_elem)
    for opt in sel.options:
        if partial.lower() in opt.text.lower():
            sel.select_by_visible_text(opt.text)
            return opt.text
    return None

def find_select_containing(driver, partial):
    """Find first <select> that has an option containing `partial`."""
    for s in driver.find_elements(By.TAG_NAME, "select"):
        result = select_by_partial(s, partial)
        if result:
            return result
    return None

# ─────────────────────────────────────────────────────────────────────
#  NAVIGATE & SET UP COURT
# ─────────────────────────────────────────────────────────────────────


def open_case_status(driver):
    """
    Load the HC services site, then click the 'Case Status' card
    in the left Search Menu sidebar. Wait for the High Court dropdown
    to become populated before returning. Restarts browser on persistent network error.
    Returns True on success, False on failure.
    """
    loaded = False
    for attempt in range(1, 4):
        try:
            driver.get(BASE_URL)
            time.sleep(3)
            loaded = True
            break
        except Exception as e:
            log(f"  ⚠ Page load attempt {attempt}/3 failed: {e}")
            time.sleep(3)

    if not loaded:
        log(f"  ⚠ Failed to load {BASE_URL} after 3 attempts — restarting browser...")
        if hasattr(driver, "restart"):
            driver.restart()
            try:
                driver.get(BASE_URL)
                time.sleep(3)
                loaded = True
            except Exception as e:
                log(f"  ✗ Failed to load {BASE_URL} even after browser restart: {e}")
                return False
        else:
            return False

    # ── Click the "Case Status" left-sidebar card ──────────────────────
    clicked = False
    strategies = [
        (By.XPATH,
         "//*[normalize-space(text())='Case Status' "
         "and (self::a or self::div or self::td or self::li or self::span)]"),
        (By.XPATH,
         "(//*[contains(normalize-space(.),'Case Status') "
         "  and not(contains(normalize-space(.),'Search')) "
         "  and not(self::h1) and not(self::h2) and not(self::h3)])[1]"),
        (By.XPATH,
         "(//*[contains(normalize-space(.),'Case Status')])[1]"),
    ]
    for by, xpath in strategies:
        try:
            el = WebDriverWait(driver, 8).until(EC.element_to_be_clickable((by, xpath)))
            el.click()
            log("  ✓ Clicked 'Case Status' sidebar card")
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        log("  ⚠ Could not find/click Case Status card — dropdowns may not appear")

    # ── Wait until the High Court dropdown is populated ────────────────
    # After the click the main panel loads a <select> with multiple HC options.
    try:
        WebDriverWait(driver, 15).until(
            lambda d: any(
                len(Select(s).options) > 1
                for s in d.find_elements(By.TAG_NAME, "select")
                if s.is_displayed()
            )
        )
        log("  ✓ High Court dropdown is populated and ready")
        return True
    except Exception:
        log("  ⚠ Timed out waiting for HC dropdown — continuing anyway")
        time.sleep(2)
        return True


def dismiss_popup(driver):
    """
    Dismiss BOTH types of popups the site shows:
      1. Browser JS alert  (driver.switch_to.alert)
      2. In-page DOM modal (e.g. 'Please Select Highcourt and Bench' with an OK button)
    Safe to call at any time — does nothing if no popup is present.
    """
    # ── Try JS browser alert first ──
    try:
        WebDriverWait(driver, 1.5).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        log(f"    ⚠ JS alert dismissed: {alert.text[:60]}")
        alert.accept()
        time.sleep(0.5)
        return True
    except Exception:
        pass

    # ── Try in-page modal OK button ──
    ok_xpaths = [
        "//button[normalize-space(text())='OK' or normalize-space(text())='Ok']",
        "//input[@type='button' and (@value='OK' or @value='Ok')]",
        "//a[normalize-space(text())='OK' or normalize-space(text())='Ok']",
        "//*[contains(@class,'modal') or contains(@class,'popup') or "
        "    contains(@class,'alert') or contains(@class,'dialog')]"
        "//button | //*[contains(@class,'modal')]//input[@type='button']",
    ]
    for xpath in ok_xpaths:
        try:
            btn = WebDriverWait(driver, 1.5).until(
                EC.element_to_be_clickable((By.XPATH, xpath))
            )
            log(f"    ⚠ DOM modal dismissed (OK button clicked)")
            btn.click()
            time.sleep(0.5)
            return True
        except Exception:
            continue
    return False


# Keep old name as alias for any callers
dismiss_alert = dismiss_popup


def setup_hc_bench(driver, court_partial, bench_partial):
    """
    Select High Court dropdown, wait for bench to populate, select bench.
    Dismisses any popups at each step. Returns True only if BOTH are set.
    """
    dismiss_popup(driver)  # clear any stale popup

    # ── Step 1: Select High Court ────────────────────────────────────
    log(f"    Selecting HC: {court_partial}")
    hc_selected = False
    all_selects = driver.find_elements(By.TAG_NAME, "select")
    for s in all_selects:
        result = select_by_partial(s, court_partial)
        if result:
            log(f"    HC ✓: {result}")
            hc_selected = True
            break
    if not hc_selected:
        log(f"    ✗ HC '{court_partial}' not found")
        return False

    dismiss_popup(driver)  # dismiss any popup triggered by HC selection

    # ── Step 2: Wait for bench dropdown to get real options ──────────
    # After selecting HC the site does an AJAX call to populate the bench dropdown.
    # We wait until there are at least 2 <select> elements and the second one
    # has more than 1 option (i.e. not just the placeholder).
    log("    Waiting for bench dropdown to populate...")
    bench_sel_elem = None
    try:
        def bench_ready(d):
            selects = d.find_elements(By.TAG_NAME, "select")
            # Need at least 2 dropdowns visible: HC and bench
            visible = [s for s in selects if s.is_displayed()]
            if len(visible) < 2:
                return False
            # The bench dropdown is the second visible one
            bench_s = visible[1]
            opts = [o for o in Select(bench_s).options
                    if o.get_attribute("value") and o.get_attribute("value") != ""]
            return len(opts) > 0

        WebDriverWait(driver, 12).until(bench_ready)
        log("    Bench dropdown populated")
        # Get the bench dropdown (second visible select)
        visible = [s for s in driver.find_elements(By.TAG_NAME, "select")
                   if s.is_displayed()]
        bench_sel_elem = visible[1] if len(visible) >= 2 else None
    except Exception:
        log("    ⚠ Timeout waiting for bench — trying anyway")
        time.sleep(3)
        visible = [s for s in driver.find_elements(By.TAG_NAME, "select")
                   if s.is_displayed()]
        bench_sel_elem = visible[1] if len(visible) >= 2 else None

    # ── Step 3: Select Bench ────────────────────────────────────────
    bench_selected = False
    if bench_sel_elem is not None:
        result = select_by_partial(bench_sel_elem, bench_partial)
        if result:
            log(f"    Bench ✓: {result}")
            bench_selected = True
        else:
            # Fallback: pick first real option
            try:
                sel = Select(bench_sel_elem)
                opts = [o for o in sel.options
                        if o.get_attribute("value") and o.get_attribute("value") != ""]
                if opts:
                    sel.select_by_value(opts[0].get_attribute("value"))
                    log(f"    Bench fallback ✓: {opts[0].text}")
                    bench_selected = True
            except Exception as e:
                log(f"    ✗ Bench fallback failed: {e}")
    else:
        log("    ✗ Could not locate bench dropdown element")

    dismiss_popup(driver)  # dismiss any popup after bench selection
    time.sleep(0.5)

    if not bench_selected:
        log(f"    ✗ BENCH NOT SELECTED for '{bench_partial}'")
        return False

    return True

def click_party_tab(driver):
    """
    Click the 'Party Name' tab.
    After clicking, dismiss any popup (DOM modal or JS alert).
    If popup appeared it means bench wasn't set — but we dismiss and continue.
    """
    try:
        el = wait_click(driver, By.XPATH,
            "//*[contains(normalize-space(.),'Party Name') and "
            "(self::a or self::li or self::td or self::span or self::div or self::th)]", t=8)
        el.click()
        time.sleep(1)
        dismiss_popup(driver)   # <-- handles the 'Please Select HC and Bench' modal
        log("    Party Name tab clicked")
    except Exception as e:
        log(f"    ⚠ Could not click Party Name tab: {e}")
        dismiss_popup(driver)

def fill_form(driver, name, year):
    """Fill petitioner field, year, select Both. Returns True on success."""
    # Party name
    filled_name = False
    for sel in ["input[name*='pet']","input[id*='pet']","input[name*='search_param']",
                "input[placeholder*='etitioner']","input[type='text']:first-of-type"]:
        try:
            f = driver.find_element(By.CSS_SELECTOR, sel)
            f.clear(); f.send_keys(name)
            filled_name = True
            break
        except Exception:
            continue
    if not filled_name:
        # Try all text inputs
        for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
            try:
                ph = (inp.get_attribute("placeholder") or "").lower()
                nm = (inp.get_attribute("name") or "").lower()
                if any(k in ph+nm for k in ["pet","party","name","search"]):
                    inp.clear(); inp.send_keys(name)
                    filled_name = True
                    break
            except Exception:
                continue
    if not filled_name:
        log(f"    ✗ Could not enter name"); return False

    # Year
    filled_year = False
    for sel in ["input[name*='year']","input[id*='year']","input[name*='reg']"]:
        try:
            f = driver.find_element(By.CSS_SELECTOR, sel)
            f.clear(); f.send_keys(str(year))
            filled_year = True
            break
        except Exception:
            continue
    if not filled_year:
        for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='text']"):
            try:
                ph = (inp.get_attribute("placeholder") or "").lower()
                nm = (inp.get_attribute("name") or "").lower()
                if "year" in ph+nm or "reg" in nm:
                    inp.clear(); inp.send_keys(str(year))
                    filled_year = True
                    break
            except Exception:
                continue
    if not filled_year:
        log(f"    ✗ Could not enter year"); return False

    # ── Both radio ─────────────────────────────────────────────────────
    # Use JavaScript to find and click the radio by its surrounding text.
    # This is the most reliable cross-browser approach.
    both_selected = False
    js_click_both = """
    // ── Primary: target known ID 'radB' (Both radio on eCourts) ──
    var byId = document.getElementById('radB');
    if (byId) { byId.click(); return 'id:radB'; }
    var radios = document.querySelectorAll("input[type='radio']");
    for (var i = 0; i < radios.length; i++) {
        var r = radios[i];
        var val = (r.value || '').toLowerCase();
        // Check value attribute
        if (val === 'b' || val === 'both') { r.click(); return 'val:' + r.value; }
        // Check text immediately after the radio button
        var nextText = '';
        var sib = r.nextSibling;
        while (sib) {
            nextText += (sib.textContent || sib.nodeValue || '');
            sib = sib.nextSibling;
        }
        if (nextText.trim().toLowerCase().startsWith('both')) {
            r.click(); return 'text:' + nextText.trim().substring(0,6);
        }
    }
    // Hard fallback: click the LAST radio (Both is always the last option)
    if (radios.length >= 3) {
        radios[radios.length - 1].click();
        return 'last:' + (radios[radios.length-1].value || '?');
    }
    return 'not_found';
    """
    try:
        js_result = driver.execute_script(js_click_both)
        log(f"    ✓ Both radio JS: {js_result}")
        if js_result and js_result != "not_found":
            both_selected = True
        time.sleep(0.3)
    except Exception as e:
        log(f"    ⚠ JS radio click error: {e}")

    # Selenium fallback: try #radB first, then last visible radio
    if not both_selected:
        try:
            rad_b = driver.find_element(By.ID, "radB")
            if rad_b.is_displayed():
                rad_b.click()
                log("    ✓ Both radio: clicked #radB")
                both_selected = True
        except Exception:
            pass
    if not both_selected:
        try:
            visible_radios = [r for r in driver.find_elements(
                By.CSS_SELECTOR, "input[type='radio']") if r.is_displayed()]
            if visible_radios:
                visible_radios[-1].click()
                log(f"    ✓ Both radio: clicked last (value={visible_radios[-1].get_attribute('value')})")
                both_selected = True
        except Exception as e:
            log(f"    ⚠ Selenium fallback radio failed: {e}")

    if not both_selected:
        log("    ⚠ Could not select Both radio")

    log(f"    Form filled: name='{name}' year={year}")
    return True

# ─────────────────────────────────────────────────────────────────────
#  CAPTCHA & SUBMIT
# ─────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────
#  AUTO CAPTCHA SOLVER
# ─────────────────────────────────────────────────────────────────────

CAPTCHA_IMG_SELECTORS = [
    "img.captcha-img",
    "#captcha_image",
    "img[src*='captcha']",
    "img[id*='captcha']",
    "img[class*='captcha']",
    # The site renders captcha as a canvas or img in a td next to the label
    "td img",
    "#captcha img",
    ".captchaImg",
]

CAPTCHA_INPUT_SELECTORS = [
    "input[name='captcha']",
    "#fcaptcha",
    "input[id*='captcha']",
    "input[name*='cap']",
    "input[placeholder*='aptcha']",
]

GO_BUTTON_SELECTORS = [
    "input[value='Go']",
    "button[value='Go']",
    "#go_btn",
    "input[type='submit'][value='Go']",
    "input[type='button'][value='Go']",
    "input[type='submit']",
]


def read_captcha_image_bytes(driver):
    """
    Screenshot just the CAPTCHA image element and return raw PNG bytes.
    Returns None if the captcha element cannot be found.
    """
    for sel in CAPTCHA_IMG_SELECTORS:
        try:
            el = driver.find_element(By.CSS_SELECTOR, sel)
            if el.is_displayed():
                png = el.screenshot_as_png
                return png
        except Exception:
            continue
    return None


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

def ocr_solve(driver):
    """
    Try to solve the CAPTCHA automatically using ddddocr with PIL preprocessing.
    If the image is distorted or unreadable (<4 chars or noise), automatically refreshes the CAPTCHA.
    """
    if not OCR_AVAILABLE:
        return None

    for attempt in range(1, 10):
        try:
            img_bytes = read_captcha_image_bytes(driver)
            if img_bytes is None:
                log("    OCR: could not locate captcha image element — refreshing captcha")
                refresh_captcha(driver)
                time.sleep(1.5)
                continue

            # 1. Raw classification
            raw_result = _ocr.classification(img_bytes).strip().replace(" ", "")
            clean_raw = re.sub(r'[^a-zA-Z0-9]', '', raw_result)
            alt_keywords = ["enter", "character", "image", "select", "audio", "captcha", "type", "hear"]
            is_alt_raw = len(clean_raw) > 8 or any(w in raw_result.lower() for w in alt_keywords)

            if not is_alt_raw and 4 <= len(clean_raw) <= 7:
                log(f"    OCR solved (raw): '{clean_raw}'")
                return clean_raw

            # 2. Preprocessed classification
            prep_bytes = preprocess_captcha_image(img_bytes)
            prep_result = _ocr.classification(prep_bytes).strip().replace(" ", "")
            clean_prep = re.sub(r'[^a-zA-Z0-9]', '', prep_result)
            is_alt_prep = len(clean_prep) > 8 or any(w in prep_result.lower() for w in alt_keywords)

            if not is_alt_prep and 4 <= len(clean_prep) <= 7:
                log(f"    OCR solved (preprocessed): '{clean_prep}'")
                return clean_prep

            # Distorted/unrecognizable image — refresh captcha to get a cleaner one
            log(f"    ⚠ CAPTCHA distorted/unrecognizable (attempt {attempt}/10) — refreshing CAPTCHA...")
            refresh_captcha(driver)
            time.sleep(1.5)

        except Exception as e:
            log(f"    OCR error (attempt {attempt}): {e}")
            refresh_captcha(driver)
            time.sleep(1.5)

    return None


def refresh_captcha(driver):
    """Click refresh/reload button for the captcha image."""
    refresh_sels = [
        "img[onclick*='refresh']",
        "img[onclick*='captcha']",
        "#refresh_captcha",
        ".captcha-refresh",
        "button[onclick*='captcha']",
        "a[onclick*='captcha']",
        "span[onclick*='captcha']",
        # The site's reload icon is often a small clickable image next to captcha
        "td img[onclick]",
    ]
    for sel in refresh_sels:
        try:
            driver.find_element(By.CSS_SELECTOR, sel).click()
            time.sleep(1)
            return True
        except Exception:
            continue
    return False


def _enter_cap_and_go(driver, cap_text):
    """
    Enter captcha text into the input field, click Go, and wait dynamically (up to 20s)
    until a definitive result appears on screen ('no_records', 'found', 'bad_captcha', or 'error').
    """
    # Enter captcha text
    entered = False
    for sel in CAPTCHA_INPUT_SELECTORS:
        try:
            f = driver.find_element(By.CSS_SELECTOR, sel)
            f.clear()
            f.send_keys(cap_text)
            entered = True
            break
        except Exception:
            continue
    if not entered:
        log("    ✗ Captcha input field not found")
        return "error"

    # Click Go
    clicked = False
    for sel in GO_BUTTON_SELECTORS:
        try:
            driver.find_element(By.CSS_SELECTOR, sel).click()
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        log("    ✗ Go button not found")
        return "error"

    # ── Dynamic Wait Loop (up to 20 seconds) ───────────────────────────
    start_time = time.time()
    while time.time() - start_time < 20:
        time.sleep(1)

        # 1. Check for JS browser alert
        try:
            alert = driver.switch_to.alert
            alert_text = alert.text.lower()
            log(f"    ⚠ Alert detected: '{alert.text}'")
            alert.accept()
            if any(p in alert_text for p in ["invalid", "wrong", "mismatch"]):
                return "bad_captcha"
            if any(p in alert_text for p in ["no record", "no case", "not found"]):
                return "no_records"
            if any(p in alert_text for p in ["invalid", "wrong", "mismatch", "error", "captcha"]):
                return "bad_captcha"
        except Exception:
            pass

        # 2. Check for DOM modal / popup
        try:
            modals = driver.find_elements(By.XPATH,
                "//*[contains(@class,'modal') or contains(@class,'popup') or contains(@id,'modal') or contains(@id,'popup') or contains(@class,'alert')]")
            for m in modals:
                if m.is_displayed():
                    m_text = m.text.lower()
                    if m_text:
                        log(f"    ⚠ DOM Modal text: '{m_text[:60]}'")
                        dismiss_popup(driver)
                        if any(p in m_text for p in ["invalid", "wrong", "mismatch", "captcha", "error", "something wrong"]):
                            return "bad_captcha"
                        if any(p in m_text for p in ["no record", "no case", "not found"]):
                            return "no_records"
        except Exception:
            pass

        # 3. Check body text
        try:
            body = driver.find_element(By.TAG_NAME, "body").text.lower()
        except Exception:
            continue

        # Check for error / bad captcha text
        if any(p in body for p in ["invalid captcha", "wrong captcha",
                                    "captcha mismatch", "captcha error",
                                    "enter correct captcha", "there is an error",
                                    "something went wrong", "try again"]):
            log(f"    ✗ Error / Bad captcha on page for captcha: '{cap_text}'")
            return "bad_captcha"

        # Check for case results table / View buttons
        m = re.search(r"total number of cases\s*[:\-]\s*(\d+)", body)
        if m and int(m.group(1)) > 0:
            return "found"

        views = driver.find_elements(By.XPATH,
            "//input[@value='View']|//a[normalize-space(text())='View']")
        if views:
            return "found"

        # Check explicit no records text ONLY
        no_rec = ["no records found", "no case found", "record not found",
                  "total number of cases : 0", "0 cases found"]
        if any(p in body for p in no_rec):
            return "no_records"

    # Timed out waiting after 20s
    log("    ⚠ Search result response timed out (20s) — returning error to retry year")
    return "error"


def do_captcha_and_go(driver):
    """
    Solve CAPTCHA automatically (ddddocr), retry up to 3 times.
    Falls back to manual terminal input if OCR keeps failing.
    Returns: 'no_records' | 'found' | 'bad_captcha' | 'error'
    """
    AUTO_TRIES = 3   # attempts with OCR before asking manually

    # ── Auto-solve attempts ───────────────────────────────────────────
    if OCR_AVAILABLE:
        for attempt in range(1, AUTO_TRIES + 1):
            cap = ocr_solve(driver)
            if not cap:
                log(f"    OCR attempt {attempt}: no text read — refreshing captcha")
                refresh_captcha(driver)
                time.sleep(1)
                continue

            log(f"    Auto-solving [{attempt}/{AUTO_TRIES}]: '{cap}'")
            result = _enter_cap_and_go(driver, cap)

            if result != "bad_captcha":
                return result   # success, no_records, or error

            # Bad — refresh and try again
            log(f"    OCR wrong — refreshing captcha for retry {attempt+1}")
            refresh_captcha(driver)
            time.sleep(1)

        log("    ⚠ OCR failed 3 times — falling back to manual input")

    # ── Manual fallback ───────────────────────────────────────────────
    print("\n" + "━"*60)
    print("  👁  AUTO-SOLVE FAILED — Look at browser, type CAPTCHA:")
    print("━"*60)
    cap = input("  CAPTCHA > ").strip()
    if not cap:
        return "error"
    return _enter_cap_and_go(driver, cap)

# ─────────────────────────────────────────────────────────────────────
#  PDF DOWNLOAD
# ─────────────────────────────────────────────────────────────────────

def save_page_as_pdf_via_print(driver, filepath):
    """
    Saves the currently rendered page/view/modal to a PDF file using Chrome DevTools Protocol (CDP) Page.printToPDF.
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
        log(f"        ✓ Saved via Print-to-PDF: {filepath.name}")
        return True
    except Exception as e:
        log(f"        ✗ Print-to-PDF error: {e}")
        return False

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

def safe_click(driver, element):
    """Click element reliably using scrollIntoView + native click with JS click fallback."""
    try:
        driver.execute_script("arguments[0].scrollIntoView({block: 'center', inline: 'nearest'});", element)
        time.sleep(0.3)
        element.click()
    except Exception:
        driver.execute_script("arguments[0].click();", element)

def handle_view_page(driver, save_dir, case_label):
    """On the case detail page, find and download all Order PDFs / details, with Print-to-PDF fallback."""
    time.sleep(3)
    handles = driver.window_handles
    if len(handles) > 1:
        driver.switch_to.window(handles[-1])
        time.sleep(2)

    order_xpath = "//table//tr[td]//a[contains(normalize-space(.),'View') or contains(normalize-space(.),'Order') or contains(@href,'pdf') or contains(@onclick,'pdf') or contains(@onclick,'display')]"
    links = driver.find_elements(By.XPATH, order_xpath)
    num_orders = len(links)
    log(f"      Orders found: {num_orders}")

    dl_count = 0
    for i in range(num_orders):
        try:
            # Re-fetch elements on each iteration to prevent StaleElementReferenceException
            current_links = driver.find_elements(By.XPATH, order_xpath)
            if i >= len(current_links):
                break
            lnk = current_links[i]

            href    = lnk.get_attribute("href") or ""
            onclick = lnk.get_attribute("onclick") or ""
            log(f"      Order {i+1}: href='{href[:60]}' onclick='{onclick[:60]}'")

            pdf_url = None

            # ── Strategy 1: Check href for PDF URL ──
            if href and ("display_pdf" in href.lower() or href.lower().endswith(".pdf") or ("pdf" in href.lower() and href.startswith("http"))):
                pdf_url = href

            # ── Strategy 2: Extract relative PDF path from onclick JS ──
            if not pdf_url and onclick:
                m = re.search(r"['\"]([^'\"]*(?:display_pdf|pdf|\.pdf)[^'\"]*)['\"]", onclick, re.I)
                if m:
                    rel_path = m.group(1)
                    pdf_url = urljoin(driver.current_url or BASE_URL, rel_path)
                    log(f"        Extracted URL from onclick: {pdf_url[:80]}")

            # If direct URL identified via href or onclick, download via requests
            if pdf_url:
                fp = save_dir / f"{case_label}_order{i+1}.pdf"
                ok = dl_via_requests(driver, pdf_url, fp)
                if ok:
                    dl_count += 1
                    continue

            # ── Strategy 3: Interactive Click + Dynamic Modal Scanning ──
            files_before = set(DOWNLOAD_DIR.rglob("*"))
            bef_handles  = set(driver.window_handles)

            # Click link natively first
            try:
                safe_click(driver, lnk)
            except Exception:
                pass

            # If onclick contains a JS function call (e.g. viewHistory), execute it directly as well
            if onclick:
                try:
                    driver.execute_script(onclick)
                except Exception:
                    pass

            # Allow AJAX response time to render modal or update DOM
            time.sleep(2)

            captured = False
            start_time = time.time()
            while time.time() - start_time < 10:
                # 3A. Check if a new browser tab/window opened
                new_handles = set(driver.window_handles) - bef_handles
                if new_handles:
                    log(f"        ✓ New tab detected ({int(time.time()-start_time)}s)")
                    driver.switch_to.window(new_handles.pop())
                    time.sleep(2)
                    cur_url = driver.current_url
                    ct = driver.execute_script("return document.contentType") or ""
                    fp = save_dir / f"{case_label}_order{i+1}.pdf"
                    if "pdf" in cur_url.lower() or "pdf" in ct.lower():
                        ok = dl_via_requests(driver, cur_url, fp)
                        if ok: dl_count += 1; captured = True
                    else:
                        # Fallback: Save tab content via Print-to-PDF
                        ok = save_page_as_pdf_via_print(driver, fp)
                        if ok: dl_count += 1; captured = True
                    driver.close()
                    driver.switch_to.window(list(set(driver.window_handles))[0])
                    break

                # 3B. Check if Chrome automatically saved a PDF to disk
                files_after = set(DOWNLOAD_DIR.rglob("*")) - files_before
                downloaded_files = [f for f in files_after if f.is_file() and not f.name.endswith(".crdownload") and not f.name.endswith(".tmp")]
                if downloaded_files:
                    latest_file = downloaded_files[0]
                    target_fp = save_dir / f"{case_label}_order{i+1}{latest_file.suffix or '.pdf'}"
                    shutil.move(str(latest_file), str(target_fp))
                    log(f"        ✓ Saved downloaded file from disk: {target_fp.name}")
                    dl_count += 1; captured = True
                    break

                # 3C. Check for in-page iframe, embed, or object PDF viewers
                frames = driver.find_elements(By.CSS_SELECTOR, "iframe[src*='pdf'], iframe[src*='display'], embed[src], object[data]")
                for frame in frames:
                    src = frame.get_attribute("src") or frame.get_attribute("data") or ""
                    if src and src != "javascript:void(0);" and not src.endswith("#"):
                        frame_url = urljoin(driver.current_url, src)
                        fp = save_dir / f"{case_label}_order{i+1}.pdf"
                        ok = dl_via_requests(driver, frame_url, fp)
                        if ok:
                            dl_count += 1; captured = True
                            break
                if captured:
                    break

                # 3D. Check for DOM Modal / History Dialogs / Popups that appeared on screen
                modal_selectors = [
                    "[class*='modal']", "[id*='modal']", "[id*='history']", "[class*='history']",
                    "[id*='popup']", "[class*='popup']", "#myModal", ".modal-dialog", ".ui-dialog"
                ]
                modal_containers = []
                for ms in modal_selectors:
                    for el in driver.find_elements(By.CSS_SELECTOR, ms):
                        if el.is_displayed() and el not in modal_containers:
                            modal_containers.append(el)

                for mc in modal_containers:
                    # Scan all links and buttons inside the modal container
                    child_links = mc.find_elements(By.CSS_SELECTOR, "a, button, input[type='button'], input[type='submit']")
                    for cl in child_links:
                        c_href  = cl.get_attribute("href") or ""
                        c_click = cl.get_attribute("onclick") or ""
                        target_url = None

                        if c_href and ("display_pdf" in c_href.lower() or c_href.lower().endswith(".pdf") or "pdf" in c_href.lower() or "download" in c_href.lower()):
                            target_url = c_href if c_href.startswith("http") else urljoin(driver.current_url, c_href)
                        elif c_click:
                            c_match = re.search(r"['\"]([^'\"]*(?:display_pdf|pdf|\.pdf|download)[^'\"]*)['\"]", c_click, re.I)
                            if c_match:
                                target_url = urljoin(driver.current_url, c_match.group(1))

                        if target_url:
                            fp = save_dir / f"{case_label}_order{i+1}.pdf"
                            ok = dl_via_requests(driver, target_url, fp)
                            if ok:
                                dl_count += 1; captured = True
                                break

                        # Try clicking child links inside the modal if direct URL extraction was not possible
                        if not captured and cl.is_displayed():
                            try:
                                safe_click(driver, cl)
                                time.sleep(1)
                            except Exception:
                                pass

                    if captured:
                        break

                    # Fallback capture: Save modal view directly as PDF via Print-to-PDF
                    mc_text = mc.text.strip()
                    if mc_text and len(mc_text) > 20:
                        pdf_fp = save_dir / f"{case_label}_order{i+1}_modal.pdf"
                        save_page_as_pdf_via_print(driver, pdf_fp)
                        dl_count += 1; captured = True
                        break

                if captured:
                    break

                time.sleep(1)

            if not captured:
                log(f"        ⚠ Could not capture Order {i+1} via link — printing page view to PDF")
                print_fp = save_dir / f"{case_label}_order{i+1}_printed.pdf"
                if save_page_as_pdf_via_print(driver, print_fp):
                    dl_count += 1

        except Exception as e:
            log(f"        ✗ Order {i+1} error: {e}")

    # Fallback: If no clickable links found or no downloads occurred, save entire case detail view via Print to PDF
    if dl_count == 0:
        log("      ℹ No downloadable order PDF links captured — saving case view via Print to PDF option...")
        print_fp = save_dir / f"{case_label}_printed_case_view.pdf"
        if save_page_as_pdf_via_print(driver, print_fp):
            dl_count += 1

    # Close detail tab and return to list
    handles = driver.window_handles
    if len(handles) > 1:
        for h in handles[1:]:
            driver.switch_to.window(h)
            driver.close()
        driver.switch_to.window(handles[0])

    return dl_count

# ─────────────────────────────────────────────────────────────────────
#  CORE: SEARCH ONE (party × court) ACROSS YEARS
# ─────────────────────────────────────────────────────────────────────

def search_hc(driver, party_name, court_label, court_partial, bench_partial):
    save_dir = DOWNLOAD_DIR / safe_name(court_label) / safe_name(party_name)
    save_dir.mkdir(parents=True, exist_ok=True)

    log("═"*65)
    log(f"  SEARCH: {party_name}")
    log(f"  COURT : {court_label}")
    log("═"*65)

    found_any = False
    need_full_setup = True   # True = navigate & re-select HC/bench/tab

    def _full_setup():
        """Navigate to base URL, pick HC + bench, click Party Name tab."""
        if not open_case_status(driver):
            log("  ✗ open_case_status failed")
            return False
        if not setup_hc_bench(driver, court_partial, bench_partial):
            log("  ✗ Could not select court/bench")
            return False
        click_party_tab(driver)
        time.sleep(1)
        try:
            WebDriverWait(driver, 8).until(
                lambda d: len(d.find_elements(
                    By.CSS_SELECTOR, "input[type='text']")) >= 2
            )
        except Exception:
            log("  ⚠ Form fields not detected yet — trying anyway")
        return True

    def _quick_reset():
        """Stay on the current page: click Reset (if present) and refresh captcha."""
        try:
            rst = driver.find_element(By.CSS_SELECTOR,
                "input[value='Reset'], button[value='Reset'], input[value='reset']")
            rst.click()
            time.sleep(0.5)
        except Exception:
            pass                       # No Reset button — just overwrite fields
        refresh_captcha(driver)
        time.sleep(0.5)

    for year in range(START_YEAR, START_YEAR - MAX_YEARS, -1):
        year_completed = False
        year_attempt = 0
        while not year_completed:
            year_attempt += 1
            if year_attempt > 1:
                log(f"\n  ▶ Year {year} (Attempt {year_attempt} — retrying year search)")
            else:
                log(f"\n  ▶ Year {year}")

            try:
                if need_full_setup:
                    if not _full_setup():
                        log("  ✗ Setup failed — retrying year with fresh setup")
                        need_full_setup = True
                        time.sleep(2)
                        continue
                    need_full_setup = False
                else:
                    # ── FAST PATH: stay on page, just clear fields + refresh captcha ──
                    log("    ↺ Staying on page — refreshing fields & captcha")
                    _quick_reset()

                # Fill petitioner name, year, Both radio
                if not fill_form(driver, party_name, year):
                    log("  ✗ Could not fill form — forcing full re-setup next")
                    need_full_setup = True
                    time.sleep(2)
                    continue

                log(f"  ✓ Form ready: name='{party_name}' year={year} status=Both")

            except Exception as e:
                log(f"  ✗ Setup error: {e} — will retry with full setup")
                need_full_setup = True
                time.sleep(2)
                continue

            # ── CAPTCHA loop ──────────────────────────────────────────────
            result = None
            try:
                for attempt in range(1, 6):
                    log(f"\n  [CAPTCHA try {attempt}/5 for year {year}]")
                    result = do_captcha_and_go(driver)
                    if result != "bad_captcha":
                        break
                    refresh_captcha(driver)
                    time.sleep(1)
            except Exception as e:
                log(f"  ✗ Captcha/Network error for year {year}: {e}")
                result = "error"

            if result == "no_records":
                log(f"  ℹ  Confirmed: No records found for year {year}")
                year_completed = True
                break

            elif result != "found":
                log(f"  ⚠  Inconclusive result / error for year {year} (result={result}) — retrying SAME year with full setup")
                need_full_setup = True   # Reload page & retry same year
                time.sleep(2)
                continue

            # ── Process results ───────────────────────────────────────────
            log(f"  ✓ CASES FOUND for year {year}!")
            found_any = True
            year_completed = True

            btn_xpath = "//input[@value='View']|//a[normalize-space(text())='View']"
            view_btns = driver.find_elements(By.XPATH, btn_xpath)
            num_btns  = len(view_btns)
            log(f"  Cases in table: {num_btns}")

            for idx in range(num_btns):
                case_label = f"{safe_name(party_name)}_{year}_case{idx+1}"
                log(f"\n  → Case {idx+1}: clicking View")
                try:
                    current_btns = driver.find_elements(By.XPATH, btn_xpath)
                    if idx >= len(current_btns):
                        break
                    btn = current_btns[idx]

                    bef = set(driver.window_handles)
                    safe_click(driver, btn)
                    time.sleep(3)
                    new = set(driver.window_handles) - bef
                    if new:
                        driver.switch_to.window(new.pop())
                    dl = handle_view_page(driver, save_dir, case_label)
                    log(f"    Downloaded {dl} file(s)")
                except Exception as e:
                    log(f"    ✗ View error: {e}")
                finally:
                    handles = driver.window_handles
                    if len(handles) > 1:
                        for h in handles[1:]:
                            try:
                                driver.switch_to.window(h); driver.close()
                            except Exception:
                                pass
                        try:
                            driver.switch_to.window(handles[0])
                        except Exception:
                            pass

            # After viewing cases the browser is back on results page — need full reload
            need_full_setup = True
            break

        if not year_success:
            log(f"  ✗ Year {year} failed after {MAX_YEAR_RETRIES} attempts — skipping to next year")
            need_full_setup = True

    if not found_any:
        log(f"  ℹ  No cases found for '{party_name}' at {court_label} in {MAX_YEARS} years")
    return found_any

# ─────────────────────────────────────────────────────────────────────
#  DISTRICT COURT: TELANGANA / RANGAREDDY
# ─────────────────────────────────────────────────────────────────────

def search_telangana_rangareddy(driver, person_name):
    """Search on District Courts portal for Telangana > Rangareddy."""
    save_dir = DOWNLOAD_DIR / "Telangana_Rangareddy" / safe_name(person_name)
    save_dir.mkdir(parents=True, exist_ok=True)

    log("═"*65)
    log(f"  DISTRICT SEARCH: {person_name}")
    log(f"  COURT: Telangana → Rangareddy")
    log("═"*65)

    found_any = False

    MAX_YEAR_RETRIES = 3
    for year in range(START_YEAR, START_YEAR - MAX_YEARS, -1):
        year_success = False
        for year_attempt in range(1, MAX_YEAR_RETRIES + 1):
            if year_attempt > 1:
                log(f"\n  ▶ Year {year} (Retry attempt {year_attempt}/{MAX_YEAR_RETRIES})")
            else:
                log(f"\n  ▶ Year {year}")

            try:
                # Load District URL with retry logic
                dist_loaded = False
                for attempt in range(1, 4):
                    try:
                        driver.get(DIST_URL)
                        time.sleep(3)
                        dist_loaded = True
                        break
                    except Exception as e:
                        log(f"    ⚠ Navigation attempt {attempt}/3 to {DIST_URL} failed: {e}")
                        time.sleep(3)

                if not dist_loaded:
                    log(f"    ✗ Could not load {DIST_URL} — skipping district court search for {person_name}")
                    return False

                # State
                r = find_select_containing(driver, "Telangana")
                if r: log(f"    State: {r}")

                time.sleep(2)

                # District
                r = find_select_containing(driver, "Ranga")
                if not r:
                    r = find_select_containing(driver, "Rangareddy")
                if r: log(f"    District: {r}")

                time.sleep(2)

                # Proceed / Go
                for sel in ["input[value='Go']","input[type='submit']","button[type='submit']"]:
                    try:
                        driver.find_element(By.CSS_SELECTOR, sel).click()
                        time.sleep(3); break
                    except Exception:
                        continue

                # Case Status
                try:
                    el = wait_click(driver, By.XPATH,
                        "//*[contains(.,'Case Status')]", t=8)
                    safe_click(driver, el); time.sleep(2)
                except Exception:
                    pass

                click_party_tab(driver)
                time.sleep(1)
                if not fill_form(driver, person_name, year):
                    log("    ✗ Could not fill form — retrying year")
                    time.sleep(2)
                    continue

            except Exception as e:
                log(f"  ✗ Setup error: {e} — retrying year")
                time.sleep(2)
                continue

            # CAPTCHA
            result = None
            try:
                for attempt in range(1, 6):
                    log(f"\n  [CAPTCHA try {attempt}/5 for year {year}]")
                    result = do_captcha_and_go(driver)
                    if result != "bad_captcha":
                        break
            except Exception as e:
                log(f"  ✗ Captcha/Network error for year {year}: {e}")
                result = "error"

            if result == "no_records":
                log(f"  ℹ  No records for {year}")
                year_success = True
                break
            elif result != "found":
                log(f"  ⚠  Inconclusive result for year {year} (result={result}) — retrying year")
                time.sleep(2)
                continue

            log(f"  ✓ CASES FOUND for year {year}!")
            found_any = True
            year_success = True

            btn_xpath = "//input[@value='View']|//a[normalize-space(text())='View']"
            view_btns = driver.find_elements(By.XPATH, btn_xpath)
            num_btns  = len(view_btns)
            for idx in range(num_btns):
                case_label = f"{safe_name(person_name)}_{year}_case{idx+1}"
                log(f"\n  → Case {idx+1}: clicking View")
                try:
                    current_btns = driver.find_elements(By.XPATH, btn_xpath)
                    if idx >= len(current_btns):
                        break
                    btn = current_btns[idx]
                    safe_click(driver, btn); time.sleep(3)
                    dl = handle_view_page(driver, save_dir, case_label)
                    log(f"    Downloaded {dl} file(s)")
                except Exception as e:
                    log(f"    ✗ View error: {e}")
            break

        if not year_success:
            log(f"  ✗ Year {year} failed after {MAX_YEAR_RETRIES} attempts — skipping to next year")

    if not found_any:
        log(f"  ℹ  No cases found for '{person_name}' at Telangana/Rangareddy")
    return found_any

# ─────────────────────────────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────────────────────────────

def main():
    print("="*70)
    print("  eCourts Case Search Automation")
    print(f"  Downloads → {DOWNLOAD_DIR.resolve()}")
    print("  You will be asked to type each CAPTCHA in this window.")
    print("="*70 + "\n")

    DOWNLOAD_DIR.mkdir(exist_ok=True)

    driver = make_driver()
    summary = []

    try:
        # ── ENTITY SEARCHES: Delhi, Rajasthan(Jaipur), Karnataka ──
        print("\n" + "★"*70)
        print("  ENTITY SEARCHES")
        print("★"*70)
        for entity in ENTITIES:
            for (label, court_p, bench_p) in ENTITY_COURTS:
                found = search_hc(driver, entity, label, court_p, bench_p)
                summary.append(("Entity", entity, label, found))

        # ── SUMMARY ──
        print("\n" + "="*70)
        print("  ENTITIES SEARCH FINAL SUMMARY")
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
