from pathlib import Path
import shutil
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


ROOT = Path(__file__).resolve().parents[1]

RESULTS_URL = "https://www.livevoterturnout.com/ENR/buckspaenr/23/en/UYzJe_Index_23.html"

DOWNLOAD_DIR = ROOT / "downloads"
LIVE_RESULTS_FILE = ROOT / "Precincts_19.csv"

LOG_DIR = ROOT / "output" / "processed"
LOG_FILE = LOG_DIR / "download_change_log.csv"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)


def now_text():
    now = datetime.now(ZoneInfo("America/New_York"))
    return f"{now.strftime('%Y-%m-%d %I:%M:%S %p').lstrip('0')}"


def newest_csv_before():
    return set(DOWNLOAD_DIR.glob("*.csv"))


def wait_for_new_csv(before, timeout=60):
    start = time.time()

    while time.time() - start < timeout:
        active_downloads = list(DOWNLOAD_DIR.glob("*.crdownload"))
        csvs = set(DOWNLOAD_DIR.glob("*.csv"))
        new_csvs = list(csvs - before)

        if new_csvs and not active_downloads:
            return max(new_csvs, key=lambda p: p.stat().st_mtime)

        time.sleep(0.5)

    raise TimeoutError("Timed out waiting for precinct CSV download.")


