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
import uuid
import base64
import hashlib
import logging
import platform
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Tuple, Dict, Any, List
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.exceptions import InvalidSignature

from src.config import APP_VERSION, APP_BUILD_DATE, EMBEDDED_PUBLIC_KEY_HEX, APP_NAME

logger = logging.getLogger(__name__)


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


def normalize_machine_id(raw_id: str) -> str:
    """Normalizes a machine fingerprint string by stripping hyphens/spaces and uppercasing."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw_id or "").upper()
    return cleaned


def format_machine_id(raw_id: str) -> str:
    """Formats a 16-char hex machine fingerprint into XXXX-XXXX-XXXX-XXXX display format."""
    norm = normalize_machine_id(raw_id)
    if len(norm) == 16:
        return f"{norm[0:4]}-{norm[4:8]}-{norm[8:12]}-{norm[12:16]}"
    return norm


def get_machine_fingerprint() -> str:
    """
    Computes a deterministic, 100% offline 16-hex-char hardware workstation fingerprint.
    Uses OS-native cryptography GUIDs (when available) and hardware node identifiers
    without making any network or socket calls.
    """
    components: List[str] = []

    if sys.platform == "win32":
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"SOFTWARE\Microsoft\Cryptography",
                0,
                winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0),
            ) as key:
                machine_guid, _ = winreg.QueryValueEx(key, "MachineGuid")
                if machine_guid:
                    components.append(f"guid:{str(machine_guid).strip().lower()}")
        except OSError as exc:
            logger.debug("Could not read Windows MachineGuid from registry: %s", exc)

    try:
        components.append(f"node:{platform.node().strip().lower()}")
        components.append(f"arch:{platform.machine().strip().lower()}")
        components.append(f"mac:{uuid.getnode()}")
    except Exception as exc:
        logger.debug("Fallback machine fingerprint attribute collection error: %s", exc)

    seed = "|".join(components) if components else "pdf-portfolio-default-host"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16].upper()
    return format_machine_id(digest)


@dataclass
class LicenseStatus:
    is_valid: bool
    message: str
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    plan: Optional[str] = None
    seats: int = 1
    raw_payload: Optional[Dict[str, Any]] = None
    machine_id: Optional[str] = None
    bound_machines: Optional[List[str]] = None
    claimed_seats: int = 0


class OfflineLicenseVerifier:
    """
    Validates cryptographically signed license tokens using an embedded Ed25519 public key.
    Enforces optional hardware machine-binding and offline seat ledger caps with ZERO network calls.
    """

    TOKEN_REGEX = re.compile(r"PPM1\.([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)")

    def __init__(
        self,
        public_key_hex: Optional[str] = None,
        app_version: str = APP_VERSION,
        build_date_iso: str = APP_BUILD_DATE,
        machine_id: Optional[str] = None,
    ):
        pub_hex = public_key_hex if public_key_hex is not None else EMBEDDED_PUBLIC_KEY_HEX
        self._public_key = ed25519.Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(pub_hex)
        )
        self._app_version = app_version
        self._app_major = int(app_version.split(".")[0])
        self._build_date = datetime.strptime(build_date_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        self._machine_id = normalize_machine_id(machine_id) if machine_id else normalize_machine_id(get_machine_fingerprint())

    @property
    def machine_id(self) -> str:
        return format_machine_id(self._machine_id)

    def verify(self, raw_input: str, seat_ledger_path: Optional[Path] = None) -> LicenseStatus:
        """
        Parses and verifies a license key block or token.
        Enforces cryptographic signature, product, version cap, maintenance window,
        optional hardware machine-binding, and optional offline seat ledger limits.
        Returns a LicenseStatus object with validity and metadata.
        """
        if not raw_input or not isinstance(raw_input, str):
            return LicenseStatus(
                is_valid=False,
                message="No license key provided.",
                machine_id=self.machine_id,
            )

        match = self.TOKEN_REGEX.search(raw_input)
        if not match:
            return LicenseStatus(
                is_valid=False,
                message="Malformed license key: missing PPM1 prefix or invalid token structure.",
                machine_id=self.machine_id,
            )

        payload_b64, sig_b64 = match.group(1), match.group(2)

        try:
            payload_bytes = b64url_decode(payload_b64)
            signature_bytes = b64url_decode(sig_b64)
        except Exception as exc:
            logger.debug("Failed to decode base64url license token: %s", exc)
            return LicenseStatus(
                is_valid=False,
                message="Failed to decode license key encoding.",
                machine_id=self.machine_id,
            )

        if len(signature_bytes) != 64:
            return LicenseStatus(
                is_valid=False,
                message=f"Invalid signature length ({len(signature_bytes)} bytes; expected 64).",
                machine_id=self.machine_id,
            )

        # 1. Cryptographic Asymmetric Signature Check
        try:
            self._public_key.verify(signature_bytes, payload_bytes)
        except InvalidSignature:
            return LicenseStatus(
                is_valid=False,
                message="Cryptographic signature verification failed (tampered key or invalid signature).",
                machine_id=self.machine_id,
            )

        # 2. Parse Canonical Payload JSON
        try:
            payload = json.loads(payload_bytes.decode("utf-8"))
        except Exception as exc:
            logger.debug("Corrupted JSON payload in license key: %s", exc)
            return LicenseStatus(
                is_valid=False,
                message="Corrupted license payload data.",
                machine_id=self.machine_id,
            )

        # 3. Product Integrity Check
        if payload.get("product") != "pdf-portfolio-maker":
            return LicenseStatus(
                is_valid=False,
                message=f"License was issued for '{payload.get('product')}', not PDF Portfolio Maker.",
                machine_id=self.machine_id,
            )

        # 4. Major Version Check
        max_version = payload.get("max_version")
        if max_version is not None and self._app_major > int(max_version):
            return LicenseStatus(
                is_valid=False,
                message=f"License is capped at version {max_version}.x (Running version: {self._app_version}).",
                raw_payload=payload,
                machine_id=self.machine_id,
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
                        raw_payload=payload,
                        machine_id=self.machine_id,
                    )
            except ValueError:
                return LicenseStatus(
                    is_valid=False,
                    message="Malformed updates_until date in license.",
                    machine_id=self.machine_id,
                )

        # 6. Optional Time-Limited Expiration
        expires_at_str = payload.get("expires_at")
        if expires_at_str:
            try:
                expires_at = datetime.strptime(expires_at_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > expires_at:
                    return LicenseStatus(
                        is_valid=False,
                        message=f"License expired on {expires_at.strftime('%Y-%m-%d')}.",
                        raw_payload=payload,
                        machine_id=self.machine_id,
                    )
            except ValueError:
                return LicenseStatus(
                    is_valid=False,
                    message="Malformed expires_at date in license.",
                    machine_id=self.machine_id,
                )

        seats = max(1, int(payload.get("seats", 1)))

        # 7. Cryptographic Hardware Machine-Binding Check (when bound in token payload)
        raw_bound = payload.get("allowed_machines")
        if raw_bound is None and payload.get("machine_id"):
            raw_bound = [payload["machine_id"]]

        bound_list: Optional[List[str]] = None
        if isinstance(raw_bound, list) and len(raw_bound) > 0:
            bound_list = [normalize_machine_id(str(m)) for m in raw_bound if str(m).strip()]
            if len(bound_list) > seats:
                return LicenseStatus(
                    is_valid=False,
                    message=(
                        f"License seat cap exceeded in hardware binding: "
                        f"{len(bound_list)} machines bound for a {seats}-seat license."
                    ),
                    raw_payload=payload,
                    machine_id=self.machine_id,
                    bound_machines=[format_machine_id(m) for m in bound_list],
                )
            if self._machine_id not in bound_list:
                return LicenseStatus(
                    is_valid=False,
                    message=(
                        f"Hardware seat lock mismatch: License Key is bound to specific workstation(s) "
                        f"and is not authorized for Machine ID {self.machine_id}."
                    ),
                    raw_payload=payload,
                    machine_id=self.machine_id,
                    bound_machines=[format_machine_id(m) for m in bound_list],
                )

        # 8. Optional Offline Seat Ledger Enforcement (tracks seats per license_id)
        claimed_count = 1
        if seat_ledger_path is not None:
            license_id = str(payload.get("license_id") or hashlib.sha256(payload_bytes).hexdigest()[:16])
            ok, claimed_count, ledger_msg = _check_or_claim_seat_in_ledger(
                ledger_path=seat_ledger_path,
                license_id=license_id,
                machine_id=self._machine_id,
                max_seats=seats,
                claim=False,
            )
            if not ok:
                return LicenseStatus(
                    is_valid=False,
                    message=ledger_msg,
                    raw_payload=payload,
                    machine_id=self.machine_id,
                    bound_machines=[format_machine_id(m) for m in bound_list] if bound_list else None,
                    claimed_seats=claimed_count,
                )

        return LicenseStatus(
            is_valid=True,
            message="License valid and active.",
            customer_name=payload.get("customer_name", "Licensed User"),
            customer_email=payload.get("customer_email"),
            plan=payload.get("plan", "solo"),
            seats=seats,
            raw_payload=payload,
            machine_id=self.machine_id,
            bound_machines=[format_machine_id(m) for m in bound_list] if bound_list else None,
            claimed_seats=claimed_count,
        )

    def activate_on_machine(self, raw_input: str, seat_ledger_path: Optional[Path] = None) -> LicenseStatus:
        """
        Verifies a license token and records a seat claim for this workstation in the offline seat ledger.
        Rejects activation if all licensed seats are already claimed by other workstation fingerprints.
        """
        ledger = seat_ledger_path if seat_ledger_path is not None else get_seat_ledger_path()
        status = self.verify(raw_input, seat_ledger_path=ledger)
        if not status.is_valid or not status.raw_payload:
            return status

        license_id = str(status.raw_payload.get("license_id") or "default")
        ok, claimed_count, ledger_msg = _check_or_claim_seat_in_ledger(
            ledger_path=ledger,
            license_id=license_id,
            machine_id=self._machine_id,
            max_seats=status.seats,
            claim=True,
        )
        status.claimed_seats = claimed_count
        if not ok:
            status.is_valid = False
            status.message = ledger_msg
        return status


# ---------------------------------------------------------------------------
# Offline Seat Ledger & Enterprise Provisioning Helpers
# ---------------------------------------------------------------------------

def get_seat_ledger_path() -> Path:
    """Returns the path to the local/shared offline seat ledger JSON file."""
    lic_path = get_license_file_path()
    return lic_path.parent / "license_seats.json"


def _check_or_claim_seat_in_ledger(
    ledger_path: Path,
    license_id: str,
    machine_id: str,
    max_seats: int,
    claim: bool = True,
) -> Tuple[bool, int, str]:
    """
    Checks or claims a seat in the offline seat ledger for `license_id`.
    Returns (allowed: bool, claimed_count: int, message: str).
    """
    norm_machine = normalize_machine_id(machine_id)
    data: Dict[str, List[str]] = {}
    if ledger_path.is_file():
        try:
            raw = json.loads(ledger_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = {str(k): [normalize_machine_id(str(m)) for m in v if str(m).strip()] for k, v in raw.items() if isinstance(v, list)}
        except Exception as exc:
            logger.debug("Could not parse offline seat ledger %s: %s", ledger_path, exc)

    claimed = data.get(license_id, [])
    if norm_machine in claimed:
        return True, len(claimed), "Workstation seat already registered."

    if len(claimed) >= max_seats:
        return (
            False,
            len(claimed),
            f"Offline seat cap reached ({len(claimed)}/{max_seats} workstation seats already claimed for license '{license_id}'). "
            f"Deactivate an existing workstation or upgrade to a multi-seat Firm License.",
        )

    if claim:
        claimed.append(norm_machine)
        data[license_id] = claimed
        try:
            ledger_path.parent.mkdir(parents=True, exist_ok=True)
            ledger_path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
        except OSError as exc:
            logger.debug("Could not persist seat ledger %s: %s", ledger_path, exc)

    return True, len(claimed), "Workstation seat claimed."


def release_seat_in_ledger(machine_id: Optional[str] = None, ledger_path: Optional[Path] = None) -> None:
    """Releases the current workstation's seat claim across any active license in the offline seat ledger."""
    ledger = ledger_path if ledger_path is not None else get_seat_ledger_path()
    if not ledger.is_file():
        return
    norm_machine = normalize_machine_id(machine_id or get_machine_fingerprint())
    try:
        raw = json.loads(ledger.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return
        modified = False
        for lic_id, machines in list(raw.items()):
            if isinstance(machines, list):
                filtered = [normalize_machine_id(str(m)) for m in machines if normalize_machine_id(str(m)) != norm_machine]
                if len(filtered) != len(machines):
                    raw[lic_id] = filtered
                    modified = True
        if modified:
            ledger.write_text(json.dumps(raw, indent=2, sort_keys=True), encoding="utf-8")
    except Exception as exc:
        logger.debug("Could not release seat in ledger %s: %s", ledger, exc)


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


def get_enterprise_license_paths() -> List[Path]:
    """
    Returns ordered pre-staged enterprise license file paths for MSI / Group Policy deployment:
    1. %LOCALAPPDATA%\\PDFPortfolioMaker\\license.lic (per-user MSI / Intune pre-staged path)
    2. %PROGRAMDATA%\\PDFPortfolioMaker\\license.lic (machine-wide MSI / SCCM pre-staged path)
    """
    paths: List[Path] = []
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        paths.append(Path(local_app_data) / "PDFPortfolioMaker" / "license.lic")
    elif sys.platform == "win32":
        paths.append(Path.home() / "AppData" / "Local" / "PDFPortfolioMaker" / "license.lic")

    program_data = os.environ.get("PROGRAMDATA")
    if program_data:
        paths.append(Path(program_data) / "PDFPortfolioMaker" / "license.lic")
    return paths


def read_gpo_registry_license() -> Optional[str]:
    """Reads a Group Policy (GPO) provisioned License Key from the Windows Registry if present."""
    if sys.platform != "win32":
        return None
    try:
        import winreg
        registry_locations = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\PDFPortfolioMaker"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Policies\PDFPortfolioMaker"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\PDFPortfolioMaker"),
        ]
        for hive, subkey in registry_locations:
            try:
                with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                    val, _ = winreg.QueryValueEx(key, "LicenseKey")
                    if val and str(val).strip():
                        return str(val).strip()
            except OSError:
                continue
    except Exception as exc:
        logger.debug("Could not query Windows Registry for GPO license: %s", exc)
    return None


