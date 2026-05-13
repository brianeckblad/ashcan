"""
Sync state management for backup synchronization.
Tracks the progress and status of S3 to local backup sync.

Cross-worker safety: a ``fcntl`` file lock (LOCK_EX | LOCK_NB) on
``instance/.sync.lock`` provides mutual exclusion across gunicorn workers
(and across processes in general). The in-process ``threading.Lock``
continues to protect state fields within a single worker.
"""
import errno
import fcntl
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict


def _resolve_lock_path() -> Path:
    """Return the path to the cross-worker sync lock file.

    Prefers the Flask ``instance`` directory when available; otherwise
    falls back to the project root's ``instance`` subdirectory.
    """
    try:
        from flask import current_app  # local import to avoid hard dependency at import time
        base = Path(current_app.instance_path)
    except Exception:
        base = Path(__file__).resolve().parent.parent.parent / 'instance'
    base.mkdir(parents=True, exist_ok=True)
    return base / '.sync.lock'


class SyncState:
    """Process-local singleton for tracking backup sync state."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Implement singleton pattern for SyncState."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize the sync state."""
        self._state_lock = threading.Lock()
        self.status = 'not_started'  # not_started, in_progress, synchronized, failed
        self.total_backups = 0
        self.completed_backups = 0
        self.current_backup = None
        self.error_message = None
        self.started_at = None
        self.completed_at = None
        self.is_app_locked = False  # Lock app operations during sync
        self.retry_count = 0  # Current retry attempt
        self.max_retries = 3  # Maximum retry attempts per backup
        # Cross-worker file lock (held for the duration of an active sync)
        self._cross_worker_fd = None

    def start_sync(self, total_backups: int):
        """Mark sync as started."""
        with self._state_lock:
            self.status = 'in_progress'
            self.total_backups = total_backups
            self.completed_backups = 0
            self.current_backup = None
            self.error_message = None
            self.started_at = datetime.now(timezone.utc)
            self.completed_at = None
            self.is_app_locked = True  # Lock app during sync
            self.retry_count = 0

    def update_progress(self, completed: int, current_backup: Optional[str] = None, retry_count: int = 0):
        """Update sync progress."""
        with self._state_lock:
            self.completed_backups = completed
            self.current_backup = current_backup
            self.retry_count = retry_count

    def complete_sync(self):
        """Mark sync as successfully completed."""
        with self._state_lock:
            self.status = 'synchronized'
            self.completed_at = datetime.now(timezone.utc)
            self.current_backup = None
            self.is_app_locked = False  # Unlock app
        self._release_cross_worker_lock()

    def fail_sync(self, error_message: str):
        """Mark sync as failed."""
        with self._state_lock:
            self.status = 'failed'
            self.error_message = error_message
            self.completed_at = datetime.now(timezone.utc)
            self.is_app_locked = False  # Unlock app even on failure
        self._release_cross_worker_lock()

    def get_state(self) -> Dict:
        """Get current sync state as dictionary."""
        with self._state_lock:
            return {
                'status': self.status,
                'total_backups': self.total_backups,
                'completed_backups': self.completed_backups,
                'current_backup': self.current_backup,
                'error_message': self.error_message,
                'started_at': self.started_at.isoformat() if self.started_at else None,
                'completed_at': self.completed_at.isoformat() if self.completed_at else None,
                'is_app_locked': self.is_app_locked,
                'progress_percent': int((self.completed_backups / self.total_backups * 100)) if self.total_backups > 0 else 0,
                'retry_count': self.retry_count,
                'max_retries': self.max_retries
            }

    def is_locked(self) -> bool:
        """Check if app operations should be locked."""
        with self._state_lock:
            return self.is_app_locked

    def lock_sync(self) -> bool:
        """Acquire the cross-worker sync lock.

        Returns True if this worker now holds the exclusive lock and may
        proceed with the sync; False if another worker/process already
        holds it (the caller must skip its sync run).
        """
        try:
            lock_path = _resolve_lock_path()
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                os.close(fd)
                if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    return False  # another worker is syncing
                raise
            with self._state_lock:
                self._cross_worker_fd = fd
                self.is_app_locked = True
            return True
        except Exception:
            # On any unexpected failure, fall back to in-process only
            with self._state_lock:
                self.is_app_locked = True
            return True

    def unlock_sync(self):
        """Release the cross-worker sync lock."""
        with self._state_lock:
            self.is_app_locked = False
        self._release_cross_worker_lock()

    def _release_cross_worker_lock(self):
        """Release the fcntl lock if we hold it (no-op otherwise)."""
        fd = None
        with self._state_lock:
            fd = self._cross_worker_fd
            self._cross_worker_fd = None
        if fd is not None:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                try:
                    os.close(fd)
                except OSError:
                    pass


# Singleton instance
sync_state = SyncState()


