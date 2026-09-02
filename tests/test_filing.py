import pytest

from mail_organizer.filing import _bucket_for, build_filing_proposals, validate_folder_name


def test_filing_plan_groups_invoices_by_year() -> None:
    rows = [
        {
            "category": "finance",
            "subject_pattern": "invoice #",
            "folder": "INBOX",
            "uid": str(index),
            "size_bytes": 100,
            "internal_date": "01-Jan-2021 00:00:00 +0000",
        }
        for index in range(1, 4)
    ]
    proposal = build_filing_proposals(rows)[0]
    assert proposal["destination"] == "Invoices/2021"
    assert proposal["message_count"] == 3


def test_filing_plan_rejects_unsafe_folder_names() -> None:
    with pytest.raises(ValueError):
        validate_folder_name("../Invoices")


def test_folder_name_validation_supports_dot_hierarchy_providers() -> None:
    assert validate_folder_name("Orders.2030") == "Orders.2030"


def test_payment_debit_does_not_match_travel_booking_substring() -> None:
    assert (
        _bucket_for(
            {
                "category": "other",
                "subject_pattern": "die abbuchung ihres abonnements ist fehlgeschlagen",
            }
        )
        is None
    )
