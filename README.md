# PDF Portfolio Maker

100% air-gapped, offline desktop application for creating ISO 32000-1 compliant PDF Portfolios (`/Collection`) on Windows—engineered for law firms, CPAs, financial auditors, and government compliance teams.

## Features

- **Native ISO 32000-1 `/Collection` Containers & Round-Trip Editing**: Packages PDFs, Word documents (`.docx`), Excel spreadsheets (`.xlsx`), Outlook emails (`.msg`, `.eml`, `.pst`, `.mbox`), and evidence media into a single standardized PDF Portfolio while preserving original Source File byte streams, metadata, and digital signatures. Also opens existing PDF Portfolios to inspect, unpack/extract, reorder, or append Source Files.
- **Legal E-Discovery Suite**: Generates a vector Cover Sheet with an automated **SHA-256 Chain-of-Custody Exhibit Manifest**, sequential **Bates Numbering** (`EXH-000001`), nested `/Collection` folder hierarchies (`/Folders`), and direct `.pst`/`.mbox`/`.eml` email archive extraction.
- **Constant-Memory Streaming I/O**: Streams multi-gigabyte video evidence and discovery files in 1 MB chunks (`iter_chunks` / `compress_and_hash_stream`) without loading entire uncompressed files into RAM.
- **100% Air-Gapped & Hardware-Bound Offline Licensing**: Makes zero outbound network calls. Offline `PPM1` License Keys are verified locally using an embedded Ed25519 public key (`src/licensing/verifier.py`) with deterministic workstation Machine ID binding, offline seat-cap ledger enforcement, and Enterprise MSI / Group Policy pre-staging (`%LOCALAPPDATA%\PDFPortfolioMaker\license.lic`, `%PROGRAMDATA%\PDFPortfolioMaker\license.lic`, and GPO Registry keys).
- **Stateless Serverless Fulfillment**: Includes a self-contained Lemon Squeezy `order_created` webhook worker (`packaging/webhook-worker/`) that cryptographically signs `PPM1` offline license keys and delivers them via Resend.

## Download & Installation

Download the latest standalone Windows installer (`PDFPortfolioMaker-Setup-1.0.0.exe`) from the [**GitHub Releases**](https://github.com/Adversarie/PDF-Portfolio-Creator/releases) page.

## Development & Packaging

```powershell
# Run the test suite (17 unit & integration tests)
pytest

# Build standalone Windows installer (PyInstaller PySide6-Essentials + Inno Setup 7)
powershell -ExecutionPolicy Bypass -File packaging/build_release.ps1
```
