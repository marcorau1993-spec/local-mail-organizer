from mail_organizer.security import (
    _finding_id,
    authentication_signals,
    phishing_finding,
    sender_identity,
)


def test_brand_impersonation_and_wrong_folder_are_high_risk() -> None:
    finding = phishing_finding(
        {
            "job_id": "a" * 32,
            "folder": "Travel",
            "uid": "1",
            "subject": "Your subscription payment could not be processed",
            "sender": "disneyplus.com <sender@spoofed.example>",
            "size_bytes": 100,
        }
    )
    assert finding is not None
    assert finding["risk_score"] == 100
    assert finding["actual_domain"] == "spoofed.example"


def test_official_brand_subdomain_is_not_flagged() -> None:
    assert (
        phishing_finding(
            {
                "folder": "INBOX",
                "subject": "Your Disney account",
                "sender": "Disney <service@mail.disneyplus.com>",
            }
        )
        is None
    )
    assert (
        phishing_finding(
            {
                "folder": "INBOX",
                "subject": "Votre commande Amazon.fr",
                "sender": '"Amazon.fr" <confirmation-commande@amazon.fr>',
            }
        )
        is None
    )


def test_merchant_name_in_subject_is_not_sender_impersonation() -> None:
    assert (
        phishing_finding(
            {
                "folder": "INBOX",
                "subject": "Beleg für Ihre Zahlung an Microsoft Payments",
                "sender": "PayPal <service@paypal.de>",
            }
        )
        is None
    )


def test_plain_brand_display_name_without_auth_evidence_is_medium_review() -> None:
    finding = phishing_finding(
        {
            "folder": "INBOX",
            "subject": "Sie haben eine Zahlung autorisiert",
            "sender": "PayPal <info@merchant.example>",
        }
    )
    assert finding is not None
    assert finding["risk"] == "medium"
    assert finding["risk_score"] == 55


def test_domain_style_brand_claim_remains_high_risk() -> None:
    finding = phishing_finding(
        {
            "folder": "INBOX",
            "subject": "Verify your account urgently",
            "sender": "paypal.com <service@unrelated.example>",
        }
    )
    assert finding is not None
    assert finding["risk"] == "high"
    assert finding["risk_score"] == 90


def test_forged_official_address_and_security_pressure_is_critical() -> None:
    finding = phishing_finding(
        {
            "folder": "INBOX",
            "subject": "Amazon security notice requires immediate action",
            "sender": '"cs.noreply@account.amazon.de" <sender@spoofed.example>',
        }
    )
    assert finding is not None
    assert finding["risk"] == "high"
    assert finding["risk_score"] == 100
    assert finding["impersonation_strength"] == "official_address_mismatch"


def test_sender_identity_uses_only_the_normalized_address() -> None:
    assert sender_identity("PayPal <BILLING@MERCHANT.EXAMPLE>") == "billing@merchant.example"


def test_security_finding_id_is_stable() -> None:
    assert _finding_id({"job_id": "job", "folder": "INBOX", "uid": "7"}) == "job:INBOX:7"


def test_authentication_results_are_parsed_without_body_content() -> None:
    signals = authentication_signals(
        b"Authentication-Results: mx.example; spf=pass; dkim=pass; dmarc=fail\r\nReply-To: reply@example.org\r\n\r\n"
    )
    assert signals["spf"] == "pass"
    assert signals["dkim"] == "pass"
    assert signals["dmarc"] == "fail"
    assert signals["reply_to"] == "reply@example.org"
