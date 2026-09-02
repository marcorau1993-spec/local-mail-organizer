"""Background coordinator for complete, resumable, read-only mailbox scans."""

from __future__ import annotations

import imaplib
import threading
from collections.abc import Iterator, Sequence

from .config import Settings
from .credentials import CredentialStore
from .imap_client import ReadOnlyImapClient
from .providers import get_provider
from .storage import ScanStore


def _chunks(values: Sequence[str], size: int) -> Iterator[Sequence[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class FullScanManager:
    """Own worker threads while SQLite remains the durable source of truth."""

    def __init__(self, settings: Settings, store: ScanStore, credentials: CredentialStore) -> None:
        self._settings = settings
        self._store = store
        self._credentials = credentials
        self._pause_flags: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def start(self, account_id: str, provider: str) -> str:
        job_id = self._store.create_job(account_id, provider)
        self._launch(job_id, account_id, provider)
        return job_id

    def pause(self, job_id: str) -> None:
        with self._lock:
            flag = self._pause_flags.get(job_id)
        if flag is not None:
            flag.set()
        self._store.set_status(job_id, "pausing")

    def resume(self, job_id: str) -> None:
        job = self._store.job(job_id)
        if job is None:
            raise LookupError("Scan job does not exist")
        with self._lock:
            thread = self._threads.get(job_id)
            if thread is not None and thread.is_alive():
                raise RuntimeError("Scan job is already running")
        self._launch(job_id, job.account_id, job.provider)

    def _launch(self, job_id: str, account_id: str, provider: str) -> None:
        pause_flag = threading.Event()
        thread = threading.Thread(
            target=self._run,
            args=(job_id, account_id, provider, pause_flag),
            daemon=True,
            name=f"mail-scan-{job_id[:8]}",
        )
        with self._lock:
            self._pause_flags[job_id] = pause_flag
            self._threads[job_id] = thread
        thread.start()

    def _run(
        self, job_id: str, account_id: str, provider_key: str, pause_flag: threading.Event
    ) -> None:
        self._store.set_status(job_id, "connecting")
        try:
            username = self._credentials.get_username(account_id)
            password = self._credentials.get_password(account_id)
            provider = get_provider(provider_key)
            with ReadOnlyImapClient(provider) as client:
                client.authenticate(username, password)
                folders = client.list_folders()
                self._store.prepare_folders(job_id, folders)
                completed = self._store.completed_folders(job_id)
                for folder, _ in folders:
                    if folder in completed:
                        continue
                    self._store.set_status(job_id, "inventory", folder=folder)
                    all_uids = client.message_uids(folder)
                    stored = self._store.stored_uids(job_id, folder)
                    remaining = [uid for uid in all_uids if uid not in stored]
                    for batch in _chunks(remaining, self._settings.full_scan_batch_size):
                        if pause_flag.is_set():
                            self._store.set_status(job_id, "paused", folder=folder)
                            return
                        messages = client.fetch_messages_by_uids(folder, batch)
                        self._store.store_batch(
                            job_id, folder, messages, self._settings.large_message_bytes
                        )
                    self._store.complete_folder(job_id, folder)
            self._store.set_status(job_id, "completed")
        except (
            imaplib.IMAP4.error,
            OSError,
            LookupError,
            RuntimeError,
            ConnectionError,
            ValueError,
        ) as exc:
            self._store.set_status(job_id, "failed", error=_safe_scan_error(exc))


def _safe_scan_error(exc: Exception) -> str:
    if isinstance(exc, LookupError):
        return "Saved account credentials are incomplete. Reconnect the account in Setup"
    if isinstance(exc, imaplib.IMAP4.error):
        detail = str(exc).casefold()
        if "authentication" in detail or "login" in detail:
            return "WEB.DE rejected the login. Reconnect the account in Setup"
        return "WEB.DE rejected an IMAP folder command. Update the app or retry the scan"
    if isinstance(exc, (OSError, ConnectionError)):
        return "WEB.DE could not be reached. Check the internet connection and retry"
    return "The read-only scan stopped safely. Retry or reconnect the account in Setup"
