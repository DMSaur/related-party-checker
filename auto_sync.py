#!/usr/bin/env python3
"""
Auto-sync script for related-party-checker project
Watches for file changes and automatically commits/pushes to GitHub
"""

import subprocess
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.absolute()


def run_git(*args):
    """Run a git command in the project directory."""
    result = subprocess.run(
        ["git"] + list(args),
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    return result.returncode, result.stdout, result.stderr


def sync():
    """Check for changes and sync to GitHub."""
    # Fetch latest
    run_git("fetch", "origin")

    # Check for local changes
    rc, stdout, _ = run_git("status", "--porcelain")
    if stdout.strip():
        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Changes detected, committing...")
        run_git("add", "-A")
        run_git(
            "commit", "-m", f"Auto-sync: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\nCo-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
        )
        run_git("pull", "--rebase", "origin", "main")
        rc, _, stderr = run_git("push", "origin", "main")
        if rc == 0:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Synced to GitHub")
        else:
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Push failed: {stderr}")
    else:
        # Check for remote changes
        rc, stdout, _ = run_git("log", "HEAD..origin/main", "--oneline")
        if stdout.strip():
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Remote changes detected, pulling...")
            run_git("pull", "origin", "main")
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Pulled latest changes")


def main():
    print(f"Auto-sync started for {PROJECT_DIR}")
    print("Watching for changes every 30 seconds...")
    print("Press Ctrl+C to stop\n")

    while True:
        try:
            sync()
            time.sleep(30)
        except KeyboardInterrupt:
            print("\nAuto-sync stopped")
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()