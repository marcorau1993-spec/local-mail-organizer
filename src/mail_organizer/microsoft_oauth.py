"""Microsoft public-client OAuth device flow and encrypted token-cache handling."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import msal  # type: ignore[import-untyped]

from .credentials import CredentialStore

SCOPES = [
    "https://outlook.office.com/IMAP.AccessAsUser.All",
    "https://outlook.office.com/SMTP.Send",
]


@dataclass(slots=True)
class DeviceSession:
    account_id: str
    status: str
    user_code: str
    verification_uri: str
    message: str
    error: str = ""


class MicrosoftOAuthManager:
    def __init__(self, credentials: CredentialStore) -> None:
        self._credentials = credentials
        self._sessions: dict[str, DeviceSession] = {}
        self._lock = threading.Lock()

    def begin(self, account_id: str, username: str, client_id: str, tenant: str) -> DeviceSession:
        authority = f"https://login.microsoftonline.com/{tenant.strip() or 'common'}"
        cache = msal.SerializableTokenCache()
        application = msal.PublicClientApplication(
            client_id, authority=authority, token_cache=cache
        )
        flow = application.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise ValueError(str(flow.get("error_description", "Microsoft device flow failed")))
        session = DeviceSession(
            account_id,
            "waiting",
            str(flow["user_code"]),
            str(flow.get("verification_uri", "https://microsoft.com/devicelogin")),
            str(flow.get("message", "Open the verification page and enter the code.")),
        )
        self._credentials.set_secret(f"oauth:{account_id}:client_id", client_id)
        self._credentials.set_secret(f"oauth:{account_id}:authority", authority)
        self._credentials.set_secret(f"oauth:{account_id}:username", username)
        with self._lock:
            self._sessions[account_id] = session
        threading.Thread(
            target=self._complete,
            args=(session, application, flow, cache),
            daemon=True,
            name=f"outlook-oauth-{account_id[:8]}",
        ).start()
        return session

    def status(self, account_id: str) -> DeviceSession | None:
        with self._lock:
            return self._sessions.get(account_id)

    def _complete(
        self,
        session: DeviceSession,
        application: msal.PublicClientApplication,
        flow: dict[str, object],
        cache: msal.SerializableTokenCache,
    ) -> None:
        result = application.acquire_token_by_device_flow(flow)
        with self._lock:
            if "access_token" in result:
                self._credentials.set_secret(f"oauth:{session.account_id}:cache", cache.serialize())
                session.status = "connected"
                session.message = "Microsoft OAuth authorization completed."
            else:
                session.status = "failed"
                session.error = str(
                    result.get("error_description", "Microsoft authorization failed")
                )


def microsoft_access_token(account_id: str, credentials: CredentialStore) -> str:
    client_id = credentials.get_secret(f"oauth:{account_id}:client_id")
    authority = credentials.get_secret(f"oauth:{account_id}:authority")
    serialized = credentials.get_secret(f"oauth:{account_id}:cache")
    cache = msal.SerializableTokenCache()
    cache.deserialize(serialized)
    application = msal.PublicClientApplication(client_id, authority=authority, token_cache=cache)
    accounts = application.get_accounts()
    if not accounts:
        raise LookupError("Microsoft authorization has expired; reconnect the account")
    result = application.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise LookupError("Microsoft authorization has expired; reconnect the account")
    if cache.has_state_changed:
        credentials.set_secret(f"oauth:{account_id}:cache", cache.serialize())
    return str(result["access_token"])
