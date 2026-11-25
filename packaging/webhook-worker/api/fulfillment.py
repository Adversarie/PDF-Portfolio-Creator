"""
packaging/webhook-worker/api/fulfillment.py
-------------------------------------------
Self-contained Ed25519 License Key Issuance & Merchant of Record Order Fulfillment module.
Deployable inside Vercel's isolated `packaging/webhook-worker` root without cross-repo imports.

Supports:
- Canonical ASCII Ed25519 token signing (PPM1, PP1, TOC1) + armored block formatting
- Injected MailSender seam (Gmail SMTP, Resend HTTP, or InMemoryMailAdapter for tests)
- Multi-provider webhook verification (Polar, Dodo Payments, Lemon Squeezy)
- Fail-closed PDF Portfolio Maker product filtering
- Operator CLI (`generate-keypair`, `mint-key`)
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol, Set, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

PRODUCT_CONFIG: Dict[str, Tuple[str, str, str]] = {
    "pdf-portfolio-maker": ("PPM1", "PDF PORTFOLIO", "PDF Portfolio Maker"),
    "picture-perfect": ("PP1", "PICTURE PERFECT", "Picture Perfect Pro"),
    "twitch-ocr-chatbot": ("TOC1", "TWITCH OCR CHATBOT", "Twitch OCR Chatbot Pro"),
}


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def canonicalize_json(payload: Dict[str, Any]) -> bytes:
    """Serializes payload deterministically matching src/licensing/verifier.py."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def normalize_machine_id(raw_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", raw_id or "").upper()


def generate_ed25519_keypair() -> Tuple[str, str]:
    priv = ed25519.Ed25519PrivateKey.generate()
    raw_priv = priv.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    raw_pub = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return raw_priv.hex(), raw_pub.hex()


