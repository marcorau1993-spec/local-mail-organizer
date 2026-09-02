from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from mail_organizer.document_text import extract_attachment_text
from mail_organizer.dropbox_archive import DropboxArchive
from mail_organizer.imap_client import ReadOnlyImapClient
from mail_organizer.providers import get_provider


class FakeImap:
    oauth_payload = b""

    def authenticate(self, mechanism: str, authobject: Any) -> tuple[str, Sequence[bytes]]:
        assert mechanism == "XOAUTH2"
        self.oauth_payload = authobject(b"")
        return "OK", []

    def login(self, user: str, password: str) -> tuple[str, Sequence[bytes]]:
        return "OK", []

    def logout(self) -> tuple[str, Sequence[bytes]]:
        return "OK", []


def test_dropbox_archive_path_is_rooted_and_rejects_traversal() -> None:
    assert DropboxArchive._path("MailOrganizer", "job/INBOX/1.eml") == (
        "/MailOrganizer/job/INBOX/1.eml"
    )
    with pytest.raises(ValueError):
        DropboxArchive._path("MailOrganizer", "../secret")


def test_plain_document_text_is_extracted_without_ai() -> None:
    text, method = extract_attachment_text(
        b"Invoice 2026-001", "invoice.txt", "text/plain", "http://127.0.0.1:11434", "x"
    )
    assert text == "Invoice 2026-001"
    assert method == "local_text"


def test_outlook_uses_xoauth2_payload() -> None:
    connection = FakeImap()
    client = ReadOnlyImapClient(get_provider("outlook"), connection=connection)  # type: ignore[arg-type]
    client.authenticate("person@example.com", "access-token")
    assert b"user=person@example.com" in connection.oauth_payload
    assert b"auth=Bearer access-token" in connection.oauth_payload
