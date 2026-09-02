from pathlib import Path

from mail_organizer.ai_cleanup import (
    GroupDecision,
    _apply_guards,
    _apply_learned_feedback,
    _baseline_decision,
    _group_inventory,
    is_provider_notice,
    is_provider_promotion,
)
from mail_organizer.api import _message_has_attachment
from mail_organizer.storage import ScanStore


def test_cleanup_groups_normalize_variable_subjects() -> None:
    messages = [
        {
            "folder": "INBOX",
            "uid": str(index),
            "subject": f"Daily notification 202600{index}",
            "sender": "Notifier <no-reply@example.invalid>",
            "sender_domain": "example.invalid",
            "size_bytes": 100,
            "internal_date": "01-Jan-2020 00:00:00 +0000",
        }
        for index in range(1, 4)
    ]
    groups = _group_inventory(messages)
    assert len(groups) == 1
    assert groups[0]["message_count"] == 3
    assert groups[0]["subject_pattern"] == "daily notification #"


def test_trash_guard_rejects_human_looking_sender() -> None:
    group = {
        "automated": False,
        "message_count": 10,
        "oldest_days": 1000,
        "baseline": {
            "category": "personal",
            "recommendation": "keep",
            "confidence": 0.95,
            "reason": "Potential correspondence",
            "protected": True,
        },
    }
    assert _apply_guards(group, None)["recommendation"] == "keep"


def test_explicit_local_feedback_overrides_model_recommendation() -> None:
    decision = {
        "category": "system",
        "recommendation": "archive_review",
        "confidence": 0.91,
        "reason": "Qwen suggestion",
        "protected": False,
    }
    corrected = _apply_learned_feedback(decision, "keep")
    assert corrected["recommendation"] == "keep"
    assert corrected["protected"] is True
    assert corrected["confidence"] == 1.0


def test_recurring_sweepstakes_are_promotion_cleanup_candidates() -> None:
    group = _group_inventory(
        [
            {
                "folder": "INBOX",
                "uid": str(index),
                "subject": "Jetzt beim Gewinnspiel gewinnen",
                "sender": "Provider Angebote <service@example.invalid>",
                "sender_domain": "example.invalid",
                "size_bytes": 100,
                "internal_date": "01-Jan-2025 00:00:00 +0000",
            }
            for index in range(3)
        ]
    )[0]
    decision = _baseline_decision(group)
    assert group["automated"] is True
    assert decision["category"] == "promotion"
    assert decision["recommendation"] == "trash_review"


def test_webde_provider_campaign_is_detected() -> None:
    assert is_provider_promotion(
        '"WEB.DE informiert" <neu@mailings.web.de>',
        "mailings.web.de",
        "Mehr Vorteile für Sie",
    )
    assert is_provider_promotion(
        '"WEB.DE Gewinnspiel" <noreply_lgs@uim.de>',
        "uim.de",
        "Erhöhen Sie Ihre Gewinnchancen",
    )


def test_webde_account_and_security_mail_is_not_provider_campaign() -> None:
    assert not is_provider_promotion(
        '"WEB.DE Sicherheit" <keineantwortadresse@sicher.web.de>',
        "sicher.web.de",
        "Ihr Passwort wurde geändert",
    )
    assert not is_provider_promotion(
        '"WEB.DE Kundenmanagement" <neu@mailings.web.de>',
        "mailings.web.de",
        "Speicherplatz für E-Mails fast voll",
    )
    assert is_provider_notice(
        '"WEB.DE Sicherheit" <keineantwortadresse@sicher.web.de>', "sicher.web.de"
    )
    assert is_provider_notice('"WEB.DE Kundenmanagement" <neu@mailings.web.de>', "mailings.web.de")
    assert not is_provider_notice("Private Person <person@web.de>", "web.de")


def test_registration_is_protected_from_promotional_substrings() -> None:
    group = _group_inventory(
        [
            {
                "folder": "INBOX",
                "uid": str(index),
                "subject": "Registration confirmation - employee portal",
                "sender": "Employee Benefits <system@benefits.example>",
                "sender_domain": "benefits.example",
                "size_bytes": 100,
                "internal_date": "01-Jan-2020 00:00:00 +0000",
            }
            for index in range(5)
        ]
    )[0]
    decision = _baseline_decision(group)
    assert decision["recommendation"] == "keep"
    assert decision["protected"] is True


def test_word_matching_does_not_confuse_transactions_or_aftersales_with_ads() -> None:
    for sender, subject in [
        ("Marketplace <messages@marketplace.example>", "Review your transaction"),
        ("Supplier Support <support@supplier.example>", "Reply to support conversation"),
        ("Auction Platform <member@auction.example>", "Question about your listed item"),
    ]:
        group = _group_inventory(
            [
                {
                    "folder": "INBOX",
                    "uid": str(index),
                    "subject": subject,
                    "sender": sender,
                    "sender_domain": sender.rsplit("@", 1)[-1].rstrip(">"),
                    "size_bytes": 100,
                    "internal_date": "01-Jan-2020 00:00:00 +0000",
                }
                for index in range(3)
            ]
        )[0]
        assert _baseline_decision(group)["recommendation"] != "trash_review"


