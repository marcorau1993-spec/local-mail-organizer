from email.message import EmailMessage
from pathlib import Path

from mail_organizer.content_index import searchable_text
from mail_organizer.imap_client import ReviewMessage
from mail_organizer.storage import ScanStore


def test_searchable_text_uses_body_but_excludes_attachments() -> None:
    message = EmailMessage()
    message["Subject"] = "Invoice"
    message.set_content("The excavator rental is due next Tuesday.")
    message.add_attachment(
        b"secret attachment words",
        maintype="application",
        subtype="octet-stream",
        filename="private.bin",
    )
    text = searchable_text(message.as_bytes(), 10_000)
    assert "excavator rental" in text
    assert "secret attachment words" not in text


def test_local_content_index_requires_all_terms_and_is_account_scoped(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "mail.sqlite3")
    store.register_account("account-a", "webde")
    job_id = store.create_job("account-a", "webde")
    store.prepare_folders(job_id, [("INBOX", 1)])
    store.store_batch(
        job_id,
        "INBOX",
        (
            ReviewMessage(
                uid="42",
                subject="Rental documents",
                sender="Office <office@example.invalid>",
                list_unsubscribe=False,
                size_bytes=500,
                internal_date="01-Jan-2031 12:00:00 +0000",
                flags=(),
                sender_domain="example.invalid",
            ),
        ),
        10_000_000,
    )
    store.set_status(job_id, "completed")
    run_id = store.create_content_index_run("account-a")
    store.store_message_content(
        "account-a",
        job_id,
        "INBOX",
        "42",
        "Rental documents",
        "Office <office@example.invalid>",
        "The excavator lease ends in September",
        "a" * 64,
    )
    store.advance_content_index(run_id, "INBOX", indexed=True)
    store.finish_content_index(run_id, "completed")

    results = store.search_message_content("account-a", "excavator September")
    assert [item["uid"] for item in results] == ["42"]
    assert store.search_message_content("account-a", "excavator zephyr") == []
    assert store.search_message_content("account-b", "excavator September") == []
    assert store.content_index_status("account-a")["indexed_messages"] == 1
    store.delete_content_index("account-a")
    assert store.search_message_content("account-a", "excavator September") == []
    assert store.content_index_status("account-a")["indexed_messages"] == 0
