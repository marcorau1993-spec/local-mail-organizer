from dataclasses import replace
from pathlib import Path

import pytest

from mail_organizer.imap_client import ReviewMessage
from mail_organizer.storage import ScanStore


def message(uid: str, *, newsletter: bool = False, size: int = 1000) -> ReviewMessage:
    return ReviewMessage(
        uid=uid,
        subject="Synthetic subject",
        sender="Sender <sender@example.invalid>",
        list_unsubscribe=newsletter,
        size_bytes=size,
        internal_date=None,
        flags=(),
        sender_domain="example.invalid",
        list_id="list.example.invalid" if newsletter else None,
    )


def test_store_is_resumable_without_double_counting(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    job_id = store.create_job("opaque-account", "webde")
    store.prepare_folders(job_id, [("INBOX", 2)])
    batch = (message("1"), message("2", newsletter=True, size=12_000_000))
    store.store_batch(job_id, "INBOX", batch, 10_000_000)
    store.store_batch(job_id, "INBOX", batch, 10_000_000)
    job = store.job(job_id)
    assert job is not None
    assert job.processed_messages == 2
    assert job.total_bytes == 12_001_000
    assert job.large_messages == 1
    assert job.newsletter_messages == 1


def test_action_groups_prioritize_newsletter_and_archive_signals(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    job_id = store.create_job("opaque-account", "webde")
    store.prepare_folders(job_id, [("INBOX", 2)])
    store.store_batch(
        job_id,
        "INBOX",
        (message("1", newsletter=True), message("2", newsletter=True, size=12_000_000)),
        10_000_000,
    )
    groups = store.action_groups(job_id, 10_000_000)
    assert groups[0]["message_count"] == 2
    assert groups[0]["unsubscribe_count"] == 2
    assert groups[0]["large_count"] == 1
    assert groups[0]["recommendation"] == "unsubscribe_review"


def test_dashboard_uses_persisted_account_scan_and_archive_state(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    store.register_account("opaque-account", "webde")
    job_id = store.create_job("opaque-account", "webde")
    store.prepare_folders(job_id, [("INBOX", 1)])
    store.store_batch(job_id, "INBOX", (message("1", size=12_000_000),), 10_000_000)
    store.set_status(job_id, "completed")
    store.save_archive_destination("opaque-account", "local_nas", str(tmp_path / "archive"))
    summary = store.dashboard_summary(10_000_000, "opaque-account")
    assert summary["connected_accounts"] == 1
    assert summary["potential_space_saved"] == 12_000_000
    assert summary["latest_scan"]["processed_messages"] == 1
    assert summary["archive"]["kind"] == "local_nas"


def test_mailbox_views_are_strictly_account_scoped(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    for account_id, sender in (
        ("account-a", "a@example.invalid"),
        ("account-b", "b@example.invalid"),
    ):
        store.register_account(account_id, "webde")
        job_id = store.create_job(account_id, "webde")
        store.prepare_folders(job_id, [("INBOX", 1)])
        item = message("1", newsletter=True, size=12_000_000)
        item = replace(item, sender=sender)
        store.store_batch(job_id, "INBOX", (item,), 10_000_000)
        store.set_status(job_id, "completed")

    a_summary = store.dashboard_summary(10_000_000, "account-a")
    a_biggest = store.biggest_messages("account-a")
    a_newsletters = store.newsletter_groups("account-a")
    assert {item["job_id"] for item in a_biggest} == {a_summary["latest_scan"]["job_id"]}
    assert {item["sender"] for item in a_newsletters} == {"a@example.invalid"}


def test_sender_ranking_and_sent_views_are_account_scoped(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    for account_id, folder, sender in (
        ("account-a", "Gesendet", "Me <me@example.invalid>"),
        ("account-b", "Sent Items", "Other <other@example.invalid>"),
    ):
        store.register_account(account_id, "webde")
        job_id = store.create_job(account_id, "webde")
        store.prepare_folders(job_id, [(folder, 2)])
        batch = tuple(
            replace(message(str(index), size=index * 1000), sender=sender) for index in range(1, 3)
        )
        store.store_batch(job_id, folder, batch, 10_000_000)
        store.set_status(job_id, "completed")
    assert store.sender_rankings("account-a")[0]["messages"] == 2
    assert store.sender_rankings("account-a")[0]["sender"] == "Me <me@example.invalid>"
    assert {item["folder"] for item in store.sent_messages("account-a")} == {"Gesendet"}
    assert store.sent_summary("account-a") == {
        "messages": 2,
        "bytes": 3000,
        "folders": ["Gesendet"],
    }
    assert {item["sender"] for item in store.sent_messages("account-b")} == {
        "Other <other@example.invalid>"
    }
    job_id, sender_messages = store.messages_from_senders("account-a", ["Me <me@example.invalid>"])
    assert job_id
    assert {item["uid"] for item in sender_messages} == {"1", "2"}
    assert store.messages_from_senders("account-b", ["Me <me@example.invalid>"])[1] == []


def test_newsletter_cleanup_resolves_every_message_in_group(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    job_id = store.create_job("opaque-account", "webde")
    store.prepare_folders(job_id, [("INBOX", 2)])
    store.store_batch(
        job_id,
        "INBOX",
        (message("1", newsletter=True), message("2", newsletter=True)),
        10_000_000,
    )
    items = store.newsletter_messages_for_representative(job_id, "INBOX", "1")
    assert {item["uid"] for item in items} == {"1", "2"}


def test_safety_rules_preferences_and_operations_are_account_scoped(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "scan.sqlite3")
    store.register_account("account-a", "webde")
    store.register_account("account-b", "gmx")
    rule_id = store.save_protection_rule("account-a", "domain", "example.invalid")
    store.update_account_preferences("account-a", {"learning_mode": 0, "max_actions": 10})
    operation_id = store.record_operation("account-a", "job-a", "INBOX", "1", "delete", "Trash")
    assert [item["id"] for item in store.protection_rules("account-a")] == [rule_id]
    assert store.protection_rules("account-b") == []
    assert store.account_preferences("account-a")["max_actions"] == 10
    assert store.account_preferences("account-b")["learning_mode"] == 1
    assert store.operation("account-a", operation_id) is not None
    assert store.operation("account-b", operation_id) is None


def test_ai_feedback_and_retention_are_account_scoped(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "mail.sqlite3")
    feedback_id = store.save_ai_cleanup_feedback(
        "account-a", "example.invalid", "daily report #", "keep"
    )
    assert feedback_id
    assert store.feedback_decision("account-a", "example.invalid", "daily report #") == "keep"
    assert store.feedback_decision("account-b", "example.invalid", "daily report #") is None
    policy_id = store.save_retention_policy("account-a", "notification", "trash_review", 730)
    assert [item["id"] for item in store.retention_policies("account-a")] == [policy_id]
    assert store.retention_policies("account-b") == []


def test_ai_quality_compares_original_model_decision_with_feedback(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "quality.sqlite3")
    store.save_ai_cleanup_feedback(
        "account-a",
        "wrong.example",
        "daily offer",
        "keep",
        "trash_review",
    )
    store.save_ai_cleanup_feedback(
        "account-a",
        "right.example",
        "old notice",
        "archive_review",
        "archive_review",
    )
    metrics = store.ai_quality_metrics("account-a")
    assert metrics["feedback_count"] == 2
    assert metrics["evaluated"] == 2
    assert metrics["agreements"] == 1
    assert metrics["agreement_rate"] == 0.5


def test_feedback_updates_only_current_accounts_suggestion(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "mail.sqlite3")
    job_id = store.create_job("account-a", "webde")
    run_id = store.create_ai_cleanup_run(job_id, 1)
    suggestion_id = "b" * 64
    store.save_ai_cleanup_suggestion(
        run_id,
        {
            "id": suggestion_id,
            "sender": "robot@example.invalid",
            "sender_domain": "example.invalid",
            "subject_pattern": "status",
            "message_count": 3,
            "total_bytes": 300,
            "oldest_date": None,
            "newest_date": None,
            "category": "system",
            "recommendation": "archive_review",
            "confidence": 0.9,
            "reason": "Qwen decision",
            "protected": False,
        },
        [{"folder": "INBOX", "uid": "1"}],
    )
    assert store.apply_ai_cleanup_feedback("account-b", suggestion_id, "trash_review") is False
    assert store.apply_ai_cleanup_feedback("account-a", suggestion_id, "trash_review") is True
    updated = store.ai_cleanup_suggestions(run_id)[0]
    assert updated["recommendation"] == "trash_review"
    assert updated["confidence"] == 1.0


def test_completed_ai_cleanup_members_are_not_offered_again(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "mail.sqlite3")
    job_id = store.create_job("account-a", "webde")
    store.prepare_folders(job_id, [("INBOX", 2)])
    store.store_batch(
        job_id,
        "INBOX",
        (message("1", size=100), message("2", size=200)),
        10_000_000,
    )
    run_id = store.create_ai_cleanup_run(job_id, 1)
    suggestion_id = "c" * 64
    store.save_ai_cleanup_suggestion(
        run_id,
        {
            "id": suggestion_id,
            "sender": "robot@example.invalid",
            "sender_domain": "example.invalid",
            "subject_pattern": "status",
            "message_count": 2,
            "total_bytes": 300,
            "oldest_date": None,
            "newest_date": None,
            "category": "system",
            "recommendation": "trash_review",
            "confidence": 0.9,
            "reason": "Qwen decision",
            "protected": False,
        },
        [{"folder": "INBOX", "uid": "1"}, {"folder": "INBOX", "uid": "2"}],
    )

    pending = store.pending_ai_cleanup_suggestions(run_id)
    assert pending[0]["message_count"] == 2
    assert pending[0]["total_bytes"] == 300

    store.record_action(job_id, "INBOX", "1", "ai_trash", "completed")
    pending = store.pending_ai_cleanup_suggestions(run_id)
    assert pending[0]["message_count"] == 1
    assert pending[0]["total_bytes"] == 200

    store.record_action(job_id, "INBOX", "2", "ai_trash", "source_missing")
    assert store.pending_ai_cleanup_suggestions(run_id) == []
    assert store.ai_cleanup_selection(run_id, [suggestion_id]) == (job_id, [])


def test_automation_runs_are_account_scoped_and_single_flight(tmp_path: Path) -> None:
    store = ScanStore(tmp_path / "mail.sqlite3")
    store.register_account("account-a", "webde")
    store.register_account("account-b", "gmx")
    store.save_filing_rule("account-a", "Invoices", 2030, "Invoices/2030")
    run_id = store.create_automation_run("account-a", "manual")

    with pytest.raises(RuntimeError, match="already running"):
        store.create_automation_run("account-a", "service")

    store.finish_automation_run(
        run_id,
        "completed",
        {"processed": 4, "moved": 2, "deferred": 1},
    )
    status = store.automation_status("account-a")
    assert status["active_rules"] == 1
    assert status["latest_run"]["status"] == "completed"
    assert status["latest_run"]["moved"] == 2
    assert store.automation_status("account-b")["runs"] == []
