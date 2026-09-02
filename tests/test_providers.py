import pytest

from mail_organizer.providers import get_provider, public_providers


def test_common_password_and_app_password_providers_are_connectable() -> None:
    for key in ("webde", "gmx", "gmail", "yahoo", "icloud", "aol", "fastmail", "posteo"):
        assert get_provider(key).connectable


def test_oauth_and_bridge_providers_use_their_secure_connector_modes() -> None:
    assert get_provider("outlook").auth_mode == "oauth2"
    assert get_provider("outlook").connectable
    assert get_provider("proton").auth_mode == "bridge"
    assert get_provider("proton").connectable
    assert get_provider("proton").imap_transport == "starttls"
    assert get_provider("proton").allow_self_signed_local


def test_public_provider_catalog_contains_no_credentials() -> None:
    catalog = public_providers()
    assert len(catalog) >= 12
    assert all("password" not in item or item["password"] is None for item in catalog)


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(ValueError):
        get_provider("unknown")
