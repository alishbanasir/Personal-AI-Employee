"""
File System Watcher — monitors the /Inbox drop folder.

Drop any file into AI_Employee_Vault/Inbox/ and this watcher will:
1. Detect the new file
2. Create a corresponding .md action item in /Needs_Action/
3. Update Dashboard.md with the new pending item

Usage:
    python src/filesystem_watcher.py --vault /path/to/AI_Employee_Vault
    python src/filesystem_watcher.py --vault /path/to/AI_Employee_Vault --dry-run
"""
import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [FileSystemWatcher] %(levelname)s: %(message)s",
)
logger = logging.getLogger("FileSystemWatcher")

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"


class DropFolderHandler(FileSystemEventHandler):
    """Handles file creation events in the /Inbox drop folder."""

    IGNORED_NAMES = {".gitkeep", ".DS_Store", "Thumbs.db"}

    def __init__(self, vault_path: Path, dry_run: bool = False):
        self.vault_path = vault_path
        self.inbox = vault_path / "Inbox"
        self.needs_action = vault_path / "Needs_Action"
        self.logs_dir = vault_path / "Logs"
        self.dry_run = dry_run or DRY_RUN

        self.needs_action.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def on_created(self, event):
        if event.is_directory:
            return
        source = Path(event.src_path)
        if source.name in self.IGNORED_NAMES or source.suffix == ".md":
            return

        logger.info(f"New file detected: {source.name}")
        self._process_file(source)

    def _process_file(self, source: Path):
        timestamp = datetime.now()
        ts_str = timestamp.strftime("%Y%m%d_%H%M%S")
        action_filename = f"FILE_{ts_str}_{source.stem}.md"
        action_path = self.needs_action / action_filename

        try:
            file_size = source.stat().st_size
        except FileNotFoundError:
            logger.warning(f"File disappeared before processing: {source}")
            return

        content = f"""---
type: file_drop
original_name: {source.name}
source_path: {source}
size_bytes: {file_size}
received: {timestamp.isoformat()}
priority: medium
status: pending
---

## File Dropped for Processing

**File:** `{source.name}`
**Size:** {file_size:,} bytes
**Received:** {timestamp.strftime('%Y-%m-%d %H:%M:%S')}

## Suggested Actions
- [ ] Review file contents
- [ ] Determine required action
- [ ] Process or archive

## Notes
_Claude: Add your analysis and action plan here._
"""

        if self.dry_run:
            logger.info(f"[DRY RUN] Would create: {action_path}")
            logger.info(f"[DRY RUN] Would NOT move file from inbox")
        else:
            action_path.write_text(content, encoding="utf-8")
            logger.info(f"Created action file: {action_filename}")
            self._log_action("file_detected", source.name, action_filename)
            self._update_dashboard(source.name, action_filename, timestamp)

    def _log_action(self, action_type: str, source_name: str, action_file: str):
        log_file = self.logs_dir / f"{datetime.now().strftime('%Y-%m-%d')}.json"
        entry = {
            "timestamp": datetime.now().isoformat(),
            "action_type": action_type,
            "actor": "filesystem_watcher",
            "source": source_name,
            "result_file": action_file,
            "result": "success",
        }
        existing = []
        if log_file.exists():
            try:
                existing = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                existing = []
        existing.append(entry)
        log_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    def _update_dashboard(self, source_name: str, action_file: str, timestamp: datetime):
        """Append a new activity entry to Dashboard.md."""
        dashboard = self.vault_path / "Dashboard.md"
        if not dashboard.exists():
            return

        text = dashboard.read_text(encoding="utf-8")
        new_row = f"| {timestamp.strftime('%Y-%m-%d %H:%M')} | File dropped: `{source_name}` → `{action_file}` | ⏳ Pending |"

        # Insert after the last table row in Recent Activity section
        marker = "| — | System initialized | ✅ |"
        if marker in text:
            text = text.replace(marker, f"{new_row}\n{marker}")
        else:
            # Append to Recent Activity section
            text += f"\n{new_row}\n"

        dashboard.write_text(text, encoding="utf-8")
        logger.info("Dashboard.md updated")


def run_watcher(vault_path: str, dry_run: bool = False):
    vault = Path(vault_path).resolve()
    inbox = vault / "Inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    logger.info(f"Vault: {vault}")
    logger.info(f"Watching: {inbox}")
    logger.info(f"Dry run: {dry_run or DRY_RUN}")

    handler = DropFolderHandler(vault, dry_run=dry_run)
    observer = Observer()
    observer.schedule(handler, str(inbox), recursive=False)
    observer.start()

    logger.info("File System Watcher started. Drop files into /Inbox to trigger actions.")
    logger.info("Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping watcher...")
        observer.stop()
    observer.join()
    logger.info("Watcher stopped.")


def main():
    parser = argparse.ArgumentParser(
        description="AI Employee File System Watcher — monitors /Inbox for new files"
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
        help="Log intended actions without creating files (safe testing mode)",
    )
    args = parser.parse_args()
    run_watcher(args.vault, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
