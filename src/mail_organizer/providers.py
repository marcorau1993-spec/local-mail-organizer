"""Anonymous provider catalog and connection requirements."""

from dataclasses import asdict, dataclass
from typing import Literal

AuthMode = Literal["password", "app_password", "oauth2", "bridge"]
Transport = Literal["ssl", "starttls"]


@dataclass(frozen=True, slots=True)
class Provider:
    key: str
    display_name: str
    imap_host: str
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 587
    auth_mode: AuthMode = "password"
    connectable: bool = True
    credential_label: str = "Password"
    instructions: tuple[str, ...] = ()
    help_url: str = ""
    imap_transport: Transport = "ssl"
    allow_self_signed_local: bool = False

    def public_dict(self) -> dict[str, object]:
        return asdict(self)


PROVIDERS = {
    "webde": Provider(
        "webde",
        "WEB.DE",
        "imap.web.de",
        smtp_host="smtp.web.de",
        instructions=("Enable POP3/IMAP retrieval in WEB.DE settings.",),
        help_url="https://hilfe.web.de/pop-imap/imap/index.html",
    ),
    "gmx": Provider(
        "gmx",
        "GMX",
        "imap.gmx.net",
        smtp_host="mail.gmx.net",
        instructions=("Enable POP3/IMAP retrieval in GMX settings.",),
        help_url="https://hilfe.gmx.net/pop-imap/imap/index.html",
    ),
    "gmail": Provider(
        "gmail",
        "Gmail / Google Workspace",
        "imap.gmail.com",
        smtp_host="smtp.gmail.com",
        auth_mode="app_password",
        credential_label="16-digit app password",
        instructions=(
            "Turn on 2-Step Verification.",
            "Create an app password for this local organizer.",
            "Workspace administrators may disallow app passwords.",
        ),
        help_url="https://support.google.com/accounts/answer/185833",
    ),
    "yahoo": Provider(
        "yahoo",
        "Yahoo Mail",
        "imap.mail.yahoo.com",
        smtp_host="smtp.mail.yahoo.com",
        auth_mode="app_password",
        credential_label="Yahoo app password",
        instructions=("Generate a third-party app password in Yahoo Account Security.",),
        help_url="https://help.yahoo.com/kb/SLN4075.html",
    ),
    "icloud": Provider(
        "icloud",
        "iCloud Mail",
        "imap.mail.me.com",
        smtp_host="smtp.mail.me.com",
        auth_mode="app_password",
        credential_label="Apple app-specific password",
        instructions=(
            "Enable two-factor authentication for the Apple Account.",
            "Generate an app-specific password.",
            "Try the address name without @icloud.com if Apple rejects the full address.",
        ),
        help_url="https://support.apple.com/102525",
    ),
    "aol": Provider(
        "aol",
        "AOL Mail",
        "imap.aol.com",
        smtp_host="smtp.aol.com",
        auth_mode="app_password",
        credential_label="AOL app password",
        instructions=("Generate an app password in AOL Account Security.",),
    ),
    "fastmail": Provider(
        "fastmail",
        "Fastmail",
        "imap.fastmail.com",
        smtp_host="smtp.fastmail.com",
        auth_mode="app_password",
        credential_label="Fastmail app password",
        instructions=("Create an app password with Mail access in Fastmail settings.",),
        help_url="https://www.fastmail.help/hc/en-us/articles/1500000279921",
    ),
    "mailbox_org": Provider(
        "mailbox_org",
        "mailbox.org",
        "imap.mailbox.org",
        smtp_host="smtp.mailbox.org",
        instructions=("Use the full mailbox.org email address as username.",),
    ),
    "posteo": Provider(
        "posteo",
        "Posteo",
        "posteo.de",
        smtp_host="posteo.de",
        instructions=("Use your Posteo address and mailbox password.",),
    ),
    "zoho": Provider(
        "zoho",
        "Zoho Mail",
        "imap.zoho.com",
        smtp_host="smtp.zoho.com",
        auth_mode="app_password",
        credential_label="Zoho app password",
        instructions=(
            "Enable IMAP access for the mailbox.",
            "Use an app-specific password when MFA is active.",
        ),
    ),
    "t_online": Provider(
        "t_online",
        "Telekom / T-Online",
        "secureimap.t-online.de",
        smtp_host="securesmtp.t-online.de",
        credential_label="Separate email password",
        instructions=(
            "Create the separate email password in the Telekom customer center; the web login password is not accepted.",
        ),
    ),
    "outlook": Provider(
        "outlook",
        "Outlook.com / Hotmail / Microsoft 365",
        "outlook.office365.com",
        smtp_host="smtp-mail.outlook.com",
        auth_mode="oauth2",
        connectable=True,
        credential_label="Microsoft OAuth2",
        instructions=(
            "Enable IMAP in Outlook settings.",
            "Microsoft requires Modern Auth / OAuth2; password login is intentionally unavailable until the OAuth connector is configured.",
        ),
        help_url="https://support.microsoft.com/office/pop-imap-and-smtp-settings-for-outlook-com-d088b986-291d-42b8-9564-9c414e2aa040",
    ),
    "proton": Provider(
        "proton",
        "Proton Mail Bridge",
        "127.0.0.1",
        imap_port=1143,
        smtp_host="127.0.0.1",
        smtp_port=1025,
        auth_mode="bridge",
        connectable=True,
        credential_label="Bridge password",
        instructions=(
            "A paid Proton plan and Proton Mail Bridge are required.",
            "Install Bridge, add the account, and keep Bridge running.",
            "Use the IMAP credentials and TLS mode displayed by Bridge, not the Proton web-login password.",
        ),
        help_url="https://proton.me/support/imap-smtp-and-pop3-setup",
        imap_transport="starttls",
        allow_self_signed_local=True,
    ),
}


def get_provider(key: str) -> Provider:
    try:
        return PROVIDERS[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported provider: {key}") from exc


def public_providers() -> list[dict[str, object]]:
    return [provider.public_dict() for provider in PROVIDERS.values()]
