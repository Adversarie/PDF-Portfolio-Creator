# Commercial Launch Specification: PDF Portfolio Maker v1.0

**Document Version**: 1.0.0  
**Target Release**: Q4 2026  
**Status**: Ready for Implementation  
**Product**: PDF Portfolio Maker (Windows Desktop Edition)  

---

## 1. Executive Summary & Value Proposition

### 1.1 The Market Opportunity
Compliance-bound professionals (law firms, corporate legal departments, forensic accountants, healthcare administrators, and real estate escrow agents) frequently need to package multiple disparate files—signed contracts, financial spreadsheets, email threads, and photo exhibits—into a single, court-ready, or audit-ready envelope.

Today, their choices are broken:
- **Cloud Converters (iLovePDF, Smallpdf)**: Strictly forbidden by HIPAA, attorney-client privilege, and GDPR compliance because they upload confidential client files to third-party web servers.
- **Adobe Acrobat Pro**: Bloated enterprise software costing **$240/year per user** on an aggressive recurring subscription.
- **Basic PDF Mergers**: Flatten all documents into a single page stream, destroying original file formats (e.g. converting dynamic Excel models into static images) and invalidating cryptographic signatures.

### 1.2 The Value Proposition
**PDF Portfolio Maker** is a lightweight, 100% offline desktop application that creates standardized **ISO 32000-1 (PDF 1.7) Portfolios**. It packages arbitrary files in their native formats with full metadata preservation, zero cloud uploads, and zero subscription fees.

- **100% Air-Gapped Privacy**: Runs entirely on the local machine. Zero telemetry, zero analytics, zero network requests.
- **True ISO 32000-1 Portfolios**: Embeds files inside an interactive `/Collection` schema recognized natively by Adobe Acrobat DC/XI, while providing an automatic vector Cover Sheet for non-collection viewers.
- **One-Time Honest Pricing**: $49 Solo / $149 5-Seat Firm license, perpetual usage, zero recurring subscription.

---

## 2. System Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PySide6 Desktop UI                              │
│                                                                        │
│  ┌────────────────────────┐  ┌──────────────────────────────────────┐  │
│  │   Header & License     │  │        Explorer Drag & Drop          │  │
│  │   Offline Verification │  │   (Accepts .pdf, .xlsx, .docx, etc.)  │  │
│  └───────────┬────────────┘  └──────────────────┬───────────────────┘  │
│              │                                  │                      │
│              ▼                                  ▼                      │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │               Source File Table (QTableWidget)                   │  │
│  │   Columns: Name | Size | Type | Date Modified | Description      │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
│                                     │                                  │
│  ┌──────────────────────────────────▼───────────────────────────────┐  │
│  │                   Cover Sheet Settings Panel                     │  │
│  │   Fields: Title | Subtitle | Organization / Author | Date        │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
│                                     │                                  │
│                                     ▼ [Start Export]                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │             Non-Blocking Worker Thread (QThread)                 │  │
│  │               Progress (0-100%) & Status Updates                 │  │
│  └──────────────────────────────────┬───────────────────────────────┘  │
└─────────────────────────────────────┼──────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      PDF Portfolio Engine (pypdf)                      │
│                                                                        │
│  1. Catalog Initialization: /Version /1.7, /PageMode /UseAttachments   │
│  2. Vector Cover Sheet: Page 1 Fallback Rendering (Helvetica Vector)  │
│  3. Collection Schema (/CollectionSchema): /F, /Size, /S, /ModDate,    │
│     /Desc field definitions                                            │
│  4. Collection Dictionary (/Collection): /View /D, /Sort /FileName     │
│  5. File Embedding: /Names /EmbeddedFiles with /CI Collection Items    │
│  6. License Stamping: Unwatermarked (Pro) vs Evaluation Header Banner  │
└─────────────────────────────────────┬──────────────────────────────────┘
                                      │
                                      ▼
                        Output: `Portfolio.pdf`
