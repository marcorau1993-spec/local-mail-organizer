"""Local-only API surface for the web interface."""

from __future__ import annotations

import hashlib
import imaplib
import re
import smtplib
from collections import defaultdict
from datetime import UTC, datetime
from email import message_from_bytes
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Literal, cast
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .ai_cleanup import AICleanupManager, is_provider_notice, is_provider_promotion
from .archive import VerifiedArchive
from .automation import (
    AutomationManager,
    FilingAgent,
    update_windows_task,
    windows_task_status,
)
from .classification import Category, QwenClassifier, Recommendation, SafeClassification
from .config import Settings
from .content_index import ContentIndexManager
from .credentials import CredentialStore
from .document_text import extract_attachment_text
from .dropbox_archive import DropboxArchive
from .filing import build_filing_proposals, validate_folder_name
from .full_scan import FullScanManager
from .imap_client import ReadOnlyImapClient
from .intelligence import (
    action_candidates,
    attachment_category,
    company_details,
    consolidate_companies,
    decoded,
    lexical_candidates,
    lifecycle_entities,
    qwen_action_review,
    qwen_semantic_search,
)
from .microsoft_oauth import MicrosoftOAuthManager
from .ollama import OllamaClient
from .providers import Provider, get_provider, public_providers
from .security import (
    authentication_signals,
    phishing_finding,
    qwen_security_review,
    sender_identity,
)
from .storage import JobRecord, ScanStore
from .unsubscribe import (
    unsubscribe_by_email,
    unsubscribe_capability,
    unsubscribe_one_click,
    unsubscribe_page_url,
)

settings = Settings()
credential_store = CredentialStore()
dropbox_archive = DropboxArchive(credential_store)
scan_store = ScanStore(settings.database_path)
full_scan_manager = FullScanManager(settings, scan_store, credential_store)
ai_cleanup_manager = AICleanupManager(settings, scan_store)
automation_manager = AutomationManager(
    FilingAgent(settings, scan_store, credential_store), scan_store
)
content_index_manager = ContentIndexManager(settings, scan_store, credential_store)
microsoft_oauth_manager = MicrosoftOAuthManager(credential_store)
app = FastAPI(title="Local Mail Organizer", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


class AccountCredentials(BaseModel):
    provider: str = "webde"
    username: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=1024)
    save_to_keyring: bool = True


class MicrosoftOAuthRequest(BaseModel):
    username: str = Field(min_length=3, max_length=320)
    client_id: str = Field(pattern="^[0-9a-fA-F-]{36}$")
    tenant: str = Field(default="common", min_length=3, max_length=128)


class ScanRequest(BaseModel):
    provider: str = "webde"
    username: str = Field(min_length=3, max_length=320)
    folder: str = Field(default="INBOX", min_length=1, max_length=255)
    limit: int | None = Field(default=None, ge=1, le=5000)


class ReviewScanRequest(BaseModel):
    provider: str = "webde"
    username: str = Field(min_length=3, max_length=320)
    folder: str = Field(default="INBOX", min_length=1, max_length=255)
    limit: int = Field(default=5, ge=1, le=25)


class FullScanRequest(BaseModel):
    provider: str = "webde"
    username: str = Field(min_length=3, max_length=320)


class ArchiveDestinationRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    kind: str = Field(default="local_nas", pattern="^(local_nas|dropbox)$")
    root_path: str = Field(min_length=3, max_length=1024)


class DropboxStartRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    app_key: str = Field(min_length=8, max_length=128)


class MessageReference(BaseModel):
    job_id: str = Field(min_length=32, max_length=64)
    folder: str = Field(min_length=1, max_length=255)
    uid: str = Field(pattern="^[0-9]+$")


class MailActionRequest(BaseModel):
    action: Literal["delete", "archive", "export_delete"]
    items: list[MessageReference] = Field(min_length=1, max_length=100)
    confirmed: bool


class SenderCleanupRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    senders: list[str] = Field(min_length=1, max_length=10)
    confirmed: bool = False


class EmptyTrashRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    confirmation: str


class ProtectionRuleRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    kind: Literal["sender", "domain", "folder", "subject"]
    value: str = Field(min_length=1, max_length=320)


class AccountPreferencesRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    paused: bool
    learning_mode: bool
    schedule_minutes: int = Field(ge=1, le=1440)
    max_actions: int = Field(ge=1, le=500)
    notify_errors: bool


class UndoRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    operation_id: str = Field(min_length=32, max_length=64)


class ConfigurationImportRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    protection_rules: list[dict[str, object]] = Field(default_factory=list, max_length=1000)
    preferences: dict[str, object] = Field(default_factory=dict)


class NewsletterActionRequest(BaseModel):
    items: list[MessageReference] = Field(min_length=1, max_length=100)
    confirmed: bool


class SecuritySafeRequest(BaseModel):
    items: list[MessageReference] = Field(min_length=1, max_length=100)
    confirmed: bool


class SecurityReviewRequest(BaseModel):
    items: list[MessageReference] = Field(min_length=1, max_length=25)


class AICleanupActionRequest(BaseModel):
    run_id: str = Field(min_length=32, max_length=64)
    suggestion_ids: list[str] = Field(min_length=1, max_length=25)
    action: Literal["archive", "trash"]
    confirmed: bool


class AICleanupFeedbackRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    suggestion_id: str = Field(min_length=64, max_length=64)
    decision: Literal["keep", "archive_review", "trash_review"]


class RetentionPolicyRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    category: str = Field(min_length=1, max_length=40)
    action: Literal["archive_review", "trash_review"]
    age_days: int = Field(ge=30, le=7300)


class FilingApplyRequest(BaseModel):
    run_id: str = Field(min_length=32, max_length=64)
    proposal_ids: list[str] = Field(min_length=1, max_length=25)
    confirmed: bool
    future_years: Literal[0, 2, 5, 10] = 0


class PrepareFoldersRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    buckets: list[Literal["Invoices", "Orders", "Travel", "Contracts", "Security"]] = Field(
        min_length=1, max_length=5
    )
    future_years: Literal[2, 5, 10]
    confirmed: bool


class FilingRuleStateRequest(BaseModel):
    enabled: bool


class ApplySavedRulesRequest(BaseModel):
    confirmed: bool
    account_id: str = Field(min_length=64, max_length=64)


class ActionInboxStateRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    job_id: str = Field(min_length=32, max_length=64)
    folder: str = Field(min_length=1, max_length=255)
    uid: str = Field(pattern="^[0-9]+$")
    status: Literal["open", "waiting", "done", "dismissed"]


class ActionInboxReviewRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    job_id: str = Field(min_length=32, max_length=64)
    folder: str = Field(min_length=1, max_length=255)
    uid: str = Field(pattern="^[0-9]+$")


class SemanticSearchRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    query: str = Field(min_length=2, max_length=500)


class AutomationRunRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    confirmed: bool


class AutomationTaskRequest(BaseModel):
    mode: Literal["install", "uninstall"]
    confirmed: bool


class ContentIndexRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)


class AttachmentScanRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    limit: int = Field(default=50, ge=1, le=250)


class AttachmentTextReference(BaseModel):
    job_id: str = Field(min_length=32, max_length=64)
    folder: str = Field(min_length=1, max_length=255)
    uid: str = Field(pattern="^[0-9]+$")
    sha256: str = Field(pattern="^[0-9a-f]{64}$")


class AttachmentTextRequest(BaseModel):
    account_id: str = Field(min_length=64, max_length=64)
    items: list[AttachmentTextReference] = Field(min_length=1, max_length=5)


@app.get("/api/automation/status")
def automation_status(account_id: str | None = None) -> dict[str, object]:
    if account_id is None:
        return {**scan_store.automation_status(), "windows_task": windows_task_status()}
    account_id_value = _validate_account_id(account_id)
    return {
        **scan_store.automation_status(account_id_value),
        "preferences": scan_store.account_preferences(account_id_value),
        "windows_task": windows_task_status(),
    }


@app.post("/api/automation/run")
def run_automation(request: AutomationRunRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    try:
        run_id = automation_manager.start(account_id_value)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id, "status": "running"}


