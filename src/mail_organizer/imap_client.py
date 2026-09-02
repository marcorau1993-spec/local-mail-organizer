"""Strictly read-only IMAP connection and metadata scanning."""

from __future__ import annotations

import imaplib
import re
import ssl
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Protocol, Self, cast

from .providers import Provider

_SIZE_RE = re.compile(rb"RFC822\.SIZE (\d+)")
_DATE_RE = re.compile(rb'INTERNALDATE "([^"]+)"')
_FLAGS_RE = re.compile(rb"FLAGS \(([^)]*)\)")
_UID_RE = re.compile(rb"UID (\d+)")
_ATOM_SAFE_RE = re.compile(r"^[A-Za-z0-9._/-]+$")
_COPYUID_RE = re.compile(rb"(?:COPYUID\s+)?\d+\s+[\d:,]+\s+([\d:,]+)")


class ImapConnection(Protocol):
    def login(self, user: str, password: str) -> tuple[str, Sequence[bytes]]: ...
    def authenticate(self, mechanism: str, authobject: object) -> tuple[str, Sequence[bytes]]: ...
    def starttls(
        self, ssl_context: ssl.SSLContext | None = None
    ) -> tuple[str, Sequence[bytes]]: ...
    def list(self) -> tuple[str, Sequence[bytes | None]]: ...
    def select(
        self, mailbox: str = "INBOX", readonly: bool = False
    ) -> tuple[str, Sequence[bytes]]: ...
    def uid(self, command: str, *args: object) -> tuple[str, Sequence[object]]: ...
    def create(self, mailbox: str) -> tuple[str, Sequence[bytes]]: ...
    def store(self, message_set: str, command: str, flags: str) -> tuple[str, Sequence[bytes]]: ...
    def expunge(self) -> tuple[str, Sequence[bytes]]: ...
    def logout(self) -> tuple[str, Sequence[bytes]]: ...


@dataclass(frozen=True, slots=True)
class MessageMetadata:
    uid: str
    size_bytes: int
    internal_date: str | None
    flags: tuple[str, ...]

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ScanSummary:
    folder: str
    scanned: int
    total_bytes: int
    large_messages: tuple[MessageMetadata, ...]

    def public_dict(self) -> dict[str, object]:
        return {
            "folder": self.folder,
            "scanned": self.scanned,
            "total_bytes": self.total_bytes,
            "large_messages": [item.public_dict() for item in self.large_messages],
        }


@dataclass(frozen=True, slots=True)
class ReviewMessage:
    uid: str
    subject: str
    sender: str
    list_unsubscribe: bool
    size_bytes: int
    internal_date: str | None
    flags: tuple[str, ...]
    sender_domain: str = ""
    list_id: str | None = None