```

---

## 3. Component Specifications

### 3.1 PDF Engine (`engine/portfolio.py`)
- **Library**: `pypdf >= 5.1.0` (Pure Python, BSD 3-Clause, zero external C++ DLLs).
- **Standards Conformance**: ISO 32000-1:2008 (PDF 1.7), Clauses 12.3.5 ("Collections"), 7.11 ("File Specifications"), and 7.7.4 ("Name Trees").
- **Collection View**: `/View /D` (Details view / structured spreadsheet grid in Acrobat).
- **Metadata Fields Schema (`/CollectionSchema`)**:
  | PDF Key | Subtype | Header Name | Acrobat Resolution |
  | :--- | :--- | :--- | :--- |
  | `/FileName` | `/F` | File Name | Native stream `/UF` filename |
  | `/FileSize` | `/Size` | Size | Stream byte length (`/Params /Size`) |
  | `/DocType` | `/S` | Type | Inferred user-friendly type string |
  | `/ModDate` | `/ModDate` | Date Modified | ISO 8824 formatted modification date |
  | `/Description`| `/Desc` | Description | User-authored inline note |
- **Fallback Cover Sheet**:
  - Automatically rendered on Page 1.
  - Displays dark-navy vector header banner with Portfolio Title, Subtitle, Organization, and Generation Date.
  - Includes a clear instructional callout for readers without interactive portfolio support (web browsers, Apple Preview, mobile viewers) pointing them to the Attachments panel.

### 3.2 User Interface (`ui/main_window.py`)
- **Framework**: `PySide6-Essentials >= 6.7.0` (QtWidgets).
- **Main Views**:
  1. **Header**: Application branding + License pill badge (`Evaluation Copy` vs `Licensed to: <Name>`).
  2. **Toolbar**: `+ Add Files...`, `Remove Selected`, `Move Up`, `Move Down`, `Clear All`.
  3. **File Grid (`QTableWidget`)**:
     - Drag-and-drop ingestion from Windows Explorer (`dragEnterEvent` & `dropEvent`).
     - Auto-calculates formatted file sizes (KB/MB) and file types.
     - Description column is editable inline with a double-click.
     - Multi-selection support (`ExtendedSelection`).
  4. **Cover Sheet Panel (`QGroupBox`)**: Configurable Title, Subtitle, and Author/Org.
  5. **Footer**: Smooth `QProgressBar` and prominent `Create PDF Portfolio...` export button.
- **Threading Model**: `PortfolioBuilderWorker` inherits `QThread`, preventing UI freezes when embedding multi-hundred-megabyte files.

### 3.3 Offline Cryptographic Licensing (`licensing/`)
- **Algorithm**: **Ed25519 (RFC 8032)** via `cryptography >= 43.0.0`.
- **Public Key**: 32-byte raw public key embedded in code.
- **Signature**: 64-byte deterministic signature. Constant-time verification in `<0.2 ms`.
- **Token Format**: `PPM1.<base64url_payload>.<base64url_signature>`
- **Payload Data**:
  ```json
  {
    "product": "pdf-portfolio-maker",
    "license_id": "ls_order_12345",
    "customer_name": "Alice Smith, Esq.",
    "customer_email": "alice@smithlaw.example",
    "plan": "solo",
    "seats": 1,
    "issued_at": "2026-10-22T08:00:00Z",
    "updates_until": "2027-10-22T08:00:00Z",
    "max_version": 1,
    "expires_at": null
  }
  ```
- **Maintenance Policy**: Checked against compile-time `APP_BUILD_DATE` (`APP_BUILD_DATE <= updates_until`). Perpetual use of all versions released within 1 year; immune to system clock manipulation.
- **Local Storage**: Persisted locally to `%APPDATA%\PDF Portfolio Maker\license.lic`.
- **Evaluation Enforcement**:
  - Valid Key: Clean, professional export.
  - Evaluation / Unregistered: Stamps header banner on Page 1: *"Created with PDF Portfolio Maker (Evaluation Copy - Unregistered)"*. All file ingestion and portfolio features remain 100% unlocked.

---

## 4. Distribution, Packaging & Store Pipeline

### 4.1 PyInstaller Spec (`packaging/pdf_portfolio_maker.spec`)
- **Mode**: `--onedir` directory bundle (`COLLECT(...)`). Instant cold startup (<0.8s), zero `%TEMP%` extraction overhead, zero heuristic AV flags.
- **Footprint Pruning**: Built against `PySide6-Essentials`. Explicitly strips `QtWebEngine`, `QtQuick`, `QtMultimedia`, `Qt3D`, and non-English Qt translation catalogs, slashing the runtime footprint from >350 MB to **~70 MB**.
- **Compression**: `upx=False` (avoids antivirus packer triggers).

### 4.2 Inno Setup Installer (`packaging/installer.iss`)
- **Privilege Scope**: Dual-mode (`PrivilegesRequired=lowest` with `PrivilegesRequiredOverridesAllowed=dialog`).
  - Standard User: Installs to `%LOCALAPPDATA%\Programs\PDF Portfolio Maker` with **zero UAC elevation prompts**.
  - Admin/Enterprise: Installs to `C:\Program Files\PDF Portfolio Maker` via `/ALLUSERS`.
- **Compression**: Solid `lzma2/ultra64` yielding a compact **~25–30 MB installer download**.
- **Shell Registration**: Registers in Windows right-click "Open With" menu without hijacking default `.pdf` reader ownership. Registers `.pdfportfolio` custom projects.

### 4.3 Code Signing & Windows SmartScreen
- **Service**: **Microsoft Trusted Signing** ($9.99/mo cloud HSM via Azure Artifact Signing).
- **Pre-Release Whitelisting**: Automated binary submission to Microsoft Security Intelligence Developer Portal.

### 4.4 Commercial Store Setup
- **Merchant of Record**: **Lemon Squeezy** (5% + 50¢ transaction fee). Handles 100% of global sales tax, EU VAT, and UK VAT remittance.
- **Pricing Tiers**:
  - **Solo Professional**: **$49** one-time (up to 2 personal computers).
  - **Firm / Team Pack**: **$149** one-time (up to 5 team computers).
- **Fulfillment**: Lemon Squeezy `order_created` webhook -> Serverless Ed25519 signer -> Resend transactional email with license block.
- **Customer Guarantee**: 30-Day Money-Back Guarantee + 48-Hour Email Support SLA.

---

## 5. File Structure of the Final Codebase

```
c:\Users\matt1\Downloads\PDF Portfolio App\
├── CONTEXT.md                    # Domain language glossary
├── requirements.txt              # Production runtime dependencies
├── app.py                        # Main entry point (launches PySide6 GUI)
│
├── src/
│   ├── __init__.py
│   ├── config.py                 # APP_VERSION, APP_BUILD_DATE, EMBEDDED_PUBLIC_KEY
│   │
│   ├── engine/
│   │   ├── __init__.py
│   │   └── portfolio_builder.py  # Pure pypdf ISO 32000-1 Collection generator
│   │
│   ├── licensing/
│   │   ├── __init__.py
│   │   ├── verifier.py           # Offline Ed25519 token validation & storage
│   │   └── issuer.py             # Serverless webhook key generator
│   │
│   └── ui/
│       ├── __init__.py
│       ├── main_window.py        # PySide6 MainWindow, table & cover sheet panels
│       ├── worker.py             # QThread background build worker
│       └── dialogs.py            # License entry dialog & about box
│
├── packaging/
│   ├── pdf_portfolio_maker.spec  # Optimized PyInstaller --onedir specification
│   ├── installer.iss             # Inno Setup 6 dual-mode installer script
│   └── build_release.ps1         # One-click clean, build, sign & package script
│
└── assets/
    ├── app_icon.ico              # Multi-resolution application icon
    └── banner.png                # Optional visual branding assets
