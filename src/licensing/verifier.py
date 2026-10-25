"""
src/licensing/verifier.py
-------------------------
Offline Ed25519 asymmetric cryptographic license verification.
Operates strictly offline with zero outbound network calls, telemetry, or sockets.
"""

import os
import sys
import re
import json
import base64
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from src.config import APP_VERSION, APP_BUILD_DATE, EMBEDDED_PUBLIC_KEY_HEX, APP_NAME


def b64url_encode(data: bytes) -> str:
    """Encodes bytes to Base64URL string without padding (RFC 4648 §5)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(token: str) -> bytes:
    """Decodes a unpadded or padded Base64URL string to bytes."""
    padding = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode((token + padding).encode("ascii"))


def canonicalize_json(obj: Dict[str, Any]) -> bytes:
    """Serializes a dictionary to canonical JSON bytes."""
    return json.dumps(obj, separators=(",", ":"), sort_keys=True, ensure_ascii=True).encode("utf-8")


@dataclass
class LicenseStatus:
    is_valid: bool
    message: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    plan: Optional[str] = None
    seats: int = 1
    raw_payload: Optional[Dict[str, Any]] = None


class OfflineLicenseVerifier:
    """
    Validates cryptographically signed license tokens using an embedded Ed25519 public key.
    Requires ZERO network calls.
    """

    TOKEN_REGEX = re.compile(r"PPM1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)")

    def __init__(
        self,
        public_key_hex: str = EMBEDDED_PUBLIC_KEY_HEX,
        app_version: str = APP_VERSION,
        build_date_iso: str = APP_BUILD_DATE,
    ):
        self._public_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(public_key_hex)
        )
        self._app_version = app_version
        self._app_major = int(app_version.split(".")[0])
        self._build_date = datetime.strptime(build_date_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)

    def verify(self, raw_input: str) -> LicenseStatus:
        """
        Parses and verifies a license key block or token.
        Returns a LicenseStatus object with validity and metadata.
        """
        if not raw_input or not isinstance(raw_input, str):
            return LicenseStatus(is_valid=False, message="No license key provided.")

        match = self.TOKEN_REGEX.search(raw_input)
        if not match:
            return LicenseStatus(
                is_valid=False,
                message="Malformed license key: missing PPM1 prefix or invalid token structure."
            )

        payload_b64, sig_b64 = match.group(1), match.group(2)

        try:
            payload_bytes = b64url_decode(payload_b64)
            signature_bytes = b64url_decode(sig_b64)
        except Exception:
            return LicenseStatus(is_valid=False, message="Failed to decode license key encoding.")

        if len(signature_bytes) != 64:
            return LicenseStatus(
                is_valid=False,
                message=f"Invalid signature length ({len(signature_bytes)} bytes; expected 64)."
            )

        # 1. Cryptographic Asymmetric Signature Check
        try:
            self._public_key.verify(signature_bytes, payload_bytes)
        except InvalidSignature:
            return LicenseStatus(
                is_valid=False,
                message="Cryptographic signature verification failed (tampered key or invalid signature)."
            )

        # 2. Parse Canonical Payload JSON
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception:
            return LicenseStatus(is_valid=False, message="Corrupted license payload data.")

        # 3. Product Integrity Check
        if payload.get("product") != "pdf-portfolio-maker":
            return LicenseStatus(
                is_valid=False,
                message=f"License was issued for '{payload.get('product')}', not PDF Portfolio Maker."
            )

        # 4. Major Version Check
        max_version = payload.get("max_version")
        if max_version is not None and self._app_major > int(max_version):
            return LicenseStatus(
                is_valid=False,
                message=f"License is capped at version {max_version}.x (Running version: {self._app_version}).",
                raw_payload=payload
            )

        # 5. Maintenance / Updates Cutoff Check (Perpetual Maintenance Model)
        updates_until_str = payload.get("updates_until")
        if updates_until_str:
            try:
                updates_until = datetime.strptime(updates_until_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if self._build_date > updates_until:
                    return LicenseStatus(
                        is_valid=False,
                        message=(
                            f"License maintenance expired on {updates_until.strftime('%Y-%m-%d')}. "
                            f"Current version build date: {self._build_date.strftime('%Y-%m-%d')}."
                        ),
                        raw_payload=payload
                    )
            except ValueError:
                return LicenseStatus(is_valid=False, message="Malformed updates_until date in license.")

        # 6. Optional Time-Limited Expiration
        expires_at_str = payload.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.strptime(expires_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires_at:
                    return LicenseStatus(
                        is_valid=False,
                        message=f"License expired on {expires_at.strftime('%Y-%m-%d')}.",
                        raw_payload=payload
                    )
            except ValueError:
                return LicenseStatus(is_valid=False, message="Malformed expires_at date in license.")

        # Success
        return LicenseStatus(
            is_valid=True,
            message="License valid and active.",
            customer_name=payload.get("customer_name", "Licensed User"),
            customer_email=payload.get("customer_email"),
            plan=payload.get("plan", "solo"),
            seats=int(payload.get("seats", 1)),
            raw_payload=payload
        )


# ---------------------------------------------------------------------------
# Local License Storage & State Helpers
# ---------------------------------------------------------------------------

def get_license_file_path() -> Path:
    """Returns the platform-standard local license file path."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path.home() / ".config"

    app_dir = base / APP_NAME
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir / "license.lic"


def load_installed_license() -> Optional[str]:
    """Reads the stored license key string from disk if present."""
    path = get_license_file_path()
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8").strip()
        except Exception:
            return None
    return None


def save_installed_license(token: str) -> None:
    """Persists a license key string to local disk."""
    path = get_license_file_path()
    path.write_text(token.strip(), encoding="utf-8")


def remove_installed_license() -> None:
    """Deletes the stored license file from disk."""
    path = get_license_file_path()
    if path.is_file():
        path.unlink(missing_ok=True)


def get_active_license_status() -> LicenseStatus:
    """Loads the installed license from disk and verifies it offline."""
    stored_token = load_installed_license()
    if not stored_token:
        return LicenseStatus(is_valid=False, message="No license installed.")
    verifier = OfflineLicenseVerifier()
    return verifier.verify(stored_token)
