import socket

import httpx
import pytest

from mail_organizer.unsubscribe import (
    mailto_request,
    one_click_url,
    unsubscribe_capability,
    unsubscribe_one_click,
    unsubscribe_page_url,
)


def test_one_click_requires_rfc_8058_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    raw = (
        b"List-Unsubscribe: <https://example.invalid/unsubscribe>\r\n"
        b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n\r\n"
    )
    assert one_click_url(raw) == "https://example.invalid/unsubscribe"


def test_one_click_rejects_private_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )
    raw = (
        b"List-Unsubscribe: <https://localhost/unsubscribe>\r\n"
        b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n\r\n"
    )
    with pytest.raises(ValueError):
        one_click_url(raw)


def test_standard_unsubscribe_without_one_click_is_manual() -> None:
    raw = b"List-Unsubscribe: <https://example.invalid/unsubscribe>\r\n\r\n"
    with pytest.raises(ValueError, match="RFC 8058"):
        one_click_url(raw)


def test_manual_unsubscribe_page_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    raw = b"List-Unsubscribe: <https://example.invalid/preferences/remove>\r\n\r\n"
    assert unsubscribe_page_url(raw) == "https://example.invalid/preferences/remove"


def test_one_click_retries_temporary_endpoint_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    monkeypatch.setattr("mail_organizer.unsubscribe.time.sleep", lambda _: None)
    responses = iter([httpx.Response(503), httpx.Response(204)])
    monkeypatch.setattr(
        "mail_organizer.unsubscribe.httpx.post", lambda *args, **kwargs: next(responses)
    )
    raw = (
        b"List-Unsubscribe: <https://example.invalid/unsubscribe>\r\n"
        b"List-Unsubscribe-Post: List-Unsubscribe=One-Click\r\n\r\n"
    )
    unsubscribe_one_click(raw)


def test_mailto_unsubscribe_is_classified_and_parsed() -> None:
    raw = (
        b"List-Unsubscribe: <mailto:list@example.invalid?"
        b"subject=unsubscribe&body=remove%20me>\r\n\r\n"
    )
    assert unsubscribe_capability(raw) == "email"
    assert mailto_request(raw) == ("list@example.invalid", "unsubscribe", "remove me")
