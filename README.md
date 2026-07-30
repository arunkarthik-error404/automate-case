# eCourts Case Search Automation

Automates case status searches on [hcservices.ecourts.gov.in](https://hcservices.ecourts.gov.in/hcservices/main.php)
and (for Telangana/Rangareddy) on [districts.ecourts.gov.in](https://districts.ecourts.gov.in/india.php).

---

## What it does

| Phase | Search type | Courts searched |
|-------|-------------|-----------------|
| 1 | **Entities** | High Court of Delhi (Principal Bench) |
| 1 | **Entities** | High Court of Rajasthan (Jaipur Bench) |
| 1 | **Entities** | High Court of Karnataka (Bengaluru) |
| 2 | **Persons** | High Court of Karnataka (Bengaluru) |
| 2 | **Persons** | Telangana District Court – Rangareddy |

For each (name × court) combination it:
1. Tries years **2026 → 2025 → … → 2017** (10 years max)
2. Selects **"Both"** (Pending + Disposed)
3. Prompts you to **type the CAPTCHA** in the terminal window
4. If cases are found → clicks **View** → downloads all **Order PDFs**
5. Logs everything to `downloads/log.txt`

---

- Space World Data Centre Private Limited
- Space World Group LLP
- G.V.R. Electro Technics Private Limited
- Sada IT Parks Private Limited
- Tulip Data Centre Services Private Limited
- Tulip Data Centre Private Limited

## Automation Scripts

### 1. eCourts High Court Automation
```powershell
d:\automate-case\venv\Scripts\python.exe ecourts_automation.py
```
And parallel worker for Persons (Karnataka & Telangana High Courts):
```powershell
d:\automate-case\venv\Scripts\python.exe ecourts_persons.py
```

### 2. NCLT Party Name Wise Automation
- **Target Site**: [https://nclt.gov.in/party-name-wise](https://nclt.gov.in/party-name-wise)
- **Targets**: 6 Company Entities across **New Delhi**, **Jaipur**, and **Karnataka (Bengaluru)** Zonal Benches
- **Years**: 2017 to 2026 (10 years)
- **Features**: Auto-solves plain text CAPTCHA, saves order documents, clicks Back to reset form state for next year.

#### Running Companies in Parallel (Faster):
You can run all 6 company searches simultaneously in parallel:
```powershell
d:\automate-case\venv\Scripts\python.exe run_all_nclt_parallel.py
```
Or run specific companies individually in separate terminal windows:
```powershell
d:\automate-case\venv\Scripts\python.exe nclt_1_spaceworld_group.py
d:\automate-case\venv\Scripts\python.exe nclt_2_spaceworld_datacentre.py
d:\automate-case\venv\Scripts\python.exe nclt_3_gvr_electrotechnics.py
d:\automate-case\venv\Scripts\python.exe nclt_4_sada_it_parks.py
d:\automate-case\venv\Scripts\python.exe nclt_5_tulip_services.py
d:\automate-case\venv\Scripts\python.exe nclt_6_tulip_datacentre.py
```

#### Running Sequentially or via CLI:
```powershell
d:\automate-case\venv\Scripts\python.exe nclt_automation.py --company-index 1
d:\automate-case\venv\Scripts\python.exe nclt_automation.py --all
```

### 3. eCourts District Courts Automation (ecourtindia_v6)
- **Target Site**: [https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index](https://services.ecourts.gov.in/ecourtindia_v6/?p=casestatus/index)
- **Target Locations**:
  - **Karnataka** -> **Bengaluru**
  - **Telangana** -> **Ranga Reddy**
- **Traversal**: State -> District -> Court Complex -> Court Establishment
- **Years**: 2020 to 2026 (7 years)
- **Targets**: 6 Persons

#### Running District Person Searches in Parallel (Fastest):
```powershell
d:\automate-case\venv\Scripts\python.exe run_all_district_persons_parallel.py
```

#### Running Individual District Person Scripts:
```powershell
d:\automate-case\venv\Scripts\python.exe ecourts_dist_person_1_janardhan_reddy.py
d:\automate-case\venv\Scripts\python.exe ecourts_dist_person_2_laxmi_reddy.py
d:\automate-case\venv\Scripts\python.exe ecourts_dist_person_3_vidya_reddy.py
d:\automate-case\venv\Scripts\python.exe ecourts_dist_person_4_veera_prakash_reddy.py
d:\automate-case\venv\Scripts\python.exe ecourts_dist_person_5_veera_reddy.py
d:\automate-case\venv\Scripts\python.exe ecourts_dist_person_6_kanaka_durga.py
```

### Folder structure of downloads
```
downloads/
  Delhi/
    Space World Data Centre Private Limited/
      Space_World_Data_Centre..._2025_case1_order1.pdf
      ...
  Rajasthan_Jaipur/
    ...
  Karnataka/
    ...
  Karnataka_Bengaluru/
    G__Janardhan_Reddy/
      ...
  Telangana_Rangareddy/
    G__Janardhan_Reddy/
      ...
  log.txt          ← full search log
```

---

## Notes

- **CAPTCHA is manual** — the script pauses and waits for you. You have 5 attempts per year before it skips.
- If a search returns **"No records found"** for a year, it automatically moves to the previous year.
- PDFs that open in a new tab are captured and saved; if the file is not a true PDF (HTML page) it is saved as `.html`.
- The script does **not** close the browser between searches — you can watch progress live.

---

## Dependencies (pre-installed in venv)

```
selenium==4.46.0
webdriver-manager==4.1.2
requests==2.34.2
```
