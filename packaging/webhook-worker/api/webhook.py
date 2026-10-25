"""
packaging/webhook-worker/api/webhook.py
---------------------------------------
Self-contained serverless Lemon Squeezy `order_created` webhook handler
for PDF Portfolio Maker.

Supports:
- Vercel Python Serverless Functions (`class handler(BaseHTTPRequestHandler)`)
- AWS Lambda Function URLs (`lambda_handler(event, context)`)

Required Environment Variables:
- LEMONSQUEEZY_WEBHOOK_SECRET : Signing secret from Lemon Squeezy Settings -> Webhooks
- ED25519_PRIVATE_KEY_HEX     : 64-char hex Ed25519 private key (.secrets/production_ed25519_private_key.txt)
- RESEND_API_KEY              : Resend transactional email API key (re_...)
- SENDER_EMAIL                : Optional sender address (default: PDF Portfolio Maker <licenses@pdfportfoliomaker.com>)
"""

import base64
import hashlib
import hmac
import json
import os
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.asymmetric import ed25519


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonicalize_json(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
    priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex.strip()))
    now = datetime.now(timezone.utc)
    updates_until = now.replace(year=now.year + (maintenance_months // 12))

    payload: Dict[str, Any] = {
        "product": "pdf-portfolio-maker",
        "license_id": order_id,
        "customer_name": customer_name.strip(),
        "customer_email": customer_email.strip().lower(),
        "plan": plan,
        "seats": seats,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updates_until": updates_until.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "max_version": max_version,
        "expires_at": expires_at,
    }

    canonical_data = canonicalize_json(payload)
    signature = priv.sign(canonical_data)
    return f"PPM1.{b64url_encode(canonical_data)}.{b64url_encode(signature)}"


def format_email_block(token: str) -> str:
    return (
        "-----BEGIN PDF PORTFOLIO LICENSE KEY-----\n"
        f"{token}\n"
        "-----END PDF PORTFOLIO LICENSE KEY-----"
    )


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    secret = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "").encode("utf-8")
    if not signature_header or not secret:
        return False
    computed = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature_header.strip())


def send_fulfillment_email(to_email: str, customer_name: str, token: str) -> bool:
    resend_api_key = os.environ.get("RESEND_API_KEY", "").strip()
    sender = os.environ.get("SENDER_EMAIL", "PDF Portfolio Maker <licenses@pdfportfoliomaker.com>")
    license_block = format_email_block(token)

    email_body = f"""Hi {customer_name},

Thank you for purchasing PDF Portfolio Maker!

Below is your permanent offline license key:

{license_block}

To activate your copy:
1. Open PDF Portfolio Maker on your Windows computer.
2. Click Help -> Enter License Key... (or click the evaluation badge in the top right).
3. Paste the entire block above into the dialog and click "Activate License".

Your license operates 100% offline. No internet connection is required to activate or create portfolios.

Best regards,
PDF Portfolio Maker Team
"""

    payload = {
        "from": sender,
        "to": [to_email],
        "subject": "Your PDF Portfolio Maker Offline License Key",
        "text": email_body,
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {resend_api_key}",
            "Content-Type": "application/json",
            "User-Agent": "PDFPortfolioMaker-Webhook/1.0",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=10) as resp:
        return 200 <= resp.status < 300


def process_webhook(headers: Dict[str, str], raw_body: bytes) -> Dict[str, Any]:
    normalized_headers = {k.lower(): v for k, v in (headers or {}).items()}
    signature = normalized_headers.get("x-signature", "")
    if not verify_signature(raw_body, signature):
        return {"status": 401, "body": {"error": "Invalid X-Signature"}}

    data = json.loads(raw_body.decode("utf-8"))
    event_name = data.get("meta", {}).get("event_name")

    if event_name == "order_created":
        order_data = data.get("data", {})
        attributes = order_data.get("attributes", {})

        order_id = str(order_data.get("id", "unknown"))
        customer_email = attributes.get("user_email", "")
        customer_name = attributes.get("user_name") or "Valued Customer"
        first_item = attributes.get("first_order_item") or {}
        variant_name = str(first_item.get("variant_name", "solo")).lower()

        seats = 5 if ("firm" in variant_name or "team" in variant_name) else 1
        plan = "firm" if seats > 1 else "solo"

        private_key_hex = os.environ.get("ED25519_PRIVATE_KEY_HEX", "")
        token = create_signed_ppm1_token(
            private_key_hex=private_key_hex,
            customer_name=customer_name,
            customer_email=customer_email,
            order_id=f"ls_{order_id}",
            plan=plan,
            seats=seats,
            maintenance_months=12,
            max_version=1,
        )

        email_sent = send_fulfillment_email(customer_email, customer_name, token)
        return {
            "status": 200,
            "body": {"received": True, "order_id": f"ls_{order_id}", "plan": plan, "seats": seats, "email_sent": email_sent},
        }

    return {"status": 200, "body": {"received": True, "ignored_event": event_name}}


class handler(BaseHTTPRequestHandler):
    """Vercel Python Serverless Function entrypoint."""

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