def load_installed_license() -> Optional[str]:
    """
    Reads the stored license key string from disk or enterprise policy if present.
    Supports zero-touch custom workflow, MSI / GPO deployment, & air-gapped provisioning:
    1. Checks environment variable PDF_PORTFOLIO_LICENSE_KEY.
    2. Checks Windows Group Policy Registry keys (HKLM/HKCU\\Software\\Policies\\PDFPortfolioMaker).
    3. Checks standard user AppData / application support path.
    4. Checks pre-staged Enterprise MSI paths (%LOCALAPPDATA%\\PDFPortfolioMaker\\license.lic
       and %PROGRAMDATA%\\PDFPortfolioMaker\\license.lic).
    5. Checks portable license.lic in sys.executable directory or current working directory.
       If a valid enterprise or portable license.lic is found and %APPDATA% does not have one,
       it is auto-persisted to %APPDATA% for seamless subsequent launches.
    """
    # 1. Environment variable override (zero-touch automated workflows / CI / containers)
    env_token = os.environ.get("PDF_PORTFOLIO_LICENSE_KEY", "").strip()
    if env_token:
        return env_token

    # 2. Windows Group Policy Registry override
    gpo_token = read_gpo_registry_license()
    if gpo_token:
        return gpo_token

    # 3. Standard AppData license file
    appdata_path = get_license_file_path()
    if appdata_path.is_file():
        try:
            content = appdata_path.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError as exc:
            logger.debug("Failed to read license file %s: %s", appdata_path, exc)

    # 4. Pre-staged Enterprise MSI paths & Portable license.lic candidates
    candidates: List[Path] = list(get_enterprise_license_paths())
    try:
        candidates.append(Path(sys.executable).parent / "license.lic")
    except Exception as exc:
        logger.debug("Could not resolve sys.executable parent path: %s", exc)
    try:
        candidates.append(Path.cwd() / "license.lic")
    except Exception as exc:
        logger.debug("Could not resolve cwd path: %s", exc)

    for cand in candidates:
        if cand.is_file():
            try:
                candidate_text = cand.read_text(encoding="utf-8").strip()
                if candidate_text:
                    verifier = OfflineLicenseVerifier()
                    status = verifier.verify(candidate_text)
                    if status.is_valid:
                        if not appdata_path.is_file():
                            save_installed_license(candidate_text)
                        return candidate_text
                    return candidate_text
            except OSError as exc:
                logger.debug("Could not read candidate license file %s: %s", cand, exc)

    return None


def save_installed_license(token: str) -> None:
    """Persists a license key string to local disk and claims a seat in the offline ledger."""
    cleaned = token.strip()
    path = get_license_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cleaned, encoding="utf-8")

    # Also record seat claim if token is a valid signed PPM1 license
    verifier = OfflineLicenseVerifier()
    verifier.activate_on_machine(cleaned)


def remove_installed_license() -> None:
    """Deletes the stored license file from disk and releases the workstation seat claim."""
    path = get_license_file_path()
    if path.is_file():
        path.unlink(missing_ok=True)
    release_seat_in_ledger()


def get_active_license_status() -> LicenseStatus:
    """Loads the installed license from disk and verifies it offline."""
    stored_token = load_installed_license()
    if not stored_token:
        return LicenseStatus(
            is_valid=False,
            message="No license installed.",
            machine_id=format_machine_id(get_machine_fingerprint()),
        )
    verifier = OfflineLicenseVerifier()
    return verifier.verify(stored_token)
