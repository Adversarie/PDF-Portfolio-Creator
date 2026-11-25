"""
tests/test_licensing.py
-----------------------
Unit tests for Ed25519 offline license verification and storage.
"""

import os
import sys
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


def test_cli_mint_key_ppm1_and_pp1(test_keypair, monkeypatch, capsys):
    from src.licensing.issuer import main as issuer_main

    priv_hex, pub_hex = test_keypair

    # 1. Mint PPM1 token via CLI
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "issuer.py",
            "mint-key",
            "--product",
            "pdf-portfolio-maker",
            "--name",
            "Alice Partner",
            "--email",
            "alice@law.example",
            "--plan",
            "firm",
            "--seats",
            "10",
            "--private-key-hex",
            priv_hex,
            "--raw",
        ],
    )
    issuer_main()
    out_ppm1, _ = capsys.readouterr()
    token_ppm1 = out_ppm1.strip()
    assert token_ppm1.startswith("PPM1.")

    verifier_ppm1 = OfflineLicenseVerifier(pub_hex)
    status_ppm1 = verifier_ppm1.verify(token_ppm1)
    assert status_ppm1.is_valid is True
    assert status_ppm1.customer_name == "Alice Partner"
    assert status_ppm1.plan == "firm"
    assert status_ppm1.seats == 10

    # 2. Mint PP1 token via CLI
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "issuer.py",
            "mint-key",
            "--product",
            "picture-perfect",
            "--name",
            "Bob Studio",
            "--email",
            "bob@photo.example",
            "--plan",
            "pro",
            "--seats",
            "2",
            "--private-key-hex",
            priv_hex,
            "--raw",
        ],
    )
    issuer_main()
    out_pp1, _ = capsys.readouterr()
    token_pp1 = out_pp1.strip()
    assert token_pp1.startswith("PP1.")


def test_auto_provisioning_env_var(monkeypatch, tmp_path):
    monkeypatch.setattr("src.licensing.verifier.get_license_file_path", lambda: tmp_path / "nonexistent.lic")
    monkeypatch.setenv("PDF_PORTFOLIO_LICENSE_KEY", "PPM1.test_env_token.test_sig")

    loaded = load_installed_license()
    assert loaded == "PPM1.test_env_token.test_sig"


def test_auto_provisioning_portable_file(test_keypair, monkeypatch, tmp_path):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    valid_token = issuer.create_license_token(
        customer_name="Dr. Portable",
        customer_email="portable@airgap.example",
        order_id="airgap_001",
        plan="solo",
    )

    fake_appdata = tmp_path / "appdata" / "license.lic"
    monkeypatch.setattr("src.licensing.verifier.get_license_file_path", lambda: fake_appdata)
    monkeypatch.delenv("PDF_PORTFOLIO_LICENSE_KEY", raising=False)

    # In a temp cwd, write portable license.lic
    portable_lic = tmp_path / "license.lic"
    portable_lic.write_text(valid_token, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("src.licensing.verifier.EMBEDDED_PUBLIC_KEY_HEX", pub_hex)

    assert not fake_appdata.exists()
    loaded = load_installed_license()
    assert loaded == valid_token
    # Check that it auto-persisted to fake_appdata
    assert fake_appdata.is_file()
    assert fake_appdata.read_text(encoding="utf-8").strip() == valid_token


def test_hardware_machine_binding_enforcement(test_keypair):
    from src.licensing.verifier import get_machine_fingerprint, normalize_machine_id

    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)

    fp = get_machine_fingerprint()
    assert len(normalize_machine_id(fp)) == 16

    # Mint a 1-seat Solo license bound specifically to workstation A1B2-C3D4-E5F6-0123
    bound_token = issuer.create_license_token(
        customer_name="Bound Solo User",
        customer_email="solo@bound.example",
        order_id="ls_bound_01",
        plan="solo",
        seats=1,
        allowed_machines=["A1B2-C3D4-E5F6-0123"],
    )

    # 1. Authorized workstation succeeds
    authorized_verifier = OfflineLicenseVerifier(pub_hex, machine_id="a1b2-c3d4-e5f6-0123")
    ok_status = authorized_verifier.verify(bound_token)
    assert ok_status.is_valid is True
    assert ok_status.bound_machines == ["A1B2-C3D4-E5F6-0123"]

    # 2. Unauthorized workstation is rejected
    unauthorized_verifier = OfflineLicenseVerifier(pub_hex, machine_id="9999-8888-7777-6666")
    bad_status = unauthorized_verifier.verify(bound_token)
    assert bad_status.is_valid is False
    assert "hardware seat lock mismatch" in bad_status.message.lower()

    # 3. Token binding more machines than licensed seats is rejected
    overbound_token = issuer.create_license_token(
        customer_name="Overbound User",
        customer_email="over@bound.example",
        order_id="ls_bound_02",
        plan="solo",
        seats=1,
        allowed_machines=["A1B2-C3D4-E5F6-0123", "1111-2222-3333-4444"],
    )
    over_status = authorized_verifier.verify(overbound_token)
    assert over_status.is_valid is False
    assert "seat cap exceeded" in over_status.message.lower()


