from datetime import UTC, datetime

from mail_organizer.intelligence import (
    action_candidates,
    attachment_category,
    company_details,
    company_key,
    consolidate_companies,
    lexical_candidates,
    lifecycle_entities,
)


def mail(uid: str, subject: str, domain: str = "billing.example.com") -> dict[str, object]:
    return {
        "job_id": "job",
        "folder": "INBOX",
        "uid": uid,
        "subject": subject,
        "sender": f"Billing <service@{domain}>",
        "sender_domain": domain,
        "size_bytes": 100,
        "internal_date": "01-Jan-2026 00:00:00 +0000",
    }


def test_action_candidates_prioritize_security_and_payment() -> None:
    items = action_candidates(
        [mail("1", "Invoice payment due"), mail("2", "Security login warning")],
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert [item["action_type"] for item in items] == ["security", "payment"]
    assert (
        action_candidates(
            [{**mail("3", "Invoice due"), "folder": "Sent"}],
            now=datetime(2026, 1, 2, tzinfo=UTC),
        )
        == []
    )


def test_company_consolidation_groups_subdomains() -> None:
    items = consolidate_companies(
        [mail("1", "A", "billing.example.com"), mail("2", "B", "mail.example.com")]
    )
    assert items[0]["company"] == "example.com"
    assert items[0]["messages"] == 2
    assert company_key("service.amazon.co.uk") == "amazon.co.uk"


def test_relationships_do_not_merge_unrelated_public_mailbox_senders() -> None:
    first = mail("1", "A", "gmail.com")
    first["sender"] = "One <one@gmail.com>"
    second = mail("2", "B", "gmail.com")
    second["sender"] = "Two <two@gmail.com>"
    companies = consolidate_companies([first, second])
    assert {item["company"] for item in companies} == {
        "one@gmail.com",
        "two@gmail.com",
    }
    details = company_details([first, second], "one@gmail.com")
    assert details["messages"] == 1
    assert details["identities"][0]["sender"] == "One <one@gmail.com>"


def test_local_search_and_lifecycle_views() -> None:
    messages = [
        mail("1", "Project Zephyr cost estimate"),
        mail("2", "Hotel booking"),
        mail("3", "Project Zephyr sweepstakes"),
    ]
    candidates = lexical_candidates("Project Zephyr estimate", messages)
    assert [item["uid"] for item in candidates] == ["1"]
    misleading = mail("4", "Your cooling box is cancelled", "unrelated-zephyr.example")
    assert lexical_candidates("Project Zephyr", [misleading]) == []
    entities = lifecycle_entities(
        [
            {"category": "order", "id": "order"},
            {"category": "subscription", "id": "contract"},
        ]
    )
    assert entities["order"][0]["id"] == "order"
    assert entities["contract"][0]["id"] == "contract"


def test_attachment_categories_are_conservative() -> None:
    assert attachment_category("invoice-2026.pdf", "Your documents") == "invoice"
    assert attachment_category("boarding-pass.pdf", "Flight") == "travel"
    assert attachment_category("photo.jpg", "Hello") == "image"


def test_action_inbox_excludes_old_newsletters_and_deduplicates_threads() -> None:
    recent = mail("1", "Payment due")
    duplicate = mail("2", "Re: Payment due")
    newsletter = {**mail("3", "New login warning"), "list_unsubscribe": 1}
    old = {**mail("4", "Security login warning"), "internal_date": "01-Jan-2020 00:00:00 +0000"}
    items = action_candidates(
        [recent, duplicate, newsletter, old],
        now=datetime(2026, 1, 2, tzinfo=UTC),
    )
    assert [item["uid"] for item in items] == ["1"]
