# PDF Portfolio Maker Coding Standards & Architecture Invariants

This document defines the strict engineering standards, terminology constraints, security invariants, and code quality expectations for the PDF Portfolio Maker application.

## 1. Canonical Domain Language

All code identifiers, comments, user interface copy, and documentation must use the canonical domain terms defined in [CONTEXT.md](CONTEXT.md). Prohibited synonyms must never be used:

- **PDF Portfolio**: A standardized document containing an ISO 32000-1 `/Collection` dictionary packaging multiple distinct files in original formats.
  - _Avoid_: Merged PDF, Combined PDF, PDF Package, Binder.
- **Source File**: An individual document or asset (PDF, DOCX, XLSX, image, etc.) embedded as a file stream inside the PDF Portfolio.
  - _Avoid_: Attachment, Page, Segment.
- **Cover Sheet**: The visual parent PDF page displayed by readers when opening the document or when lacking interactive `/Collection` rendering.
  - _Avoid_: Splash screen, Home page, Title page.
- **Collection Schema**: Standardized field definitions (Name, Size, Type, Date, Description) stored in `/CF` dictating viewer metadata columns.
  - _Avoid_: Custom attributes, properties table, column layout.
- **License Key**: A cryptographically signed string (`PPM1` token) verified completely offline by the desktop application.
  - _Avoid_: Serial number, activation code, registration token.

## 2. File Encoding & BOM Prohibition

- All Python source files (`.py`), configuration files, tests, and build scripts (`.iss`, `.ps1`, `.bat`) must be encoded in **UTF-8 without BOM**.
- Files must never start with `0xEF, 0xBB, 0xBF`.
- **PowerShell 5.1 Warning**: Never write files using `Set-Content -Encoding UTF8` as it injects a 3-byte BOM (e.g. historical bug in `src/config.py`). Use explicit BOM-free .NET writers:
  ```powershell
  $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($targetPath, $contentString, $utf8NoBom)
  ```
- In Python, always specify explicit encoding:
  ```python
  with open(path, "w", encoding="utf-8", newline="\n") as f:
      f.write(content)
  ```

## 3. Security & Architectural Invariants

### 100% Air-Gapped Zero-Network Runtime
- The desktop client application must operate with **absolute zero network connectivity**.
- The desktop codebase (`src/`, `app.py`) must **never import socket, urllib, requests, httpx, or any telemetry/cloud libraries**.
- All functionality—including PDF assembly, compression, and license validation—must execute locally without external dependencies.

### Offline Cryptographic License Verification
- Commercial authorization is granted via Ed25519 digital signatures formatted as `PPM1` tokens.
- Verification in the client desktop app uses only the embedded public key (`EMBEDDED_PUBLIC_KEY_HEX` in `src/config.py`).
- The client binary must never bundle or read private keys (`production_ed25519_private_key.txt`).

### Isolated Serverless Fulfillment
- License generation and email distribution occur exclusively in the stateless serverless worker (`packaging/webhook-worker/api/webhook.py`).
- The worker verifies Lemon Squeezy HMAC-SHA256 signatures, creates signed `PPM1` tokens using the private key, and dispatches them via Resend transactional email.
- This worker code must remain strictly separated from desktop client packaging.

## 4. Engineering Rigor & Error Handling

- **No Silent Exception Swallowing**: Bare `except:` or `except Exception: pass` blocks are strictly forbidden. Errors in PDF processing or signature verification must raise descriptive exceptions or present clear user notifications.
- **Robust PDF Specification Compliance**: Embedded `/Collection` dictionaries and `/EmbeddedFiles` streams must strictly conform to ISO 32000-1 standards to ensure cross-reader compatibility (Adobe Acrobat, PDF-XChange, Foxit).
- **No Workarounds**: File parsing, schema mapping, and cryptographic routines must be implemented at the root level without temporary patches or bypasses.
