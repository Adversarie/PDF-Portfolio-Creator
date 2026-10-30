"""
tests/test_webhook_worker.py
----------------------------
Comprehensive test suite for the serverless Lemon Squeezy webhook handler.
Tests:
- Valid HMAC + Ed25519 PPM1 key generation + mocked Resend 200 -> HTTP 200
- Resend failure -> HTTP 502
- Invalid HMAC -> HTTP 401
- Invalid JSON -> HTTP 400
- Firm vs Solo tier detection (via variant_name and custom_data)
"""

import hashlib
import hmac
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure packaging/webhook-worker is in sys.path
WORKER_DIR = Path(__file__).parent.parent / "packaging" / "webhook-worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from api.webhook import create_signed_ppm1_token, process_webhook, verify_signature  # noqa: E402
from src.licensing.verifier import OfflineLicenseVerifier  # noqa: E402

TEST_SECRET = "test_webhook_secret_12345"
TEST_PRIVKEY_HEX = "45678da407cc57b047a1c90339bec3c0d69332117e3be570dd4bc0640fb85862"
# Corresponding public key for TEST_PRIVKEY_HEX:
TEST_PUBKEY_HEX = "209850db3e18e6840d4a357cc82562ff0e7f05645d6c7020becd237cf6b6972b"


def compute_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


@pytest.fixture(autouse=True)
def setup_webhook_env(monkeypatch):
    monkeypatch.setenv("LEMONSQUEEZY_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.setenv("ED25519_PRIVATE_KEY_HEX", TEST_PRIVKEY_HEX)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_dummy_key_12345")
    monkeypatch.setenv("SENDER_EMAIL", "licenses@pictureperfect.click")


def test_invalid_hmac_returns_401():
    body = b'{"hello": "world"}'
    headers = {"X-Signature": "invalid_signature_hex"}
    result = process_webhook(headers, body)
    assert result["status"] == 401
    assert "Invalid X-Signature" in result["body"]["error"]


def test_invalid_json_returns_400():
    raw_body = b"Not valid { json at all!"
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}
    result = process_webhook(headers, raw_body)
    assert result["status"] == 400
    assert "Invalid JSON body" in result["body"]["error"]


def test_valid_order_created_solo_resend_200():
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99881,
            "attributes": {
                "user_name": "Alice Solo",
                "user_email": "alice@example.com",
                "first_order_item": {
                    "variant_name": "Solo License (1 Workstation)",
                },
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        result = process_webhook(headers, raw_body)
        assert result["status"] == 200
        assert result["body"]["received"] is True
        assert result["body"]["order_id"] == "ls_99881"
        assert result["body"]["plan"] == "solo"
        assert result["body"]["seats"] == 1
        assert result["body"]["email_sent"] is True
        assert mock_urlopen.called


def test_resend_failure_returns_502():
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99882,
            "attributes": {
                "user_name": "Bob Retry",
                "user_email": "bob@example.com",
                "first_order_item": {
                    "variant_name": "Solo License",
                },
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}

    with patch("urllib.request.urlopen", side_effect=TimeoutError("Resend gateway timeout")):
        result = process_webhook(headers, raw_body)
        assert result["status"] == 502
        assert result["body"]["email_sent"] is False
        assert "Failed to send fulfillment email" in result["body"]["error"]


def test_firm_tier_detection_via_variant_name():
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99883,
            "attributes": {
                "user_name": "Law Firm Partner",
                "user_email": "partner@lawfirm.com",
                "first_order_item": {
                    "variant_name": "Firm License (5 Seats)",
                },
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}

    with patch("api.webhook.send_fulfillment_email", return_value=True):
        result = process_webhook(headers, raw_body)
        assert result["status"] == 200
        assert result["body"]["plan"] == "firm"
        assert result["body"]["seats"] == 5


def test_firm_tier_detection_via_custom_data():
    payload = {
        "meta": {
            "event_name": "order_created",
            "custom_data": {"tier": "firm", "seats": 5},
        },
        "data": {
            "id": 99884,
            "attributes": {
                "user_name": "Firm Purchaser",
                "user_email": "finance@firm.com",
                "first_order_item": {
                    "variant_name": "Custom Enterprise",
                },
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}

    with patch("api.webhook.send_fulfillment_email", return_value=True):
        result = process_webhook(headers, raw_body)
        assert result["status"] == 200
        assert result["body"]["plan"] == "firm"
        assert result["body"]["seats"] == 5


def test_signed_token_verifiable_by_offline_verifier():
    token = create_signed_ppm1_token(
        private_key_hex=TEST_PRIVKEY_HEX,
        customer_name="Carol Crypto",
        customer_email="carol@test.com",
        order_id="ls_77777",
        plan="firm",
        seats=5,
    )
    assert token.startswith("PPM1.")

    verifier = OfflineLicenseVerifier(TEST_PUBKEY_HEX, app_version="1.0.0", build_date_iso="2026-11-01T00:00:00Z")
    status = verifier.verify(token)
    assert status.is_valid is True
    assert status.plan == "firm"
    assert status.seats == 5
    assert status.customer_email == "carol@test.com"


def test_invalid_private_key_hex_guarded(monkeypatch):
    monkeypatch.setenv("ED25519_PRIVATE_KEY_HEX", "corrupted_non_hex_key")
    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99885,
            "attributes": {
                "user_name": "Dave Key",
                "user_email": "dave@example.com",
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}

    result = process_webhook(headers, raw_body)
    assert result["status"] == 500
    assert "Key configuration error" in result["body"]["error"]
