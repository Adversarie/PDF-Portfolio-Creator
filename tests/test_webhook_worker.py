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

import base64
import hashlib
import hmac
import json
import os
import smtplib
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure packaging/webhook-worker is in sys.path
WORKER_DIR = Path(__file__).parent.parent / "packaging" / "webhook-worker"
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from api.fulfillment import (  # noqa: E402
    InMemoryMailAdapter,
    issue_ed25519_token,
    main as fulfillment_cli_main,
    process_order_webhook,
)
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
    monkeypatch.setenv("MOR_PROVIDER", "auto")
    monkeypatch.setenv("LEMONSQUEEZY_WEBHOOK_SECRET", TEST_SECRET)
    monkeypatch.delenv("POLAR_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("DODO_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("PDF_SOLO_PRODUCT_ID", raising=False)
    monkeypatch.delenv("PDF_FIRM_PRODUCT_ID", raising=False)
    monkeypatch.setenv("ED25519_PRIVATE_KEY_HEX", TEST_PRIVKEY_HEX)
    monkeypatch.setenv("RESEND_API_KEY", "re_test_dummy_key_12345")
    monkeypatch.setenv("SENDER_EMAIL", "licenses@pictureperfect.click")
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("GMAIL_USER", raising=False)
    monkeypatch.delenv("GMAIL_FROM_EMAIL", raising=False)
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_PORT", raising=False)
    monkeypatch.delenv("EMAIL_PROVIDER", raising=False)


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


def test_valid_order_created_gmail_smtp_ssl_200(monkeypatch):
    monkeypatch.setenv("GMAIL_USER", "matt18201@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.delenv("RESEND_API_KEY", raising=False)

    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99890,
            "attributes": {
                "user_name": "Gmail Buyer",
                "user_email": "buyer@gmail.example",
                "first_order_item": {"variant_name": "Solo License"},
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)
    headers = {"X-Signature": sig}

    mock_server = MagicMock()
    mock_smtp_ctx = MagicMock()
    mock_smtp_ctx.__enter__.return_value = mock_server
    mock_smtp_ctx.__exit__.return_value = None

    with patch("smtplib.SMTP_SSL", return_value=mock_smtp_ctx) as mock_smtp_ssl:
        result = process_webhook(headers, raw_body)
        assert result["status"] == 200
        assert result["body"]["email_sent"] is True
        assert result["body"]["plan"] == "solo"

        mock_smtp_ssl.assert_called_once()
        args, _ = mock_smtp_ssl.call_args
        assert args[0] == "smtp.gmail.com"
        assert args[1] == 465
        mock_server.login.assert_called_once_with("matt18201@gmail.com", "abcdefghijklmnop")
        mock_server.send_message.assert_called_once()
        sent_msg = mock_server.send_message.call_args[0][0]
        assert sent_msg["To"] == "buyer@gmail.example"
        assert sent_msg["From"] == "PDF Portfolio Maker <matt18201@gmail.com>"
        assert "-----BEGIN PDF PORTFOLIO LICENSE KEY-----" in sent_msg.get_content()
        assert "PPM1." in sent_msg.get_content()


def test_gmail_smtp_starttls_port_587(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")
    monkeypatch.setenv("SMTP_PORT", "587")

    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99891,
            "attributes": {
                "user_name": "StartTLS Buyer",
                "user_email": "tls@example.com",
                "first_order_item": {"variant_name": "Firm License (5 Seats)"},
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)

    mock_server = MagicMock()
    mock_smtp_ctx = MagicMock()
    mock_smtp_ctx.__enter__.return_value = mock_server
    mock_smtp_ctx.__exit__.return_value = None

    with patch("smtplib.SMTP", return_value=mock_smtp_ctx) as mock_smtp:
        result = process_webhook({"X-Signature": sig}, raw_body)
        assert result["status"] == 200
        assert result["body"]["plan"] == "firm"
        assert result["body"]["seats"] == 5
        mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=10)
        assert mock_server.starttls.called
        mock_server.login.assert_called_once_with("matt18201@gmail.com", "abcdefghijklmnop")
        mock_server.send_message.assert_called_once()


def test_gmail_smtp_failure_returns_502(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")

    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99892,
            "attributes": {
                "user_name": "Auth Fail Buyer",
                "user_email": "fail@example.com",
                "first_order_item": {"variant_name": "Solo License"},
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)

    with patch("smtplib.SMTP_SSL", side_effect=smtplib.SMTPAuthenticationError(535, b"Bad credentials")):
        result = process_webhook({"X-Signature": sig}, raw_body)
        assert result["status"] == 502
        assert result["body"]["email_sent"] is False
        assert "Failed to send fulfillment email" in result["body"]["error"]


def test_gmail_preferred_over_resend_unless_overridden(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcdefghijklmnop")
    monkeypatch.setenv("RESEND_API_KEY", "re_test_dummy_key_12345")

    payload = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 99893,
            "attributes": {
                "user_name": "Dual Config",
                "user_email": "dual@example.com",
                "first_order_item": {"variant_name": "Solo License"},
            },
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    sig = compute_signature(TEST_SECRET, raw_body)

    mock_server = MagicMock()
    mock_smtp_ctx = MagicMock()
    mock_smtp_ctx.__enter__.return_value = mock_server
    mock_smtp_ctx.__exit__.return_value = None

    with patch("smtplib.SMTP_SSL", return_value=mock_smtp_ctx) as mock_smtp_ssl, patch(
        "urllib.request.urlopen"
    ) as mock_urlopen:
        result = process_webhook({"X-Signature": sig}, raw_body)
        assert result["status"] == 200
        assert mock_smtp_ssl.called
        assert not mock_urlopen.called


def _make_standard_webhook_headers(raw_body: bytes, secret_bytes: bytes, wh_id: str = "msg_1", ts: int | None = None) -> dict:
    ts_str = str(int(time.time()) if ts is None else ts)
    signed = f"{wh_id}.{ts_str}.".encode("utf-8") + raw_body
    sig_b64 = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode("ascii")
    return {
        "webhook-id": wh_id,
        "webhook-timestamp": ts_str,
        "webhook-signature": f"v1,{sig_b64}",
    }


def test_polar_order_paid_standard_webhooks_and_product_filter(monkeypatch):
    polar_secret = "polar_whsec_utf8_secret_abc"
    monkeypatch.setenv("MOR_PROVIDER", "polar")
    monkeypatch.setenv("POLAR_WEBHOOK_SECRET", polar_secret)
    monkeypatch.setenv("PDF_SOLO_PRODUCT_ID", "prod_pdf_solo")
    monkeypatch.setenv("PDF_FIRM_PRODUCT_ID", "prod_pdf_firm")

    mail = InMemoryMailAdapter()

    # 1. Non-PDF order (Picture Perfect) must be ignored fail-closed with 200 and 0 emails sent
    pp_payload = {
        "type": "order.paid",
        "data": {
            "id": "ord_pp_001",
            "product_id": "prod_picture_perfect",
            "product": {"id": "prod_picture_perfect", "name": "Picture Perfect Pro"},
            "customer": {"email": "photo@example.com", "name": "Photo Studio"},
            "metadata": {},
        },
    }
    raw_pp = json.dumps(pp_payload).encode("utf-8")
    res_ignored = process_order_webhook(
        _make_standard_webhook_headers(raw_pp, polar_secret.encode("utf-8")),
        raw_pp,
        mail_sender=mail,
    )
    assert res_ignored["status"] == 200
    assert res_ignored["body"]["ignored"] is True
    assert len(mail.sent_messages) == 0

    # 2. PDF Firm order mints 5-seat PPM1 token and sends via injected mail adapter
    pdf_payload = {
        "type": "order.paid",
        "data": {
            "id": "ord_pdf_002",
            "product_id": "prod_pdf_firm",
            "product": {"id": "prod_pdf_firm", "name": "PDF Portfolio Maker Firm"},
            "customer": {"email": "partner@firm.com", "name": "Firm Partner"},
            "metadata": {},
        },
    }
    raw_pdf = json.dumps(pdf_payload).encode("utf-8")
    res_ok = process_order_webhook(
        _make_standard_webhook_headers(raw_pdf, polar_secret.encode("utf-8")),
        raw_pdf,
        mail_sender=mail,
    )
    assert res_ok["status"] == 200
    assert res_ok["body"]["order_id"] == "polar_ord_pdf_002"
    assert res_ok["body"]["plan"] == "firm"
    assert res_ok["body"]["seats"] == 5
    assert len(mail.sent_messages) == 1
    assert "PPM1." in mail.sent_messages[0].body


def test_dodo_payment_succeeded_whsec_base64_and_product_filter(monkeypatch):
    raw_key = b"0123456789abcdef0123456789abcdef"
    whsec = "whsec_" + base64.b64encode(raw_key).decode("ascii")
    monkeypatch.setenv("MOR_PROVIDER", "dodo")
    monkeypatch.setenv("DODO_WEBHOOK_SECRET", whsec)
    monkeypatch.setenv("PDF_SOLO_PRODUCT_ID", "pdt_pdf_solo")
    monkeypatch.setenv("PDF_FIRM_PRODUCT_ID", "pdt_pdf_firm")

    mail = InMemoryMailAdapter()

    # Valid Dodo Solo purchase
    dodo_payload = {
        "type": "payment.succeeded",
        "data": {
            "payment_id": "pay_dodo_101",
            "customer": {"email": "solo@dodo.example", "name": "Solo Esq"},
            "product_cart": [{"product_id": "pdt_pdf_solo", "name": "PDF Portfolio Solo", "quantity": 1}],
            "metadata": {},
        },
    }
    raw_dodo = json.dumps(dodo_payload).encode("utf-8")
    res_ok = process_order_webhook(
        _make_standard_webhook_headers(raw_dodo, raw_key),
        raw_dodo,
        mail_sender=mail,
    )
    assert res_ok["status"] == 200
    assert res_ok["body"]["order_id"] == "dodo_pay_dodo_101"
    assert res_ok["body"]["plan"] == "solo"
    assert res_ok["body"]["seats"] == 1
    assert len(mail.sent_messages) == 1

    # Expired timestamp (>300s) rejected with 401
    old_headers = _make_standard_webhook_headers(raw_dodo, raw_key, ts=int(time.time()) - 900)
    res_old = process_order_webhook(old_headers, raw_dodo, mail_sender=mail)
    assert res_old["status"] == 401


def test_lemonsqueezy_non_pdf_product_ignored_and_toc1_cli_minting(capsys):
    mail = InMemoryMailAdapter()
    ls_non_pdf = {
        "meta": {"event_name": "order_created"},
        "data": {
            "id": 55501,
            "attributes": {
                "user_name": "Streamer",
                "user_email": "streamer@twitch.example",
                "first_order_item": {"product_id": 1472500, "product_name": "Twitch OCR Chatbot Pro", "variant_name": "Annual"},
            },
        },
    }
    raw_ls = json.dumps(ls_non_pdf).encode("utf-8")
    res = process_order_webhook({"X-Signature": compute_signature(TEST_SECRET, raw_ls)}, raw_ls, mail_sender=mail)
    assert res["status"] == 200
    assert res["body"]["ignored"] is True
    assert len(mail.sent_messages) == 0

    exit_code = fulfillment_cli_main([
        "mint-key",
        "--product", "twitch-ocr-chatbot",
        "--name", "VIP Streamer",
        "--email", "vip@twitch.example",
        "--plan", "vip",
        "--seats", "2",
        "--private-key-hex", TEST_PRIVKEY_HEX,
        "--raw",
    ])
    assert exit_code == 0
    out, _ = capsys.readouterr()
    assert out.strip().startswith("TOC1.")


