"""
tests/test_licensing.py
-----------------------
Unit tests for Ed25519 offline license verification and storage.
"""

import os
from pathlib import Path
import pytest

from src.licensing.verifier import (
    OfflineLicenseVerifier,
    save_installed_license,
    load_installed_license,
    remove_installed_license,
    get_license_file_path,
)
from src.licensing.issuer import LicenseIssuer


@pytest.fixture
def test_keypair():
    priv, pub = LicenseIssuer.generate_keypair()
    return priv, pub


def test_keypair_generation_and_valid_verification(test_keypair):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    verifier = OfflineLicenseVerifier(pub_hex, app_version="1.0.0", build_date_iso="2026-11-01T00:00:00Z")

    token = issuer.create_license_token(
        customer_name="Jane Doe, Esq.",
        customer_email="jane@lawfirm.example",
        order_id="ls_order_12345",
        plan="firm",
        seats=5,
        maintenance_months=12,
        max_version=1,
    )

    status = verifier.verify(token)
    assert status.is_valid is True
    assert status.customer_name == "Jane Doe, Esq."
    assert status.customer_email == "jane@lawfirm.example"
    assert status.plan == "firm"
    assert status.seats == 5


def test_email_block_extraction(test_keypair):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    verifier = OfflineLicenseVerifier(pub_hex)

    token = issuer.create_license_token(
        customer_name="Bob Smith",
        customer_email="bob@example.com",
        order_id="ls_9999",
    )
    email_text = f"""
    Thank you for purchasing!
    Here is your license block:

    -----BEGIN PDF PORTFOLIO LICENSE KEY-----
       {token}
    -----END PDF PORTFOLIO LICENSE KEY-----

    Enjoy using the product!
    """

    status = verifier.verify(email_text)
    assert status.is_valid is True
    assert status.customer_name == "Bob Smith"


def test_tampered_signature_rejection(test_keypair):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    verifier = OfflineLicenseVerifier(pub_hex)

    token = issuer.create_license_token(
        customer_name="Alice",
        customer_email="alice@example.com",
        order_id="ls_1001",
    )

    # Corrupt last character of the signature
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    status = verifier.verify(tampered)
    assert status.is_valid is False
    assert "tampered" in status.message.lower() or "failed" in status.message.lower()


def test_major_version_cap(test_keypair):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    # App is version 2.0.0
    v2_verifier = OfflineLicenseVerifier(pub_hex, app_version="2.0.0")

    token = issuer.create_license_token(
        customer_name="Charlie",
        customer_email="charlie@example.com",
        order_id="ls_1002",
        max_version=1,  # Capped at v1
    )

    status = v2_verifier.verify(token)
    assert status.is_valid is False
    assert "capped at version 1.x" in status.message


def test_perpetual_maintenance_cutoff(test_keypair):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    # App was built in 2029 (way past 1-year maintenance)
    future_verifier = OfflineLicenseVerifier(
        pub_hex,
        app_version="1.5.0",
        build_date_iso="2029-01-01T00:00:00Z"
    )

    token = issuer.create_license_token(
        customer_name="Dana",
        customer_email="dana@example.com",
        order_id="ls_1003",
        maintenance_months=12,
    )

    status = future_verifier.verify(token)
    assert status.is_valid is False
    assert "maintenance expired" in status.message.lower()


def test_local_storage_persistence(tmp_path, monkeypatch):
    test_lic_file = tmp_path / "test_license.lic"
    monkeypatch.setattr("src.licensing.verifier.get_license_file_path", lambda: test_lic_file)

    assert load_installed_license() is None

    test_token = "PPM1.dummy_payload.dummy_signature"
    save_installed_license(test_token)

    assert test_lic_file.is_file()
    assert load_installed_license() == test_token

    remove_installed_license()
    assert not test_lic_file.exists()
    assert load_installed_license() is None


def test_embedded_production_public_key_and_webhook_worker(monkeypatch):
    import hashlib
    import hmac
    import json
    import importlib.util
    from src.config import EMBEDDED_PUBLIC_KEY_HEX, APP_VERSION, APP_BUILD_DATE

    # Verify EMBEDDED_PUBLIC_KEY_HEX is a valid 32-byte (64-hex-char) Ed25519 key
    assert len(EMBEDDED_PUBLIC_KEY_HEX) == 64
    raw_pub_bytes = bytes.fromhex(EMBEDDED_PUBLIC_KEY_HEX)
    assert len(raw_pub_bytes) == 32

    # Load standalone serverless webhook worker module
    worker_path = Path(__file__).resolve().parent.parent / "packaging" / "webhook-worker" / "api" / "webhook.py"
    spec = importlib.util.spec_from_file_location("webhook_worker", worker_path)
    webhook_worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(webhook_worker)

    priv_hex, pub_hex = LicenseIssuer.generate_keypair()
    secret = "test_ls_webhook_secret_99"
    monkeypatch.setenv("LEMONSQUEEZY_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("ED25519_PRIVATE_KEY_HEX", priv_hex)

    captured_emails = []

    def fake_send_email(to_email: str, customer_name: str, token: str) -> bool:
        captured_emails.append((to_email, customer_name, token))
        return True

    monkeypatch.setattr(webhook_worker, "send_fulfillment_email", fake_send_email)

    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": "88421",
            "attributes": {
                "user_email": "partner@firm.example",
                "user_name": "Partner LLP",
                "first_order_item": {"variant_name": "Firm License (5 Seats)"},
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()

    res = webhook_worker.process_webhook({"X-Signature": sig}, raw_body)
    assert res["status"] == 200
    assert res["body"]["plan"] == "firm"
    assert res["body"]["seats"] == 5
    assert len(captured_emails) == 1

    _, _, issued_token = captured_emails[0]
    verifier = OfflineLicenseVerifier(pub_hex, app_version=APP_VERSION, build_date_iso=APP_BUILD_DATE)
    verified = verifier.verify(issued_token)
    assert verified.is_valid is True
    assert verified.plan == "firm"
    assert verified.seats == 5

