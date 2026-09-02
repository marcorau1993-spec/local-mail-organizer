from pathlib import Path

import pytest

from mail_organizer.api import (
    FilingApplyRequest,
    NewsletterActionRequest,
    _verify_archive_root,
    account_id,
)


def test_account_identifier_is_normalized_and_opaque() -> None:
    first = account_id("webde", " Example@web.de ")
    second = account_id("webde", "example@web.de")
    assert first == second
    assert "example" not in first
    assert len(first) == 64


def test_archive_root_is_verified_with_temporary_round_trip(tmp_path: Path) -> None:
    archive = tmp_path / "archive"
    assert _verify_archive_root(str(archive)) == archive.resolve()
    assert list(archive.iterdir()) == []


def test_archive_root_requires_absolute_path() -> None:
    with pytest.raises(ValueError):
        _verify_archive_root("relative/archive")


def test_newsletter_batch_accepts_up_to_one_hundred_items() -> None:
    items = [{"job_id": "a" * 32, "folder": "INBOX", "uid": str(index + 1)} for index in range(100)]
    request = NewsletterActionRequest(items=items, confirmed=True)
    assert len(request.items) == 100


def test_filing_request_accepts_supported_future_horizons() -> None:
    request = FilingApplyRequest(
        run_id="a" * 32,
        proposal_ids=["invoices-2026"],
        confirmed=True,
        future_years=10,
    )
    assert request.future_years == 10


def test_filing_request_rejects_arbitrary_future_horizon() -> None:
    with pytest.raises(ValueError):
        FilingApplyRequest(
            run_id="a" * 32,
            proposal_ids=["invoices-2026"],
            confirmed=True,
            future_years=3,
        )
