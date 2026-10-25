# PDF Portfolio Maker

100% air-gapped, offline desktop application for creating ISO 32000-1 compliant PDF Portfolios (`/Collection`) on Windows—engineered for law firms, CPAs, financial auditors, and government compliance teams.

## Features

- **Native ISO 32000-1 `/Collection` Containers**: Packages PDFs, Word documents (`.docx`), Excel spreadsheets (`.xlsx`), Outlook emails (`.msg`), and evidence images into a single standardized PDF Portfolio while preserving original Source File byte streams, metadata, and digital signatures.
- **Automated Vector Cover Sheet & Collection Schema**: Generates a clean vector Cover Sheet and standard `/CF` Collection Schema (`Name`, `Size`, `Type`, `Modified Date`, `Description`) compatible with Adobe Acrobat Reader, Foxit, and court e-filing portals.
- **100% Air-Gapped & Offline**: Makes zero outbound network calls. Offline `PPM1` license keys are verified locally using an embedded Ed25519 public key (`src/licensing/verifier.py`) and stored in `%LOCALAPPDATA%\PDFPortfolioMaker\license.lic`.
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
