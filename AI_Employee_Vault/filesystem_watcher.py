import time
from pathlib import Path
import shutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class DropFolderHandler(FileSystemEventHandler):
    def __init__(self, vault_path):
        self.vault_path = Path(vault_path)
        self.needs_action = self.vault_path / 'Needs_Action'
        self.inbox = self.vault_path / 'Inbox'
        
        # Folders check karein
        self.needs_action.mkdir(exist_ok=True)
        self.inbox.mkdir(exist_ok=True)

    def on_created(self, event):
        if event.is_directory: return
        source = Path(event.src_path)
        
        # File ko Needs_Action mein copy karein [cite: 258, 259]
        dest = self.needs_action / f'FILE_{source.name}'
        shutil.copy2(source, dest)
        
        # Metadata file banayein taake Claude ko context mile [cite: 260, 261]
        meta_path = dest.with_suffix('.md')
        meta_path.write_text(f"---\ntype: file_drop\nstatus: pending\n---\nNew file '{source.name}' detected for processing.")
        print(f"Detected: {source.name} -> Moved to Needs_Action")

if __name__ == "__main__":
    vault = "." # Agar aap vault folder ke andar hain
    event_handler = DropFolderHandler(vault)
    observer = Observer()
    observer.schedule(event_handler, path="./Inbox", recursive=False)
    observer.start()
    print("Watcher is running... Drop a file in /Inbox to test.")
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt: observer.stop()
    observer.join()