def test_recent_campaign_group_cannot_be_sent_to_trash_review() -> None:
    group = _group_inventory(
        [
            {
                "folder": "INBOX",
                "uid": "1",
                "subject": "Special offer sale",
                "sender": "Deals <no-reply@example.invalid>",
                "sender_domain": "example.invalid",
                "size_bytes": 100,
                "internal_date": "01-Jan-2020 00:00:00 +0000",
            },
            {
                "folder": "INBOX",
                "uid": "2",
                "subject": "Special offer sale",
                "sender": "Deals <no-reply@example.invalid>",
                "sender_domain": "example.invalid",
                "size_bytes": 100,
                "internal_date": "25-Aug-2026 00:00:00 +0000",
            },
            {
                "folder": "INBOX",
                "uid": "3",
                "subject": "Special offer sale",
                "sender": "Deals <no-reply@example.invalid>",
                "sender_domain": "example.invalid",
                "size_bytes": 100,
                "internal_date": "25-Aug-2026 00:00:00 +0000",
            },
        ]
    )[0]
    assert _baseline_decision(group)["recommendation"] != "trash_review"


def test_encoded_subject_is_decoded_before_rule_matching() -> None:
    group = _group_inventory(
        [
            {
                "folder": "INBOX",
                "uid": str(index),
                "subject": "=?utf-8?q?Frage_gesendet_=28Angebotsende_morgen=29?=",
                "sender": "eBay member <member@members.ebay.de>",
                "sender_domain": "members.ebay.de",
                "size_bytes": 100,
                "internal_date": "01-Jan-2020 00:00:00 +0000",
            }
            for index in range(3)
        ]
    )[0]
    assert "angebotsende" in group["subject_pattern"]
    assert _baseline_decision(group)["recommendation"] != "trash_review"


def test_provider_account_deletion_notice_beats_campaign_sender_rule() -> None:
    group = _group_inventory(
        [
            {
                "folder": "INBOX",
                "uid": "1",
                "subject": "Achtung: Ihr WEB.DE Postfach wird in Kürze gelöscht",
                "sender": '"WEB.DE Kundenmanagement" <neu@mailings.web.de>',
                "sender_domain": "mailings.web.de",
                "size_bytes": 100,
                "internal_date": "01-Jan-2020 00:00:00 +0000",
            }
        ]
    )[0]
    decision = _baseline_decision(group)
    assert decision["recommendation"] == "keep"
    assert decision["protected"] is True


def test_spam_label_is_not_used_for_legitimate_cleanup_decisions() -> None:
    group = {
        "automated": True,
        "message_count": 10,
        "newest_days": 1000,
        "baseline": {
            "category": "system",
            "recommendation": "archive_review",
            "confidence": 0.9,
            "reason": "Automated mail",
            "protected": False,
        },
    }
    important = GroupDecision(
        group_id="group",
        category="spam",
        recommendation="keep",
        confidence=0.95,
        reason="Legitimate transaction",
        potentially_important=True,
    )
    assert _apply_guards(group, important) == {
        "category": "other",
        "recommendation": "keep",
        "confidence": 0.95,
        "reason": "Qwen identified potentially important content; spam label discarded",
        "protected": True,
    }
    uncertain = important.model_copy(
        update={"potentially_important": False, "recommendation": "archive_review"}
    )
    result = _apply_guards(group, uncertain)
    assert result["category"] == "other"
    assert result["recommendation"] == "manual_review"
    assert result["protected"] is True


def test_attachment_detection_protects_named_parts() -> None:
    raw = (
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=x\r\n\r\n"
        b"--x\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
        b"--x\r\nContent-Type: application/pdf; name=invoice.pdf\r\n"
        b"Content-Disposition: attachment; filename=invoice.pdf\r\n\r\ndata\r\n--x--"
    )
    assert _message_has_attachment(raw) is True


def test_ai_cleanup_run_persists_progress(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "mail.sqlite3")
    job_id = store.create_job("account", "webde")
    run_id = store.create_ai_cleanup_run(job_id, 1)
    store.save_ai_cleanup_suggestion(
        run_id,
        {
            "id": "a" * 64,
            "sender": "no-reply@example.invalid",
            "sender_domain": "example.invalid",
            "subject_pattern": "notification #",
            "message_count": 1,
            "total_bytes": 100,
            "oldest_date": None,
            "newest_date": None,
            "category": "notification",
            "recommendation": "trash_review",
            "confidence": 0.95,
            "reason": "Old automated notification",
            "protected": False,
        },
        [{"folder": "INBOX", "uid": "1"}],
    )
    run = store.ai_cleanup_run(run_id)
    assert run is not None
    assert run["processed_groups"] == 1
    assert store.ai_cleanup_suggestions(run_id)[0]["recommendation"] == "trash_review"
