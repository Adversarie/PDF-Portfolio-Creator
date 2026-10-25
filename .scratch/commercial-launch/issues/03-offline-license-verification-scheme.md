# 03 Offline License Verification Scheme

Type: research
Status: resolved
Blocked by:

## Question

How should offline asymmetric cryptographic license verification be implemented in Python for purchases made via Lemon Squeezy or Gumroad?

1. Which cryptographic signature scheme (e.g. Ed25519 via `cryptography` library) provides the best balance of compact key format, security, and simplicity?
2. How should the license payload be structured (e.g., licensed name/email, issue date, product edition/version constraints)?
3. How can Lemon Squeezy (or Gumroad) webhooks sign and generate this key automatically upon purchase, and how does the desktop app verify it using an embedded public key without ever making outbound network calls?
4. Produce a minimal Python verification module and key generator script.

## Answer

### 1. Selected Scheme: Ed25519 (RFC 8032)
- **Algorithm**: Ed25519 (EdDSA over Curve25519) via the standard PyCA `cryptography` package.
- **Key Sizes**: 32-byte raw public key embedded in client; 64-byte deterministic signature.
- **Advantages**: 100% deterministic (no RNG failure at signing time), side-channel resistant, constant-time verification in <0.2 ms, compact Base64URL string (~200 chars).

### 2. Payload Structure & Canonical Serialization
- **Fields**: `product` ("pdf-portfolio-maker"), `license_id` (order ID), `customer_name`, `customer_email`, `plan` ("pro"), `seats` (int), `issued_at` (ISO 8601), `updates_until` (ISO 8601 maintenance cut-off), `max_version` (1), `expires_at` (null for perpetual).
- **Perpetual Maintenance Model**: Verified against the compile-time `APP_BUILD_DATE` embedded in the executable (`APP_BUILD_DATE <= updates_until`). No system clock rollback vulnerabilities.
- **Serialization**: Canonical UTF-8 JSON (`separators=(',', ':')`, `sort_keys=True`).
- **Token Format**: `PPM1.<base64url_payload>.<base64url_signature>` wrapped in standard email block delimiters.

### 3. Fulfillment & Local Storage
- **Webhook Pipeline**: Lemon Squeezy sends `order_created` -> verified via HMAC-SHA256 (`X-Signature`) -> serverless function signs payload with private key -> dispatches transactional email via Resend/Postmark.
- **Client Storage**: Persisted locally at `%APPDATA%\PDF Portfolio Maker\license.lic` (Windows) / `~/Library/Application Support/PDF Portfolio Maker/license.lic` (macOS).
- **Verification**: Verified on startup and before portfolio generation strictly offline with the bundled 32-byte public key. If unregistered/expired, the application stamps an evaluation banner on the Cover Sheet; if valid, it unlocks clean export and displays licensed licensee details.

