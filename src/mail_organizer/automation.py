"""Conservative background filing agent for approved local rules."""

from __future__ import annotations

import argparse
import imaplib
import json
import logging
import os
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

import httpx

from .classification import Category, QwenClassifier
from .config import Settings
from .credentials import CredentialStore
from .filing import validate_folder_name
from .imap_client import ReadOnlyImapClient, ReviewMessage
from .providers import get_provider
from .storage import ScanStore

_CATEGORY_BUCKET = {
    Category.FINANCE: "Invoices",
    Category.ORDER: "Orders",
    Category.TRAVEL: "Travel",
    Category.LEGAL: "Contracts",
    Category.SECURITY: "Security",
}


class FilingAgent:
    """Move only confidently categorized mail covered by an approved rule."""

    def __init__(self, settings: Settings, store: ScanStore, credentials: CredentialStore) -> None:
        self.settings = settings
        self.store = store
        self.credentials = credentials
        self.classifier = QwenClassifier(settings.ollama_base_url, settings.ollama_model)

    def run_once(self) -> dict[str, int]:
        totals = {"accounts": 0, "processed": 0, "moved": 0, "deferred": 0}
        for account in self.store.automated_accounts():
            account_id = str(account["id"])
            if not self._is_due(account_id):
                continue
            try:
                run_id = self.store.create_automation_run(account_id, "service")
            except RuntimeError:
                continue
            result = self.execute_run(run_id, account_id)
            if result["status"] == "completed":
                totals["accounts"] += 1
                for key in ("processed", "moved", "deferred"):
                    totals[key] += int(result[key])
        return totals

    def _is_due(self, account_id: str) -> bool:
        latest = self.store.automation_status(account_id).get("latest_run")
        if not isinstance(latest, dict):
            return True
        timestamp = latest.get("finished_at") or latest.get("started_at")
        if not timestamp:
            return True
        try:
            previous = datetime.fromisoformat(str(timestamp)).astimezone(UTC)
        except ValueError:
            return True
        minutes = int(self.store.account_preferences(account_id)["schedule_minutes"])
        return datetime.now(UTC) >= previous + timedelta(minutes=minutes)

    def execute_run(self, run_id: str, account_id: str) -> dict[str, int | str]:
        account = self.store.account(account_id)
        if account is None:
            self.store.finish_automation_run(run_id, "failed", error="Account is unavailable")
            return {"status": "failed", "processed": 0, "moved": 0, "deferred": 0}
        preferences = self.store.account_preferences(account_id)
        if preferences["paused"]:
            self.store.finish_automation_run(run_id, "skipped", error="Account is paused")
            return {"status": "skipped", "processed": 0, "moved": 0, "deferred": 0}
        if preferences["learning_mode"]:
            self.store.finish_automation_run(
                run_id, "skipped", error="Learning mode prevents automatic moves"
            )
            return {"status": "skipped", "processed": 0, "moved": 0, "deferred": 0}
        totals = {"accounts": 1, "processed": 0, "moved": 0, "deferred": 0}
        try:
            self._process_account(account_id, str(account["provider"]), totals)
        except (
            imaplib.IMAP4.error,
            OSError,
            LookupError,
            ConnectionError,
            ValueError,
        ) as exc:
            self.store.finish_automation_run(run_id, "failed", totals, _safe_error(exc))
            return {"status": "failed", **totals}
        self.store.finish_automation_run(run_id, "completed", totals)
        return {"status": "completed", **totals}

    def _process_account(self, account_id: str, provider_key: str, totals: dict[str, int]) -> None:
        preferences = self.store.account_preferences(account_id)
        active_buckets = {
            str(rule["bucket"])
            for rule in self.store.filing_rules(account_id, enabled_only=True)
            if str(rule.get("account_id", account_id)) == account_id
        }
        if not active_buckets:
            return
        username = self.credentials.get_username(account_id)
        password = self.credentials.get_password(account_id)
        with ReadOnlyImapClient(get_provider(provider_key)) as client:
            client.authenticate(username, password)
            all_uids = client.message_uids("INBOX")
            checked = self.store.automated_uids(account_id, "INBOX", all_uids)
            pending = [uid for uid in all_uids if uid not in checked][
                -min(self.settings.automation_batch_size, int(preferences["max_actions"])) :
            ]
            for message in client.fetch_messages_by_uids("INBOX", pending):
                self._process_message(client, account_id, active_buckets, message, totals)

    def _process_message(
        self,
        client: ReadOnlyImapClient,
        account_id: str,
        active_buckets: set[str],
        message: ReviewMessage,
        totals: dict[str, int],
    ) -> None:
        try:
            classification = self.classifier.classify(message)
        except (httpx.HTTPError, ValueError, KeyError):
            totals["deferred"] += 1
            return
        bucket = _CATEGORY_BUCKET.get(classification.category)
        year = _message_year(message)
        if (
            bucket is None
            or bucket not in active_buckets
            or year is None
            or classification.confidence < 0.90
        ):
            self.store.record_automation(account_id, "INBOX", message.uid, "no_match")
            totals["processed"] += 1
            return
        destination = validate_folder_name(client.ensure_folder_path(bucket, str(year)))
        client.move_message("INBOX", message.uid, destination)
        self.store.save_filing_rule(account_id, bucket, year, destination)
        self.store.record_automation(account_id, "INBOX", message.uid, "moved", destination)
        totals["processed"] += 1
        totals["moved"] += 1


