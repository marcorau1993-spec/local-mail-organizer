"""Verified Dropbox archive adapter using OAuth 2 PKCE and refresh tokens."""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from .credentials import CredentialStore

AUTHORIZE_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
API_URL = "https://api.dropboxapi.com/2"
CONTENT_URL = "https://content.dropboxapi.com/2"
REDIRECT_URI = "http://127.0.0.1:8765/api/archive/dropbox/callback"
CHUNK_SIZE = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class DropboxAuthorization:
    url: str
    state: str


class DropboxArchive:
    def __init__(self, credentials: CredentialStore) -> None:
        self._credentials = credentials

    def begin(self, account_id: str, app_key: str) -> DropboxAuthorization:
        verifier = secrets.token_urlsafe(64)[:96]
        challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .decode()
            .rstrip("=")
        )
        state = secrets.token_urlsafe(32)
        session = {"account_id": account_id, "app_key": app_key, "verifier": verifier}
        self._credentials.set_secret(f"dropbox:state:{state}", json.dumps(session))
        params = {
            "client_id": app_key,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "token_access_type": "offline",
            "code_challenge_method": "S256",
            "code_challenge": challenge,
            "state": state,
        }
        return DropboxAuthorization(f"{AUTHORIZE_URL}?{urlencode(params)}", state)

    def complete(self, state: str, code: str) -> str:
        key = f"dropbox:state:{state}"
        session = json.loads(self._credentials.get_secret(key))
        self._credentials.delete_secret(key)
        with httpx.Client(timeout=30) as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "grant_type": "authorization_code",
                    "client_id": session["app_key"],
                    "code_verifier": session["verifier"],
                    "redirect_uri": REDIRECT_URI,
                },
            )
            response.raise_for_status()
            payload = response.json()
        refresh_token = str(payload.get("refresh_token", ""))
        if not refresh_token:
            raise ValueError("Dropbox did not return an offline refresh token")
        account_id = str(session["account_id"])
        self._credentials.set_secret(f"dropbox:{account_id}:app_key", str(session["app_key"]))
        self._credentials.set_secret(f"dropbox:{account_id}:refresh_token", refresh_token)
        return account_id

    def connected(self, account_id: str) -> bool:
        try:
            self._credentials.get_secret(f"dropbox:{account_id}:app_key")
            self._credentials.get_secret(f"dropbox:{account_id}:refresh_token")
        except LookupError:
            return False
        return True

    def disconnect(self, account_id: str) -> None:
        self._credentials.delete_secret(f"dropbox:{account_id}:app_key")
        self._credentials.delete_secret(f"dropbox:{account_id}:refresh_token")

    def verify(self, account_id: str, root_path: str) -> None:
        path = self._path(root_path, f".local-mail-organizer/write-test-{secrets.token_hex(8)}.bin")
        content = b"local-mail-organizer Dropbox verification"
        self.store(account_id, path, content, absolute=True)
        token = self._access_token(account_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Dropbox-API-Arg": json.dumps({"path": path}),
        }
        with httpx.Client(timeout=30) as client:
            downloaded = client.post(f"{CONTENT_URL}/files/download", headers=headers)
            downloaded.raise_for_status()
            if downloaded.content != content:
                raise OSError("Dropbox verification download did not match")
            deleted = client.post(
                f"{API_URL}/files/delete_v2",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"path": path},
            )
            deleted.raise_for_status()

    def store(
        self,
        account_id: str,
        relative_path: str,
        content: bytes,
        *,
        root_path: str = "",
        absolute: bool = False,
    ) -> str:
        path = relative_path if absolute else self._path(root_path, relative_path)
        token = self._access_token(account_id)
        if len(content) <= 150 * 1024 * 1024:
            metadata = self._upload(token, path, content)
        else:
            metadata = self._upload_session(token, path, content)
        if int(str(metadata.get("size", -1))) != len(content):
            raise OSError("Dropbox size verification failed")
        return path

    def _access_token(self, account_id: str) -> str:
        app_key = self._credentials.get_secret(f"dropbox:{account_id}:app_key")
        refresh = self._credentials.get_secret(f"dropbox:{account_id}:refresh_token")
        with httpx.Client(timeout=30) as client:
            response = client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh,
                    "client_id": app_key,
                },
            )
            response.raise_for_status()
            return str(response.json()["access_token"])

    @staticmethod
    def _path(root_path: str, relative_path: str) -> str:
        parts = [part for part in relative_path.replace("\\", "/").split("/") if part]
        if any(part in {".", ".."} for part in parts):
            raise ValueError("Dropbox archive path contains traversal")
        root = "/" + root_path.strip("/ ") if root_path.strip("/ ") else ""
        return root + "/" + "/".join(parts)

    @staticmethod
    def _upload(token: str, path: str, content: bytes) -> dict[str, object]:
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "Dropbox-API-Arg": json.dumps({"path": path, "mode": "overwrite", "autorename": False}),
        }
        with httpx.Client(timeout=120) as client:
            response = client.post(f"{CONTENT_URL}/files/upload", headers=headers, content=content)
            response.raise_for_status()
            return dict(response.json())

    @staticmethod
    def _upload_session(token: str, path: str, content: bytes) -> dict[str, object]:
        auth = {"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"}
        with httpx.Client(timeout=120) as client:
            first = content[:CHUNK_SIZE]
            response = client.post(
                f"{CONTENT_URL}/files/upload_session/start",
                headers={**auth, "Dropbox-API-Arg": json.dumps({"close": False})},
                content=first,
            )
            response.raise_for_status()
            session_id = response.json()["session_id"]
            offset = len(first)
            while len(content) - offset > CHUNK_SIZE:
                chunk = content[offset : offset + CHUNK_SIZE]
                response = client.post(
                    f"{CONTENT_URL}/files/upload_session/append_v2",
                    headers={
                        **auth,
                        "Dropbox-API-Arg": json.dumps(
                            {"cursor": {"session_id": session_id, "offset": offset}, "close": False}
                        ),
                    },
                    content=chunk,
                )
                response.raise_for_status()
                offset += len(chunk)
            response = client.post(
                f"{CONTENT_URL}/files/upload_session/finish",
                headers={
                    **auth,
                    "Dropbox-API-Arg": json.dumps(
                        {
                            "cursor": {"session_id": session_id, "offset": offset},
                            "commit": {"path": path, "mode": "overwrite", "autorename": False},
                        }
                    ),
                },
                content=content[offset:],
            )
            response.raise_for_status()
            return dict(response.json())