```

---

## 6. Implementation Task Backlog

With planning complete, implementation proceeds in 4 ordered phases:

1. **Phase 1: Core Engine Refactoring (`src/engine/`)**
   - Move tested ISO 32000-1 generator from `prototype_app.py` into `src/engine/portfolio_builder.py`.
   - Add unit tests validating `/Collection`, `/CollectionSchema`, and `/CI` item dictionaries using `pypdf`.

2. **Phase 2: Licensing Subsystem (`src/licensing/`)**
   - Implement `src/licensing/verifier.py` with Ed25519 client verification and local app data storage.
   - Wire license verification into `portfolio_builder.py` (controlling Cover Sheet evaluation watermark).
   - Create license activation dialog in `src/ui/dialogs.py`.

3. **Phase 3: Production PySide6 UI (`src/ui/`)**
   - Modularize GUI layout into `src/ui/main_window.py`.
   - Add keyboard shortcuts (Delete, Ctrl+O, Ctrl+S) and double-click to edit description.
   - Refactor `app.py` as root launcher.

4. **Phase 4: Build & Release Automation (`packaging/`)**
   - Set up `packaging/pdf_portfolio_maker.spec` and `packaging/installer.iss`.
   - Test full packaging run with `build_release.ps1` to produce `PDFPortfolioMaker-Setup-1.0.0.exe`.
   - Configure Lemon Squeezy product listings and deploy webhook signer.