def test_offline_seat_ledger_cap_and_release(test_keypair, tmp_path):
    from src.licensing.verifier import release_seat_in_ledger

    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    ledger_file = tmp_path / "license_seats.json"

    # 2-seat license
    token = issuer.create_license_token(
        customer_name="Small Firm",
        customer_email="firm@example.com",
        order_id="ls_ledger_2seat",
        plan="firm",
        seats=2,
    )

    v_mach1 = OfflineLicenseVerifier(pub_hex, machine_id="1111-1111-1111-1111")
    v_mach2 = OfflineLicenseVerifier(pub_hex, machine_id="2222-2222-2222-2222")
    v_mach3 = OfflineLicenseVerifier(pub_hex, machine_id="3333-3333-3333-3333")

    # Seat 1 claims successfully
    s1 = v_mach1.activate_on_machine(token, seat_ledger_path=ledger_file)
    assert s1.is_valid is True
    assert s1.claimed_seats == 1

    # Seat 2 claims successfully
    s2 = v_mach2.activate_on_machine(token, seat_ledger_path=ledger_file)
    assert s2.is_valid is True
    assert s2.claimed_seats == 2

    # Seat 3 is blocked by 2-seat cap
    s3 = v_mach3.activate_on_machine(token, seat_ledger_path=ledger_file)
    assert s3.is_valid is False
    assert "offline seat cap reached" in s3.message.lower()

    # Releasing Seat 1 allows Seat 3 to claim
    release_seat_in_ledger(machine_id="1111-1111-1111-1111", ledger_path=ledger_file)
    s3_retry = v_mach3.activate_on_machine(token, seat_ledger_path=ledger_file)
    assert s3_retry.is_valid is True
    assert s3_retry.claimed_seats == 2


def test_prestaged_localappdata_enterprise_license(test_keypair, monkeypatch, tmp_path):
    priv_hex, pub_hex = test_keypair
    issuer = LicenseIssuer(priv_hex)
    enterprise_token = issuer.create_license_token(
        customer_name="Defense Agency",
        customer_email="it@agency.gov",
        order_id="gov_msi_001",
        plan="firm",
        seats=5,
    )

    fake_roaming = tmp_path / "roaming" / "PDF Portfolio Maker" / "license.lic"
    fake_localappdata = tmp_path / "localappdata"
    prestaged_lic = fake_localappdata / "PDFPortfolioMaker" / "license.lic"
    prestaged_lic.parent.mkdir(parents=True, exist_ok=True)
    prestaged_lic.write_text(enterprise_token, encoding="utf-8")

    monkeypatch.setattr("src.licensing.verifier.get_license_file_path", lambda: fake_roaming)
    monkeypatch.setattr("src.licensing.verifier.read_gpo_registry_license", lambda: None)
    monkeypatch.setattr("src.licensing.verifier.EMBEDDED_PUBLIC_KEY_HEX", pub_hex)
    monkeypatch.delenv("PDF_PORTFOLIO_LICENSE_KEY", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(fake_localappdata))
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "empty_programdata"))
    monkeypatch.chdir(tmp_path)

    loaded = load_installed_license()
    assert loaded == enterprise_token
    assert fake_roaming.is_file()


