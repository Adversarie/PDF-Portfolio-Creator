"""
src/licensing/issuer.py
-----------------------
Server / Vendor Side: Ed25519 Key Generation & License Signing.
Runs on the developer workstation or in the Lemon Squeezy serverless webhook.
"""

import sys
import json
from datetime import datetime, timezone
from typing import Tuple, Dict, Any, Optional

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives import serialization

from src.licensing.verifier import b64url_encode, canonicalize_json


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
            bytes.fromhex(private_key_hex)
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
    ) -> str:
        """
        Creates a signed PPM1 license token string.
        """
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
        signature = self._private_key.sign(canonical_data)  # Exactly 64 bytes

        encoded_payload = b64url_encode(canonical_data)
        encoded_sig = b64url_encode(signature)

        return f"PPM1.{encoded_payload}.{encoded_sig}"

    @classmethod
    def format_email_block(cls, token: str) -> str:
        """Wraps a license token in recognizable human delimiters for delivery."""
        return (
            "-----BEGIN PDF PORTFOLIO LICENSE KEY-----\n"
            f"{token}\n"
            "-----END PDF PORTFOLIO LICENSE KEY-----"
        )


if __name__ == "__main__":
    # Quick CLI for issuing a test key or generating keypairs
    if len(sys.argv) > 1 and sys.argv[1] == "generate-keypair":
        priv, pub = LicenseIssuer.generate_keypair()
        print(f"PRIVATE_KEY_HEX={priv}")
        print(f"PUBLIC_KEY_HEX={pub}")
    else:
        print("Usage: python -m src.licensing.issuer generate-keypair")