class ReadOnlyImapClient:
    """IMAP client that intentionally exposes no mutating operations."""

    def __init__(self, provider: Provider, connection: ImapConnection | None = None) -> None:
        self._provider = provider
        context = ssl.create_default_context()
        if provider.allow_self_signed_local:
            if provider.imap_host not in {"127.0.0.1", "localhost", "::1"}:
                raise ValueError("Self-signed TLS is restricted to the local loopback interface")
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        if connection is not None:
            self._connection = connection
        elif provider.imap_transport == "starttls":
            plain = imaplib.IMAP4(provider.imap_host, provider.imap_port, timeout=20)
            status, _ = plain.starttls(ssl_context=context)
            if status != "OK":
                raise ConnectionError("Unable to establish IMAP STARTTLS")
            self._connection = cast(ImapConnection, plain)
        else:
            self._connection = cast(
                ImapConnection,
                imaplib.IMAP4_SSL(
                    provider.imap_host, provider.imap_port, ssl_context=context, timeout=20
                ),
            )
        self._authenticated = False

    def authenticate(self, username: str, password: str) -> None:
        if self._provider.auth_mode == "oauth2":
            self.authenticate_oauth2(username, password)
            return
        status, _ = self._connection.login(username, password)
        if status != "OK":
            raise ConnectionError("IMAP authentication failed")
        self._authenticated = True

    def authenticate_oauth2(self, username: str, access_token: str) -> None:
        payload = f"user={username}\x01auth=Bearer {access_token}\x01\x01".encode()
        status, _ = self._connection.authenticate("XOAUTH2", lambda _: payload)
        if status != "OK":
            raise ConnectionError("IMAP OAuth authentication failed")
        self._authenticated = True

    def test_connection(self) -> int:
        self._require_authentication()
        status, folders = self._connection.list()
        if status != "OK":
            raise ConnectionError("Unable to list IMAP folders")
        return sum(folder is not None for folder in folders)

    def list_folders(self) -> list[tuple[str, int]]:
        """List selectable folders and their message counts without changing state."""
        self._require_authentication()
        status, raw_folders = self._connection.list()
        if status != "OK":
            raise ConnectionError("Unable to list IMAP folders")
        folders: list[tuple[str, int]] = []
        for raw in raw_folders:
            if raw is None or b"\\Noselect" in raw:
                continue
            name = _parse_folder_name(raw)
            if name is None:
                continue
            select_status, count_data = self._connection.select(
                _mailbox_argument(name), readonly=True
            )
            if select_status != "OK":
                continue
            count = int(count_data[0]) if count_data and count_data[0].isdigit() else 0
            folders.append((name, count))
        return folders

    def message_uids(self, folder: str) -> list[str]:
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open IMAP folder in read-only mode")
        status, search_data = self._connection.uid("SEARCH", None, "ALL")
        if status != "OK" or not search_data or not isinstance(search_data[0], bytes):
            raise ConnectionError("Unable to enumerate message identifiers")
        return [value.decode("ascii") for value in search_data[0].split()]

    def fetch_messages_by_uids(self, folder: str, uids: Sequence[str]) -> tuple[ReviewMessage, ...]:
        """Fetch one batch of safe headers with a single read-only IMAP command."""
        if not uids:
            return ()
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open IMAP folder in read-only mode")
        status, fetch_data = self._connection.uid(
            "FETCH",
            ",".join(uids),
            "(UID RFC822.SIZE INTERNALDATE FLAGS BODY.PEEK[HEADER.FIELDS (SUBJECT FROM LIST-ID LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)])",
        )
        if status != "OK":
            raise ConnectionError("Unable to fetch read-only message headers")
        return _review_messages(fetch_data)

    def scan_folder(self, folder: str, limit: int, large_message_bytes: int) -> ScanSummary:
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open IMAP folder in read-only mode")
        status, search_data = self._connection.uid("SEARCH", None, "ALL")
        if status != "OK" or not search_data or not isinstance(search_data[0], bytes):
            raise ConnectionError("Unable to enumerate message identifiers")
        uids = search_data[0].split()[-limit:]
        messages: list[MessageMetadata] = []
        for uid_bytes in uids:
            uid = uid_bytes.decode("ascii")
            status, fetch_data = self._connection.uid(
                "FETCH", uid, "(UID RFC822.SIZE INTERNALDATE FLAGS)"
            )
            if status != "OK":
                continue
            raw = next((item[0] for item in fetch_data if isinstance(item, tuple)), b"")
            if not isinstance(raw, bytes):
                continue
            size_match = _SIZE_RE.search(raw)
            if size_match is None:
                continue
            date_match = _DATE_RE.search(raw)
            flags_match = _FLAGS_RE.search(raw)
            flags = (
                tuple(flags_match.group(1).decode("ascii", "replace").split())
                if flags_match
                else ()
            )
            messages.append(
                MessageMetadata(
                    uid=uid,
                    size_bytes=int(size_match.group(1)),
                    internal_date=date_match.group(1).decode("ascii", "replace")
                    if date_match
                    else None,
                    flags=flags,
                )
            )
        large = tuple(message for message in messages if message.size_bytes >= large_message_bytes)
        return ScanSummary(folder, len(messages), sum(item.size_bytes for item in messages), large)

    def fetch_review_messages(self, folder: str, limit: int) -> tuple[ReviewMessage, ...]:
        """Fetch a bounded set of headers without setting the Seen flag."""
        uids = self.message_uids(folder)[-limit:]
        return self.fetch_messages_by_uids(folder, uids)

    def fetch_raw_message(self, folder: str, uid: str) -> bytes:
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open source folder")
        status, data = self._connection.uid("FETCH", uid, "(UID BODY.PEEK[])")
        if status != "OK":
            raise ConnectionError("Unable to fetch message for verified export")
        content = next(
            (item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)),
            None,
        )
        if content is None:
            raise ConnectionError("Message content was not returned")
        return content

    def fetch_unsubscribe_headers(self, folder: str, uid: str) -> bytes:
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open newsletter folder")
        status, data = self._connection.uid(
            "FETCH",
            uid,
            "(UID BODY.PEEK[HEADER.FIELDS (LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)])",
        )
        if status != "OK":
            raise ConnectionError("Unable to fetch unsubscribe headers")
        content = next(
            (item[1] for item in data if isinstance(item, tuple) and isinstance(item[1], bytes)),
            None,
        )
        if content is None:
            raise ConnectionError("Unsubscribe headers were not returned")
        return content

    def fetch_unsubscribe_headers_by_uids(
        self, folder: str, uids: Sequence[str]
    ) -> dict[str, bytes]:
        if not uids:
            return {}
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open newsletter folder")
        status, data = self._connection.uid(
            "FETCH",
            ",".join(uids),
            "(UID BODY.PEEK[HEADER.FIELDS (LIST-UNSUBSCRIBE LIST-UNSUBSCRIBE-POST)])",
        )
        if status != "OK":
            raise ConnectionError("Unable to fetch unsubscribe headers")
        results: dict[str, bytes] = {}
        for item in data:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            metadata, headers = item
            if not isinstance(metadata, bytes) or not isinstance(headers, bytes):
                continue
            uid_match = _UID_RE.search(metadata)
            if uid_match is not None:
                results[uid_match.group(1).decode("ascii")] = headers
        return results

    def fetch_security_headers_by_uids(self, folder: str, uids: Sequence[str]) -> dict[str, bytes]:
        if not uids:
            return {}
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open folder for security review")
        status, data = self._connection.uid(
            "FETCH",
            ",".join(uids),
            "(UID BODY.PEEK[HEADER.FIELDS (FROM REPLY-TO RETURN-PATH AUTHENTICATION-RESULTS RECEIVED-SPF)])",
        )
        if status != "OK":
            raise ConnectionError("Unable to fetch security headers")
        results: dict[str, bytes] = {}
        for item in data:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            metadata, headers = item
            if not isinstance(metadata, bytes) or not isinstance(headers, bytes):
                continue
            uid_match = _UID_RE.search(metadata)
            if uid_match is not None:
                results[uid_match.group(1).decode("ascii")] = headers
        return results

    def move_message(self, folder: str, uid: str, destination: str) -> str:
        """Move one explicitly approved message without expunging unrelated mail."""
        self._require_authentication()
        status, _ = self._connection.select(_mailbox_argument(folder), readonly=False)
        if status != "OK":
            raise ConnectionError("Unable to open source folder")
        status, data = self._connection.uid("MOVE", uid, _mailbox_argument(destination))
        if status != "OK":
            raise ConnectionError("Server rejected the message move")
        candidates = list(data)
        response = getattr(self._connection, "response", None)
        if callable(response):
            _, copyuid_data = response("COPYUID")
            candidates.extend(copyuid_data or [])
        for candidate in candidates:
            if isinstance(candidate, bytes) and (match := _COPYUID_RE.search(candidate)):
                destination_set = match.group(1).decode("ascii")
                if destination_set.isdigit():
                    return destination_set
        return uid

    def special_folder(self, role: str, fallbacks: tuple[str, ...]) -> str:
        """Resolve a provider-localized IMAP special-use mailbox."""
        self._require_authentication()
        status, raw_folders = self._connection.list()
        if status != "OK":
            raise ConnectionError("Unable to list IMAP folders")
        marker = f"\\{role}".encode("ascii").lower()
        parsed: list[str] = []
        for raw in raw_folders:
            if raw is None:
                continue
            name = _parse_folder_name(raw)
            if name is None:
                continue
            parsed.append(name)
            if marker in raw.lower():
                return name
        by_name = {name.casefold(): name for name in parsed}
        for fallback in fallbacks:
            if fallback.casefold() in by_name:
                return by_name[fallback.casefold()]
        raise ConnectionError(f"Server does not advertise a {role} folder")

    def trash_folder(self) -> str:
        return self.special_folder(
            "Trash", ("Trash", "TRASH", "Deleted", "Deleted Items", "Papierkorb", "Gelöscht")
        )

    def archive_folder(self) -> str:
        return self.special_folder("Archive", ("Archive", "Archiv"))

    def folder_delimiter(self) -> str:
        """Return the hierarchy delimiter advertised by this IMAP provider."""
        self._require_authentication()
        status, raw_folders = self._connection.list()
        if status != "OK":
            raise ConnectionError("Unable to read mailbox hierarchy")
        for raw in raw_folders:
            if raw is None:
                continue
            match = re.search(rb"\)\s+(?:\"([^\"]+)\"|([^ ]+))\s+", raw)
            if match:
                value = (match.group(1) or match.group(2)).decode("ascii", "ignore")
                if value.upper() != "NIL" and len(value) == 1:
                    return value
        return "/"

    def folder_path(self, *parts: str) -> str:
        return self.folder_delimiter().join(parts)

    def ensure_folder_path(self, *parts: str) -> str:
        """Create every hierarchy level required by a provider."""
        delimiter = self.folder_delimiter()
        current: list[str] = []
        for part in parts:
            current.append(part)
            self.ensure_folder(delimiter.join(current))
        return delimiter.join(current)

    def empty_folder(self, folder: str) -> int:
        """Permanently remove every message from one explicitly resolved folder."""
        self._require_authentication()
        status, count_data = self._connection.select(_mailbox_argument(folder), readonly=False)
        if status != "OK":
            raise ConnectionError("Unable to open Trash folder")
        count = int(count_data[0]) if count_data and count_data[0].isdigit() else 0
        if count == 0:
            return 0
        status, _ = self._connection.store("1:*", "+FLAGS.SILENT", "(\\Deleted)")
        if status != "OK":
            raise ConnectionError("Server rejected Trash cleanup")
        status, _ = self._connection.expunge()
        if status != "OK":
            raise ConnectionError("Server rejected permanent Trash cleanup")
        return count

    def folder_message_count(self, folder: str) -> int:
        """Return a mailbox count without changing flags or message state."""
        self._require_authentication()
        status, count_data = self._connection.select(_mailbox_argument(folder), readonly=True)
        if status != "OK":
            raise ConnectionError("Unable to open mailbox")
        return int(count_data[0]) if count_data and count_data[0].isdigit() else 0

    def ensure_folder(self, name: str) -> None:
        self._require_authentication()
        status, raw_folders = self._connection.list()
        existing = {
            parsed
            for raw in raw_folders
            if raw is not None and (parsed := _parse_folder_name(raw)) is not None
        }
        if status == "OK" and name in existing:
            return
        create_status, _ = self._connection.create(_mailbox_argument(name))
        if create_status != "OK":
            raise ConnectionError("Unable to create archive folder")

    def close(self) -> None:
        if self._authenticated:
            self._connection.logout()
            self._authenticated = False

    def _require_authentication(self) -> None:
        if not self._authenticated:
            raise RuntimeError("IMAP client is not authenticated")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


