"""
packaging/webhook-worker/api/webhook.py
---------------------------------------
Thin HTTP / AWS Lambda entrypoint delegating order fulfillment and
Ed25519 license key issuance to `api/fulfillment.py`.
"""

import base64
import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from api.fulfillment import (  # type: ignore[import-not-found]
        GmailSmtpAdapter,
        InMemoryMailAdapter,
        ResendHttpAdapter,
        build_fulfillment_email_content,
        canonicalize_json,
        format_license_block,
        issue_ed25519_token,
        process_order_webhook,
        send_license_email,
        verify_lemonsqueezy_signature,
        verify_standard_webhook,
    )
except ImportError:
    import importlib.util as _importlib_util

    _FULFILLMENT_PATH = Path(__file__).resolve().parent / "fulfillment.py"
    _fspec = _importlib_util.spec_from_file_location("fulfillment", _FULFILLMENT_PATH)
    _fmod = _importlib_util.module_from_spec(_fspec)  # type: ignore[arg-type]
    _fspec.loader.exec_module(_fmod)  # type: ignore[union-attr]
    GmailSmtpAdapter = _fmod.GmailSmtpAdapter
    InMemoryMailAdapter = _fmod.InMemoryMailAdapter
    ResendHttpAdapter = _fmod.ResendHttpAdapter
    build_fulfillment_email_content = _fmod.build_fulfillment_email_content
    canonicalize_json = _fmod.canonicalize_json
    format_license_block = _fmod.format_license_block
    issue_ed25519_token = _fmod.issue_ed25519_token
    process_order_webhook = _fmod.process_order_webhook
    send_license_email = _fmod.send_license_email
    verify_lemonsqueezy_signature = _fmod.verify_lemonsqueezy_signature
    verify_standard_webhook = _fmod.verify_standard_webhook


def create_signed_ppm1_token(
    private_key_hex: str,
    customer_name: str,
    customer_email: str,
    order_id: str,
    plan: str = "solo",
    seats: int = 1,
    maintenance_months: int = 12,
    max_version: int = 1,
    expires_at: Optional[str] = None,
) -> str:
    return issue_ed25519_token(
        private_key_hex=private_key_hex,
        customer_name=customer_name,
        customer_email=customer_email,
        order_id=order_id,
        plan=plan,
        seats=seats,
        maintenance_months=maintenance_months,
        max_version=max_version,
        expires_at=expires_at,
        product="pdf-portfolio-maker",
    )


def format_email_block(token: str) -> str:
    return format_license_block(token, product="pdf-portfolio-maker")


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    return verify_lemonsqueezy_signature(raw_body, signature_header)


def send_via_gmail_smtp(to_email: str, customer_name: str, token: str) -> bool:
    subject, body = build_fulfillment_email_content(customer_name, token, product="pdf-portfolio-maker")
    return GmailSmtpAdapter().send(to_email, subject, body, "PDF Portfolio Maker")


def send_via_resend(to_email: str, customer_name: str, token: str) -> bool:
    subject, body = build_fulfillment_email_content(customer_name, token, product="pdf-portfolio-maker")
    return ResendHttpAdapter().send(to_email, subject, body, "PDF Portfolio Maker")


def send_fulfillment_email(to_email: str, customer_name: str, token: str) -> bool:
    return send_license_email(to_email, customer_name, token, product="pdf-portfolio-maker")


def process_webhook(headers: Dict[str, str], raw_body: bytes, mail_sender: Optional[Any] = None) -> Dict[str, Any]:
    effective_sender = mail_sender if mail_sender is not None else send_fulfillment_email
    return process_order_webhook(headers, raw_body, mail_sender=effective_sender)


class handler(BaseHTTPRequestHandler):
    """Vercel Python Serverless Function entrypoint."""

    def do_GET(self):
        body_bytes = json.dumps({"status": "active", "service": "PDF Portfolio Maker Webhook"}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(content_length)
        headers_dict = {k: v for k, v in self.headers.items()}
        result = process_webhook(headers_dict, raw_body)

        body_bytes = json.dumps(result["body"]).encode("utf-8")
        self.send_response(result["status"])
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body_bytes)))
        self.end_headers()
        self.wfile.write(body_bytes)


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """AWS Lambda Function URL entrypoint."""
    raw_body_str = event.get("body", "") or ""
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body_str)
    else:
        raw_body = raw_body_str.encode("utf-8")

    result = process_webhook(event.get("headers") or {}, raw_body)
    return {
        "statusCode": result["status"],
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(result["body"]),
    }