@app.post("/api/automation/windows-task")
def configure_automation_task(request: AutomationTaskRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    try:
        return update_windows_task(request.mode == "install")
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _object_int(value: object) -> int:
    if isinstance(value, (int, str)):
        return int(value)
    raise TypeError("Expected an integer-compatible value")


def account_id(provider: str, username: str) -> str:
    """Derive an opaque local key without exposing the address in keyring labels."""
    value = f"{provider}:{username.strip().casefold()}".encode()
    return hashlib.sha256(value).hexdigest()


@app.get("/api/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "local_only": settings.app_host in {"127.0.0.1", "localhost"},
        "dry_run": settings.dry_run,
        "destructive_actions_allowed": settings.destructive_actions_allowed,
        "provider": settings.mail_provider,
        "model": settings.ollama_model,
    }


@app.get("/api/providers")
def providers() -> dict[str, object]:
    return {"providers": public_providers()}


@app.post("/api/accounts/outlook/oauth/start")
def start_outlook_oauth(request: MicrosoftOAuthRequest) -> dict[str, object]:
    opaque_id = account_id("outlook", request.username)
    try:
        session = microsoft_oauth_manager.begin(
            opaque_id, request.username, request.client_id, request.tenant
        )
    except (ValueError, OSError) as exc:
        raise HTTPException(
            status_code=400, detail="Could not start Microsoft authorization"
        ) from exc
    credential_store.set_secret(f"{opaque_id}:username", request.username)
    return {
        "account_id": opaque_id,
        "status": session.status,
        "user_code": session.user_code,
        "verification_uri": session.verification_uri,
        "message": session.message,
    }


@app.get("/api/accounts/outlook/oauth/status")
def outlook_oauth_status(account_id_value: str) -> dict[str, object]:
    _validate_account_id(account_id_value)
    session = microsoft_oauth_manager.status(account_id_value)
    if session is None:
        raise HTTPException(status_code=404, detail="Microsoft authorization session was not found")
    if session.status == "connected":
        try:
            username = credential_store.get_username(account_id_value)
            with ReadOnlyImapClient(get_provider("outlook")) as client:
                client.authenticate(username, credential_store.get_password(account_id_value))
                folder_count = client.test_connection()
            scan_store.register_account(account_id_value, "outlook")
            return {
                "status": "connected",
                "folder_count": folder_count,
                "account_id": account_id_value,
            }
        except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
            raise HTTPException(
                status_code=400, detail="Microsoft OAuth succeeded but IMAP access failed"
            ) from exc
    return {"status": session.status, "message": session.message, "error": session.error}


@app.get("/api/accounts")
def accounts() -> dict[str, object]:
    results: list[dict[str, object]] = []
    for item in scan_store.accounts():
        opaque_id = str(item["id"])
        try:
            username = credential_store.get_username(opaque_id)
        except LookupError:
            username = "Reconnect required"
        results.append({**item, "username": username})
    return {"accounts": results}


@app.get("/api/ollama/status")
def ollama_status() -> dict[str, object]:
    try:
        return OllamaClient(settings.ollama_base_url, settings.ollama_model).status()
    except (httpx.HTTPError, ValueError):
        return {"reachable": False, "model": settings.ollama_model, "model_available": False}


@app.post("/api/accounts/test")
def test_account(request: AccountCredentials) -> dict[str, object]:
    provider = _provider_or_400(request.provider)
    if not provider.connectable:
        raise HTTPException(
            status_code=409,
            detail=f"{provider.display_name} requires the {provider.auth_mode} connector",
        )
    try:
        with ReadOnlyImapClient(provider) as client:
            client.authenticate(request.username, request.password)
            folder_count = client.test_connection()
    except (imaplib.IMAP4.error, OSError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail="Secure IMAP connection failed") from exc
    opaque_id = account_id(request.provider, request.username)
    if request.save_to_keyring:
        credential_store.set_account(opaque_id, request.username, request.password)
        scan_store.register_account(opaque_id, request.provider)
    return {
        "connected": True,
        "provider": provider.display_name,
        "folder_count": folder_count,
        "credential_saved": request.save_to_keyring,
    }


@app.get("/api/dashboard")
def dashboard(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    return {
        **scan_store.dashboard_summary(settings.large_message_bytes, account_id),
        "dry_run": True,
        "destructive_actions_allowed": False,
    }


@app.get("/api/archive/destination")
def archive_destination(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    destination = scan_store.archive_destination(account_id)
    return {"configured": destination is not None, "destination": destination}


@app.get("/api/mail/biggest")
def biggest_mail(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    return {"items": scan_store.biggest_messages(account_id), "limit": 250}


@app.get("/api/mail/activity-overview")
def mail_activity_overview(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    sent = scan_store.sent_messages(account_id)
    return {
        "senders": scan_store.sender_rankings(account_id),
        "sent": sent,
        "sent_summary": scan_store.sent_summary(account_id),
        "limits": {"senders": 500, "sent": 500},
    }


def _sender_cleanup_plan(
    request: SenderCleanupRequest,
) -> tuple[JobRecord, list[dict[str, object]], list[dict[str, object]]]:
    account_id_value = _validate_account_id(request.account_id)
    scan_job_id, items = scan_store.messages_from_senders(account_id_value, request.senders)
    job = scan_store.job(scan_job_id) if scan_job_id else None
    if job is None:
        raise HTTPException(status_code=409, detail="Run a complete mailbox scan first")
    rules = scan_store.protection_rules(account_id_value)
    protected = [
        {**item, "protection_reason": reason}
        for item in items
        if (reason := _protection_reason(item, rules))
    ]
    protected_keys = {(str(item["folder"]), str(item["uid"])) for item in protected}
    actionable = [
        item for item in items if (str(item["folder"]), str(item["uid"])) not in protected_keys
    ]
    return job, actionable, protected


@app.post("/api/mail/senders/cleanup-preview")
def preview_sender_cleanup(request: SenderCleanupRequest) -> dict[str, object]:
    _, actionable, protected = _sender_cleanup_plan(request)
    return {
        "senders": len(request.senders),
        "messages": len(actionable) + len(protected),
        "actionable": len(actionable),
        "protected": len(protected),
        "bytes": sum(int(item["size_bytes"]) for item in actionable),
        "protected_examples": [
            {
                "subject": item["subject"],
                "reason": item["protection_reason"],
            }
            for item in protected[:10]
        ],
        "destination": "Trash",
        "permanent_deletion": False,
    }


@app.post("/api/mail/senders/cleanup")
def execute_sender_cleanup(request: SenderCleanupRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    job, actionable, protected = _sender_cleanup_plan(request)
    completed = 0
    failed = 0
    unavailable = 0
    try:
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(
                credential_store.get_username(job.account_id),
                credential_store.get_password(job.account_id),
            )
            destination = client.trash_folder()
            for item in actionable:
                folder = str(item["folder"])
                uid = str(item["uid"])
                try:
                    moved_uid = client.move_message(folder, uid, destination)
                except ConnectionError:
                    unavailable += 1
                    continue
                except (imaplib.IMAP4.error, OSError, ValueError):
                    failed += 1
                    continue
                scan_store.record_action(job.id, folder, uid, "delete", "completed")
                scan_store.record_operation(
                    job.account_id, job.id, folder, moved_uid, "delete", destination
                )
                completed += 1
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Sender cleanup stopped safely after {completed} completed messages",
        ) from exc
    return {
        "requested": len(actionable),
        "completed": completed,
        "protected": len(protected),
        "failed": failed,
        "unavailable": unavailable,
        "destination": destination,
    }


@app.get("/api/insights")
def insights(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    return scan_store.mailbox_insights(account_id)


@app.get("/api/intelligence/action-inbox")
def action_inbox(account_id: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    states = scan_store.action_inbox_states(account_id_value)
    items = action_candidates(scan_store.latest_inventory(account_id_value))
    for item in items:
        key = (str(item["job_id"]), str(item["folder"]), str(item["uid"]))
        item["status"] = states.get(key, "open")
    return {
        "items": items[:1000],
        "summary": {
            status: sum(item["status"] == status for item in items)
            for status in ("open", "waiting", "done", "dismissed")
        },
        "limit": 1000,
        "max_age_days": 45,
        "local_only": True,
    }


@app.post("/api/intelligence/action-inbox/state")
def set_action_inbox_state(request: ActionInboxStateRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    item = scan_store.inventory_item(request.job_id, request.folder, request.uid)
    job = scan_store.job(request.job_id)
    if item is None or job is None or job.account_id != account_id_value:
        raise HTTPException(status_code=404, detail="Action item was not found for this account")
    scan_store.save_action_inbox_state(
        account_id_value, request.job_id, request.folder, request.uid, request.status
    )
    return {"updated": True, "status": request.status}


def _message_text_preview(raw: bytes) -> str:
    message = message_from_bytes(raw)
    plain_parts: list[str] = []
    html_parts: list[str] = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        if content_type not in {"text/plain", "text/html"}:
            continue
        payload = part.get_payload(decode=True)
        if not isinstance(payload, bytes):
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, "replace")
        except LookupError:
            text = payload.decode("utf-8", "replace")
        if content_type == "text/plain":
            plain_parts.append(text)
        else:
            html_parts.append(text)
    combined = "\n".join(plain_parts)
    if not combined and html_parts:
        combined = re.sub(r"<[^>]+>", " ", "\n".join(html_parts))
    return re.sub(r"\s+", " ", combined).strip()[:8000]


@app.post("/api/intelligence/action-inbox/review")
def review_action_item(request: ActionInboxReviewRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    item = scan_store.inventory_item(request.job_id, request.folder, request.uid)
    job = scan_store.job(request.job_id)
    if item is None or job is None or job.account_id != account_id_value:
        raise HTTPException(status_code=404, detail="Action item was not found for this account")
    try:
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(
                credential_store.get_username(account_id_value),
                credential_store.get_password(account_id_value),
            )
            raw = client.fetch_raw_message(request.folder, request.uid)
        result = qwen_action_review(
            decoded(str(item["subject"])),
            decoded(str(item["sender"])),
            str(item.get("internal_date") or ""),
            _message_text_preview(raw),
            settings.ollama_base_url,
            settings.ollama_model,
        )
    except (
        imaplib.IMAP4.error,
        OSError,
        LookupError,
        ConnectionError,
        httpx.HTTPError,
        ValueError,
    ) as exc:
        raise HTTPException(status_code=400, detail="Local action review stopped safely") from exc
    return {**result.model_dump(), "local_only": True, "message_marked_read": False}


@app.post("/api/intelligence/search")
def semantic_mail_search(request: SemanticSearchRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    inventory = scan_store.latest_inventory(account_id_value)
    metadata_candidates = lexical_candidates(request.query, inventory)
    content_candidates = scan_store.search_message_content(account_id_value, request.query)
    candidates_by_id: dict[tuple[str, str, str], dict[str, object]] = {}
    for item in [*content_candidates, *metadata_candidates]:
        key = (str(item["job_id"]), str(item["folder"]), str(item["uid"]))
        candidates_by_id.setdefault(key, item)
    candidates = list(candidates_by_id.values())[:120]
    used_qwen = False
    explanation = "Strict local metadata match"
    results = candidates[:50]
    if candidates:
        try:
            results, explanation = qwen_semantic_search(
                request.query, candidates, settings.ollama_base_url, settings.ollama_model
            )
            used_qwen = True
        except (httpx.HTTPError, ValueError, KeyError):
            pass
    return {
        "query": request.query,
        "results": results,
        "candidate_count": len(candidates),
        "content_candidate_count": len(content_candidates),
        "metadata_candidate_count": len(metadata_candidates),
        "explanation": explanation,
        "qwen_used": used_qwen,
        "content_sent_external": False,
    }


@app.get("/api/intelligence/content-index")
def content_index_status(account_id: str) -> dict[str, object]:
    return scan_store.content_index_status(_validate_account_id(account_id))


@app.post("/api/intelligence/content-index/start")
def start_content_index(request: ContentIndexRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    try:
        run_id = content_index_manager.start(account_id_value)
    except (LookupError, RuntimeError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id, "status": "running", "local_only": True}


@app.delete("/api/intelligence/content-index")
def clear_content_index(account_id: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    try:
        scan_store.delete_content_index(account_id_value)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"deleted": True, "local_only": True}


@app.get("/api/intelligence/relationships")
def relationship_insights(account_id: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    companies = consolidate_companies(scan_store.latest_inventory(account_id_value))
    return {"companies": companies[:500], "limit": 500}


@app.get("/api/intelligence/company")
def company_insights(account_id: str, company: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    normalized = company.casefold().strip()
    if not normalized or len(normalized) > 320:
        raise HTTPException(
            status_code=400, detail="A valid company or sender identity is required"
        )
    details = company_details(scan_store.latest_inventory(account_id_value), normalized)
    if not details["messages"]:
        raise HTTPException(status_code=404, detail="Company identity was not found")
    return details


@app.get("/api/intelligence/lifecycle")
def lifecycle_insights(account_id: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    run = scan_store.ai_cleanup_run(account_id=account_id_value)
    suggestions = scan_store.ai_cleanup_suggestions(str(run["id"]), limit=50_000) if run else []
    return {"run": run, "entities": lifecycle_entities(suggestions)}


@app.get("/api/intelligence/attachments")
def attachment_insights(account_id: str) -> dict[str, object]:
    return scan_store.attachment_insights(_validate_account_id(account_id))


@app.post("/api/intelligence/attachments/scan")
def scan_attachments(request: AttachmentScanRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    account = next((item for item in scan_store.accounts() if item["id"] == account_id_value), None)
    if account is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    messages = scan_store.biggest_messages(account_id_value, request.limit)
    indexed_messages = 0
    indexed_attachments = 0
    try:
        with ReadOnlyImapClient(get_provider(str(account["provider"]))) as client:
            client.authenticate(
                credential_store.get_username(account_id_value),
                credential_store.get_password(account_id_value),
            )
            for item in messages:
                try:
                    raw = client.fetch_raw_message(str(item["folder"]), str(item["uid"]))
                except ConnectionError:
                    continue
                message = message_from_bytes(raw)
                attachments: list[dict[str, object]] = []
                for part in message.walk():
                    filename = decoded(str(part.get_filename() or ""))
                    if not filename and part.get_content_disposition() != "attachment":
                        continue
                    payload = part.get_payload(decode=True)
                    content = payload if isinstance(payload, bytes) else b""
                    safe_name = filename or "unnamed-attachment"
                    attachments.append(
                        {
                            "filename": safe_name[:255],
                            "content_type": part.get_content_type()[:120],
                            "size_bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "category": attachment_category(
                                safe_name, decoded(str(item["subject"]))
                            ),
                        }
                    )
                scan_store.replace_message_attachments(
                    account_id_value,
                    str(item["job_id"]),
                    str(item["folder"]),
                    str(item["uid"]),
                    attachments,
                )
                indexed_messages += 1
                indexed_attachments += len(attachments)
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Attachment scan stopped safely after {indexed_messages} messages",
        ) from exc
    return {
        "indexed_messages": indexed_messages,
        "indexed_attachments": indexed_attachments,
        **scan_store.attachment_insights(account_id_value),
    }


@app.get("/api/intelligence/quality")
def ai_quality(account_id: str) -> dict[str, object]:
    return scan_store.ai_quality_metrics(_validate_account_id(account_id))


@app.get("/api/intelligence/health")
def mailbox_health(account_id: str) -> dict[str, object]:
    return scan_store.mailbox_health(_validate_account_id(account_id))


@app.get("/api/search")
def search_mailbox(account_id: str, q: str = "", folder: str | None = None) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    if len(q) > 320:
        raise HTTPException(status_code=400, detail="Search query is too long")
    return {"items": scan_store.search_inventory(account_id, q, folder), "limit": 500}


@app.get("/api/safety-center")
def safety_center(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    return {
        "rules": scan_store.protection_rules(account_id),
        "operations": scan_store.operations(account_id),
        "preferences": scan_store.account_preferences(account_id),
    }


@app.post("/api/protection-rules")
def add_protection_rule(request: ProtectionRuleRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    rule_id = scan_store.save_protection_rule(request.account_id, request.kind, request.value)
    return {"id": rule_id, "rules": scan_store.protection_rules(request.account_id)}


@app.delete("/api/protection-rules/{rule_id}")
def remove_protection_rule(rule_id: str, account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    scan_store.delete_protection_rule(account_id, rule_id)
    return {"rules": scan_store.protection_rules(account_id)}


@app.post("/api/account-preferences")
def save_account_preferences(request: AccountPreferencesRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    scan_store.update_account_preferences(
        request.account_id, request.model_dump(exclude={"account_id"})
    )
    return {"preferences": scan_store.account_preferences(request.account_id)}


@app.post("/api/mail/actions/preview")
def preview_mail_action(request: MailActionRequest) -> dict[str, object]:
    first_job = scan_store.job(request.items[0].job_id)
    if first_job is None or any(item.job_id != first_job.id for item in request.items):
        raise HTTPException(status_code=400, detail="All selected messages must belong to one scan")
    rules = scan_store.protection_rules(first_job.account_id)
    protected: list[dict[str, str]] = []
    for reference in request.items:
        item = scan_store.inventory_item(reference.job_id, reference.folder, reference.uid)
        if item is not None and (reason := _protection_reason(item, rules)):
            protected.append({"uid": reference.uid, "reason": reason})
    if protected:
        raise HTTPException(
            status_code=409,
            detail={"message": "Protected messages were blocked", "items": protected},
        )
    rules = scan_store.protection_rules(first_job.account_id)
    messages = []
    for reference in request.items:
        item = scan_store.inventory_item(reference.job_id, reference.folder, reference.uid)
        if item is None:
            continue
        reason = _protection_reason(item, rules)
        messages.append({**item, "protected": bool(reason), "protection_reason": reason})
    return {
        "action": request.action,
        "messages": messages,
        "count": len(messages),
        "bytes": sum(int(item["size_bytes"]) for item in messages),
        "protected": sum(bool(item["protected"]) for item in messages),
    }


@app.post("/api/operations/undo")
def undo_operation(request: UndoRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    event = scan_store.operation(request.account_id, request.operation_id)
    if event is None or event.get("undo_status") == "completed":
        raise HTTPException(status_code=404, detail="Undoable operation was not found")
    if event.get("destination") is None or event["action"] not in (
        "delete",
        "archive",
        "export_delete",
        "ai_trash",
        "ai_archive",
        "newsletter_cleanup",
    ):
        raise HTTPException(status_code=409, detail="This operation cannot be undone")
    job = scan_store.job(str(event["job_id"]))
    if job is None:
        raise HTTPException(status_code=404, detail="Original scan was not found")
    try:
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(
                credential_store.get_username(job.account_id),
                credential_store.get_password(job.account_id),
            )
            client.move_message(str(event["destination"]), str(event["uid"]), str(event["folder"]))
        scan_store.mark_operation_undone(request.operation_id)
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Undo stopped safely") from exc
    return {"status": "undone"}


@app.get("/api/config/export")
def export_configuration(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    account = next(item for item in scan_store.accounts() if item["id"] == account_id)
    return {
        "format": "local-mail-organizer-config-v1",
        "provider": account["provider"],
        "protection_rules": scan_store.protection_rules(account_id),
        "filing_rules": scan_store.filing_rules(account_id),
        "preferences": scan_store.account_preferences(account_id),
        "contains_credentials": False,
    }


@app.post("/api/config/import")
def import_configuration(request: ConfigurationImportRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    imported = 0
    for rule in request.protection_rules:
        kind = str(rule.get("kind", ""))
        value = str(rule.get("value", ""))
        if kind in {"sender", "domain", "folder", "subject"} and value:
            scan_store.save_protection_rule(request.account_id, kind, value)
            imported += 1
    allowed_preferences = {
        key: value
        for key, value in request.preferences.items()
        if key in {"paused", "learning_mode", "schedule_minutes", "max_actions", "notify_errors"}
    }
    if allowed_preferences:
        scan_store.update_account_preferences(request.account_id, allowed_preferences)
    return {"imported_rules": imported, "contains_credentials": False}


@app.get("/api/diagnostics")
def diagnostics(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    latest = scan_store.latest_job(account_id)
    return {
        "api": "ok",
        "database": "ok",
        "credential_available": bool(credential_store.get_username(account_id)),
        "latest_scan_status": latest.status if latest else None,
        "ollama_model": settings.ollama_model,
        "privacy": "No message content or credentials included",
    }


@app.get("/api/security/findings")
def security_findings(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    inventory = scan_store.security_inventory(account_id)
    allowed = scan_store.security_allowlist(account_id)
    findings = [
        finding
        for row in inventory
        if sender_identity(str(row["sender"])) not in allowed
        and (finding := phishing_finding(row)) is not None
    ]
    findings.sort(key=lambda item: _object_int(item["risk_score"]), reverse=True)
    reviews = scan_store.security_ai_reviews({str(item["job_id"]) for item in findings})
    return {
        "findings": findings,
        "analyzed": len(inventory),
        "assessments": [
            {**review, "finding_id": f"{review['job_id']}:{review['folder']}:{review['uid']}"}
            for review in reviews
        ],
    }


@app.post("/api/security/safe")
def mark_security_senders_safe(request: SecuritySafeRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    saved = 0
    for reference in request.items:
        item = scan_store.inventory_item(reference.job_id, reference.folder, reference.uid)
        if item is None:
            continue
        identity = sender_identity(str(item["sender"]))
        if identity:
            job = scan_store.job(reference.job_id)
            if job is None:
                continue
            scan_store.allow_security_sender(job.account_id, identity)
            saved += 1
    return {"saved": saved}


@app.post("/api/security/qwen-review")
def qwen_review_security_findings(request: SecurityReviewRequest) -> dict[str, object]:
    first_job = scan_store.job(request.items[0].job_id)
    if first_job is None or any(item.job_id != first_job.id for item in request.items):
        raise HTTPException(status_code=400, detail="All selections must belong to one scan")
    findings: list[dict[str, object]] = []
    for reference in request.items:
        item = scan_store.inventory_item(reference.job_id, reference.folder, reference.uid)
        finding = phishing_finding(item) if item else None
        if finding is not None:
            findings.append(finding)
    try:
        username = credential_store.get_username(first_job.account_id)
        password = credential_store.get_password(first_job.account_id)
        headers: dict[tuple[str, str], bytes] = {}
        grouped: dict[str, list[str]] = defaultdict(list)
        for reference in request.items:
            grouped[reference.folder].append(reference.uid)
        with ReadOnlyImapClient(get_provider(first_job.provider)) as client:
            client.authenticate(username, password)
            for folder, uids in grouped.items():
                for uid, raw in client.fetch_security_headers_by_uids(folder, uids).items():
                    headers[(folder, uid)] = raw
        for finding in findings:
            finding["authentication"] = authentication_signals(
                headers.get((str(finding["folder"]), str(finding["uid"])), b"")
            )
        assessments = qwen_security_review(
            findings, settings.ollama_base_url, settings.ollama_model
        )
        references = {f"{item['job_id']}:{item['folder']}:{item['uid']}": item for item in findings}
        for assessment in assessments:
            reference = references.get(str(assessment["finding_id"]))
            if reference:
                scan_store.save_security_ai_review(
                    str(reference["job_id"]),
                    str(reference["folder"]),
                    str(reference["uid"]),
                    str(assessment["verdict"]),
                    float(assessment["confidence"]),
                    str(assessment["reason"]),
                )
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise HTTPException(
            status_code=503, detail="Local Qwen security review is unavailable"
        ) from exc
    return {
        "assessments": assessments,
        "authentication": {
            f"{item['job_id']}:{item['folder']}:{item['uid']}": item.get("authentication")
            for item in findings
        },
    }


@app.get("/api/newsletters")
def newsletters(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    return {"groups": scan_store.newsletter_groups(account_id), "limit": 500}


@app.post("/api/ai-cleanup/start")
def start_ai_cleanup(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    latest = scan_store.ai_cleanup_run(account_id=account_id)
    if latest and latest["status"] == "running":
        latest_id = str(latest["id"])
        if ai_cleanup_manager.is_active(latest_id):
            return {"run_id": latest_id, "status": "running"}
        scan_store.finish_ai_cleanup_run(
            latest_id,
            "failed",
            "The previous local worker stopped; a new analysis was started",
        )
    try:
        run_id = ai_cleanup_manager.start(account_id)
    except LookupError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run_id, "status": "running"}


@app.get("/api/ai-cleanup")
def ai_cleanup(account_id: str, run_id: str | None = None) -> dict[str, object]:
    _validate_account_id(account_id)
    run = scan_store.ai_cleanup_run(run_id, account_id)
    if run is None:
        return {"run": None, "suggestions": [], "summary": None}
    all_suggestions = scan_store.pending_ai_cleanup_suggestions(str(run["id"]), limit=50_000)
    suggestions = all_suggestions[:1000]
    summary = {
        "groups_analyzed": len(all_suggestions),
        "messages_analyzed": sum(int(item["message_count"]) for item in all_suggestions),
        "trash_messages": sum(
            int(item["message_count"])
            for item in all_suggestions
            if item["recommendation"] == "trash_review"
        ),
        "trash_bytes": sum(
            int(item["total_bytes"])
            for item in all_suggestions
            if item["recommendation"] == "trash_review"
        ),
        "archive_messages": sum(
            int(item["message_count"])
            for item in all_suggestions
            if item["recommendation"] == "archive_review"
        ),
        "archive_bytes": sum(
            int(item["total_bytes"])
            for item in all_suggestions
            if item["recommendation"] == "archive_review"
        ),
        "protected_messages": sum(
            int(item["message_count"]) for item in all_suggestions if bool(item["protected"])
        ),
    }
    return {
        "run": run,
        "suggestions": suggestions,
        "summary": summary,
        "suggestion_limit": 1000,
        "feedback": scan_store.ai_cleanup_feedback(account_id),
    }


@app.post("/api/ai-cleanup/feedback")
def save_ai_cleanup_feedback(request: AICleanupFeedbackRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    run = scan_store.ai_cleanup_run(account_id=account_id_value)
    if run is None:
        raise HTTPException(status_code=409, detail="Run AI Cleanup first")
    suggestion = next(
        (
            item
            for item in scan_store.ai_cleanup_suggestions(str(run["id"]), limit=50_000)
            if item["id"] == request.suggestion_id
        ),
        None,
    )
    if suggestion is None:
        raise HTTPException(status_code=404, detail="Cleanup suggestion was not found")
    if bool(suggestion["protected"]) and request.decision == "trash_review":
        raise HTTPException(
            status_code=409,
            detail="A deterministic protection rule blocks Trash; archive or keep this group",
        )
    feedback_id = scan_store.save_ai_cleanup_feedback(
        account_id_value,
        str(suggestion["sender_domain"]),
        str(suggestion["subject_pattern"]),
        request.decision,
        str(suggestion["recommendation"]),
    )
    if not scan_store.apply_ai_cleanup_feedback(
        account_id_value, request.suggestion_id, request.decision
    ):
        raise HTTPException(status_code=409, detail="Current analysis could not be updated")
    return {
        "id": feedback_id,
        "saved": True,
        "current_analysis_updated": True,
        "applies_to_future_runs": True,
    }


def _retention_preview(account_id_value: str) -> dict[str, object]:
    run = scan_store.ai_cleanup_run(account_id=account_id_value)
    policies = scan_store.retention_policies(account_id_value)
    if run is None:
        return {"policies": policies, "groups": 0, "messages": 0, "bytes": 0, "matches": []}
    now = datetime.now(UTC)
    matches: list[dict[str, object]] = []
    for policy in policies:
        if not policy["enabled"]:
            continue
        for item in scan_store.ai_cleanup_suggestions(str(run["id"]), limit=50_000):
            if item["category"] != policy["category"] or bool(item["protected"]):
                continue
            try:
                date = parsedate_to_datetime(str(item["newest_date"] or ""))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                age_days = max(0, (now - date).days)
            except (TypeError, ValueError, OverflowError):
                continue
            if age_days >= int(policy["age_days"]):
                matches.append(
                    {
                        "policy_id": policy["id"],
                        "suggestion_id": item["id"],
                        "category": item["category"],
                        "action": policy["action"],
                        "messages": item["message_count"],
                        "bytes": item["total_bytes"],
                    }
                )
    return {
        "policies": policies,
        "groups": len(matches),
        "messages": sum(int(item["messages"]) for item in matches),
        "bytes": sum(int(item["bytes"]) for item in matches),
        "matches": matches[:100],
        "dry_run": True,
    }


@app.get("/api/retention/preview")
def retention_preview(account_id: str) -> dict[str, object]:
    return _retention_preview(_validate_account_id(account_id))


@app.post("/api/retention/policies")
def save_retention_policy(request: RetentionPolicyRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    policy_id = scan_store.save_retention_policy(
        account_id_value, request.category, request.action, request.age_days
    )
    return {"id": policy_id, **_retention_preview(account_id_value)}


@app.delete("/api/retention/policies/{policy_id}")
def delete_retention_policy(policy_id: str, account_id: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    scan_store.delete_retention_policy(account_id_value, policy_id)
    return _retention_preview(account_id_value)


@app.get("/api/filing-rules/preview")
def preview_filing_rules(account_id: str) -> dict[str, object]:
    account_id_value = _validate_account_id(account_id)
    run = scan_store.ai_cleanup_run(account_id=account_id_value)
    if run is None:
        return {"matched_rules": 0, "groups": 0, "messages": 0, "bytes": 0, "dry_run": True}
    _, _, rows = scan_store.filing_candidates(str(run["id"]))
    active = {
        str(rule["bucket"]) for rule in scan_store.filing_rules(account_id_value, enabled_only=True)
    }
    proposals = [item for item in build_filing_proposals(rows) if str(item["bucket"]) in active]
    return {
        "matched_rules": len(active),
        "groups": len(proposals),
        "messages": sum(int(item["message_count"]) for item in proposals),
        "bytes": sum(int(item["total_bytes"]) for item in proposals),
        "proposals": [
            {key: value for key, value in item.items() if key != "members"}
            for item in proposals[:100]
        ],
        "dry_run": True,
    }


@app.get("/api/promotions")
def promotions(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    run = scan_store.ai_cleanup_run(account_id=account_id)
    if run is None:
        return {"run": None, "groups": []}
    groups = []
    # Promotions are often many small, one-off campaigns and therefore sit
    # outside the general AI Cleanup page's 1,000-row review window.
    for original in scan_store.pending_ai_cleanup_suggestions(str(run["id"]), limit=50_000):
        item = dict(original)
        provider_campaign = is_provider_promotion(
            str(item["sender"]),
            str(item["sender_domain"]),
            str(item["subject_pattern"]),
        )
        if provider_campaign:
            item.update(
                category="promotion",
                recommendation="trash_review",
                confidence=0.98,
                protected=False,
                reason="Recognized WEB.DE/GMX provider advertising campaign",
            )
        elif is_provider_notice(str(item["sender"]), str(item["sender_domain"])):
            item.update(
                category="provider_notice",
                recommendation="trash_review",
                confidence=1.0,
                protected=False,
                reason="WEB.DE/GMX provider notice — review before cleanup",
            )
        if (
            item["recommendation"] == "trash_review"
            and not bool(item["protected"])
            and item["category"]
            in {"promotion", "provider_notice", "notification", "system", "other"}
        ):
            groups.append(item)
    return {"run": run, "groups": groups}


@app.post("/api/ai-cleanup/actions")
def execute_ai_cleanup_action(request: AICleanupActionRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    try:
        scan_job_id, items = scan_store.ai_cleanup_selection(request.run_id, request.suggestion_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if not items:
        raise HTTPException(status_code=404, detail="No cleanup suggestions were selected")
    selected_ids = set(request.suggestion_ids)
    returned_ids = {str(item["suggestion_id"]) for item in items}
    if returned_ids != selected_ids:
        raise HTTPException(status_code=400, detail="One or more suggestions are invalid")
    provider_promotions = {
        str(item["suggestion_id"])
        for item in items
        if (
            is_provider_promotion(
                str(item["sender"]),
                str(item["sender_domain"]),
                str(item["subject_pattern"]),
            )
            or is_provider_notice(str(item["sender"]), str(item["sender_domain"]))
        )
    }
    if any(
        bool(item["protected"]) and str(item["suggestion_id"]) not in provider_promotions
        for item in items
    ):
        raise HTTPException(status_code=409, detail="Protected suggestions cannot be changed")
    if request.action == "trash" and any(
        item["recommendation"] != "trash_review"
        and str(item["suggestion_id"]) not in provider_promotions
        for item in items
    ):
        raise HTTPException(
            status_code=409, detail="Only explicit trash-review suggestions can move to Trash"
        )
    job = scan_store.job(scan_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Source scan is unavailable")
    moved = 0
    attachment_protected = 0
    safety_protected = 0
    already_completed = 0
    source_missing = 0
    failed = 0
    failure_reasons: defaultdict[str, int] = defaultdict(int)
    action_name = "ai_archive" if request.action == "archive" else "ai_trash"
    rules = scan_store.protection_rules(job.account_id)
    destination = "Archive" if request.action == "archive" else "Trash"
    try:
        username = credential_store.get_username(job.account_id)
        password = credential_store.get_password(job.account_id)
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(username, password)
            if request.action == "archive":
                try:
                    destination = client.archive_folder()
                except ConnectionError:
                    client.ensure_folder("Archive")
                    destination = "Archive"
            else:
                destination = client.trash_folder()
            unique_items: dict[tuple[str, str], dict[str, object]] = {}
            for item in items:
                unique_items.setdefault((str(item["folder"]), str(item["uid"])), item)
            live_uids: dict[str, set[str] | None] = {}
            for folder in {folder for folder, _uid in unique_items}:
                try:
                    live_uids[folder] = set(client.message_uids(folder))
                except (imaplib.IMAP4.error, OSError, ConnectionError):
                    # A folder-level lookup failure must not be mistaken for an absent message.
                    live_uids[folder] = None
            for (folder, uid), item in unique_items.items():
                if live_uids[folder] is not None and uid not in live_uids[folder]:
                    scan_store.record_action(
                        scan_job_id, folder, uid, action_name, "source_missing"
                    )
                    source_missing += 1
                    continue
                folder = str(item["folder"])
                uid = str(item["uid"])
                if scan_store.action_completed(scan_job_id, folder, uid, action_name):
                    already_completed += 1
                    continue
                try:
                    inventory_item = scan_store.inventory_item(scan_job_id, folder, uid)
                    if (
                        inventory_item is not None
                        and str(item["suggestion_id"]) not in provider_promotions
                        and _protection_reason(inventory_item, rules)
                    ):
                        scan_store.record_action(
                            scan_job_id, folder, uid, action_name, "safety_protected"
                        )
                        safety_protected += 1
                        continue
                    raw = client.fetch_raw_message(folder, uid)
                    if _message_has_attachment(raw):
                        attachment_protected += 1
                        scan_store.record_action(
                            scan_job_id, folder, uid, action_name, "attachment_protected"
                        )
                        continue
                    moved_uid = client.move_message(folder, uid, destination)
                    scan_store.record_action(scan_job_id, folder, uid, action_name, "completed")
                    scan_store.record_operation(
                        job.account_id,
                        scan_job_id,
                        folder,
                        moved_uid,
                        action_name,
                        destination,
                    )
                    moved += 1
                except imaplib.IMAP4.error:
                    scan_store.record_action(scan_job_id, folder, uid, action_name, "imap_rejected")
                    failure_reasons["IMAP server rejected the operation"] += 1
                    failed += 1
                except ConnectionError:
                    scan_store.record_action(scan_job_id, folder, uid, action_name, "mailbox_error")
                    failure_reasons["Mailbox could not fetch or move the message"] += 1
                    failed += 1
                except OSError:
                    scan_store.record_action(scan_job_id, folder, uid, action_name, "network_error")
                    failure_reasons["Network connection failed"] += 1
                    failed += 1
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Cleanup stopped safely after {moved} completed messages",
        ) from exc
    return {
        "requested": len(unique_items),
        "moved": moved,
        "attachment_protected": attachment_protected,
        "safety_protected": safety_protected,
        "already_completed": already_completed,
        "source_missing": source_missing,
        "failed": failed,
        "failure_reasons": dict(failure_reasons),
        "destination": destination,
    }


def _message_has_attachment(raw: bytes) -> bool:
    message = message_from_bytes(raw)
    return any(
        part.get_filename() is not None or part.get_content_disposition() == "attachment"
        for part in message.walk()
    )


@app.get("/api/filing-plan")
def filing_plan(account_id: str, run_id: str | None = None) -> dict[str, object]:
    _validate_account_id(account_id)
    run = scan_store.ai_cleanup_run(run_id, account_id)
    if run is None:
        return {
            "run_id": None,
            "proposals": [],
            "rules": scan_store.filing_rules(account_id),
        }
    try:
        _, _, rows = scan_store.filing_candidates(str(run["id"]))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    proposals = [
        {key: value for key, value in proposal.items() if key != "members"}
        for proposal in build_filing_proposals(rows)
    ]
    return {
        "run_id": run["id"],
        "proposals": proposals,
        "rules": scan_store.filing_rules(account_id),
    }


@app.post("/api/filing-plan/apply")
def apply_filing_plan(request: FilingApplyRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    try:
        scan_job_id, account_id_value, rows = scan_store.filing_candidates(request.run_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    proposals = {str(proposal["id"]): proposal for proposal in build_filing_proposals(rows)}
    if any(proposal_id not in proposals for proposal_id in request.proposal_ids):
        raise HTTPException(status_code=400, detail="One or more filing proposals are invalid")
    job = scan_store.job(scan_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Source scan is unavailable")
    moved = 0
    failed = 0
    created_rules = 0
    prepared_future_folders = 0
    try:
        username = credential_store.get_username(job.account_id)
        password = credential_store.get_password(job.account_id)
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(username, password)
            selected_buckets: set[str] = set()
            for proposal_id in request.proposal_ids:
                proposal = proposals[proposal_id]
                selected_buckets.add(str(proposal["bucket"]))
                destination = validate_folder_name(
                    client.ensure_folder_path(str(proposal["bucket"]), str(proposal["year"]))
                )
                scan_store.save_filing_rule(
                    account_id_value,
                    str(proposal["bucket"]),
                    _object_int(proposal["year"]),
                    destination,
                )
                created_rules += 1
                for item in cast(list[dict[str, object]], proposal["members"]):
                    folder = str(item["folder"])
                    uid = str(item["uid"])
                    if scan_store.action_completed(scan_job_id, folder, uid, "filing_rule"):
                        continue
                    try:
                        client.move_message(folder, uid, destination)
                        scan_store.record_action(
                            scan_job_id, folder, uid, "filing_rule", "completed"
                        )
                        moved += 1
                    except (imaplib.IMAP4.error, OSError, ConnectionError):
                        failed += 1
            current_year = datetime.now(UTC).year
            for bucket in selected_buckets:
                for year in range(current_year + 1, current_year + request.future_years + 1):
                    destination = validate_folder_name(client.ensure_folder_path(bucket, str(year)))
                    scan_store.save_filing_rule(account_id_value, bucket, year, destination)
                    created_rules += 1
                    prepared_future_folders += 1
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Filing stopped safely after {moved} completed messages",
        ) from exc
    return {
        "moved": moved,
        "failed": failed,
        "created_rules": created_rules,
        "prepared_future_folders": prepared_future_folders,
    }


@app.post("/api/filing-plan/prepare")
def prepare_filing_folders(request: PrepareFoldersRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    account = next(item for item in scan_store.accounts() if item["id"] == request.account_id)
    prepared: list[str] = []
    created_rules = 0
    try:
        with ReadOnlyImapClient(get_provider(str(account["provider"]))) as client:
            client.authenticate(
                credential_store.get_username(request.account_id),
                credential_store.get_password(request.account_id),
            )
            delimiter = client.folder_delimiter()
            current_year = datetime.now(UTC).year
            for bucket in dict.fromkeys(request.buckets):
                for year in range(current_year, current_year + request.future_years + 1):
                    destination = validate_folder_name(client.ensure_folder_path(bucket, str(year)))
                    scan_store.save_filing_rule(request.account_id, bucket, year, destination)
                    prepared.append(destination)
                    created_rules += 1
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Folder preparation stopped safely after {len(prepared)} folders",
        ) from exc
    return {
        "provider": account["provider"],
        "delimiter": delimiter,
        "folders": prepared,
        "created_rules": created_rules,
    }


@app.post("/api/filing-rules/{rule_id}/state")
def set_filing_rule_state(rule_id: str, request: FilingRuleStateRequest) -> dict[str, object]:
    if len(rule_id) != 32 or not rule_id.isalnum():
        raise HTTPException(status_code=400, detail="Invalid filing rule")
    if not scan_store.set_filing_rule_enabled(rule_id, request.enabled):
        raise HTTPException(status_code=404, detail="Filing rule does not exist")
    return {"updated": True, "enabled": request.enabled}


@app.post("/api/filing-rules/apply")
def apply_saved_filing_rules(request: ApplySavedRulesRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    _validate_account_id(request.account_id)
    run = scan_store.ai_cleanup_run(account_id=request.account_id)
    if run is None:
        raise HTTPException(status_code=409, detail="Run AI Cleanup first")
    scan_job_id, _, rows = scan_store.filing_candidates(str(run["id"]))
    active_buckets = {
        str(rule["bucket"])
        for rule in scan_store.filing_rules(request.account_id, enabled_only=True)
    }
    proposals = [
        proposal
        for proposal in build_filing_proposals(rows)
        if str(proposal["bucket"]) in active_buckets
    ]
    if not proposals:
        return {"moved": 0, "failed": 0, "matched_rules": 0}
    job = scan_store.job(scan_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Source scan is unavailable")
    moved = 0
    failed = 0
    try:
        username = credential_store.get_username(job.account_id)
        password = credential_store.get_password(job.account_id)
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(username, password)
            for proposal in proposals:
                bucket = str(proposal["bucket"])
                year = _object_int(proposal["year"])
                destination = validate_folder_name(client.ensure_folder_path(bucket, str(year)))
                scan_store.save_filing_rule(request.account_id, bucket, year, destination)
                for item in cast(list[dict[str, object]], proposal["members"]):
                    folder = str(item["folder"])
                    uid = str(item["uid"])
                    if scan_store.action_completed(scan_job_id, folder, uid, "filing_rule"):
                        continue
                    try:
                        client.move_message(folder, uid, destination)
                        scan_store.record_action(
                            scan_job_id, folder, uid, "filing_rule", "completed"
                        )
                        moved += 1
                    except (imaplib.IMAP4.error, OSError, ConnectionError):
                        failed += 1
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Saved rules stopped safely after {moved} completed messages",
        ) from exc
    return {"moved": moved, "failed": failed, "matched_rules": len(proposals)}


@app.get("/api/newsletters/capabilities")
def newsletter_capabilities(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    groups = scan_store.newsletter_groups(account_id)
    if not groups:
        return {"capabilities": []}
    job = scan_store.job(str(groups[0]["job_id"]))
    if job is None:
        raise HTTPException(status_code=404, detail="No completed scan is available")
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for group in groups:
        grouped[str(group["folder"])].append(group)
    capabilities: list[dict[str, str]] = []
    try:
        username = credential_store.get_username(job.account_id)
        password = credential_store.get_password(job.account_id)
        with ReadOnlyImapClient(get_provider(job.provider)) as client:
            client.authenticate(username, password)
            for folder, folder_groups in grouped.items():
                for start in range(0, len(folder_groups), 100):
                    batch = folder_groups[start : start + 100]
                    headers = client.fetch_unsubscribe_headers_by_uids(
                        folder, [str(group["uid"]) for group in batch]
                    )
                    for group in batch:
                        uid = str(group["uid"])
                        raw_headers = headers.get(uid, b"")
                        method = unsubscribe_capability(raw_headers)
                        capability = {
                            "job_id": str(group["job_id"]),
                            "folder": folder,
                            "uid": uid,
                            "method": method,
                        }
                        try:
                            capability["page_url"] = unsubscribe_page_url(raw_headers)
                        except (ValueError, OSError):
                            pass
                        capabilities.append(capability)
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(
            status_code=400, detail="Could not analyze unsubscribe methods"
        ) from exc
    return {"capabilities": capabilities}


@app.post("/api/mail/actions")
def execute_mail_action(request: MailActionRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    first_job = scan_store.job(request.items[0].job_id)
    if first_job is None or any(item.job_id != first_job.id for item in request.items):
        raise HTTPException(status_code=400, detail="All selected messages must belong to one scan")
    try:
        username = credential_store.get_username(first_job.account_id)
        password = credential_store.get_password(first_job.account_id)
        provider = get_provider(first_job.provider)
        archive = scan_store.archive_destination(first_job.account_id)
        if request.action == "export_delete" and archive is None:
            raise HTTPException(
                status_code=409, detail="Configure Local / NAS archive storage first"
            )
        completed = 0
        failed = 0
        unavailable = 0
        archived_only = 0
        results: list[dict[str, str]] = []
        with ReadOnlyImapClient(provider) as client:
            client.authenticate(username, password)
            trash_folder = client.trash_folder() if request.action != "archive" else None
            if request.action == "archive":
                try:
                    archive_folder = client.archive_folder()
                except ConnectionError:
                    client.ensure_folder("Archive")
                    archive_folder = "Archive"
            for reference in request.items:
                item = scan_store.inventory_item(reference.job_id, reference.folder, reference.uid)
                if item is None:
                    unavailable += 1
                    results.append({**reference.model_dump(), "status": "not_in_inventory"})
                    continue
                archive_verified = False
                try:
                    if request.action == "export_delete":
                        if archive is None:
                            raise RuntimeError("Archive configuration disappeared")
                        raw = client.fetch_raw_message(reference.folder, reference.uid)
                        relative = (
                            Path(reference.job_id) / reference.folder / f"{reference.uid}.eml"
                        )
                        if archive["kind"] == "dropbox":
                            dropbox_archive.store(
                                first_job.account_id,
                                relative.as_posix(),
                                raw,
                                root_path=str(archive["root_path"]),
                            )
                        else:
                            VerifiedArchive(Path(str(archive["root_path"]))).store(relative, raw)
                        archive_verified = True
                        moved_uid = client.move_message(
                            reference.folder, reference.uid, str(trash_folder)
                        )
                    elif request.action == "archive":
                        moved_uid = client.move_message(
                            reference.folder, reference.uid, archive_folder
                        )
                    else:
                        moved_uid = client.move_message(
                            reference.folder, reference.uid, str(trash_folder)
                        )
                except ConnectionError:
                    if archive_verified:
                        archived_only += 1
                        results.append({**reference.model_dump(), "status": "exported_move_failed"})
                    else:
                        unavailable += 1
                        results.append({**reference.model_dump(), "status": "message_unavailable"})
                    continue
                except (imaplib.IMAP4.error, OSError, ValueError):
                    failed += 1
                    results.append({**reference.model_dump(), "status": "failed_safely"})
                    continue
                scan_store.record_action(
                    reference.job_id, reference.folder, reference.uid, request.action, "completed"
                )
                destination = archive_folder if request.action == "archive" else trash_folder
                scan_store.record_operation(
                    first_job.account_id,
                    reference.job_id,
                    reference.folder,
                    moved_uid,
                    request.action,
                    str(destination),
                )
                completed += 1
                results.append({**reference.model_dump(), "status": "completed"})
    except HTTPException:
        raise
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Action stopped after {locals().get('completed', 0)} completed messages",
        ) from exc
    return {
        "requested": len(request.items),
        "completed": completed,
        "failed": failed,
        "unavailable": unavailable,
        "exported_move_failed": archived_only,
        "action": request.action,
        "results": results,
        "rescan_recommended": unavailable > 0,
    }


@app.post("/api/mail/trash/empty")
def empty_trash(request: EmptyTrashRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    if request.confirmation != "EMPTY TRASH":
        raise HTTPException(
            status_code=400, detail="Type EMPTY TRASH to confirm permanent deletion"
        )
    account = next(item for item in scan_store.accounts() if item["id"] == request.account_id)
    try:
        username = credential_store.get_username(request.account_id)
        password = credential_store.get_password(request.account_id)
        with ReadOnlyImapClient(get_provider(str(account["provider"]))) as client:
            client.authenticate(username, password)
            folder = client.trash_folder()
            deleted = client.empty_folder(folder)
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Trash cleanup stopped safely") from exc
    return {"deleted": deleted, "folder": folder}


@app.get("/api/mail/trash/status")
def trash_status(account_id: str) -> dict[str, object]:
    account_id = _validate_account_id(account_id)
    account = next(item for item in scan_store.accounts() if item["id"] == account_id)
    try:
        with ReadOnlyImapClient(get_provider(str(account["provider"]))) as client:
            client.authenticate(
                credential_store.get_username(account_id),
                credential_store.get_password(account_id),
            )
            folder = client.trash_folder()
            count = client.folder_message_count(folder)
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Could not read Trash status") from exc
    return {"count": count, "folder": folder}


@app.post("/api/newsletters/unsubscribe")
def unsubscribe_newsletters(request: NewsletterActionRequest) -> dict[str, object]:
    if not request.confirmed:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    first_job = scan_store.job(request.items[0].job_id)
    if first_job is None or any(item.job_id != first_job.id for item in request.items):
        raise HTTPException(status_code=400, detail="All selections must belong to one scan")
    completed = 0
    manual = 0
    failed = 0
    deleted_messages = 0
    cleanup_failed = 0
    results: list[dict[str, str]] = []
    try:
        username = credential_store.get_username(first_job.account_id)
        password = credential_store.get_password(first_job.account_id)
        provider = get_provider(first_job.provider)
        with ReadOnlyImapClient(provider) as client:
            client.authenticate(username, password)
            trash_folder = client.trash_folder()
            rules = scan_store.protection_rules(first_job.account_id)
            for reference in request.items:
                if (
                    scan_store.inventory_item(reference.job_id, reference.folder, reference.uid)
                    is None
                ):
                    failed += 1
                    results.append({**reference.model_dump(), "status": "not_found"})
                    continue
                already_unsubscribed = scan_store.action_completed(
                    reference.job_id, reference.folder, reference.uid, "unsubscribe"
                )
                result_status = "resumed" if already_unsubscribed else "unsubscribed"
                try:
                    if not already_unsubscribed:
                        raw = client.fetch_unsubscribe_headers(reference.folder, reference.uid)
                        method = unsubscribe_capability(raw)
                        if method == "automatic":
                            try:
                                unsubscribe_one_click(raw)
                            except (httpx.HTTPError, OSError, ConnectionError) as endpoint_error:
                                try:
                                    unsubscribe_by_email(
                                        raw,
                                        username=username,
                                        password=password,
                                        smtp_host=get_provider(first_job.provider).smtp_host,
                                        smtp_port=get_provider(first_job.provider).smtp_port,
                                        auth_mode=provider.auth_mode,
                                        allow_self_signed_local=provider.allow_self_signed_local,
                                    )
                                except ValueError:
                                    raise endpoint_error
                                result_status = "email_fallback"
                        elif method == "email":
                            unsubscribe_by_email(
                                raw,
                                username=username,
                                password=password,
                                smtp_host=get_provider(first_job.provider).smtp_host,
                                smtp_port=get_provider(first_job.provider).smtp_port,
                                auth_mode=provider.auth_mode,
                                allow_self_signed_local=provider.allow_self_signed_local,
                            )
                        else:
                            raise ValueError("Manual unsubscribe is required")
                except ValueError:
                    manual += 1
                    results.append({**reference.model_dump(), "status": "manual"})
                    continue
                except (
                    imaplib.IMAP4.error,
                    httpx.HTTPError,
                    smtplib.SMTPException,
                    OSError,
                    ConnectionError,
                ):
                    failed += 1
                    results.append({**reference.model_dump(), "status": "endpoint_failed"})
                    continue
                if not already_unsubscribed:
                    scan_store.record_action(
                        reference.job_id,
                        reference.folder,
                        reference.uid,
                        "unsubscribe",
                        "completed",
                    )
                    completed += 1
                for message in scan_store.newsletter_messages_for_representative(
                    reference.job_id, reference.folder, reference.uid
                ):
                    try:
                        message_folder = str(message["folder"])
                        message_uid = str(message["uid"])
                        if scan_store.action_completed(
                            reference.job_id,
                            message_folder,
                            message_uid,
                            "newsletter_cleanup",
                        ):
                            continue
                        inventory_item = scan_store.inventory_item(
                            reference.job_id, message_folder, message_uid
                        )
                        if inventory_item is not None and _protection_reason(inventory_item, rules):
                            scan_store.record_action(
                                reference.job_id,
                                message_folder,
                                message_uid,
                                "newsletter_cleanup",
                                "safety_protected",
                            )
                            continue
                        if message_folder.casefold() != "trash":
                            moved_uid = client.move_message(
                                message_folder, message_uid, trash_folder
                            )
                            scan_store.record_operation(
                                first_job.account_id,
                                reference.job_id,
                                message_folder,
                                moved_uid,
                                "newsletter_cleanup",
                                trash_folder,
                            )
                        scan_store.record_action(
                            reference.job_id,
                            message_folder,
                            message_uid,
                            "newsletter_cleanup",
                            "completed",
                        )
                        deleted_messages += 1
                    except (imaplib.IMAP4.error, OSError, ConnectionError):
                        cleanup_failed += 1
                results.append(
                    {
                        **reference.model_dump(),
                        "status": result_status,
                    }
                )
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The mailbox connection failed before the batch could be processed",
        ) from exc
    return {
        "requested": len(request.items),
        "completed": completed,
        "manual_review": manual,
        "failed": failed,
        "deleted_messages": deleted_messages,
        "cleanup_failed": cleanup_failed,
        "results": results,
    }


@app.post("/api/archive/destination")
def configure_archive_destination(request: ArchiveDestinationRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    try:
        if request.kind == "dropbox":
            if not dropbox_archive.connected(request.account_id):
                raise LookupError("Connect Dropbox first")
            root_value = "/" + request.root_path.strip("/ ")
            dropbox_archive.verify(request.account_id, root_value)
        else:
            root_value = str(_verify_archive_root(request.root_path))
    except (httpx.HTTPError, OSError, ValueError, LookupError) as exc:
        raise HTTPException(
            status_code=400,
            detail="The archive path is unavailable or not writable",
        ) from exc
    scan_store.save_archive_destination(request.account_id, request.kind, root_value)
    return {
        "configured": True,
        "destination": scan_store.archive_destination(request.account_id),
        "integrity_check": "passed",
    }


@app.post("/api/intelligence/attachments/extract")
def extract_attachment_content(request: AttachmentTextRequest) -> dict[str, object]:
    account_id_value = _validate_account_id(request.account_id)
    account = next((item for item in scan_store.accounts() if item["id"] == account_id_value), None)
    if account is None:
        raise HTTPException(status_code=404, detail="Account was not found")
    completed = 0
    unsupported = 0
    failed = 0
    try:
        with ReadOnlyImapClient(get_provider(str(account["provider"]))) as client:
            client.authenticate(
                credential_store.get_username(account_id_value),
                credential_store.get_password(account_id_value),
            )
            for reference in request.items:
                try:
                    raw = client.fetch_raw_message(reference.folder, reference.uid)
                    message = message_from_bytes(raw)
                    matched = False
                    for part in message.walk():
                        payload = part.get_payload(decode=True)
                        content = payload if isinstance(payload, bytes) else b""
                        if hashlib.sha256(content).hexdigest() != reference.sha256:
                            continue
                        matched = True
                        filename = decoded(str(part.get_filename() or "unnamed-attachment"))
                        text, method = extract_attachment_text(
                            content,
                            filename,
                            part.get_content_type(),
                            settings.ollama_base_url,
                            settings.ollama_vision_model,
                        )
                        scan_store.save_attachment_text(
                            account_id_value,
                            reference.job_id,
                            reference.folder,
                            reference.uid,
                            reference.sha256,
                            text,
                            method,
                        )
                        if text:
                            completed += 1
                        else:
                            unsupported += 1
                        break
                    if not matched:
                        failed += 1
                except (ConnectionError, OSError, ValueError, httpx.HTTPError):
                    failed += 1
    except (imaplib.IMAP4.error, OSError, LookupError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail="Document extraction stopped safely") from exc
    return {
        "completed": completed,
        "unsupported": unsupported,
        "failed": failed,
        **scan_store.attachment_insights(account_id_value),
    }


@app.get("/api/archive/dropbox/status")
def dropbox_status(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    return {"connected": dropbox_archive.connected(account_id)}


@app.post("/api/archive/dropbox/start")
def start_dropbox(request: DropboxStartRequest) -> dict[str, object]:
    _validate_account_id(request.account_id)
    authorization = dropbox_archive.begin(request.account_id, request.app_key.strip())
    return {"authorization_url": authorization.url}


@app.get("/api/archive/dropbox/callback")
def complete_dropbox(code: str, state: str) -> RedirectResponse:
    try:
        dropbox_archive.complete(state, code)
    except (httpx.HTTPError, LookupError, ValueError):
        return RedirectResponse(f"{settings.web_origin}/archive?dropbox=failed")
    return RedirectResponse(f"{settings.web_origin}/archive?dropbox=connected")


@app.delete("/api/archive/dropbox")
def disconnect_dropbox(account_id: str) -> dict[str, object]:
    _validate_account_id(account_id)
    dropbox_archive.disconnect(account_id)
    return {"connected": False}


def _verify_archive_root(value: str) -> Path:
    root = Path(value).expanduser()
    if not root.is_absolute():
        raise ValueError("Archive root must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    root = root.resolve(strict=True)
    test_name = Path(".local-mail-organizer") / f"write-test-{uuid4().hex}.bin"
    receipt = VerifiedArchive(root).store(test_name, b"local-mail-organizer archive verification")
    receipt.path.unlink()
    try:
        receipt.path.parent.rmdir()
    except OSError:
        pass
    return root


@app.post("/api/scan/metadata")
def scan_metadata(request: ScanRequest) -> dict[str, object]:
    provider = _provider_or_400(request.provider)
    try:
        password = credential_store.get_password(account_id(request.provider, request.username))
    except LookupError as exc:
        raise HTTPException(
            status_code=409, detail="Test and save the account credential first"
        ) from exc
    try:
        with ReadOnlyImapClient(provider) as client:
            client.authenticate(request.username, password)
            result = client.scan_folder(
                request.folder,
                request.limit or settings.scan_limit,
                settings.large_message_bytes,
            )
    except (imaplib.IMAP4.error, OSError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail="Read-only metadata scan failed") from exc
    return {
        "dry_run": True,
        "threshold_bytes": settings.large_message_bytes,
        **result.public_dict(),
    }


@app.post("/api/scan/review")
def scan_for_review(request: ReviewScanRequest) -> dict[str, object]:
    """Classify recent header data without changing messages or flags."""
    provider = _provider_or_400(request.provider)
    try:
        password = credential_store.get_password(account_id(request.provider, request.username))
    except LookupError as exc:
        raise HTTPException(
            status_code=409, detail="Test and save the account credential first"
        ) from exc
    try:
        with ReadOnlyImapClient(provider) as client:
            client.authenticate(request.username, password)
            messages = client.fetch_review_messages(request.folder, request.limit)
    except (imaplib.IMAP4.error, OSError, ConnectionError) as exc:
        raise HTTPException(status_code=400, detail="Read-only review scan failed") from exc

    classifier = QwenClassifier(settings.ollama_base_url, settings.ollama_model)
    results: list[dict[str, object]] = []
    for message in messages:
        try:
            classification = classifier.classify(message)
        except (httpx.HTTPError, ValueError):
            classification = SafeClassification(
                uid=message.uid,
                category=Category.OTHER,
                confidence=0,
                recommendation=Recommendation.MANUAL_REVIEW,
                reason="Local model output was unavailable or invalid",
                protected=True,
                protection_reason="Classification failure defaults to manual review",
            )
        results.append(
            {
                "uid": message.uid,
                "subject": message.subject,
                "sender": message.sender,
                "size_bytes": message.size_bytes,
                "list_unsubscribe": message.list_unsubscribe,
                "classification": classification.model_dump(mode="json"),
            }
        )
    return {
        "dry_run": True,
        "destructive_actions_allowed": False,
        "folder": request.folder,
        "count": len(results),
        "items": results,
    }


@app.post("/api/full-scan/start")
def start_full_scan(request: FullScanRequest) -> dict[str, object]:
    _provider_or_400(request.provider)
    opaque_id = account_id(request.provider, request.username)
    try:
        credential_store.get_password(opaque_id)
        credential_store.get_username(opaque_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=409, detail="Test and save the account credential first"
        ) from exc
    latest = scan_store.latest_job(opaque_id)
    if latest is not None and latest.status in {"queued", "connecting", "inventory", "pausing"}:
        raise HTTPException(status_code=409, detail="A complete mailbox scan is already active")
    job_id = full_scan_manager.start(opaque_id, request.provider)
    job = scan_store.job(job_id)
    return _job_response(job)


@app.post("/api/full-scan/latest")
def latest_full_scan(request: FullScanRequest) -> dict[str, object]:
    job = scan_store.latest_job(account_id(request.provider, request.username))
    if job is None:
        raise HTTPException(
            status_code=404, detail="No complete mailbox scan exists for this account"
        )
    return {**_job_response(job), "folders": scan_store.folder_progress(job.id)}


@app.get("/api/full-scan/{job_id}")
def full_scan_status(job_id: str) -> dict[str, object]:
    job = scan_store.job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    return {**_job_response(job), "folders": scan_store.folder_progress(job_id)}


@app.post("/api/full-scan/{job_id}/pause")
def pause_full_scan(job_id: str) -> dict[str, object]:
    if scan_store.job(job_id) is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    full_scan_manager.pause(job_id)
    return {"job_id": job_id, "status": "pausing"}


@app.post("/api/full-scan/{job_id}/resume")
def resume_full_scan(job_id: str) -> dict[str, object]:
    try:
        full_scan_manager.resume(job_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="Scan job not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail="Scan job is already running") from exc
    return {"job_id": job_id, "status": "connecting"}


@app.get("/api/full-scan/{job_id}/plan")
def full_scan_plan(job_id: str) -> dict[str, object]:
    job = scan_store.job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Scan job not found")
    groups = scan_store.action_groups(job_id, settings.large_message_bytes)
    return {
        "job_id": job_id,
        "status": job.status,
        "dry_run": True,
        "destructive_actions_allowed": False,
        "groups": groups,
    }


def _job_response(job: JobRecord | None) -> dict[str, object]:
    if job is None:
        raise HTTPException(status_code=500, detail="Scan job could not be created")
    return {
        "job_id": job.id,
        "status": job.status,
        "current_folder": job.current_folder,
        "total_messages": job.total_messages,
        "processed_messages": job.processed_messages,
        "progress_percent": job.progress_percent,
        "total_bytes": job.total_bytes,
        "large_messages": job.large_messages,
        "newsletter_messages": job.newsletter_messages,
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "error": job.error,
        "dry_run": True,
        "destructive_actions_allowed": False,
    }


def _provider_or_400(key: str) -> Provider:
    try:
        return get_provider(key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unsupported provider") from exc


def _validate_account_id(value: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise HTTPException(status_code=400, detail="Invalid account identifier")
    if not any(str(item["id"]) == value for item in scan_store.accounts()):
        raise HTTPException(status_code=404, detail="Account does not exist")
    return value


def _protection_reason(item: dict[str, object], rules: list[dict[str, object]]) -> str | None:
    values = {
        "sender": str(item.get("sender", "")).casefold(),
        "domain": str(item.get("sender_domain", "")).casefold(),
        "folder": str(item.get("folder", "")).casefold(),
        "subject": str(item.get("subject", "")).casefold(),
    }
    for rule in rules:
        if not rule.get("enabled"):
            continue
        kind = str(rule["kind"])
        needle = str(rule["value"]).casefold()
        if kind in values and needle in values[kind]:
            return f"Protected by {kind} rule: {rule['value']}"
    return None