def _review_messages(fetch_data: Sequence[object]) -> tuple[ReviewMessage, ...]:
    messages: list[ReviewMessage] = []
    for item in fetch_data:
        if not isinstance(item, tuple) or len(item) != 2:
            continue
        metadata = item[0] if isinstance(item[0], bytes) else b""
        headers = item[1] if isinstance(item[1], bytes) else b""
        uid_match = _UID_RE.search(metadata)
        size_match = _SIZE_RE.search(metadata)
        if uid_match is None or size_match is None:
            continue
        parsed_headers = _parse_headers(headers)
        sender = parsed_headers.get("from", "(unknown sender)")
        address = parseaddr(sender)[1]
        sender_domain = address.rpartition("@")[2].casefold() if "@" in address else ""
        date_match = _DATE_RE.search(metadata)
        flags_match = _FLAGS_RE.search(metadata)
        messages.append(
            ReviewMessage(
                uid=uid_match.group(1).decode("ascii"),
                subject=parsed_headers.get("subject", "(no subject)"),
                sender=sender,
                list_unsubscribe="list-unsubscribe" in parsed_headers,
                size_bytes=int(size_match.group(1)),
                internal_date=date_match.group(1).decode("ascii", "replace")
                if date_match
                else None,
                flags=tuple(flags_match.group(1).decode("ascii", "replace").split())
                if flags_match
                else (),
                sender_domain=sender_domain,
                list_id=parsed_headers.get("list-id"),
            )
        )
    return tuple(messages)


def _parse_folder_name(raw: bytes) -> str | None:
    text = raw.decode("ascii", "replace").strip()
    if text.endswith('"'):
        quoted: list[str] = re.findall(r'"((?:[^"\\]|\\.)*)"', text)
        if quoted:
            return quoted[-1].replace('\\"', '"').replace("\\\\", "\\")
    parts = text.rsplit(" ", 1)
    return parts[-1].strip() if parts else None


def _mailbox_argument(folder: str) -> str:
    """Quote server-provided mailbox names when they are not valid IMAP atoms."""
    if _ATOM_SAFE_RE.fullmatch(folder):
        return folder
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _parse_headers(raw: bytes) -> dict[str, str]:
    values: dict[str, str] = {}
    current = ""
    for line in raw.decode("utf-8", "replace").splitlines():
        if line[:1].isspace() and current:
            values[current] = f"{values[current]} {line.strip()}"
            continue
        name, separator, value = line.partition(":")
        if separator:
            current = name.strip().casefold()
            try:
                values[current] = str(make_header(decode_header(value.strip())))[:500]
            except (LookupError, UnicodeError):
                values[current] = value.strip()[:500]
    return values
