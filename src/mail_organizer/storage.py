"""Local SQLite persistence for resumable mailbox inventory and plans."""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .imap_client import ReviewMessage


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    account_id: str
    provider: str
    status: str
    current_folder: str | None
    total_messages: int
    processed_messages: int
    total_bytes: int
    large_messages: int
    newsletter_messages: int
    created_at: str
    updated_at: str
    error: str | None

    @property
    def progress_percent(self) -> float:
        if self.total_messages == 0:
            return 0.0 if self.status != "completed" else 100.0
        return round(self.processed_messages * 100 / self.total_messages, 1)


class ScanStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        statements = [
            """CREATE TABLE IF NOT EXISTS scan_jobs (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, provider TEXT NOT NULL,
                status TEXT NOT NULL, current_folder TEXT, total_messages INTEGER NOT NULL DEFAULT 0,
                processed_messages INTEGER NOT NULL DEFAULT 0, total_bytes INTEGER NOT NULL DEFAULT 0,
                large_messages INTEGER NOT NULL DEFAULT 0, newsletter_messages INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS scan_folders (
                job_id TEXT NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
                name TEXT NOT NULL, total_messages INTEGER NOT NULL DEFAULT 0,
                processed_messages INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (job_id, name)
            )""",
            """CREATE TABLE IF NOT EXISTS inventory_messages (
                job_id TEXT NOT NULL REFERENCES scan_jobs(id) ON DELETE CASCADE,
                folder TEXT NOT NULL, uid TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL,
                sender_domain TEXT NOT NULL, list_id TEXT, list_unsubscribe INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL, internal_date TEXT, flags_json TEXT NOT NULL,
                PRIMARY KEY (job_id, folder, uid)
            )""",
            """CREATE TABLE IF NOT EXISTS accounts (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, connected_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS archive_destinations (
                id INTEGER PRIMARY KEY CHECK (id = 1), kind TEXT NOT NULL,
                root_path TEXT NOT NULL, verified_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS account_archive_destinations (
                account_id TEXT PRIMARY KEY, kind TEXT NOT NULL,
                root_path TEXT NOT NULL, verified_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS action_audit (
                id TEXT PRIMARY KEY, job_id TEXT NOT NULL, folder TEXT NOT NULL,
                uid TEXT NOT NULL, action TEXT NOT NULL, result TEXT NOT NULL,
                created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS ai_cleanup_runs (
                id TEXT PRIMARY KEY, scan_job_id TEXT NOT NULL,
                status TEXT NOT NULL, total_groups INTEGER NOT NULL DEFAULT 0,
                processed_groups INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS ai_cleanup_suggestions (
                id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES ai_cleanup_runs(id) ON DELETE CASCADE,
                sender TEXT NOT NULL, sender_domain TEXT NOT NULL, subject_pattern TEXT NOT NULL,
                message_count INTEGER NOT NULL, total_bytes INTEGER NOT NULL,
                oldest_date TEXT, newest_date TEXT, category TEXT NOT NULL,
                recommendation TEXT NOT NULL, confidence REAL NOT NULL,
                reason TEXT NOT NULL, protected INTEGER NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS ai_cleanup_members (
                suggestion_id TEXT NOT NULL REFERENCES ai_cleanup_suggestions(id) ON DELETE CASCADE,
                folder TEXT NOT NULL, uid TEXT NOT NULL,
                PRIMARY KEY (suggestion_id, folder, uid)
            )""",
            """CREATE TABLE IF NOT EXISTS filing_rules (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, bucket TEXT NOT NULL,
                target_year INTEGER NOT NULL, destination TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(account_id, bucket, target_year)
            )""",
            """CREATE TABLE IF NOT EXISTS automation_audit (
                account_id TEXT NOT NULL, folder TEXT NOT NULL, uid TEXT NOT NULL,
                result TEXT NOT NULL, destination TEXT, detail TEXT,
                processed_at TEXT NOT NULL,
                PRIMARY KEY (account_id, folder, uid)
            )""",
            """CREATE TABLE IF NOT EXISTS automation_runs (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, trigger TEXT NOT NULL,
                status TEXT NOT NULL, processed INTEGER NOT NULL DEFAULT 0,
                moved INTEGER NOT NULL DEFAULT 0, deferred INTEGER NOT NULL DEFAULT 0,
                started_at TEXT NOT NULL, finished_at TEXT, error TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS security_allowlist (
                sender_address TEXT PRIMARY KEY, created_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS account_security_allowlist (
                account_id TEXT NOT NULL, sender_address TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY (account_id, sender_address)
            )""",
            """CREATE TABLE IF NOT EXISTS protection_rules (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, kind TEXT NOT NULL,
                value TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, UNIQUE(account_id, kind, value)
            )""",
            """CREATE TABLE IF NOT EXISTS operation_events (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, job_id TEXT NOT NULL,
                folder TEXT NOT NULL, uid TEXT NOT NULL, action TEXT NOT NULL,
                destination TEXT, status TEXT NOT NULL, undo_status TEXT,
                created_at TEXT NOT NULL, undone_at TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS account_preferences (
                account_id TEXT PRIMARY KEY, paused INTEGER NOT NULL DEFAULT 0,
                learning_mode INTEGER NOT NULL DEFAULT 1,
                schedule_minutes INTEGER NOT NULL DEFAULT 15,
                max_actions INTEGER NOT NULL DEFAULT 25,
                notify_errors INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS security_ai_reviews (
                job_id TEXT NOT NULL, folder TEXT NOT NULL, uid TEXT NOT NULL,
                verdict TEXT NOT NULL, confidence REAL NOT NULL, reason TEXT NOT NULL,
                reviewed_at TEXT NOT NULL, PRIMARY KEY(job_id, folder, uid)
            )""",
            """CREATE TABLE IF NOT EXISTS ai_cleanup_feedback (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL,
                sender_domain TEXT NOT NULL, subject_pattern TEXT NOT NULL,
                decision TEXT NOT NULL, model_decision TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(account_id, sender_domain, subject_pattern)
            )""",
            """CREATE TABLE IF NOT EXISTS retention_policies (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, category TEXT NOT NULL,
                action TEXT NOT NULL, age_days INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, UNIQUE(account_id, category)
            )""",
            """CREATE TABLE IF NOT EXISTS action_inbox_state (
                account_id TEXT NOT NULL, job_id TEXT NOT NULL, folder TEXT NOT NULL,
                uid TEXT NOT NULL, status TEXT NOT NULL, updated_at TEXT NOT NULL,
                PRIMARY KEY(account_id, job_id, folder, uid)
            )""",
            """CREATE TABLE IF NOT EXISTS attachment_index (
                account_id TEXT NOT NULL, job_id TEXT NOT NULL, folder TEXT NOT NULL,
                uid TEXT NOT NULL, filename TEXT NOT NULL, content_type TEXT NOT NULL,
                size_bytes INTEGER NOT NULL, sha256 TEXT NOT NULL, category TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                PRIMARY KEY(account_id, job_id, folder, uid, filename, sha256)
            )""",
            """CREATE TABLE IF NOT EXISTS content_index_runs (
                id TEXT PRIMARY KEY, account_id TEXT NOT NULL, scan_job_id TEXT NOT NULL,
                status TEXT NOT NULL, total_messages INTEGER NOT NULL DEFAULT 0,
                processed_messages INTEGER NOT NULL DEFAULT 0,
                indexed_messages INTEGER NOT NULL DEFAULT 0,
                skipped_messages INTEGER NOT NULL DEFAULT 0, current_folder TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error TEXT
            )""",
            """CREATE TABLE IF NOT EXISTS message_content (
                account_id TEXT NOT NULL, job_id TEXT NOT NULL, folder TEXT NOT NULL,
                uid TEXT NOT NULL, subject TEXT NOT NULL, sender TEXT NOT NULL,
                body_text TEXT NOT NULL, content_hash TEXT NOT NULL, indexed_at TEXT NOT NULL,
                PRIMARY KEY(account_id, job_id, folder, uid)
            )""",
            """CREATE VIRTUAL TABLE IF NOT EXISTS message_content_fts USING fts5(
                account_id UNINDEXED, job_id UNINDEXED, folder UNINDEXED, uid UNINDEXED,
                subject, sender, body_text,
                tokenize='unicode61 remove_diacritics 2'
            )""",
            "CREATE INDEX IF NOT EXISTS idx_inventory_job_sender ON inventory_messages(job_id, sender_domain, sender)",
            "CREATE INDEX IF NOT EXISTS idx_inventory_job_list ON inventory_messages(job_id, list_unsubscribe, list_id)",
            "CREATE INDEX IF NOT EXISTS idx_inventory_job_size ON inventory_messages(job_id, size_bytes)",
            "CREATE INDEX IF NOT EXISTS idx_scan_jobs_account_created ON scan_jobs(account_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_action_audit_message_action ON action_audit(job_id, folder, uid, action, result)",
            "CREATE INDEX IF NOT EXISTS idx_ai_cleanup_run_recommendation ON ai_cleanup_suggestions(run_id, recommendation, protected)",
            "CREATE INDEX IF NOT EXISTS idx_ai_cleanup_members_suggestion ON ai_cleanup_members(suggestion_id)",
            "CREATE INDEX IF NOT EXISTS idx_filing_rules_account_enabled ON filing_rules(account_id, enabled)",
            "CREATE INDEX IF NOT EXISTS idx_automation_audit_processed ON automation_audit(processed_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_automation_runs_account_started ON automation_runs(account_id, started_at DESC)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_automation_runs_account_running ON automation_runs(account_id) WHERE status='running'",
            "CREATE INDEX IF NOT EXISTS idx_operation_events_account_created ON operation_events(account_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_ai_feedback_account_match ON ai_cleanup_feedback(account_id, sender_domain, subject_pattern)",
            "CREATE INDEX IF NOT EXISTS idx_retention_account_enabled ON retention_policies(account_id, enabled)",
            "CREATE INDEX IF NOT EXISTS idx_action_inbox_account_status ON action_inbox_state(account_id, status)",
            "CREATE INDEX IF NOT EXISTS idx_attachment_account_category ON attachment_index(account_id, category)",
            "CREATE INDEX IF NOT EXISTS idx_attachment_hash ON attachment_index(account_id, sha256)",
            "CREATE INDEX IF NOT EXISTS idx_content_runs_account_created ON content_index_runs(account_id, created_at DESC)",
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_content_runs_account_running ON content_index_runs(account_id) WHERE status='running'",
            "CREATE INDEX IF NOT EXISTS idx_message_content_account_job ON message_content(account_id, job_id)",
        ]
        with closing(self._connect()) as connection:
            for statement in statements:
                connection.execute(statement)
            feedback_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(ai_cleanup_feedback)")
            }
            if "model_decision" not in feedback_columns:
                connection.execute("ALTER TABLE ai_cleanup_feedback ADD COLUMN model_decision TEXT")
            attachment_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(attachment_index)")
            }
            if "extracted_text" not in attachment_columns:
                connection.execute("ALTER TABLE attachment_index ADD COLUMN extracted_text TEXT")
            if "extraction_status" not in attachment_columns:
                connection.execute("ALTER TABLE attachment_index ADD COLUMN extraction_status TEXT")
            if "extraction_method" not in attachment_columns:
                connection.execute("ALTER TABLE attachment_index ADD COLUMN extraction_method TEXT")
            connection.execute(
                """INSERT OR IGNORE INTO accounts (id, provider, connected_at)
                SELECT account_id, provider, MIN(created_at) FROM scan_jobs
                GROUP BY account_id, provider"""
            )
            connection.execute(
                """INSERT OR IGNORE INTO account_archive_destinations
                (account_id, kind, root_path, verified_at)
                SELECT a.id, d.kind, d.root_path, d.verified_at
                FROM accounts a CROSS JOIN archive_destinations d WHERE d.id=1"""
            )
            connection.execute("PRAGMA optimize")
            connection.commit()

    def register_account(self, account_id: str, provider: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO accounts (id, provider, connected_at) VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET provider=excluded.provider""",
                (account_id, provider, _now()),
            )
            connection.commit()

    def save_archive_destination(self, account_id: str, kind: str, root_path: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO account_archive_destinations
                (account_id, kind, root_path, verified_at)
                VALUES (?, ?, ?, ?) ON CONFLICT(account_id) DO UPDATE SET
                kind=excluded.kind, root_path=excluded.root_path,
                verified_at=excluded.verified_at""",
                (account_id, kind, root_path, _now()),
            )
            connection.commit()

    def archive_destination(self, account_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT kind, root_path, verified_at
                FROM account_archive_destinations WHERE account_id=?""",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None

    def accounts(self) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT id, provider, connected_at FROM accounts ORDER BY connected_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def account(self, account_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT id, provider, connected_at FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
        return dict(row) if row else None

    def protection_rules(self, account_id: str) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT id, kind, value, enabled, created_at FROM protection_rules
                WHERE account_id=? ORDER BY kind, value""",
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_protection_rule(self, account_id: str, kind: str, value: str) -> str:
        rule_id = uuid4().hex
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO protection_rules (id, account_id, kind, value, enabled, created_at)
                VALUES (?, ?, ?, ?, 1, ?) ON CONFLICT(account_id, kind, value)
                DO UPDATE SET enabled=1""",
                (rule_id, account_id, kind, value.casefold().strip(), _now()),
            )
            connection.commit()
        return rule_id

    def delete_protection_rule(self, account_id: str, rule_id: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM protection_rules WHERE id=? AND account_id=?", (rule_id, account_id)
            )
            connection.commit()

    def record_operation(
        self,
        account_id: str,
        job_id: str,
        folder: str,
        uid: str,
        action: str,
        destination: str | None,
        status: str = "completed",
    ) -> str:
        operation_id = uuid4().hex
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO operation_events
                (id, account_id, job_id, folder, uid, action, destination, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    operation_id,
                    account_id,
                    job_id,
                    folder,
                    uid,
                    action,
                    destination,
                    status,
                    _now(),
                ),
            )
            connection.commit()
        return operation_id

    def operations(self, account_id: str, limit: int = 500) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM operation_events WHERE account_id=?
                ORDER BY created_at DESC LIMIT ?""",
                (account_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def operation(self, account_id: str, operation_id: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM operation_events WHERE id=? AND account_id=?",
                (operation_id, account_id),
            ).fetchone()
        return dict(row) if row else None

    def mark_operation_undone(self, operation_id: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE operation_events SET undo_status='completed', undone_at=? WHERE id=?",
                (_now(), operation_id),
            )
            connection.commit()

    def account_preferences(self, account_id: str) -> dict[str, object]:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO account_preferences
                (account_id, updated_at) VALUES (?, ?)""",
                (account_id, _now()),
            )
            connection.commit()
            row = connection.execute(
                "SELECT * FROM account_preferences WHERE account_id=?", (account_id,)
            ).fetchone()
        return dict(row)

    def update_account_preferences(self, account_id: str, values: dict[str, object]) -> None:
        current = self.account_preferences(account_id)
        merged = {**current, **values}
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE account_preferences SET paused=?, learning_mode=?,
                schedule_minutes=?, max_actions=?, notify_errors=?, updated_at=?
                WHERE account_id=?""",
                (
                    int(merged["paused"]),
                    int(merged["learning_mode"]),
                    int(merged["schedule_minutes"]),
                    int(merged["max_actions"]),
                    int(merged["notify_errors"]),
                    _now(),
                    account_id,
                ),
            )
            connection.commit()

    def save_ai_cleanup_feedback(
        self,
        account_id: str,
        sender_domain: str,
        subject_pattern: str,
        decision: str,
        model_decision: str | None = None,
    ) -> str:
        feedback_id = uuid4().hex
        timestamp = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO ai_cleanup_feedback
                (id, account_id, sender_domain, subject_pattern, decision,
                model_decision, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, sender_domain, subject_pattern) DO UPDATE SET
                decision=excluded.decision,
                model_decision=COALESCE(ai_cleanup_feedback.model_decision,
                    excluded.model_decision), updated_at=excluded.updated_at""",
                (
                    feedback_id,
                    account_id,
                    sender_domain.casefold().strip(),
                    subject_pattern.casefold().strip(),
                    decision,
                    model_decision,
                    timestamp,
                    timestamp,
                ),
            )
            connection.commit()
            row = connection.execute(
                """SELECT id FROM ai_cleanup_feedback WHERE account_id=?
                AND sender_domain=? AND subject_pattern=?""",
                (
                    account_id,
                    sender_domain.casefold().strip(),
                    subject_pattern.casefold().strip(),
                ),
            ).fetchone()
        return str(row["id"])

    def ai_cleanup_feedback(self, account_id: str) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT id, sender_domain, subject_pattern, decision,
                model_decision, updated_at
                FROM ai_cleanup_feedback WHERE account_id=? ORDER BY updated_at DESC""",
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def apply_ai_cleanup_feedback(self, account_id: str, suggestion_id: str, decision: str) -> bool:
        protected = int(decision == "keep")
        reason = f"Learned from your account-local correction: {decision.replace('_', ' ')}"
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                """UPDATE ai_cleanup_suggestions SET recommendation=?, confidence=1.0,
                reason=?, protected=? WHERE id=? AND EXISTS (
                    SELECT 1 FROM ai_cleanup_runs r JOIN scan_jobs j
                    ON j.id=r.scan_job_id WHERE r.id=ai_cleanup_suggestions.run_id
                    AND j.account_id=?
                )""",
                (decision, reason, protected, suggestion_id, account_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    def feedback_decision(
        self, account_id: str, sender_domain: str, subject_pattern: str
    ) -> str | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT decision FROM ai_cleanup_feedback WHERE account_id=?
                AND sender_domain=? AND subject_pattern=?""",
                (account_id, sender_domain.casefold().strip(), subject_pattern.casefold().strip()),
            ).fetchone()
        return str(row["decision"]) if row else None

    def save_retention_policy(
        self, account_id: str, category: str, action: str, age_days: int
    ) -> str:
        policy_id = uuid4().hex
        timestamp = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO retention_policies
                (id, account_id, category, action, age_days, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(account_id, category) DO UPDATE SET action=excluded.action,
                age_days=excluded.age_days, enabled=1, updated_at=excluded.updated_at""",
                (policy_id, account_id, category, action, age_days, timestamp, timestamp),
            )
            connection.commit()
            row = connection.execute(
                "SELECT id FROM retention_policies WHERE account_id=? AND category=?",
                (account_id, category),
            ).fetchone()
        return str(row["id"])

    def retention_policies(self, account_id: str) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT id, category, action, age_days, enabled, updated_at
                FROM retention_policies WHERE account_id=? ORDER BY category""",
                (account_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_retention_policy(self, account_id: str, policy_id: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "DELETE FROM retention_policies WHERE id=? AND account_id=?",
                (policy_id, account_id),
            )
            connection.commit()

    def dashboard_summary(self, large_threshold: int, account_id: str) -> dict[str, object]:
        with closing(self._connect()) as connection:
            account_count = int(connection.execute("SELECT COUNT(*) FROM accounts").fetchone()[0])
            latest = connection.execute(
                """SELECT * FROM scan_jobs
                WHERE account_id=?
                ORDER BY CASE WHEN status='completed' THEN 0 ELSE 1 END, created_at DESC
                LIMIT 1""",
                (account_id,),
            ).fetchone()
            potential_bytes = 0
            if latest is not None:
                potential_bytes = int(
                    connection.execute(
                        """SELECT COALESCE(SUM(size_bytes), 0) FROM inventory_messages
                        WHERE job_id=? AND size_bytes>=?""",
                        (latest["id"], large_threshold),
                    ).fetchone()[0]
                )
        return {
            "connected_accounts": account_count,
            "latest_scan": _public_job_dict(latest),
            "potential_space_saved": potential_bytes,
            "archive": self.archive_destination(account_id),
        }

    def latest_inventory(self, account_id: str, limit: int = 50_000) -> list[dict[str, object]]:
        latest = self.latest_job(account_id)
        if latest is None:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT job_id, folder, uid, subject, sender, sender_domain,
                list_id, list_unsubscribe, size_bytes, internal_date, flags_json
                FROM inventory_messages m
                WHERE job_id=? AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid AND a.result='completed'
                    AND a.action IN ('delete', 'archive', 'export_delete', 'ai_trash', 'ai_archive')
                ) LIMIT ?""",
                (latest.id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def action_inbox_states(self, account_id: str) -> dict[tuple[str, str, str], str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT job_id, folder, uid, status FROM action_inbox_state
                WHERE account_id=?""",
                (account_id,),
            ).fetchall()
        return {
            (str(row["job_id"]), str(row["folder"]), str(row["uid"])): str(row["status"])
            for row in rows
        }

    def save_action_inbox_state(
        self, account_id: str, job_id: str, folder: str, uid: str, status: str
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO action_inbox_state
                (account_id, job_id, folder, uid, status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, job_id, folder, uid)
                DO UPDATE SET status=excluded.status, updated_at=excluded.updated_at""",
                (account_id, job_id, folder, uid, status, _now()),
            )
            connection.commit()

    def replace_message_attachments(
        self,
        account_id: str,
        job_id: str,
        folder: str,
        uid: str,
        attachments: list[dict[str, object]],
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """DELETE FROM attachment_index WHERE account_id=? AND job_id=?
                AND folder=? AND uid=?""",
                (account_id, job_id, folder, uid),
            )
            connection.executemany(
                """INSERT INTO attachment_index
                (account_id, job_id, folder, uid, filename, content_type,
                size_bytes, sha256, category, indexed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        account_id,
                        job_id,
                        folder,
                        uid,
                        item["filename"],
                        item["content_type"],
                        item["size_bytes"],
                        item["sha256"],
                        item["category"],
                        _now(),
                    )
                    for item in attachments
                ],
            )
            connection.commit()

    def attachment_insights(self, account_id: str, limit: int = 1000) -> dict[str, object]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT a.*, i.subject, i.sender, i.internal_date,
                COUNT(*) OVER (PARTITION BY a.account_id, a.sha256) AS copies
                FROM attachment_index a JOIN inventory_messages i
                ON i.job_id=a.job_id AND i.folder=a.folder AND i.uid=a.uid
                WHERE a.account_id=? ORDER BY a.size_bytes DESC LIMIT ?""",
                (account_id, limit),
            ).fetchall()
            summary = connection.execute(
                """SELECT COUNT(*) AS attachments, COALESCE(SUM(size_bytes),0) AS bytes,
                COUNT(DISTINCT sha256) AS unique_files FROM attachment_index
                WHERE account_id=?""",
                (account_id,),
            ).fetchone()
        return {"summary": dict(summary), "items": [dict(row) for row in rows]}

    def save_attachment_text(
        self,
        account_id: str,
        job_id: str,
        folder: str,
        uid: str,
        sha256: str,
        text: str,
        method: str,
    ) -> None:
        status = "extracted" if text else method
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE attachment_index SET extracted_text=?, extraction_status=?,
                extraction_method=?, indexed_at=? WHERE account_id=? AND job_id=?
                AND folder=? AND uid=? AND sha256=?""",
                (text, status, method, _now(), account_id, job_id, folder, uid, sha256),
            )
            connection.commit()

    def create_content_index_run(self, account_id: str) -> str:
        latest = self.latest_job(account_id)
        if latest is None or latest.status != "completed":
            raise LookupError("Run a complete mailbox scan before building the content index")
        run_id = uuid4().hex
        with closing(self._connect()) as connection:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM inventory_messages WHERE job_id=?", (latest.id,)
                ).fetchone()[0]
            )
            existing = int(
                connection.execute(
                    """SELECT COUNT(*) FROM message_content
                    WHERE account_id=? AND job_id=?""",
                    (account_id, latest.id),
                ).fetchone()[0]
            )
            try:
                connection.execute(
                    """INSERT INTO content_index_runs
                    (id, account_id, scan_job_id, status, total_messages,
                    processed_messages, indexed_messages, created_at, updated_at)
                    VALUES (?, ?, ?, 'running', ?, ?, ?, ?, ?)""",
                    (run_id, account_id, latest.id, total, existing, existing, _now(), _now()),
                )
                connection.commit()
            except sqlite3.IntegrityError as exc:
                raise RuntimeError("Content indexing is already running for this account") from exc
        return run_id

    def content_index_pending(
        self, run_id: str
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        with closing(self._connect()) as connection:
            run = connection.execute(
                "SELECT * FROM content_index_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise LookupError("Content index run does not exist")
            rows = connection.execute(
                """SELECT i.job_id, i.folder, i.uid, i.subject, i.sender, i.size_bytes
                FROM inventory_messages i WHERE i.job_id=? AND NOT EXISTS (
                    SELECT 1 FROM message_content c WHERE c.account_id=?
                    AND c.job_id=i.job_id AND c.folder=i.folder AND c.uid=i.uid
                ) ORDER BY i.folder, CAST(i.uid AS INTEGER)""",
                (run["scan_job_id"], run["account_id"]),
            ).fetchall()
        return dict(run), [dict(row) for row in rows]

    def recover_content_index_runs(self) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE content_index_runs SET status='interrupted',
                error='The previous local process stopped; start indexing to resume',
                updated_at=? WHERE status='running'""",
                (_now(),),
            )
            connection.commit()

    def store_message_content(
        self,
        account_id: str,
        job_id: str,
        folder: str,
        uid: str,
        subject: str,
        sender: str,
        body_text: str,
        content_hash: str,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO message_content
                (account_id, job_id, folder, uid, subject, sender, body_text,
                content_hash, indexed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, job_id, folder, uid) DO UPDATE SET
                subject=excluded.subject, sender=excluded.sender,
                body_text=excluded.body_text, content_hash=excluded.content_hash,
                indexed_at=excluded.indexed_at""",
                (
                    account_id,
                    job_id,
                    folder,
                    uid,
                    subject,
                    sender,
                    body_text,
                    content_hash,
                    _now(),
                ),
            )
            connection.execute(
                """DELETE FROM message_content_fts WHERE account_id=? AND job_id=?
                AND folder=? AND uid=?""",
                (account_id, job_id, folder, uid),
            )
            connection.execute(
                """INSERT INTO message_content_fts
                (account_id, job_id, folder, uid, subject, sender, body_text)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (account_id, job_id, folder, uid, subject, sender, body_text),
            )
            connection.commit()

    def advance_content_index(
        self, run_id: str, folder: str, *, indexed: bool, skipped: bool = False
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE content_index_runs SET
                processed_messages=processed_messages+1,
                indexed_messages=indexed_messages+?,
                skipped_messages=skipped_messages+?, current_folder=?, updated_at=?
                WHERE id=?""",
                (int(indexed), int(skipped), folder, _now(), run_id),
            )
            connection.commit()

    def finish_content_index(self, run_id: str, status: str, error: str | None = None) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE content_index_runs SET status=?, error=?, current_folder=NULL,
                updated_at=? WHERE id=?""",
                (status, error, _now(), run_id),
            )
            connection.commit()

    def content_index_status(self, account_id: str) -> dict[str, object]:
        latest_job = self.latest_job(account_id)
        with closing(self._connect()) as connection:
            run = connection.execute(
                """SELECT * FROM content_index_runs WHERE account_id=?
                ORDER BY created_at DESC LIMIT 1""",
                (account_id,),
            ).fetchone()
            indexed = 0
            if latest_job is not None:
                indexed = int(
                    connection.execute(
                        """SELECT COUNT(*) FROM message_content
                        WHERE account_id=? AND job_id=?""",
                        (account_id, latest_job.id),
                    ).fetchone()[0]
                )
        result = dict(run) if run else None
        if result:
            total = int(result["total_messages"])
            result["progress_percent"] = (
                round(int(result["processed_messages"]) * 100 / total, 1) if total else 100.0
            )
        return {
            "run": result,
            "indexed_messages": indexed,
            "scan_job_id": latest_job.id if latest_job else None,
            "scan_messages": latest_job.total_messages if latest_job else 0,
        }

    def delete_content_index(self, account_id: str) -> None:
        with closing(self._connect()) as connection:
            running = connection.execute(
                """SELECT 1 FROM content_index_runs
                WHERE account_id=? AND status='running' LIMIT 1""",
                (account_id,),
            ).fetchone()
            if running:
                raise RuntimeError("Wait for content indexing to finish before clearing it")
            connection.execute("DELETE FROM message_content_fts WHERE account_id=?", (account_id,))
            connection.execute("DELETE FROM message_content WHERE account_id=?", (account_id,))
            connection.execute("DELETE FROM content_index_runs WHERE account_id=?", (account_id,))
            connection.commit()

    def search_message_content(
        self, account_id: str, query: str, limit: int = 120
    ) -> list[dict[str, object]]:
        latest = self.latest_job(account_id)
        if latest is None:
            return []
        terms = [term for term in re.findall(r"[^\W_]+", query, flags=re.UNICODE) if len(term) > 1]
        if not terms:
            return []
        match_query = " AND ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT f.job_id, f.folder, f.uid, f.subject, f.sender,
                snippet(message_content_fts, 6, '[', ']', ' … ', 24) AS body_snippet,
                bm25(message_content_fts, 0, 0, 0, 0, 8.0, 5.0, 1.0) AS search_rank,
                i.sender_domain, i.size_bytes, i.internal_date, i.flags_json
                FROM message_content_fts f JOIN inventory_messages i
                ON i.job_id=f.job_id AND i.folder=f.folder AND i.uid=f.uid
                WHERE message_content_fts MATCH ? AND f.account_id=? AND f.job_id=?
                ORDER BY search_rank LIMIT ?""",
                (match_query, account_id, latest.id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def ai_quality_metrics(self, account_id: str) -> dict[str, object]:
        run = self.ai_cleanup_run(account_id=account_id)
        feedback = self.ai_cleanup_feedback(account_id)
        feedback_map = {
            (str(item["sender_domain"]), str(item["subject_pattern"])): item
            for item in feedback
            if item.get("model_decision")
        }
        evaluated = list(feedback_map.values())
        agreements = sum(str(item["model_decision"]) == str(item["decision"]) for item in evaluated)
        return {
            "feedback_count": len(feedback),
            "evaluated": len(evaluated),
            "agreements": agreements,
            "agreement_rate": round(agreements / len(evaluated), 3) if evaluated else None,
            "run_id": run["id"] if run else None,
        }

    def biggest_messages(self, account_id: str, limit: int = 250) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            latest = connection.execute(
                "SELECT id FROM scan_jobs WHERE status='completed' AND account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if latest is None:
                return []
            rows = connection.execute(
                """SELECT job_id, folder, uid, subject, sender, size_bytes, internal_date
                FROM inventory_messages m WHERE job_id=? AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.action IN ('delete', 'archive', 'export_delete')
                    AND a.result='completed'
                )
                ORDER BY size_bytes DESC LIMIT ?""",
                (latest["id"], limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def sender_rankings(self, account_id: str, limit: int = 500) -> list[dict[str, object]]:
        latest = self.latest_job(account_id)
        if latest is None:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT sender, sender_domain, COUNT(*) AS messages,
                COALESCE(SUM(size_bytes), 0) AS bytes,
                MIN(internal_date) AS oldest_date, MAX(internal_date) AS newest_date
                FROM inventory_messages m WHERE job_id=?
                AND lower(folder) NOT LIKE '%trash%' AND lower(folder) NOT LIKE '%deleted%'
                AND lower(folder) NOT LIKE '%papierkorb%'
                AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.action IN ('delete', 'archive', 'export_delete')
                    AND a.result='completed'
                )
                GROUP BY lower(sender), lower(sender_domain)
                ORDER BY messages DESC, bytes DESC LIMIT ?""",
                (latest.id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def messages_from_senders(
        self, account_id: str, senders: list[str]
    ) -> tuple[str, list[dict[str, object]]]:
        latest = self.latest_job(account_id)
        if latest is None or not senders:
            return "", []
        placeholders = ",".join("?" for _ in senders)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT job_id, folder, uid, subject, sender, sender_domain,
                size_bytes, internal_date FROM inventory_messages m
                WHERE job_id=? AND lower(sender) IN ({placeholders})
                AND lower(folder) NOT LIKE '%trash%' AND lower(folder) NOT LIKE '%deleted%'
                AND lower(folder) NOT LIKE '%papierkorb%'
                AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.action IN ('delete', 'archive', 'export_delete')
                    AND a.result='completed'
                ) ORDER BY size_bytes DESC""",
                (latest.id, *(sender.casefold() for sender in senders)),
            ).fetchall()
        return latest.id, [dict(row) for row in rows]

    def sent_messages(self, account_id: str, limit: int = 500) -> list[dict[str, object]]:
        latest = self.latest_job(account_id)
        if latest is None:
            return []
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT job_id, folder, uid, subject, sender, size_bytes, internal_date
                FROM inventory_messages m WHERE job_id=? AND (
                    lower(folder) LIKE '%sent%' OR lower(folder) LIKE '%gesendet%'
                    OR lower(folder) LIKE '%postausgang%' OR lower(folder) LIKE '%enviado%'
                    OR lower(folder) LIKE '%envoyé%' OR lower(folder) LIKE '%posta inviata%'
                ) AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.action IN ('delete', 'archive', 'export_delete')
                    AND a.result='completed'
                ) ORDER BY size_bytes DESC LIMIT ?""",
                (latest.id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def sent_summary(self, account_id: str) -> dict[str, object]:
        latest = self.latest_job(account_id)
        if latest is None:
            return {"messages": 0, "bytes": 0, "folders": []}
        folder_match = """(
            lower(folder) LIKE '%sent%' OR lower(folder) LIKE '%gesendet%'
            OR lower(folder) LIKE '%postausgang%' OR lower(folder) LIKE '%enviado%'
            OR lower(folder) LIKE '%envoyé%' OR lower(folder) LIKE '%posta inviata%'
        )"""
        with closing(self._connect()) as connection:
            total = connection.execute(
                f"""SELECT COUNT(*) AS messages, COALESCE(SUM(size_bytes), 0) AS bytes
                FROM inventory_messages WHERE job_id=? AND {folder_match}""",
                (latest.id,),
            ).fetchone()
            folders = connection.execute(
                f"""SELECT DISTINCT folder FROM inventory_messages
                WHERE job_id=? AND {folder_match} ORDER BY folder""",
                (latest.id,),
            ).fetchall()
        return {**dict(total), "folders": [str(row["folder"]) for row in folders]}

    def mailbox_insights(self, account_id: str) -> dict[str, object]:
        latest = self.latest_job(account_id)
        if latest is None:
            return {"by_year": [], "by_sender": [], "by_folder": [], "duplicates": []}
        with closing(self._connect()) as connection:
            by_sender = connection.execute(
                """SELECT sender_domain AS label, COUNT(*) AS messages,
                SUM(size_bytes) AS bytes FROM inventory_messages WHERE job_id=?
                GROUP BY sender_domain ORDER BY bytes DESC LIMIT 30""",
                (latest.id,),
            ).fetchall()
            by_folder = connection.execute(
                """SELECT folder AS label, COUNT(*) AS messages, SUM(size_bytes) AS bytes
                FROM inventory_messages WHERE job_id=? GROUP BY folder
                ORDER BY bytes DESC""",
                (latest.id,),
            ).fetchall()
            by_year = connection.execute(
                """SELECT CASE WHEN internal_date GLOB '__-___-____*'
                THEN substr(internal_date, 8, 4)
                ELSE COALESCE(substr(internal_date, 1, 4), 'Unknown') END AS label,
                COUNT(*) AS messages, SUM(size_bytes) AS bytes FROM inventory_messages
                WHERE job_id=? GROUP BY label ORDER BY label DESC""",
                (latest.id,),
            ).fetchall()
            duplicates = connection.execute(
                """SELECT subject, sender, size_bytes, COUNT(*) AS copies,
                GROUP_CONCAT(folder || ':' || uid) AS members
                FROM inventory_messages WHERE job_id=? AND size_bytes>0
                GROUP BY lower(subject), lower(sender), size_bytes HAVING COUNT(*)>1
                ORDER BY (COUNT(*)-1)*size_bytes DESC LIMIT 250""",
                (latest.id,),
            ).fetchall()
        return {
            "by_sender": [dict(row) for row in by_sender],
            "by_folder": [dict(row) for row in by_folder],
            "by_year": [dict(row) for row in by_year],
            "duplicates": [dict(row) for row in duplicates],
        }

    def mailbox_health(self, account_id: str) -> dict[str, object]:
        latest = self.latest_job(account_id)
        if latest is None:
            return {"score": 0, "history": [], "current": None}
        with closing(self._connect()) as connection:
            history = connection.execute(
                """SELECT id, processed_messages AS messages, total_bytes AS bytes,
                large_messages, newsletter_messages, created_at
                FROM scan_jobs WHERE account_id=? AND status='completed'
                ORDER BY created_at DESC LIMIT 24""",
                (account_id,),
            ).fetchall()
            current = connection.execute(
                """SELECT COUNT(DISTINCT folder) AS folders,
                COUNT(DISTINCT lower(sender_domain)) AS domains,
                SUM(CASE WHEN lower(folder) LIKE '%inbox%' OR upper(folder)='INBOX'
                    THEN 1 ELSE 0 END) AS inbox_messages
                FROM inventory_messages WHERE job_id=?""",
                (latest.id,),
            ).fetchone()
        newsletter_ratio = latest.newsletter_messages / max(latest.processed_messages, 1)
        large_ratio = latest.large_messages / max(latest.processed_messages, 1)
        score = max(0, round(100 - min(45, newsletter_ratio * 100) - min(25, large_ratio * 500)))
        return {
            "score": score,
            "history": [dict(row) for row in history],
            "current": {
                **dict(current),
                "job_id": latest.id,
                "status": latest.status,
                "processed_messages": latest.processed_messages,
                "total_messages": latest.total_messages,
                "total_bytes": latest.total_bytes,
                "large_messages": latest.large_messages,
                "newsletter_messages": latest.newsletter_messages,
                "updated_at": latest.updated_at,
            },
        }

    def search_inventory(
        self, account_id: str, query: str, folder: str | None = None, limit: int = 500
    ) -> list[dict[str, object]]:
        latest = self.latest_job(account_id)
        if latest is None:
            return []
        needle = f"%{query.casefold()}%"
        parameters: list[object] = [latest.id, needle, needle, needle]
        folder_clause = ""
        if folder:
            folder_clause = " AND folder=?"
            parameters.append(folder)
        parameters.append(limit)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT job_id, folder, uid, subject, sender, sender_domain,
                size_bytes, internal_date, flags_json FROM inventory_messages
                WHERE job_id=? AND (lower(subject) LIKE ? OR lower(sender) LIKE ?
                OR lower(sender_domain) LIKE ?)"""
                + folder_clause
                + " ORDER BY size_bytes DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def security_inventory(self, account_id: str, limit: int = 50000) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            latest = connection.execute(
                "SELECT id FROM scan_jobs WHERE status='completed' AND account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if latest is None:
                return []
            rows = connection.execute(
                """SELECT job_id, folder, uid, subject, sender, sender_domain,
                size_bytes, internal_date FROM inventory_messages m
                WHERE job_id=?
                AND UPPER(folder) NOT IN ('SENT', 'DRAFTS', 'TRASH')
                AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.action='delete' AND a.result='completed')
                LIMIT ?""",
                (latest["id"], limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def security_allowlist(self, account_id: str) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT sender_address FROM account_security_allowlist WHERE account_id=?",
                (account_id,),
            ).fetchall()
        return {str(row["sender_address"]) for row in rows}

    def security_ai_reviews(self, job_ids: set[str]) -> list[dict[str, object]]:
        if not job_ids:
            return []
        placeholders = ",".join("?" for _ in job_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT * FROM security_ai_reviews WHERE job_id IN ({placeholders})""",
                tuple(job_ids),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_security_ai_review(
        self, job_id: str, folder: str, uid: str, verdict: str, confidence: float, reason: str
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO security_ai_reviews
                (job_id, folder, uid, verdict, confidence, reason, reviewed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(job_id, folder, uid)
                DO UPDATE SET verdict=excluded.verdict,
                confidence=excluded.confidence, reason=excluded.reason,
                reviewed_at=excluded.reviewed_at""",
                (job_id, folder, uid, verdict, confidence, reason, _now()),
            )
            connection.commit()

    def allow_security_sender(self, account_id: str, sender_address: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT OR IGNORE INTO account_security_allowlist
                (account_id, sender_address, created_at) VALUES (?, ?, ?)""",
                (account_id, sender_address.strip().casefold(), _now()),
            )
            connection.commit()

    def newsletter_groups(self, account_id: str, limit: int = 500) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            latest = connection.execute(
                "SELECT id FROM scan_jobs WHERE status='completed' AND account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if latest is None:
                return []
            rows = connection.execute(
                """SELECT job_id, sender, sender_domain, COALESCE(list_id, '') AS list_id,
                COUNT(*) AS message_count, SUM(size_bytes) AS total_bytes,
                MIN(folder || char(31) || uid) AS reference
                FROM inventory_messages
                WHERE job_id=? AND (list_unsubscribe=1 OR list_id IS NOT NULL)
                AND NOT EXISTS (
                    SELECT 1 FROM action_audit a
                    JOIN inventory_messages done ON done.job_id=a.job_id
                    AND done.folder=a.folder AND done.uid=a.uid
                    WHERE a.job_id=inventory_messages.job_id
                    AND done.sender=inventory_messages.sender
                    AND COALESCE(done.list_id, '')=COALESCE(inventory_messages.list_id, '')
                    AND a.action='unsubscribe' AND a.result='completed'
                )
                GROUP BY sender, sender_domain, COALESCE(list_id, '')
                ORDER BY message_count DESC LIMIT ?""",
                (latest["id"], limit),
            ).fetchall()
        groups: list[dict[str, object]] = []
        for row in rows:
            group = dict(row)
            folder, uid = str(group.pop("reference")).split("\x1f", 1)
            groups.append({**group, "folder": folder, "uid": uid})
        return groups

    def inventory_item(self, job_id: str, folder: str, uid: str) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT job_id, folder, uid, subject, sender, size_bytes
                FROM inventory_messages WHERE job_id=? AND folder=? AND uid=?""",
                (job_id, folder, uid),
            ).fetchone()
        return dict(row) if row else None

    def newsletter_messages_for_representative(
        self, job_id: str, folder: str, uid: str
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            representative = connection.execute(
                """SELECT sender, COALESCE(list_id, '') AS list_id
                FROM inventory_messages WHERE job_id=? AND folder=? AND uid=?""",
                (job_id, folder, uid),
            ).fetchone()
            if representative is None:
                return []
            rows = connection.execute(
                """SELECT job_id, folder, uid FROM inventory_messages
                WHERE job_id=? AND sender=? AND COALESCE(list_id, '')=?""",
                (job_id, representative["sender"], representative["list_id"]),
            ).fetchall()
        return [dict(row) for row in rows]

    def record_action(self, job_id: str, folder: str, uid: str, action: str, result: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO action_audit
                (id, job_id, folder, uid, action, result, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uuid4().hex, job_id, folder, uid, action, result, _now()),
            )
            connection.commit()

    def action_completed(self, job_id: str, folder: str, uid: str, action: str) -> bool:
        """Return whether an action already completed, making retries idempotent."""
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT 1 FROM action_audit
                WHERE job_id=? AND folder=? AND uid=? AND action=? AND result='completed'
                LIMIT 1""",
                (job_id, folder, uid, action),
            ).fetchone()
        return row is not None

    def ai_cleanup_inventory(self, account_id: str) -> tuple[str, list[dict[str, object]]]:
        with closing(self._connect()) as connection:
            latest = connection.execute(
                "SELECT id FROM scan_jobs WHERE status='completed' AND account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
            if latest is None:
                raise LookupError("No completed mailbox scan is available")
            rows = connection.execute(
                """SELECT folder, uid, subject, sender, sender_domain, size_bytes, internal_date
                FROM inventory_messages m WHERE job_id=?
                AND list_unsubscribe=0 AND list_id IS NULL
                AND lower(folder) NOT LIKE '%trash%'
                AND lower(folder) NOT LIKE '%deleted%'
                AND lower(folder) NOT LIKE '%papierkorb%'
                AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=m.job_id
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.action IN ('delete', 'archive', 'ai_trash', 'ai_archive')
                    AND a.result='completed'
                )""",
                (latest["id"],),
            ).fetchall()
        return str(latest["id"]), [dict(row) for row in rows]

    def create_ai_cleanup_run(self, scan_job_id: str, total_groups: int) -> str:
        run_id = uuid4().hex
        timestamp = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO ai_cleanup_runs
                (id, scan_job_id, status, total_groups, processed_groups, created_at, updated_at)
                VALUES (?, ?, 'running', ?, 0, ?, ?)""",
                (run_id, scan_job_id, total_groups, timestamp, timestamp),
            )
            connection.commit()
        return run_id

    def save_ai_cleanup_suggestion(
        self, run_id: str, suggestion: dict[str, object], members: list[dict[str, object]]
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO ai_cleanup_suggestions
                (id, run_id, sender, sender_domain, subject_pattern, message_count,
                total_bytes, oldest_date, newest_date, category, recommendation,
                confidence, reason, protected)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    suggestion["id"],
                    run_id,
                    suggestion["sender"],
                    suggestion["sender_domain"],
                    suggestion["subject_pattern"],
                    suggestion["message_count"],
                    suggestion["total_bytes"],
                    suggestion["oldest_date"],
                    suggestion["newest_date"],
                    suggestion["category"],
                    suggestion["recommendation"],
                    suggestion["confidence"],
                    suggestion["reason"],
                    int(bool(suggestion["protected"])),
                ),
            )
            connection.executemany(
                """INSERT INTO ai_cleanup_members (suggestion_id, folder, uid)
                VALUES (?, ?, ?)""",
                [(suggestion["id"], item["folder"], item["uid"]) for item in members],
            )
            connection.execute(
                """UPDATE ai_cleanup_runs SET processed_groups=processed_groups+1,
                updated_at=? WHERE id=?""",
                (_now(), run_id),
            )
            connection.commit()

    def finish_ai_cleanup_run(self, run_id: str, status: str, error: str | None = None) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE ai_cleanup_runs SET status=?, error=?, updated_at=? WHERE id=?",
                (status, error, _now(), run_id),
            )
            connection.commit()

    def ai_cleanup_run(
        self, run_id: str | None = None, account_id: str | None = None
    ) -> dict[str, object] | None:
        with closing(self._connect()) as connection:
            if run_id and account_id:
                row = connection.execute(
                    """SELECT r.* FROM ai_cleanup_runs r JOIN scan_jobs j
                    ON j.id=r.scan_job_id WHERE r.id=? AND j.account_id=?""",
                    (run_id, account_id),
                ).fetchone()
            elif run_id:
                row = connection.execute(
                    "SELECT * FROM ai_cleanup_runs WHERE id=?", (run_id,)
                ).fetchone()
            else:
                if account_id is None:
                    row = connection.execute(
                        "SELECT * FROM ai_cleanup_runs ORDER BY created_at DESC LIMIT 1"
                    ).fetchone()
                else:
                    row = connection.execute(
                        """SELECT r.* FROM ai_cleanup_runs r JOIN scan_jobs j
                        ON j.id=r.scan_job_id WHERE j.account_id=?
                        ORDER BY r.created_at DESC LIMIT 1""",
                        (account_id,),
                    ).fetchone()
        return dict(row) if row else None

    def ai_cleanup_suggestions(self, run_id: str, limit: int = 1000) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM ai_cleanup_suggestions WHERE run_id=?
                ORDER BY protected ASC,
                CASE recommendation WHEN 'trash_review' THEN 0 WHEN 'archive_review' THEN 1 ELSE 2 END,
                message_count DESC LIMIT ?""",
                (run_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def pending_ai_cleanup_suggestions(
        self, run_id: str, limit: int = 1000
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            run = connection.execute(
                "SELECT scan_job_id FROM ai_cleanup_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                return []
            suggestions = connection.execute(
                "SELECT * FROM ai_cleanup_suggestions WHERE run_id=?",
                (run_id,),
            ).fetchall()
            members = connection.execute(
                """SELECT suggestion_id, folder, uid FROM ai_cleanup_members
                WHERE suggestion_id IN (
                    SELECT id FROM ai_cleanup_suggestions WHERE run_id=?
                )""",
                (run_id,),
            ).fetchall()
            inventory_rows = connection.execute(
                """SELECT folder, uid, size_bytes FROM inventory_messages
                WHERE job_id=?""",
                (run["scan_job_id"],),
            ).fetchall()
            completed_rows = connection.execute(
                """SELECT folder, uid FROM action_audit WHERE job_id=?
                AND result IN ('completed', 'source_missing')
                AND action IN ('delete', 'archive',
                'export_delete', 'ai_trash', 'ai_archive', 'newsletter_cleanup',
                'filing_rule')""",
                (run["scan_job_id"],),
            ).fetchall()
        completed = {(str(row["folder"]), str(row["uid"])) for row in completed_rows}
        sizes = {
            (str(row["folder"]), str(row["uid"])): int(row["size_bytes"]) for row in inventory_rows
        }
        remaining: dict[str, tuple[int, int]] = {}
        for member in members:
            if (str(member["folder"]), str(member["uid"])) in completed:
                continue
            suggestion_id = str(member["suggestion_id"])
            count, size = remaining.get(suggestion_id, (0, 0))
            remaining[suggestion_id] = (
                count + 1,
                size + sizes.get((str(member["folder"]), str(member["uid"])), 0),
            )
        rows = [
            {
                **dict(row),
                "message_count": remaining[str(row["id"])][0],
                "total_bytes": remaining[str(row["id"])][1],
            }
            for row in suggestions
            if str(row["id"]) in remaining
        ]
        recommendation_order = {"trash_review": 0, "archive_review": 1}
        rows.sort(
            key=lambda item: (
                bool(item["protected"]),
                recommendation_order.get(str(item["recommendation"]), 2),
                -int(item["message_count"]),
            )
        )
        return rows[:limit]

    def pending_ai_cleanup_summary(self, run_id: str) -> dict[str, object]:
        rows = self.pending_ai_cleanup_suggestions(run_id, limit=50_000)
        return {
            "groups_analyzed": len(rows),
            "messages_analyzed": sum(int(item["message_count"]) for item in rows),
            "trash_messages": sum(
                int(item["message_count"])
                for item in rows
                if item["recommendation"] == "trash_review"
            ),
            "trash_bytes": sum(
                int(item["total_bytes"])
                for item in rows
                if item["recommendation"] == "trash_review"
            ),
            "archive_messages": sum(
                int(item["message_count"])
                for item in rows
                if item["recommendation"] == "archive_review"
            ),
            "archive_bytes": sum(
                int(item["total_bytes"])
                for item in rows
                if item["recommendation"] == "archive_review"
            ),
            "protected_messages": sum(
                int(item["message_count"]) for item in rows if bool(item["protected"])
            ),
        }

    def ai_cleanup_summary(self, run_id: str) -> dict[str, object]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """SELECT COUNT(*) AS groups_analyzed,
                COALESCE(SUM(message_count), 0) AS messages_analyzed,
                COALESCE(SUM(CASE WHEN recommendation='trash_review' THEN message_count ELSE 0 END), 0) AS trash_messages,
                COALESCE(SUM(CASE WHEN recommendation='trash_review' THEN total_bytes ELSE 0 END), 0) AS trash_bytes,
                COALESCE(SUM(CASE WHEN recommendation='archive_review' THEN message_count ELSE 0 END), 0) AS archive_messages,
                COALESCE(SUM(CASE WHEN recommendation='archive_review' THEN total_bytes ELSE 0 END), 0) AS archive_bytes,
                COALESCE(SUM(CASE WHEN protected=1 THEN message_count ELSE 0 END), 0) AS protected_messages
                FROM ai_cleanup_suggestions WHERE run_id=?""",
                (run_id,),
            ).fetchone()
        return dict(row)

    def filing_candidates(self, run_id: str) -> tuple[str, str, list[dict[str, object]]]:
        with closing(self._connect()) as connection:
            run = connection.execute(
                """SELECT r.scan_job_id, j.account_id FROM ai_cleanup_runs r
                JOIN scan_jobs j ON j.id=r.scan_job_id WHERE r.id=?""",
                (run_id,),
            ).fetchone()
            if run is None:
                raise LookupError("AI cleanup run does not exist")
            rows = connection.execute(
                """SELECT s.category, s.subject_pattern, s.confidence,
                m.folder, m.uid, i.size_bytes, i.internal_date
                FROM ai_cleanup_suggestions s
                JOIN ai_cleanup_members m ON m.suggestion_id=s.id
                CROSS JOIN inventory_messages i
                INDEXED BY sqlite_autoindex_inventory_messages_1
                ON i.job_id=? AND i.folder=m.folder AND i.uid=m.uid
                WHERE s.run_id=? AND s.confidence>=0.90""",
                (run["scan_job_id"], run_id),
            ).fetchall()
            completed_rows = connection.execute(
                """SELECT folder, uid FROM action_audit
                WHERE job_id=? AND action='filing_rule' AND result='completed'""",
                (run["scan_job_id"],),
            ).fetchall()
        completed = {(str(row["folder"]), str(row["uid"])) for row in completed_rows}
        candidates = [
            dict(row) for row in rows if (str(row["folder"]), str(row["uid"])) not in completed
        ]
        return str(run["scan_job_id"]), str(run["account_id"]), candidates

    def save_filing_rule(
        self, account_id: str, bucket: str, target_year: int, destination: str
    ) -> str:
        rule_id = uuid4().hex
        timestamp = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO filing_rules
                (id, account_id, bucket, target_year, destination, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(account_id, bucket, target_year) DO UPDATE SET
                destination=excluded.destination, enabled=1, updated_at=excluded.updated_at""",
                (rule_id, account_id, bucket, target_year, destination, timestamp, timestamp),
            )
            connection.commit()
            row = connection.execute(
                """SELECT id FROM filing_rules
                WHERE account_id=? AND bucket=? AND target_year=?""",
                (account_id, bucket, target_year),
            ).fetchone()
        return str(row["id"])

    def filing_rules(
        self, account_id: str | None = None, *, enabled_only: bool = False
    ) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT id, account_id, bucket, target_year, destination, enabled, created_at, updated_at
                FROM filing_rules WHERE (enabled=1 OR ?=0)
                AND (account_id=? OR ? IS NULL)
                ORDER BY target_year DESC, bucket""",
                (int(enabled_only), account_id, account_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def set_filing_rule_enabled(self, rule_id: str, enabled: bool) -> bool:
        with closing(self._connect()) as connection:
            cursor = connection.execute(
                "UPDATE filing_rules SET enabled=?, updated_at=? WHERE id=?",
                (int(enabled), _now(), rule_id),
            )
            connection.commit()
        return cursor.rowcount == 1

    def automated_accounts(self) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT a.id, a.provider FROM accounts a
                WHERE EXISTS (SELECT 1 FROM filing_rules r
                    WHERE r.account_id=a.id AND r.enabled=1)
                ORDER BY a.connected_at"""
            ).fetchall()
        return [dict(row) for row in rows]

    def automated_uids(self, account_id: str, folder: str, uids: list[str]) -> set[str]:
        if not uids:
            return set()
        placeholders = ",".join("?" for _ in uids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""SELECT uid FROM automation_audit
                WHERE account_id=? AND folder=? AND uid IN ({placeholders})""",
                (account_id, folder, *uids),
            ).fetchall()
        return {str(row["uid"]) for row in rows}

    def record_automation(
        self,
        account_id: str,
        folder: str,
        uid: str,
        result: str,
        destination: str | None = None,
        detail: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """INSERT INTO automation_audit
                (account_id, folder, uid, result, destination, detail, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, folder, uid) DO UPDATE SET
                result=excluded.result, destination=excluded.destination,
                detail=excluded.detail, processed_at=excluded.processed_at""",
                (account_id, folder, uid, result, destination, detail, _now()),
            )
            connection.commit()

    def create_automation_run(self, account_id: str, trigger: str) -> str:
        run_id = uuid4().hex
        try:
            with closing(self._connect()) as connection:
                connection.execute(
                    """INSERT INTO automation_runs
                    (id, account_id, trigger, status, started_at)
                    VALUES (?, ?, ?, 'running', ?)""",
                    (run_id, account_id, trigger, _now()),
                )
                connection.commit()
        except sqlite3.IntegrityError as exc:
            raise RuntimeError("Automation is already running for this account") from exc
        return run_id

    def finish_automation_run(
        self,
        run_id: str,
        status: str,
        totals: dict[str, int] | None = None,
        error: str | None = None,
    ) -> None:
        values = totals or {}
        with closing(self._connect()) as connection:
            connection.execute(
                """UPDATE automation_runs SET status=?, processed=?, moved=?, deferred=?,
                finished_at=?, error=? WHERE id=?""",
                (
                    status,
                    int(values.get("processed", 0)),
                    int(values.get("moved", 0)),
                    int(values.get("deferred", 0)),
                    _now(),
                    error,
                    run_id,
                ),
            )
            connection.commit()

    def automation_runs(self, account_id: str, limit: int = 25) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """SELECT * FROM automation_runs WHERE account_id=?
                ORDER BY started_at DESC LIMIT ?""",
                (account_id, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def automation_status(self, account_id: str | None = None) -> dict[str, object]:
        with closing(self._connect()) as connection:
            if account_id is None:
                row = connection.execute(
                    """SELECT COUNT(*) processed,
                    SUM(CASE WHEN result='moved' THEN 1 ELSE 0 END) moved,
                    MAX(processed_at) last_activity FROM automation_audit"""
                ).fetchone()
                return dict(row)
            row = connection.execute(
                """SELECT COUNT(*) processed,
                SUM(CASE WHEN result='moved' THEN 1 ELSE 0 END) moved,
                SUM(CASE WHEN result='no_match' THEN 1 ELSE 0 END) no_match,
                MAX(processed_at) last_activity FROM automation_audit
                WHERE account_id=?""",
                (account_id,),
            ).fetchone()
            active_rules = connection.execute(
                """SELECT COUNT(*) FROM filing_rules
                WHERE account_id=? AND enabled=1""",
                (account_id,),
            ).fetchone()[0]
        runs = self.automation_runs(account_id)
        return {
            **dict(row),
            "active_rules": int(active_rules),
            "latest_run": runs[0] if runs else None,
            "runs": runs,
        }

    def ai_cleanup_selection(
        self, run_id: str, suggestion_ids: list[str]
    ) -> tuple[str, list[dict[str, object]]]:
        if not suggestion_ids:
            return "", []
        placeholders = ",".join("?" for _ in suggestion_ids)
        with closing(self._connect()) as connection:
            run = connection.execute(
                "SELECT scan_job_id FROM ai_cleanup_runs WHERE id=?", (run_id,)
            ).fetchone()
            if run is None:
                raise LookupError("AI cleanup run does not exist")
            rows = connection.execute(
                f"""SELECT s.id AS suggestion_id, s.protected, s.recommendation,
                s.sender, s.sender_domain, s.subject_pattern,
                m.folder, m.uid FROM ai_cleanup_suggestions s
                JOIN ai_cleanup_members m ON m.suggestion_id=s.id
                WHERE s.run_id=? AND s.id IN ({placeholders})
                AND NOT EXISTS (
                    SELECT 1 FROM action_audit a WHERE a.job_id=?
                    AND a.folder=m.folder AND a.uid=m.uid
                    AND a.result IN ('completed', 'source_missing')
                    AND a.action IN ('delete', 'archive', 'export_delete', 'ai_trash',
                        'ai_archive', 'newsletter_cleanup', 'filing_rule')
                )""",
                (run_id, *suggestion_ids, run["scan_job_id"]),
            ).fetchall()
        return str(run["scan_job_id"]), [dict(row) for row in rows]

    def create_job(self, account_id: str, provider: str) -> str:
        job_id = uuid4().hex
        timestamp = _now()
        with closing(self._connect()) as connection:
            connection.execute(
                "INSERT INTO scan_jobs (id, account_id, provider, status, created_at, updated_at) VALUES (?, ?, ?, 'queued', ?, ?)",
                (job_id, account_id, provider, timestamp, timestamp),
            )
            connection.commit()
        return job_id

    def set_status(
        self, job_id: str, status: str, *, folder: str | None = None, error: str | None = None
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE scan_jobs SET status=?, current_folder=?, error=?, updated_at=? WHERE id=?",
                (status, folder, error, _now(), job_id),
            )
            connection.commit()

    def prepare_folders(self, job_id: str, folders: list[tuple[str, int]]) -> None:
        total = sum(count for _, count in folders)
        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT INTO scan_folders (job_id, name, total_messages, processed_messages, completed) VALUES (?, ?, ?, 0, 0) ON CONFLICT(job_id, name) DO UPDATE SET total_messages=excluded.total_messages",
                [(job_id, name, count) for name, count in folders],
            )
            connection.execute(
                "UPDATE scan_jobs SET total_messages=?, updated_at=? WHERE id=?",
                (total, _now(), job_id),
            )
            connection.commit()

    def store_batch(
        self, job_id: str, folder: str, messages: tuple[ReviewMessage, ...], large_threshold: int
    ) -> None:
        if not messages:
            return
        rows = [
            (
                job_id,
                folder,
                item.uid,
                item.subject,
                item.sender,
                item.sender_domain,
                item.list_id,
                int(item.list_unsubscribe),
                item.size_bytes,
                item.internal_date,
                json.dumps(item.flags),
            )
            for item in messages
        ]
        with closing(self._connect()) as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO inventory_messages (job_id, folder, uid, subject, sender, sender_domain, list_id, list_unsubscribe, size_bytes, internal_date, flags_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )
            folder_count = connection.execute(
                "SELECT COUNT(*) FROM inventory_messages WHERE job_id=? AND folder=?",
                (job_id, folder),
            ).fetchone()[0]
            totals = connection.execute(
                "SELECT COUNT(*), COALESCE(SUM(size_bytes),0), SUM(CASE WHEN size_bytes>=? THEN 1 ELSE 0 END), SUM(CASE WHEN list_unsubscribe=1 OR list_id IS NOT NULL THEN 1 ELSE 0 END) FROM inventory_messages WHERE job_id=?",
                (large_threshold, job_id),
            ).fetchone()
            connection.execute(
                "UPDATE scan_folders SET processed_messages=? WHERE job_id=? AND name=?",
                (folder_count, job_id, folder),
            )
            connection.execute(
                "UPDATE scan_jobs SET processed_messages=?, total_bytes=?, large_messages=?, newsletter_messages=?, updated_at=? WHERE id=?",
                (*totals, _now(), job_id),
            )
            connection.commit()

    def stored_uids(self, job_id: str, folder: str) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT uid FROM inventory_messages WHERE job_id=? AND folder=?", (job_id, folder)
            ).fetchall()
        return {str(row["uid"]) for row in rows}

    def complete_folder(self, job_id: str, folder: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                "UPDATE scan_folders SET completed=1 WHERE job_id=? AND name=?", (job_id, folder)
            )
            connection.commit()

    def completed_folders(self, job_id: str) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT name FROM scan_folders WHERE job_id=? AND completed=1", (job_id,)
            ).fetchall()
        return {str(row["name"]) for row in rows}

    def job(self, job_id: str) -> JobRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute("SELECT * FROM scan_jobs WHERE id=?", (job_id,)).fetchone()
        return JobRecord(**dict(row)) if row else None

    def latest_job(self, account_id: str) -> JobRecord | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM scan_jobs WHERE account_id=? ORDER BY created_at DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return JobRecord(**dict(row)) if row else None

    def action_groups(self, job_id: str, large_threshold: int) -> list[dict[str, object]]:
        query = """SELECT sender, sender_domain, COALESCE(list_id, '') AS list_id,
            COUNT(*) AS message_count, SUM(size_bytes) AS total_bytes,
            SUM(CASE WHEN list_unsubscribe=1 THEN 1 ELSE 0 END) AS unsubscribe_count,
            SUM(CASE WHEN size_bytes>=? THEN 1 ELSE 0 END) AS large_count,
            SUM(CASE WHEN lower(folder) LIKE '%spam%' OR lower(folder) LIKE '%junk%' THEN 1 ELSE 0 END) AS spam_count,
            SUM(CASE WHEN lower(folder) LIKE '%trash%' OR lower(folder) LIKE '%deleted%' OR lower(folder) LIKE '%papierkorb%' THEN 1 ELSE 0 END) AS trash_count
            FROM inventory_messages WHERE job_id=?
            GROUP BY sender, sender_domain, COALESCE(list_id, '')
            ORDER BY message_count DESC"""
        with closing(self._connect()) as connection:
            rows = connection.execute(query, (large_threshold, job_id)).fetchall()
        groups: list[dict[str, object]] = []
        for row in rows:
            recommendation = "manual_review"
            if row["trash_count"] == row["message_count"]:
                recommendation = "cleanup_review"
            elif row["spam_count"] == row["message_count"]:
                recommendation = "quarantine_review"
            elif row["unsubscribe_count"] or row["list_id"]:
                recommendation = "unsubscribe_review"
            if row["large_count"]:
                recommendation = (
                    "archive_review" if recommendation == "manual_review" else recommendation
                )
            groups.append({**dict(row), "recommendation": recommendation})
        return groups

    def folder_progress(self, job_id: str) -> list[dict[str, object]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT name, total_messages, processed_messages, completed FROM scan_folders WHERE job_id=? ORDER BY name",
                (job_id,),
            ).fetchall()
        return [dict(row) for row in rows]


def _public_job_dict(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "job_id": row["id"],
        "status": row["status"],
        "processed_messages": row["processed_messages"],
        "total_messages": row["total_messages"],
        "total_bytes": row["total_bytes"],
        "large_messages": row["large_messages"],
        "newsletter_messages": row["newsletter_messages"],
        "updated_at": row["updated_at"],
    }
