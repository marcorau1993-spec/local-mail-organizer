"""Resumable, private full-text indexing for local mailbox search."""

from __future__ import annotations

import hashlib
import imaplib
import re
import threading
from collections import defaultdict
from email import message_from_bytes
from email.message import Message
from html.parser import HTMLParser

from .config import Settings
from .credentials import CredentialStore
from .imap_client import ReadOnlyImapClient
from .intelligence import decoded
from .providers import get_provider
from .storage import ScanStore


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "svg"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._ignored:
            self._ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def _decoded_payload(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, "replace")
    except LookupError:
        return payload.decode("utf-8", "replace")


def searchable_text(raw: bytes, limit: int) -> str:
    message = message_from_bytes(raw)
    plain: list[str] = []
    html: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment" or part.get_filename():
            continue
        if part.get_content_type() == "text/plain":
            plain.append(_decoded_payload(part))
        elif part.get_content_type() == "text/html":
            html.append(_decoded_payload(part))
    text = "\n".join(plain)
    if not text and html:
        parser = _TextExtractor()
        parser.feed("\n".join(html))
        text = " ".join(parser.parts)
    return re.sub(r"\s+", " ", text).strip()[:limit]


class ContentIndexManager:
    """Build a local FTS5 index without marking source messages as read."""

    def __init__(self, settings: Settings, store: ScanStore, credentials: CredentialStore) -> None:
        self._settings = settings
        self._store = store
        self._credentials = credentials
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._store.recover_content_index_runs()

    def start(self, account_id: str) -> str:
        run_id = self._store.create_content_index_run(account_id)
        thread = threading.Thread(
            target=self._run,
            args=(run_id,),
            daemon=True,
            name=f"mail-content-index-{run_id[:8]}",
        )
        with self._lock:
            self._threads[run_id] = thread
        thread.start()
        return run_id

    def _run(self, run_id: str) -> None:
        try:
            run, rows = self._store.content_index_pending(run_id)
            account_id = str(run["account_id"])
            account = self._store.account(account_id)
            if account is None:
                raise LookupError("Account is unavailable")
            grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
            for row in rows:
                grouped[str(row["folder"])].append(row)
            with ReadOnlyImapClient(get_provider(str(account["provider"]))) as client:
                client.authenticate(
                    self._credentials.get_username(account_id),
                    self._credentials.get_password(account_id),
                )
                for folder, messages in grouped.items():
                    live_uids = set(client.message_uids(folder))
                    for item in messages:
                        uid = str(item["uid"])
                        subject = decoded(str(item["subject"]))
                        sender = decoded(str(item["sender"]))
                        if uid not in live_uids:
                            self._store.advance_content_index(
                                run_id, folder, indexed=False, skipped=True
                            )
                            continue
                        body = ""
                        oversized = (
                            int(item["size_bytes"]) > self._settings.content_index_max_message_bytes
                        )
                        if not oversized:
                            try:
                                body = searchable_text(
                                    client.fetch_raw_message(folder, uid),
                                    self._settings.content_index_body_chars,
                                )
                            except ConnectionError:
                                self._store.advance_content_index(
                                    run_id, folder, indexed=False, skipped=True
                                )
                                continue
                        digest = hashlib.sha256(
                            f"{subject}\0{sender}\0{body}".encode("utf-8", "replace")
                        ).hexdigest()
                        self._store.store_message_content(
                            account_id,
                            str(item["job_id"]),
                            folder,
                            uid,
                            subject,
                            sender,
                            body,
                            digest,
                        )
                        self._store.advance_content_index(
                            run_id, folder, indexed=True, skipped=oversized
                        )
            self._store.finish_content_index(run_id, "completed")
        except (
            imaplib.IMAP4.error,
            OSError,
            LookupError,
            ConnectionError,
            ValueError,
        ) as exc:
            self._store.finish_content_index(run_id, "failed", _safe_error(exc))


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, LookupError):
        return "Saved account credentials are incomplete"
    if isinstance(exc, imaplib.IMAP4.error):
        return "The provider rejected the read-only content request"
    if isinstance(exc, (OSError, ConnectionError)):
        return "The mail provider could not be reached"
    return "Local content indexing stopped safely"
