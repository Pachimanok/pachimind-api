import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer

from app.core.vault_index import vault_index

logger = logging.getLogger(__name__)


def _auto_link_file(path_str: str, processing: set, lock: threading.Lock) -> None:
    """Runs the structural linker for a single note after a short debounce."""
    def _run():
        try:
            from app.core.vault_linker import generate_links_for_note, EXCLUDED_PREFIXES
            from app.core.id_utils import path_to_id
            from app.config import settings

            path = Path(path_str)
            vault_root = Path(settings.vault_path)
            try:
                rel = str(path.relative_to(vault_root))
            except ValueError:
                return
            if any(rel.startswith(p) for p in EXCLUDED_PREFIXES):
                return
            note = vault_index.get(path_to_id(rel))
            if note:
                result = generate_links_for_note(vault_index, vault_root, note, dry_run=False)
                if result and result.changes:
                    logger.info(f"Auto-linked {len(result.changes)} changes: {note.path}")
        except Exception as e:
            logger.warning(f"Auto-link failed for {path_str}: {e}")
        finally:
            with lock:
                processing.discard(path_str)

    t = threading.Timer(1.0, _run)
    t.daemon = True
    t.start()


class VaultEventHandler(FileSystemEventHandler):
    def __init__(self):
        super().__init__()
        self._processing: set[str] = set()
        self._lock = threading.Lock()

    def _schedule_link(self, path_str: str) -> None:
        with self._lock:
            if path_str in self._processing:
                return
            self._processing.add(path_str)
        _auto_link_file(path_str, self._processing, self._lock)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            vault_index.rebuild_file(Path(event.src_path))
            self._schedule_link(str(event.src_path))
            logger.debug(f"Nota actualizada: {event.src_path}")

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            vault_index.rebuild_file(Path(event.src_path))
            self._schedule_link(str(event.src_path))
            logger.debug(f"Nota creada: {event.src_path}")

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and str(event.src_path).endswith(".md"):
            vault_index.remove_file(Path(event.src_path))
            logger.debug(f"Nota eliminada: {event.src_path}")

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            if str(event.src_path).endswith(".md"):
                vault_index.remove_file(Path(event.src_path))
            if str(event.dest_path).endswith(".md"):
                vault_index.rebuild_file(Path(event.dest_path))
                self._schedule_link(str(event.dest_path))


def start_watcher(vault_path: str) -> Observer:
    observer = Observer()
    observer.schedule(VaultEventHandler(), vault_path, recursive=True)
    observer.start()
    logger.info(f"Watcher activo sobre: {vault_path}")
    return observer
