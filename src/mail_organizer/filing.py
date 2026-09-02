"""Deterministic filing plans derived from locally generated AI classifications."""

from __future__ import annotations

import re
from collections import defaultdict
from email.utils import parsedate_to_datetime

_BUCKETS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    (
        "Invoices",
        ("finance", "invoice", "rechnung", "receipt", "beleg", "payment", "zahlung"),
        "Financial records",
    ),
    (
        "Orders",
        ("order", "bestellung", "purchase", "kauf", "shipping", "delivery"),
        "Orders and purchase records",
    ),
    (
        "Travel",
        ("travel", "reise", "booking", "buchung", "flight", "hotel"),
        "Travel and booking records",
    ),
    (
        "Contracts",
        ("legal", "contract", "vertrag", "agreement", "vereinbarung"),
        "Contracts and legal records",
    ),
    (
        "Security",
        ("security", "sicherheit", "password", "passwort", "login"),
        "Account and security records",
    ),
    (
        "Accounts",
        ("account", "registration", "registrierung", "activation", "aktivierung"),
        "Account registration and access records",
    ),
    (
        "Support",
        ("support", "ticket", "refund", "rückerstattung", "cancellation", "kündigung"),
        "Support cases and service requests",
    ),
    (
        "Subscriptions",
        ("subscription", "abonnement", "mitgliedschaft", "membership"),
        "Subscription and membership records",
    ),
    (
        "Health",
        ("health", "medical", "arzt", "termin", "appointment"),
        "Health and appointment records",
    ),
    (
        "Marketplace",
        ("marketplace", "nutzer-anfrage", "nutzeranfrage", "kleinanzeige"),
        "Marketplace conversations",
    ),
)
_SAFE_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_-]{0,119}$")


def build_filing_proposals(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    reasons: dict[str, str] = {}
    for row in rows:
        bucket_match = _bucket_for(row)
        year = _year(str(row.get("internal_date") or ""))
        if bucket_match is None or year is None:
            continue
        grouped[(bucket_match[0], year)].append(row)
        reasons[bucket_match[0]] = bucket_match[2]
    proposals: list[dict[str, object]] = []
    for (bucket_name, year), members in grouped.items():
        destination = validate_folder_name(f"{bucket_name}/{year}")
        proposals.append(
            {
                "id": f"{bucket_name.casefold()}-{year}",
                "bucket": bucket_name,
                "year": year,
                "destination": destination,
                "reason": reasons[bucket_name],
                "message_count": len(members),
                "total_bytes": sum(_integer(row["size_bytes"]) for row in members),
                "members": [
                    {"folder": str(row["folder"]), "uid": str(row["uid"])} for row in members
                ],
            }
        )
    return sorted(proposals, key=lambda item: _integer(item["message_count"]), reverse=True)


def _integer(value: object) -> int:
    if isinstance(value, (int, str)):
        return int(value)
    raise TypeError("Expected an integer-compatible value")


def validate_folder_name(value: str) -> str:
    if (
        not _SAFE_FOLDER.fullmatch(value)
        or "//" in value
        or value.endswith(("/", " "))
        or ".." in value
    ):
        raise ValueError("Unsafe mail folder name")
    return value


def _bucket_for(row: dict[str, object]) -> tuple[str, tuple[str, ...], str] | None:
    text = f"{row.get('category', '')} {row.get('subject_pattern', '')}".casefold()
    for bucket in _BUCKETS:
        if any(
            re.search(rf"(?<!\w){re.escape(term)}(?!\w)", text) is not None for term in bucket[1]
        ):
            return bucket
    return None


def _year(value: str) -> int | None:
    try:
        year = parsedate_to_datetime(value).year
    except (TypeError, ValueError, OverflowError):
        return None
    return year if 1990 <= year <= 2100 else None
