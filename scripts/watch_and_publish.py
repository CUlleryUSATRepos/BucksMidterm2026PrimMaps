from pathlib import Path
import csv
import subprocess
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
INTERVAL_SECONDS = 5 * 60

CHANGE_LOG = ROOT / "output" / "processed" / "download_change_log.csv"
SOUND_FILE = ROOT / "sadtrombone.swf.mp3"
SOUND_SCRIPT = ROOT / "scripts" / "play_sound.ps1"


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


def latest_download_status():
    if not CHANGE_LOG.exists():
        return None

    with CHANGE_LOG.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        return None

    return rows[-1]


def play_update_sound():
    if not SOUND_FILE.exists():
        print("Sound file not found:", SOUND_FILE)
        return

    if not SOUND_SCRIPT.exists():
        print("Sound script not found:", SOUND_SCRIPT)
        return

    print("Playing update sound:", SOUND_FILE)

    subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SOUND_SCRIPT),
            "-SoundPath",
            str(SOUND_FILE),
        ],
        cwd=ROOT,
        check=False,
    )


def maybe_play_update_sound():
    last = latest_download_status()

    if not last:
        print("No download-change log row found.")
        return

    status = str(last.get("status", "")).lower()
    delta = str(last.get("delta_total_votes", "0"))

    if status in {"changed", "first_file"}:
        print(f"New results detected. Status={status}, delta_total_votes={delta}")
        play_update_sound()
    else:
        print(f"No new vote changes detected. Status={status}, delta_total_votes={delta}")


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

    # Play sound only if the downloaded file actually changed.
    maybe_play_update_sound()

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