class AutomationManager:
    """Launch explicitly requested automation runs without blocking the API."""

    def __init__(self, agent: FilingAgent, store: ScanStore) -> None:
        self._agent = agent
        self._store = store

    def start(self, account_id: str) -> str:
        run_id = self._store.create_automation_run(account_id, "manual")
        threading.Thread(
            target=self._agent.execute_run,
            args=(run_id, account_id),
            daemon=True,
            name=f"mail-automation-{run_id[:8]}",
        ).start()
        return run_id


def windows_task_status() -> dict[str, object]:
    if os.name != "nt":
        return {"supported": False, "installed": False, "state": "unsupported"}
    command = (
        "$task=Get-ScheduledTask -TaskName 'Local Mail Organizer Agent' "
        "-ErrorAction SilentlyContinue;"
        'if($null -eq $task){\'{"installed":false,"state":"not installed"}\'}'
        "else{$info=Get-ScheduledTaskInfo -TaskName $task.TaskName;"
        "[pscustomobject]@{installed=$true;state=[string]$task.State;"
        "last_run_time=$info.LastRunTime.ToString('o');"
        "last_result=$info.LastTaskResult}|ConvertTo-Json -Compress}"
    )
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            check=True,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        payload = json.loads(completed.stdout.strip())
        return {"supported": True, **payload}
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return {"supported": True, "installed": False, "state": "status unavailable"}


def update_windows_task(install: bool) -> dict[str, object]:
    if os.name != "nt":
        raise RuntimeError("Windows Task Scheduler is unavailable")
    project_root = Path(__file__).resolve().parents[2]
    script = (
        project_root
        / "scripts"
        / ("install_automation.ps1" if install else "uninstall_automation.ps1")
    )
    try:
        subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
            ],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError("Windows automation task could not be updated") from exc
    return windows_task_status()


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, LookupError):
        return "Saved credentials are incomplete"
    if isinstance(exc, imaplib.IMAP4.error):
        return "The mail provider rejected an IMAP operation"
    if isinstance(exc, (OSError, ConnectionError)):
        return "The mail provider could not be reached"
    return "The automation run stopped safely"


def _message_year(message: ReviewMessage) -> int | None:
    if not message.internal_date:
        return None
    try:
        year = datetime.strptime(message.internal_date, "%d-%b-%Y %H:%M:%S %z").year
    except ValueError:
        return None
    return year if 1990 <= year <= 2100 else None


def _logger() -> logging.Logger:
    log_path = Path("data/automation.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mail-organizer-automation")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.addHandler(RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3))
    return logger


def main() -> None:
    parser = argparse.ArgumentParser(description="Run approved mailbox filing rules")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit")
    args = parser.parse_args()
    settings = Settings()
    agent = FilingAgent(settings, ScanStore(settings.database_path), CredentialStore())
    logger = _logger()
    while True:
        try:
            logger.info("automation cycle: %s", agent.run_once())
        except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
            logger.error("automation cycle stopped safely: %s", type(exc).__name__)
        if args.once:
            return
        time.sleep(settings.automation_interval_seconds)


if __name__ == "__main__":
    main()
