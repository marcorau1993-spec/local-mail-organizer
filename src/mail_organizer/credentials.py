"""Credential storage backed by the operating-system keyring."""

import keyring

SERVICE_NAME = "local-mail-organizer"


class CredentialStore:
    def set_secret(self, key: str, value: str) -> None:
        if not value:
            raise ValueError("Secret must not be empty")
        keyring.set_password(SERVICE_NAME, key, value)

    def get_secret(self, key: str) -> str:
        value = keyring.get_password(SERVICE_NAME, key)
        if value is None:
            raise LookupError("No secret is stored for this integration")
        return value

    def delete_secret(self, key: str) -> None:
        try:
            keyring.delete_password(SERVICE_NAME, key)
        except keyring.errors.PasswordDeleteError:
            pass

    def set_account(self, account_id: str, username: str, password: str) -> None:
        self.set_password(account_id, password)
        keyring.set_password(SERVICE_NAME, f"{account_id}:username", username)

    def set_password(self, account_id: str, password: str) -> None:
        if not password:
            raise ValueError("Password must not be empty")
        keyring.set_password(SERVICE_NAME, account_id, password)

    def get_password(self, account_id: str) -> str:
        if keyring.get_password(SERVICE_NAME, f"oauth:{account_id}:client_id") is not None:
            from .microsoft_oauth import microsoft_access_token

            return microsoft_access_token(account_id, self)
        password = keyring.get_password(SERVICE_NAME, account_id)
        if password is None:
            raise LookupError("No credential is stored for this account")
        return password

    def get_username(self, account_id: str) -> str:
        username = keyring.get_password(SERVICE_NAME, f"{account_id}:username")
        if username is None:
            raise LookupError("No username is stored for this account")
        return username

    def delete_password(self, account_id: str) -> None:
        for key in (account_id, f"{account_id}:username"):
            try:
                keyring.delete_password(SERVICE_NAME, key)
            except keyring.errors.PasswordDeleteError:
                continue
