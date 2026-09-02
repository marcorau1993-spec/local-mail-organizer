from pathlib import Path

import pytest

from mail_organizer.archive import VerifiedArchive


def test_archive_writes_and_verifies_content(tmp_path: Path) -> None:
    receipt = VerifiedArchive(tmp_path).store(Path("messages/opaque-id.eml"), b"content")
    assert receipt.path.read_bytes() == b"content"
    assert receipt.size_bytes == 7
    assert len(receipt.sha256) == 64


def test_archive_rejects_path_traversal(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        VerifiedArchive(tmp_path).store(Path("../escape.eml"), b"content")