def issue_ed25519_token(
    private_key_hex: str,
    customer_name: str,
    customer_email: str,
    order_id: str,
    plan: str = "solo",
    seats: int = 1,
    maintenance_months: int = 12,
    max_version: int = 1,
    expires_at: Optional[str] = None,
    product: str = "pdf-portfolio-maker",
    updates_until: Optional[str] = None,
    allowed_machines: Optional[List[str]] = None,
) -> str:
    """Signs a deterministic Ed25519 license token (PPM1 / PP1 / TOC1)."""
    if product not in PRODUCT_CONFIG:
        raise ValueError(f"Unsupported product slug: {product}")

    priv_key_str = (private_key_hex or "").strip()
    if not priv_key_str or len(priv_key_str) != 64:
        raise ValueError("Invalid ED25519_PRIVATE_KEY_HEX: expected 64-character hex string")
    try:
        priv = ed25519.Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_key_str))
    except Exception as exc:
        raise ValueError(f"Failed to load Ed25519 private key: {exc}")

    now = datetime.now(timezone.utc)
    if updates_until is None:
        updates_until_dt = now.replace(year=now.year + (maintenance_months // 12))
        updates_until_str = updates_until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        updates_until_str = updates_until if "T" in updates_until else f"{updates_until}T23:59:59Z"

    prefix = PRODUCT_CONFIG[product][0]
    payload: Dict[str, Any] = {
        "product": product,
        "license_id": order_id,
        "customer_name": (customer_name or "Licensed User").strip(),
        "customer_email": (customer_email or "").strip().lower(),
        "plan": plan,
        "seats": seats,
        "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "updates_until": updates_until_str,
        "max_version": max_version,
        "expires_at": expires_at,
    }

    if allowed_machines:
        normalized = [normalize_machine_id(m) for m in allowed_machines if normalize_machine_id(m)]
        if normalized:
            payload["allowed_machines"] = normalized

    canonical_data = canonicalize_json(payload)
    signature = priv.sign(canonical_data)
    return f"{prefix}.{b64url_encode(canonical_data)}.{b64url_encode(signature)}"


def infer_product_from_token(token: str) -> str:
    stripped = (token or "").strip()
    for slug, (prefix, _, _) in PRODUCT_CONFIG.items():
        if f"{prefix}." in stripped:
            return slug
    return "pdf-portfolio-maker"


def format_license_block(token: str, product: Optional[str] = None) -> str:
    slug = product or infer_product_from_token(token)
    tag = PRODUCT_CONFIG.get(slug, PRODUCT_CONFIG["pdf-portfolio-maker"])[1]
    return (
        f"-----BEGIN {tag} LICENSE KEY-----\n"
        f"{token}\n"
        f"-----END {tag} LICENSE KEY-----"
    )


def build_fulfillment_email_content(
    customer_name: str,
    token: str,
    product: Optional[str] = None,
) -> Tuple[str, str]:
    slug = product or infer_product_from_token(token)
    app_label = PRODUCT_CONFIG.get(slug, PRODUCT_CONFIG["pdf-portfolio-maker"])[2]
    license_block = format_license_block(token, product=slug)
    subject = f"Your {app_label} Offline License Key"

    if slug == "pdf-portfolio-maker":
        body = f"""Hi {customer_name},

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
    else:
        body = f"""Hi {customer_name},

Thank you for purchasing {app_label}!

Below is your offline license key:

{license_block}

Paste the entire block above into the License dialog inside {app_label} (or save it as license.lic next to the application) to activate immediately.

Best regards,
Matthew Bone
https://pictureperfect.click
"""
    return subject, body


class MailAdapter(Protocol):
    def send(self, to_email: str, subject: str, body: str, product_label: str) -> bool:
        ...


@dataclass
class SentEmailRecord:
    to_email: str
    subject: str
    body: str
    product_label: str


@dataclass
class InMemoryMailAdapter:
    succeed: bool = True
    sent_messages: List[SentEmailRecord] = field(default_factory=list)

    def send(self, to_email: str, subject: str, body: str, product_label: str) -> bool:
        if not self.succeed:
            return False
        self.sent_messages.append(
            SentEmailRecord(to_email=to_email, subject=subject, body=body, product_label=product_label)
        )
        return True


class GmailSmtpAdapter:
    def send(self, to_email: str, subject: str, body: str, product_label: str) -> bool:
        app_password = "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split())
        gmail_user = os.environ.get("GMAIL_USER", "").strip() or "matt18201@gmail.com"
        if not app_password or not gmail_user or not to_email:
            return False

        smtp_host = os.environ.get("SMTP_HOST", "").strip() or "smtp.gmail.com"
        try:
            smtp_port = int(os.environ.get("SMTP_PORT", "").strip() or "465")
        except ValueError:
            return False

        from_header = os.environ.get("GMAIL_FROM_EMAIL", "").strip() or f"{product_label} <{gmail_user}>"
        msg = EmailMessage()
        msg["From"] = from_header
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.set_content(body)

        context = ssl.create_default_context()
        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=10, context=context) as server:
                    server.login(gmail_user, app_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                    server.ehlo()
                    server.starttls(context=context)
                    server.ehlo()
                    server.login(gmail_user, app_password)
                    server.send_message(msg)
            return True
        except (smtplib.SMTPException, OSError, TimeoutError, ValueError):
            return False


class ResendHttpAdapter:
    def send(self, to_email: str, subject: str, body: str, product_label: str) -> bool:
        resend_api_key = os.environ.get("RESEND_API_KEY", "").strip()
        if not resend_api_key or not to_email:
            return False
        sender = os.environ.get("SENDER_EMAIL", "licenses@pictureperfect.click")
        payload = {"from": sender, "to": [to_email], "subject": subject, "text": body}
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
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return 200 <= resp.status < 300
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            return False


def resolve_mail_adapter(mail_sender: Optional[MailAdapter] = None) -> MailAdapter:
    if mail_sender is not None:
        return mail_sender
    provider = os.environ.get("EMAIL_PROVIDER", "auto").strip().lower()
    if provider == "gmail":
        return GmailSmtpAdapter()
    if provider == "resend":
        return ResendHttpAdapter()
    if "".join(os.environ.get("GMAIL_APP_PASSWORD", "").split()):
        return GmailSmtpAdapter()
    return ResendHttpAdapter()


def send_license_email(
    to_email: str,
    customer_name: str,
    token: str,
    product: Optional[str] = None,
    mail_sender: Optional[Any] = None,
) -> bool:
    slug = product or infer_product_from_token(token)
    app_label = PRODUCT_CONFIG.get(slug, PRODUCT_CONFIG["pdf-portfolio-maker"])[2]
    subject, body = build_fulfillment_email_content(customer_name, token, product=slug)

    if callable(mail_sender):
        return bool(mail_sender(to_email, customer_name, token))

    adapter = resolve_mail_adapter(mail_sender)
    return adapter.send(to_email, subject, body, app_label)


def verify_lemonsqueezy_signature(raw_body: bytes, signature_header: str, secret: Optional[str] = None) -> bool:
    sec = (secret if secret is not None else os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "")).encode("utf-8")
    if not signature_header or not sec:
        return False
    computed = hmac.new(sec, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature_header.strip())


def _decode_standard_webhook_secret(secret: str, secret_encoding: str) -> Optional[bytes]:
    cleaned = (secret or "").strip()
    if not cleaned:
        return None
    if secret_encoding == "utf8":
        return cleaned.encode("utf-8")
    if secret_encoding == "whsec_base64":
        if cleaned.startswith("whsec_"):
            cleaned = cleaned[len("whsec_"):]
        padding = "=" * (-len(cleaned) % 4)
        try:
            return base64.b64decode(cleaned + padding)
        except Exception:
            return None
    raise ValueError(f"Unsupported secret encoding: {secret_encoding}")


def verify_standard_webhook(
    raw_body: bytes,
    headers: Dict[str, str],
    secret: str,
    secret_encoding: str = "utf8",
    tolerance_seconds: int = 300,
    now_ts: Optional[int] = None,
) -> bool:
    norm = {k.lower(): v for k, v in (headers or {}).items()}
    wh_id = norm.get("webhook-id", "").strip()
    wh_ts = norm.get("webhook-timestamp", "").strip()
    wh_sig = norm.get("webhook-signature", "").strip()
    if not wh_id or not wh_ts or not wh_sig:
        return False

    try:
        ts_int = int(wh_ts)
    except ValueError:
        return False

    current_ts = int(time.time()) if now_ts is None else now_ts
    if abs(current_ts - ts_int) > tolerance_seconds:
        return False

    key_bytes = _decode_standard_webhook_secret(secret, secret_encoding)
    if not key_bytes:
        return False

    signed_payload = f"{wh_id}.{wh_ts}.".encode("utf-8") + raw_body
    expected_b64 = base64.b64encode(hmac.new(key_bytes, signed_payload, hashlib.sha256).digest()).decode("ascii")

    for part in wh_sig.split():
        if "," not in part:
            continue
        version, sig_val = part.split(",", 1)
        if version == "v1" and hmac.compare_digest(expected_b64, sig_val):
            return True
    return False


def _detect_webhook_provider(normalized_headers: Dict[str, str]) -> str:
    configured = os.environ.get("MOR_PROVIDER", "auto").strip().lower()
    if configured in ("polar", "dodo", "lemonsqueezy"):
        return configured
    if normalized_headers.get("x-signature"):
        return "lemonsqueezy"
    if normalized_headers.get("webhook-signature"):
        if os.environ.get("POLAR_WEBHOOK_SECRET", "").strip():
            return "polar"
        if os.environ.get("DODO_WEBHOOK_SECRET", "").strip():
            return "dodo"
    return "lemonsqueezy"


def _parse_id_set(env_key: str) -> Set[str]:
    raw = os.environ.get(env_key, "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def _resolve_pdf_tier(
    product_id: str,
    product_name: str,
    variant_name: str,
    custom_data: Dict[str, Any],
) -> Optional[Tuple[str, int]]:
    """
    Fail-closed product filter for PDF Portfolio Maker.
    Returns (plan, seats) for PDF Portfolio Maker orders, or None to ignore non-PDF orders.
    """
    solo_ids = _parse_id_set("PDF_SOLO_PRODUCT_ID")
    firm_ids = _parse_id_set("PDF_FIRM_PRODUCT_ID")
    pid = (product_id or "").strip()

    if solo_ids or firm_ids:
        if pid in firm_ids:
            return ("firm", 5)
        if pid in solo_ids:
            return ("solo", 1)
        return None

    # No explicit product IDs configured: require product name (if present) to indicate PDF/Portfolio
    pname_lower = (product_name or "").strip().lower()
    if pname_lower and ("pdf" not in pname_lower and "portfolio" not in pname_lower):
        return None

    custom_plan = str(custom_data.get("plan") or custom_data.get("tier") or "").lower()
    custom_seats = custom_data.get("seats")
    vname_lower = (variant_name or "").lower()

    is_firm = (
        "firm" in vname_lower
        or "team" in vname_lower
        or "firm" in pname_lower
        or "team" in pname_lower
        or "firm" in custom_plan
        or "team" in custom_plan
        or (isinstance(custom_seats, (int, str)) and str(custom_seats).isdigit() and int(custom_seats) > 1)
    )
    seats = (
        int(custom_seats)
        if (isinstance(custom_seats, (int, str)) and str(custom_seats).isdigit() and int(custom_seats) > 1)
        else (5 if is_firm else 1)
    )
    return ("firm" if is_firm else "solo", seats)


def _extract_order_details(provider: str, data: Dict[str, Any]) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    if provider == "polar":
        event_type = data.get("type")
        if event_type != "order.paid":
            return str(event_type or "unknown"), None
        order = data.get("data") or {}
        customer = order.get("customer") or {}
        product_obj = order.get("product") or {}
        return event_type, {
            "order_id": f"polar_{order.get('id', 'unknown')}",
            "customer_email": customer.get("email", ""),
            "customer_name": customer.get("name") or "Valued Customer",
            "product_id": str(order.get("product_id") or product_obj.get("id") or ""),
            "product_name": str(product_obj.get("name") or ""),
            "variant_name": str(product_obj.get("name") or "solo"),
            "custom_data": order.get("metadata") or {},
        }

    if provider == "dodo":
        event_type = data.get("type")
        if event_type != "payment.succeeded":
            return str(event_type or "unknown"), None
        payment = data.get("data") or {}
        customer = payment.get("customer") or {}
        cart = payment.get("product_cart") or []
        solo_ids = _parse_id_set("PDF_SOLO_PRODUCT_ID")
        firm_ids = _parse_id_set("PDF_FIRM_PRODUCT_ID")
        chosen_item: Dict[str, Any] = cart[0] if cart else {}
        if solo_ids or firm_ids:
            for item in cart:
                item_pid = str(item.get("product_id") or "")
                if item_pid in solo_ids or item_pid in firm_ids:
                    chosen_item = item
                    break
        return event_type, {
            "order_id": f"dodo_{payment.get('payment_id', 'unknown')}",
            "customer_email": customer.get("email", ""),
            "customer_name": customer.get("name") or "Valued Customer",
            "product_id": str(chosen_item.get("product_id") or ""),
            "product_name": str(chosen_item.get("name") or ""),
            "variant_name": str(chosen_item.get("name") or "solo"),
            "custom_data": payment.get("metadata") or {},
        }

    # Lemon Squeezy
    event_name = (data.get("meta") or {}).get("event_name")
    if event_name != "order_created":
        return str(event_name or "unknown"), None
    order_data = data.get("data") or {}
    attributes = order_data.get("attributes") or {}
    first_item = attributes.get("first_order_item") or {}
    return event_name, {
        "order_id": f"ls_{order_data.get('id', 'unknown')}",
        "customer_email": attributes.get("user_email", ""),
        "customer_name": attributes.get("user_name") or "Valued Customer",
        "product_id": str(first_item.get("product_id") or ""),
        "product_name": str(first_item.get("product_name") or ""),
        "variant_name": str(first_item.get("variant_name") or "solo"),
        "custom_data": (data.get("meta") or {}).get("custom_data") or {},
    }


def process_order_webhook(
    headers: Dict[str, str],
    raw_body: bytes,
    mail_sender: Optional[Any] = None,
) -> Dict[str, Any]:
    normalized_headers = {k.lower(): v for k, v in (headers or {}).items()}
    provider = _detect_webhook_provider(normalized_headers)

    if provider == "polar":
        secret = os.environ.get("POLAR_WEBHOOK_SECRET", "")
        if not verify_standard_webhook(raw_body, normalized_headers, secret, secret_encoding="utf8"):
            return {"status": 401, "body": {"error": "Invalid Polar webhook signature"}}
    elif provider == "dodo":
        secret = os.environ.get("DODO_WEBHOOK_SECRET", "")
        if not verify_standard_webhook(raw_body, normalized_headers, secret, secret_encoding="whsec_base64"):
            return {"status": 401, "body": {"error": "Invalid Dodo webhook signature"}}
    else:
        sig = normalized_headers.get("x-signature", "")
        if not verify_lemonsqueezy_signature(raw_body, sig):
            return {"status": 401, "body": {"error": "Invalid X-Signature"}}

    try:
        data = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"status": 400, "body": {"error": "Invalid JSON body"}}

    event_name, order = _extract_order_details(provider, data)
    if order is None:
        return {"status": 200, "body": {"received": True, "ignored_event": event_name}}

    tier = _resolve_pdf_tier(
        product_id=order["product_id"],
        product_name=order["product_name"],
        variant_name=order["variant_name"],
        custom_data=order["custom_data"],
    )
    if tier is None:
        return {
            "status": 200,
            "body": {
                "received": True,
                "ignored": True,
                "reason": "non_pdf_product",
                "product_id": order["product_id"],
                "product_name": order["product_name"],
            },
        }

    plan, seats = tier
    private_key_hex = os.environ.get("ED25519_PRIVATE_KEY_HEX", "")
    try:
        token = issue_ed25519_token(
            private_key_hex=private_key_hex,
            customer_name=order["customer_name"],
            customer_email=order["customer_email"],
            order_id=order["order_id"],
            plan=plan,
            seats=seats,
            maintenance_months=12,
            max_version=1,
            product="pdf-portfolio-maker",
        )
    except ValueError as err:
        return {"status": 500, "body": {"error": f"Key configuration error: {err}"}}

    email_sent = send_license_email(
        to_email=order["customer_email"],
        customer_name=order["customer_name"],
        token=token,
        product="pdf-portfolio-maker",
        mail_sender=mail_sender,
    )
    if not email_sent:
        return {
            "status": 502,
            "body": {
                "error": "Failed to send fulfillment email",
                "order_id": order["order_id"],
                "email_sent": False,
            },
        }

    return {
        "status": 200,
        "body": {
            "received": True,
            "provider": provider,
            "order_id": order["order_id"],
            "plan": plan,
            "seats": seats,
            "email_sent": True,
        },
    }


def _find_production_private_key() -> Optional[str]:
    candidates = [
        Path.cwd() / ".secrets" / "production_ed25519_private_key.txt",
        Path(__file__).resolve().parents[3] / ".secrets" / "production_ed25519_private_key.txt",
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                for line in cand.read_text(encoding="utf-8").splitlines():
                    if line.startswith("ED25519_PRIVATE_KEY_HEX="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
            except OSError:
                pass
    return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Unified Ed25519 License Key Issuance & Fulfillment CLI")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("generate-keypair", help="Generate a fresh Ed25519 keypair")

    def _add_mint_args(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--product",
            choices=list(PRODUCT_CONFIG.keys()),
            default="pdf-portfolio-maker",
            help="Target product slug",
        )
        p.add_argument("--name", default="Licensed User", help="Customer name")
        p.add_argument("--email", default="owner@pictureperfect.click", help="Customer email")
        p.add_argument("--order-id", default=None, help="Order or license ID")
        p.add_argument("--plan", default=None, help="Plan tier (e.g. pro, solo, firm, vip)")
        p.add_argument("--seats", type=int, default=1, help="Licensed seat count")
        p.add_argument("--updates-until", default=None, help="Updates cutoff date (YYYY-MM-DD or ISO 8601)")
        p.add_argument("--expires-at", default=None, help="Optional expiration date")
        p.add_argument("--max-version", type=int, default=1, help="Max major version")
        p.add_argument("--machine-id", action="append", default=None, help="Optional hardware Machine ID(s)")
        p.add_argument("--private-key-hex", default=None, help="Ed25519 private key hex")
        p.add_argument("--raw", action="store_true", help="Output raw token only")
        p.add_argument("--send-email", action="store_true", help="Email license key via configured Gmail/Resend")

    mint_parser = subparsers.add_parser("mint-key", help="Mint a signed license token")
    _add_mint_args(mint_parser)
    _add_mint_args(parser)

    args = parser.parse_args(argv)

    if args.command == "generate-keypair":
        priv, pub = generate_ed25519_keypair()
        print(f"PRIVATE_KEY_HEX={priv}")
        print(f"PUBLIC_KEY_HEX={pub}")
        return 0

    priv_hex = args.private_key_hex or os.environ.get("ED25519_PRIVATE_KEY_HEX", "").strip() or _find_production_private_key()
    if not priv_hex:
        print("Error: No Ed25519 private key found in .secrets or --private-key-hex", file=sys.stderr)
        return 1

    plan = args.plan or ("solo" if args.product == "pdf-portfolio-maker" else "pro")
    order_id = args.order_id or f"manual_{int(datetime.now(timezone.utc).timestamp())}"

    allowed_machines: List[str] = []
    if args.machine_id:
        for item in args.machine_id:
            for part in str(item).split(","):
                if part.strip():
                    allowed_machines.append(part.strip())

    token = issue_ed25519_token(
        private_key_hex=priv_hex,
        customer_name=args.name,
        customer_email=args.email,
        order_id=order_id,
        plan=plan,
        seats=args.seats,
        max_version=args.max_version,
        expires_at=args.expires_at,
        product=args.product,
        updates_until=args.updates_until,
        allowed_machines=allowed_machines or None,
    )

    if args.raw:
        print(token)
    else:
        print(format_license_block(token, product=args.product))

    if args.send_email:
        if not send_license_email(args.email, args.name, token, product=args.product):
            print("Error: Failed to send fulfillment email. Check GMAIL_APP_PASSWORD or RESEND_API_KEY.", file=sys.stderr)
            return 1
        print(f"[OK] Emailed {PRODUCT_CONFIG[args.product][2]} license key to {args.email}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
