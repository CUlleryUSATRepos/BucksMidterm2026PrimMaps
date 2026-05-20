from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
INTERVAL_SECONDS = 5 * 60


def timestamp():
    now = datetime.now(ZoneInfo("America/New_York"))
    return f"{now.strftime('%Y-%m-%d %I:%M:%S %p').lstrip('0')}"


def run(cmd, check=True):
    print("\nRunning:", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT)

    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(cmd)}")

    return result.returncode


def has_git_changes():
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def commit_and_push():
    run(["git", "add", "Precincts_19.csv", "output/processed", "docs/index.html", "scripts"])

    if not has_git_changes():
        print("No git changes to commit.")
        return

    msg = f"Update primary results dashboard {timestamp()}"
    run(["git", "commit", "-m", msg])
    run(["git", "push"])


def one_cycle():
    print("\n" + "=" * 70)
    print("Checking for latest precinct results:", timestamp())
    print("=" * 70)

    # Downloads latest precinct CSV, copies it to Precincts_19.csv, and rebuilds docs/index.html.
    run([sys.executable, "scripts/download_latest_precinct_results.py"])

    # Commit/push whatever changed, including timestamp update.
    commit_and_push()

    print("Cycle complete:", timestamp())


def main():
    print("Starting election-night watcher.")
    print("Press Ctrl+C to stop.")
    print(f"Interval: {INTERVAL_SECONDS // 60} minutes")

    try:
        while True:
            try:
                one_cycle()
            except Exception as e:
                print("\nERROR during cycle:", e)
                print("Will try again after the next interval.")

            print(f"\nSleeping {INTERVAL_SECONDS // 60} minutes...")
            time.sleep(INTERVAL_SECONDS)

    except KeyboardInterrupt:
        print("\nStopped by user.")


if __name__ == "__main__":
    main()
