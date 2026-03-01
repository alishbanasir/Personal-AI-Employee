"""
Basic Orchestrator — coordinates the AI Employee components.

Responsibilities:
- Starts and monitors the File System Watcher
- Scans /Needs_Action for items requiring Claude processing
- Watches /Approved folder for HITL-approved actions
- Updates Dashboard.md with current system stats

Usage:
    python src/orchestrator.py --vault /path/to/AI_Employee_Vault
    python src/orchestrator.py --vault /path/to/AI_Employee_Vault --dry-run
"""
import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Orchestrator] %(levelname)s: %(message)s",
)
logger = logging.getLogger("Orchestrator")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


class Orchestrator:
    def __init__(self, vault_path: str, dry_run: bool = False):
        self.vault = Path(vault_path).resolve()
        self.dry_run = dry_run or DRY_RUN
        self.watcher_process = None
        self.gmail_process = None
        self.twitter_process = None

        # Folder references
        self.inbox = self.vault / "Inbox"
        self.needs_action = self.vault / "Needs_Action"
        self.plans = self.vault / "Plans"
        self.done = self.vault / "Done"
        self.pending_approval = self.vault / "Pending_Approval"
        self.approved = self.vault / "Approved"
        self.rejected = self.vault / "Rejected"
        self.logs_dir = self.vault / "Logs"

        # Ensure all folders exist
        for folder in [
            self.inbox, self.needs_action, self.plans, self.done,
            self.pending_approval, self.approved, self.rejected, self.logs_dir,
        ]:
            folder.mkdir(parents=True, exist_ok=True)

    def start_file_watcher(self):
        """Launch filesystem_watcher.py as a subprocess."""
        script = Path(__file__).parent / "filesystem_watcher.py"
        cmd = [sys.executable, str(script), "--vault", str(self.vault)]
        if self.dry_run:
            cmd.append("--dry-run")

        logger.info(f"Starting file watcher: {' '.join(cmd)}")
        if not self.dry_run:
            self.watcher_process = subprocess.Popen(cmd)
            logger.info(f"File watcher PID: {self.watcher_process.pid}")
        else:
            logger.info("[DRY RUN] Would start file watcher subprocess")

    def start_gmail_watcher(self):
        """Launch gmail_watcher.py as a subprocess (only if credentials exist)."""
        creds_path = os.getenv("GMAIL_CREDENTIALS_PATH", "gmail_credentials.json")
        if not Path(creds_path).exists():
            logger.info("Gmail credentials not found — skipping Gmail Watcher.")
            return

        script = Path(__file__).parent / "gmail_watcher.py"
        cmd = [sys.executable, str(script), "--vault", str(self.vault)]
        if self.dry_run:
            cmd.append("--dry-run")

        logger.info(f"Starting Gmail watcher: {' '.join(cmd)}")
        if not self.dry_run:
            self.gmail_process = subprocess.Popen(cmd)
            logger.info(f"Gmail watcher PID: {self.gmail_process.pid}")
        else:
            logger.info("[DRY RUN] Would start Gmail watcher subprocess")

    def start_twitter_poster(self):
        """Launch twitter_poster.py as a subprocess (only if API keys are set)."""
        if not os.getenv("TWITTER_API_KEY"):
            logger.info("TWITTER_API_KEY not set — skipping Twitter Poster.")
            return

        script = Path(__file__).parent / "twitter_poster.py"
        cmd = [sys.executable, str(script), "--vault", str(self.vault), "--watch"]
        if self.dry_run:
            cmd.append("--dry-run")

        logger.info(f"Starting Twitter poster: {' '.join(cmd)}")
        if not self.dry_run:
            self.twitter_process = subprocess.Popen(cmd)
            logger.info(f"Twitter poster PID: {self.twitter_process.pid}")
        else:
            logger.info("[DRY RUN] Would start Twitter poster subprocess")

    def check_watcher_health(self):
        """Restart watchers if they have crashed."""
        if self.watcher_process and self.watcher_process.poll() is not None:
            logger.warning("File watcher has stopped. Restarting...")
            self.start_file_watcher()
        if self.gmail_process and self.gmail_process.poll() is not None:
            logger.warning("Gmail watcher has stopped. Restarting...")
            self.start_gmail_watcher()
        if self.twitter_process and self.twitter_process.poll() is not None:
            logger.warning("Twitter poster has stopped. Restarting...")
            self.start_twitter_poster()

    def get_pending_items(self) -> list[Path]:
        """Return all .md files in /Needs_Action (excluding .gitkeep)."""
        return [
            f for f in self.needs_action.glob("*.md")
            if f.name != ".gitkeep"
        ]

    def get_approved_items(self) -> list[Path]:
        """Return all .md files in /Approved waiting for execution."""
        return [
            f for f in self.approved.glob("*.md")
            if f.name != ".gitkeep"
        ]

    def update_dashboard_stats(self):
        """Refresh the quick stats block in Dashboard.md."""
        dashboard = self.vault / "Dashboard.md"
        if not dashboard.exists():
            return

        inbox_count = len([f for f in self.inbox.iterdir() if f.name not in {".gitkeep", ".DS_Store"}])
        needs_action_count = len(self.get_pending_items())
        pending_approval_count = len([f for f in self.pending_approval.glob("*.md") if f.name != ".gitkeep"])

        done_today = len([
            f for f in self.done.glob("*.md")
            if f.name != ".gitkeep" and
               datetime.fromtimestamp(f.stat().st_mtime).date() == datetime.now().date()
        ])

        text = dashboard.read_text(encoding="utf-8")

        # Replace stats block
        import re
        stats_pattern = r"(- \*\*Inbox items:\*\* )\d+(.*\n- \*\*Needs Action:\*\* )\d+(.*\n- \*\*Done today:\*\* )\d+(.*\n- \*\*Pending approval:\*\* )\d+"
        replacement = (
            f"- **Inbox items:** {inbox_count}"
            f"\n- **Needs Action:** {needs_action_count}"
            f"\n- **Done today:** {done_today}"
            f"\n- **Pending approval:** {pending_approval_count}"
        )
        new_text = re.sub(stats_pattern, replacement, text)
        if new_text != text:
            dashboard.write_text(new_text, encoding="utf-8")
            logger.info("Dashboard stats updated")

    def log_action(self, action_type: str, details: dict):
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "actor": "orchestrator",
            "action_type": action_type,
            **details,
        }
        existing = []
        if log_file.exists():
            try:
                existing = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        existing.append(entry)
        log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def run(self, scan_interval: int = 30):
        logger.info(f"Orchestrator starting. Vault: {self.vault}")
        logger.info(f"Dry run: {self.dry_run}")

        self.start_file_watcher()
        self.start_gmail_watcher()
        self.start_twitter_poster()
        self.log_action("orchestrator_start", {"vault": str(self.vault)})

        logger.info(f"Scanning every {scan_interval}s. Press Ctrl+C to stop.")

        try:
            while True:
                self.check_watcher_health()

                pending = self.get_pending_items()
                approved = self.get_approved_items()

                if pending:
                    logger.info(f"{len(pending)} item(s) in /Needs_Action waiting for Claude processing.")
                    for item in pending:
                        logger.info(f"  → {item.name}")

                if approved:
                    logger.info(f"{len(approved)} item(s) in /Approved waiting for execution.")
                    for item in approved:
                        logger.info(f"  → {item.name} (requires MCP action — Silver/Gold tier)")

                self.update_dashboard_stats()
                time.sleep(scan_interval)

        except KeyboardInterrupt:
            logger.info("Shutting down orchestrator...")
            if self.watcher_process:
                self.watcher_process.terminate()
                self.watcher_process.wait()
            if self.gmail_process:
                self.gmail_process.terminate()
                self.gmail_process.wait()
            if self.twitter_process:
                self.twitter_process.terminate()
                self.twitter_process.wait()
            self.log_action("orchestrator_stop", {})
            logger.info("Orchestrator stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="AI Employee Orchestrator — coordinates all components"
    )
    parser.add_argument(
        "--vault",
        required=True,
        help="Absolute path to AI_Employee_Vault directory",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Safe testing mode — no external actions taken",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Scan interval in seconds (default: 30)",
    )
    args = parser.parse_args()

    orchestrator = Orchestrator(args.vault, dry_run=args.dry_run)
    orchestrator.run(scan_interval=args.interval)


if __name__ == "__main__":
    main()
