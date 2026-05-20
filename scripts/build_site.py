from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

OUTPUT_HTML = ROOT / "output" / "primary_results_dashboard.html"
DOCS_DIR = ROOT / "docs"
DOCS_INDEX = DOCS_DIR / "index.html"


def run(cmd):
    print("\nRunning:", " ".join(cmd))
    result = subprocess.run(cmd, cwd=ROOT)
    if result.returncode != 0:
        sys.exit(result.returncode)


def main():
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    run([sys.executable, "scripts/build_processed_results.py"])
    run([sys.executable, "scripts/build_interactive_dashboard.py"])

    if not OUTPUT_HTML.exists():
        raise FileNotFoundError(f"Missing expected dashboard: {OUTPUT_HTML}")

    shutil.copy2(OUTPUT_HTML, DOCS_INDEX)

    print("\nCopied dashboard to:", DOCS_INDEX)
    print("Ready to commit docs/index.html")


if __name__ == "__main__":
    main()
