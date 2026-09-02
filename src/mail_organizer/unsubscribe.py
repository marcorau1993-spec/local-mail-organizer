"""Strict RFC 8058 one-click newsletter unsubscription."""

from __future__ import annotations

import base64
import ipaddress
import re
import smtplib
import socket
import ssl
import time
from email import message_from_bytes
from email.message import EmailMessage
from email.utils import parseaddr
from urllib.parse import parse_qs, unquote, urlsplit

import httpx

_HTTPS_LINK = re.compile(r"<(https://[^>]+)>", re.IGNORECASE)
_MAILTO_LINK = re.compile(r"<(mailto:[^>]+)>", re.IGNORECASE)


def unsubscribe_capability(raw_message: bytes) -> str:
    message = message_from_bytes(raw_message)
    unsubscribe = message.get("List-Unsubscribe", "")
    post = message.get("List-Unsubscribe-Post", "")
    if "list-unsubscribe=one-click" in post.casefold() and _HTTPS_LINK.search(unsubscribe):
        return "automatic"
    if _MAILTO_LINK.search(unsubscribe):
        return "email"
    if unsubscribe:
        return "manual"
    return "unavailable"


def one_click_url(raw_message: bytes) -> str:
    message = message_from_bytes(raw_message)
    post = message.get("List-Unsubscribe-Post", "")
    if "list-unsubscribe=one-click" not in post.casefold():
        raise ValueError("Newsletter does not support RFC 8058 one-click unsubscribe")
    match = _HTTPS_LINK.search(message.get("List-Unsubscribe", ""))
    if match is None:
        raise ValueError("Newsletter has no HTTPS unsubscribe endpoint")
    url = match.group(1)
    _require_public_https(url)
    return url


def unsubscribe_page_url(raw_message: bytes) -> str:
    """Return a validated public HTTPS unsubscribe page when one is advertised."""
    message = message_from_bytes(raw_message)
    match = _HTTPS_LINK.search(message.get("List-Unsubscribe", ""))
    if match is None:
        raise ValueError("Newsletter has no HTTPS unsubscribe page")
    url = match.group(1)
    _require_public_https(url)
    return url


def mailto_request(raw_message: bytes) -> tuple[str, str, str]:
    message = message_from_bytes(raw_message)
    match = _MAILTO_LINK.search(message.get("List-Unsubscribe", ""))
    if match is None:
        raise ValueError("Newsletter has no mailto unsubscribe endpoint")
    parsed = urlsplit(match.group(1))
    recipient = unquote(parsed.path)
    address = parseaddr(recipient)[1]
    if (
        not address
        or address != recipient
        or "\r" in address
        or "\n" in address
        or len(address) > 320
    ):
        raise ValueError("Unsafe unsubscribe recipient")
    query = parse_qs(parsed.query, keep_blank_values=True)
    subject = query.get("subject", ["unsubscribe"])[0][:200]
    body = query.get("body", ["unsubscribe"])[0][:2000]
    if any(char in subject for char in "\r\n"):
        raise ValueError("Unsafe unsubscribe subject")
    return address, subject, body


def unsubscribe_by_email(
    raw_message: bytes,
    *,
    username: str,
    password: str,
    smtp_host: str,
    smtp_port: int,
    auth_mode: str = "password",
    allow_self_signed_local: bool = False,
) -> None:
    recipient, subject, body = mailto_request(raw_message)
    message = EmailMessage()
    message["From"] = username
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    context = ssl.create_default_context()
    if allow_self_signed_local:
        if smtp_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Self-signed SMTP TLS is restricted to loopback")
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as connection:
        connection.starttls(context=context)
        if auth_mode == "oauth2":
            payload = base64.b64encode(
                f"user={username}\x01auth=Bearer {password}\x01\x01".encode()
            ).decode()
            code, _ = connection.docmd("AUTH", f"XOAUTH2 {payload}")
            if code != 235:
                raise smtplib.SMTPAuthenticationError(code, b"OAuth authentication failed")
        else:
            connection.login(username, password)
        connection.send_message(message)


def unsubscribe_one_click(raw_message: bytes) -> None:
    url = one_click_url(raw_message)
    for attempt in range(2):
        try:
            response = httpx.post(
                url,
                content=b"List-Unsubscribe=One-Click",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                follow_redirects=False,
                timeout=20,
            )
        except httpx.TransportError:
            if attempt == 0:
                time.sleep(1)
                continue
            raise
        if 200 <= response.status_code < 300:
            return
        if attempt == 0 and (response.status_code == 429 or response.status_code >= 500):
            time.sleep(1)
            continue
        if response.status_code == 429:
            raise ConnectionError("Newsletter endpoint rate limited the request")
        if response.status_code >= 500:
            raise ConnectionError("Newsletter endpoint is temporarily unavailable")
        raise ConnectionError("Newsletter endpoint rejected one-click unsubscribe")


def _require_public_https(url: str) -> None:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
    ):
        raise ValueError("Only standard public HTTPS endpoints are allowed")
    addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("Unsubscribe endpoint did not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError("Private or local unsubscribe endpoints are blocked")
