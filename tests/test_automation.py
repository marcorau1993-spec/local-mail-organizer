from mail_organizer.automation import _message_year
from mail_organizer.imap_client import ReviewMessage


def test_automation_uses_message_internal_year() -> None:
    message = ReviewMessage(
        uid="42",
        subject="Invoice",
        sender="billing@example.invalid",
        list_unsubscribe=False,
        size_bytes=100,
        internal_date="01-Jan-2031 12:00:00 +0000",
        flags=(),
    )
    assert _message_year(message) == 2031


def test_automation_defers_messages_without_a_valid_year() -> None:
    message = ReviewMessage(
        uid="42",
        subject="Invoice",
        sender="billing@example.invalid",
        list_unsubscribe=False,
        size_bytes=100,
        internal_date=None,
        flags=(),
    )
    assert _message_year(message) is None
