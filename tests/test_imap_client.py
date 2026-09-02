from mail_organizer.imap_client import ReadOnlyImapClient
from mail_organizer.providers import get_provider


class FakeImap:
    def __init__(self) -> None:
        self.readonly: bool | None = None
        self.fetch_queries: list[str] = []
        self.selected_mailboxes: list[str] = []

    def login(self, user: str, password: str):
        return "OK", [b"authenticated"]

    def list(self):
        return "OK", [b"INBOX", b"Spam"]

    def select(self, mailbox: str = "INBOX", readonly: bool = False):
        self.readonly = readonly
        self.selected_mailboxes.append(mailbox)
        return "OK", [b"2"]

    def uid(self, command: str, *args: object):
        if command == "SEARCH":
            return "OK", [b"1 2"]
        uid = str(args[0])
        self.fetch_queries.append(str(args[1]))
        size = b"500" if uid == "1" else b"12000000"
        headers = b"Subject: Monthly update\r\nFrom: Example <sender@example.invalid>\r\nList-Unsubscribe: <https://example.invalid/unsubscribe>\r\n\r\n"
        return "OK", [
            (
                b"1 (UID "
                + uid.encode()
                + b" RFC822.SIZE "
                + size
                + b' INTERNALDATE "30-Aug-2026 12:00:00 +0200" FLAGS (\\Seen))',
                headers,
            )
        ]

    def logout(self):
        return "BYE", [b"closed"]


def test_metadata_scan_uses_readonly_select_and_finds_large_mail() -> None:
    connection = FakeImap()
    with ReadOnlyImapClient(get_provider("webde"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        summary = client.scan_folder("INBOX", limit=10, large_message_bytes=10_000_000)
    assert connection.readonly is True
    assert summary.scanned == 2
    assert summary.total_bytes == 12_000_500
    assert [message.uid for message in summary.large_messages] == ["2"]


def test_review_fetch_uses_body_peek_and_parses_bounded_headers() -> None:
    connection = FakeImap()
    with ReadOnlyImapClient(get_provider("webde"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        messages = client.fetch_review_messages("INBOX", limit=1)
    assert connection.readonly is True
    assert "BODY.PEEK" in connection.fetch_queries[-1]
    assert messages[0].subject == "Monthly update"
    assert messages[0].list_unsubscribe is True


def test_folder_names_with_spaces_are_quoted_for_imap_commands() -> None:
    connection = FakeImap()
    connection.list = lambda: (
        "OK",
        [b'(\\HasNoChildren) "/" "Deleted Messages"'],
    )
    with ReadOnlyImapClient(get_provider("webde"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        folders = client.list_folders()
    assert folders == [("Deleted Messages", 2)]
    assert connection.selected_mailboxes == ['"Deleted Messages"']


def test_unquoted_folder_name_is_not_confused_with_quoted_delimiter() -> None:
    connection = FakeImap()
    connection.list = lambda: (
        "OK",
        [b'(\\HasNoChildren) "/" INBOX'],
    )
    with ReadOnlyImapClient(get_provider("webde"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        folders = client.list_folders()
    assert folders == [("INBOX", 2)]
    assert connection.selected_mailboxes == ["INBOX"]


def test_provider_localized_trash_folder_uses_special_use_flag() -> None:
    connection = FakeImap()
    connection.list = lambda: (
        "OK",
        [b'(\\HasNoChildren \\Trash) "/" "Geloescht"', b'(\\HasNoChildren) "/" INBOX'],
    )
    with ReadOnlyImapClient(get_provider("gmx"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        assert client.trash_folder() == "Geloescht"


def test_folder_message_count_uses_readonly_select() -> None:
    connection = FakeImap()
    with ReadOnlyImapClient(get_provider("gmx"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        assert client.folder_message_count("Trash") == 2
    assert connection.readonly is True


def test_provider_folder_path_uses_advertised_hierarchy_delimiter() -> None:
    connection = FakeImap()
    connection.list = lambda: ("OK", [b'(\\HasNoChildren) "." INBOX'])
    with ReadOnlyImapClient(get_provider("gmx"), connection=connection) as client:
        client.authenticate("anonymous@example.invalid", "secret")
        assert client.folder_path("Orders", "2030") == "Orders.2030"
