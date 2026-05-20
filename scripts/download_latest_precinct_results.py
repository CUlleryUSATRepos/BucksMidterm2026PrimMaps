from pathlib import Path
import shutil
import subprocess
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


ROOT = Path(__file__).resolve().parents[1]

RESULTS_URL = "https://www.livevoterturnout.com/ENR/buckspaenr/23/en/UYzJe_Index_23.html"

DOWNLOAD_DIR = ROOT / "downloads"
LIVE_RESULTS_FILE = ROOT / "Precincts_19.csv"

DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


def newest_csv_before():
    return set(DOWNLOAD_DIR.glob("*.csv"))


def wait_for_new_csv(before, timeout=60):
    start = time.time()

    while time.time() - start < timeout:
        # Chrome uses .crdownload while a download is still active.
        active_downloads = list(DOWNLOAD_DIR.glob("*.crdownload"))

        csvs = set(DOWNLOAD_DIR.glob("*.csv"))
        new_csvs = list(csvs - before)

        if new_csvs and not active_downloads:
            return max(new_csvs, key=lambda p: p.stat().st_mtime)

        time.sleep(0.5)

    raise TimeoutError("Timed out waiting for precinct CSV download.")


def run(cmd):
    print("\nRunning:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)

    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
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

    print("Downloaded:", downloaded)

    shutil.copy2(downloaded, LIVE_RESULTS_FILE)
    print("Copied to:", LIVE_RESULTS_FILE)

    run([sys.executable, "scripts/build_site.py"])

    print("\nDone.")
    print("Review locally:")
    print(ROOT / "output" / "primary_results_dashboard.html")


if __name__ == "__main__":
    main()