def run(cmd):
    print("\nRunning:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode != 0:
        sys.exit(result.returncode)


def load_results_for_compare(path):
    df = pd.read_csv(path, skiprows=2)

    required = ["Precinct", "Contest Name", "Candidate Name", "Votes"]
    missing = [c for c in required if c not in df.columns]

    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")

    out = df[required].copy()

    out["Votes"] = (
        out["Votes"]
        .astype(str)
        .str.replace(",", "", regex=False)
        .str.strip()
    )

    out["Votes"] = pd.to_numeric(out["Votes"], errors="coerce").fillna(0).astype(int)

    # One row per precinct/contest/candidate.
    out = (
        out.groupby(["Precinct", "Contest Name", "Candidate Name"], as_index=False)
        .agg(Votes=("Votes", "sum"))
    )

    return out


def compare_results(old_path, new_path):
    checked_at = now_text()

    if not old_path.exists():
        msg = {
            "checked_at": checked_at,
            "status": "first_file",
            "old_total_votes": 0,
            "new_total_votes": 0,
            "delta_total_votes": 0,
            "changed_rows": 0,
            "changed_precincts": 0,
            "changed_contests": 0,
            "downloaded_file": str(new_path),
        }

        print("\nNo existing Precincts_19.csv found. Treating this as the first file.")
        append_log(msg)
        return msg

    old = load_results_for_compare(old_path)
    new = load_results_for_compare(new_path)

    key_cols = ["Precinct", "Contest Name", "Candidate Name"]

    old_total = int(old["Votes"].sum())
    new_total = int(new["Votes"].sum())

    merged = old.merge(
        new,
        on=key_cols,
        how="outer",
        suffixes=("_old", "_new")
    )

    merged["Votes_old"] = merged["Votes_old"].fillna(0).astype(int)
    merged["Votes_new"] = merged["Votes_new"].fillna(0).astype(int)
    merged["delta_votes"] = merged["Votes_new"] - merged["Votes_old"]

    changed = merged.loc[merged["delta_votes"].ne(0)].copy()

    status = "changed" if len(changed) else "no_change"

    msg = {
        "checked_at": checked_at,
        "status": status,
        "old_total_votes": old_total,
        "new_total_votes": new_total,
        "delta_total_votes": new_total - old_total,
        "changed_rows": int(len(changed)),
        "changed_precincts": int(changed["Precinct"].nunique()) if len(changed) else 0,
        "changed_contests": int(changed["Contest Name"].nunique()) if len(changed) else 0,
        "downloaded_file": str(new_path),
    }

    print("\n" + "-" * 70)
    print("DOWNLOAD COMPARISON")
    print("-" * 70)
    print("Checked at:", checked_at)
    print("Status:", status.upper())
    print(f"Total votes: {old_total:,} -> {new_total:,} ({new_total - old_total:+,})")
    print("Changed precinct/contest/candidate rows:", f"{len(changed):,}")
    print("Precincts with changes:", msg["changed_precincts"])
    print("Contests with changes:", msg["changed_contests"])

    if len(changed):
        contest_changes = (
            changed.groupby("Contest Name", as_index=False)
            .agg(delta_votes=("delta_votes", "sum"))
        )
        contest_changes["abs_delta"] = contest_changes["delta_votes"].abs()
        contest_changes = contest_changes.sort_values("abs_delta", ascending=False).head(12)

        candidate_changes = (
            changed.groupby(["Contest Name", "Candidate Name"], as_index=False)
            .agg(delta_votes=("delta_votes", "sum"))
        )
        candidate_changes["abs_delta"] = candidate_changes["delta_votes"].abs()
        candidate_changes = candidate_changes.sort_values("abs_delta", ascending=False).head(12)

        precinct_changes = (
            changed.groupby("Precinct", as_index=False)
            .agg(delta_votes=("delta_votes", "sum"))
        )
        precinct_changes["abs_delta"] = precinct_changes["delta_votes"].abs()
        precinct_changes = precinct_changes.sort_values("abs_delta", ascending=False).head(12)

        print("\nTop contest changes:")
        for _, row in contest_changes.iterrows():
            print(f"  {row['Contest Name']}: {int(row['delta_votes']):+,}")

        print("\nTop candidate changes:")
        for _, row in candidate_changes.iterrows():
            print(f"  {row['Contest Name']} | {row['Candidate Name']}: {int(row['delta_votes']):+,}")

        print("\nTop precinct changes:")
        for _, row in precinct_changes.iterrows():
            print(f"  {row['Precinct']}: {int(row['delta_votes']):+,}")

    print("-" * 70)

    append_log(msg)
    return msg


def append_log(row):
    log_row = pd.DataFrame([row])

    if LOG_FILE.exists():
        old_log = pd.read_csv(LOG_FILE)
        out = pd.concat([old_log, log_row], ignore_index=True)
    else:
        out = log_row

    out.to_csv(LOG_FILE, index=False)


def download_precinct_csv():
    print("Opening results page...")
    print(RESULTS_URL)

    before = newest_csv_before()

    chrome_options = Options()
    chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1600,1200")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")

    prefs = {
        "download.default_directory": str(DOWNLOAD_DIR),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "safebrowsing.enabled": True,
    }

    chrome_options.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(options=chrome_options)

    try:
        driver.get(RESULTS_URL)

        wait = WebDriverWait(driver, 30)

        print("Opening Reports tab...")
        reports_tab = wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//a[contains(@class, 'custom-tab') and normalize-space()='Reports']")
            )
        )

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", reports_tab)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", reports_tab)

        print("Clicking precinct CSV download button...")
        btn = wait.until(
            EC.presence_of_element_located((By.ID, "btnPrecinctCsv"))
        )

        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", btn)
        time.sleep(0.5)
        driver.execute_script("arguments[0].click();", btn)

        downloaded = wait_for_new_csv(before, timeout=90)

    finally:
        driver.quit()

    return downloaded


def main():
    downloaded = download_precinct_csv()

    print("Downloaded:", downloaded)

    compare_results(LIVE_RESULTS_FILE, downloaded)

    shutil.copy2(downloaded, LIVE_RESULTS_FILE)
    print("Copied to:", LIVE_RESULTS_FILE)

    run([sys.executable, "scripts/build_site.py"])

    print("\nDone.")
    print("Change log:", LOG_FILE)
    print("Review locally:")
    print(ROOT / "output" / "primary_results_dashboard.html")


if __name__ == "__main__":
    main()
