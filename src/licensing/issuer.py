"""
src/licensing/issuer.py
-----------------------
Server / Vendor Side: Ed25519 Key Generation & License Signing.
Runs on the developer workstation or in the Lemon Squeezy serverless webhook.
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from src.licensing.verifier import b64url_encode, canonicalize_json


def find_production_private_key() -> Optional[str]:
    """Finds and extracts the ED25519_PRIVATE_KEY_HEX from local repository .secrets directory."""
    candidates = [
        Path.cwd() / ".secrets" / "production_ed25519_private_key.txt",
        Path(__file__).resolve().parent.parent.parent / ".secrets" / "production_ed25519_private_key.txt",
        Path(__file__).resolve().parent.parent / ".secrets" / "production_ed25519_private_key.txt",
    ]
    for cand in candidates:
        if cand.is_file():
            try:
                for line in cand.read_text(encoding="utf-8").splitlines():
                    if line.startswith("ED25519_PRIVATE_KEY_HEX="):
                        val = line.split("=", 1)[1].strip()
                        if val:
                            return val
            except Exception:
                pass
    return None


class LicenseIssuer:
    """Signs and issues Ed25519 license tokens using the vendor private key."""

    @staticmethod
    def generate_keypair() -> Tuple[str, str]:
        """Generates a new Ed25519 keypair as 64-character hex strings (32 raw bytes each)."""
        priv = ed25519.Ed25519PrivateKey.generate()
        raw_priv = priv.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        pub = priv.public_key()
        raw_pub = pub.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        return raw_priv.hex(), raw_pub.hex()

    def __init__(self, private_key_hex: str):
        self._private_key = ed25519.Ed25519PrivateKey.from_private_bytes(
            bytes.fromhex(private_key_hex.strip())
        )

    def create_license_token(
        self,
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
    ) -> str:
        """
        Creates a signed Ed25519 license token string.
        PPM1.<b64url_payload>.<b64url_sig> for 'pdf-portfolio-maker'
        PP1.<b64url_payload>.<b64url_sig> for 'picture-perfect'
        """
        now = datetime.now(timezone.utc)
        if updates_until is None:
            updates_until_dt = now.replace(year=now.year + (maintenance_months // 12))
            updates_until_str = updates_until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            updates_until_str = updates_until if "T" in updates_until else f"{updates_until}T23:59:59Z"

        prefix = "PP1" if product == "picture-perfect" else "PPM1"

        payload: Dict[str, Any] = {
            "product": product,
            "license_id": order_id,
            "customer_name": customer_name.strip(),
            "customer_email": customer_email.strip().lower(),
            "plan": plan,
            "seats": seats,
            "issued_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "updates_until": updates_until_str,
            "max_version": max_version,
            "expires_at": expires_at,
        }

        canonical_data = canonicalize_json(payload)
        signature = self._private_key.sign(canonical_data)  # Exactly 64 bytes

        encoded_payload = b64url_encode(canonical_data)
        encoded_sig = b64url_encode(signature)

        return f"{prefix}.{encoded_payload}.{encoded_sig}"

    @classmethod
    def format_email_block(cls, token: str, product: str = "pdf-portfolio-maker") -> str:
        """Wraps a license token in recognizable human delimiters for delivery."""
        is_pp = product == "picture-perfect" or token.startswith("PP1.")
        tag = "PICTURE PERFECT" if is_pp else "PDF PORTFOLIO"
        return (
            f"-----BEGIN {tag} LICENSE KEY-----\n"
            f"{token}\n"
            f"-----END {tag} LICENSE KEY-----"
        )


def main():
    parser = argparse.ArgumentParser(description="Ed25519 License Issuer CLI")
    subparsers = parser.add_subparsers(dest="command")

    # generate-keypair command
    subparsers.add_parser("generate-keypair", help="Generate a fresh Ed25519 keypair")

    # mint-key command
    mint_parser = subparsers.add_parser("mint-key", help="Mint a signed license token")
    mint_parser.add_argument("--product", choices=["pdf-portfolio-maker", "picture-perfect"], default="pdf-portfolio-maker", help="Target product")
    mint_parser.add_argument("--name", default="Licensed User", help="Customer name")
    mint_parser.add_argument("--email", default="owner@pictureperfect.click", help="Customer email")
    mint_parser.add_argument("--order-id", default=None, help="Order or license ID")
    mint_parser.add_argument("--plan", default=None, help="Plan tier (e.g. pro, solo, firm, vip)")
    mint_parser.add_argument("--seats", type=int, default=1, help="Licensed seat count")
    mint_parser.add_argument("--updates-until", default=None, help="Updates cutoff date (YYYY-MM-DD or ISO 8601)")
    mint_parser.add_argument("--expires-at", default=None, help="Optional expiration date")
    mint_parser.add_argument("--max-version", type=int, default=1, help="Max major version")
    mint_parser.add_argument("--private-key-hex", default=None, help="Ed25519 private key hex (defaults to .secrets file)")
    mint_parser.add_argument("--raw", action="store_true", help="Output raw token only (no delimiters)")

    # Also support top-level arguments if user directly invokes without subcommand:
    parser.add_argument("--product", choices=["pdf-portfolio-maker", "picture-perfect"], default="pdf-portfolio-maker")
    parser.add_argument("--name", default="Licensed User")
    parser.add_argument("--email", default="owner@pictureperfect.click")
    parser.add_argument("--order-id", default=None)
    parser.add_argument("--plan", default=None)
    parser.add_argument("--seats", type=int, default=1)
    parser.add_argument("--updates-until", default=None)
    parser.add_argument("--expires-at", default=None)
    parser.add_argument("--max-version", type=int, default=1)
    parser.add_argument("--private-key-hex", default=None)
    parser.add_argument("--raw", action="store_true")

    args = parser.parse_args()

    if args.command == "generate-keypair" or (len(sys.argv) > 1 and sys.argv[1] == "generate-keypair"):
        priv, pub = LicenseIssuer.generate_keypair()
        print(f"PRIVATE_KEY_HEX={priv}")
        print(f"PUBLIC_KEY_HEX={pub}")
        return

    priv_hex = args.private_key_hex or find_production_private_key()
    if not priv_hex:
        print("Error: No Ed25519 private key found in .secrets or provided via --private-key-hex", file=sys.stderr)
        sys.exit(1)

    plan = args.plan
    if not plan:
        plan = "pro" if args.product == "picture-perfect" else "solo"

    order_id = args.order_id or f"manual_{int(datetime.now(timezone.utc).timestamp())}"

    issuer = LicenseIssuer(priv_hex)
    token = issuer.create_license_token(
        customer_name=args.name,
        customer_email=args.email,
        order_id=order_id,
        plan=plan,
        seats=args.seats,
        max_version=args.max_version,
        expires_at=args.expires_at,
        product=args.product,
        updates_until=args.updates_until,
    )

    if args.raw:
        print(token)
    else:
        print(LicenseIssuer.format_email_block(token, product=args.product))


if __name__ == "__main__":
    main()
