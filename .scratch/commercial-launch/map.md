## Destination

A comprehensive Commercial Launch Spec & Implementation Roadmap (`.scratch/commercial-launch/spec.md`) specifying the v1.0 architecture, True PDF Portfolio engine integration, PySide6 UI, offline asymmetric license verification, and Windows installer pipeline for a commercial release.

## Notes

- Domain glossary lives in [CONTEXT.md](../../CONTEXT.md).
- Target audience: Compliance-bound professionals (legal, accounting, healthcare, real estate) requiring 100% offline document packaging and total privacy.
- Product definition: True PDF Portfolio creator (ISO 32000-1 `/Collection` dictionary) embedding arbitrary source files with a standardized collection schema and fallback cover sheet.
- Stack decision: Python backend + PySide6 (Qt) UI, packaged for Windows via PyInstaller + Inno Setup.
- Monetization: One-time purchase desktop software activated via offline asymmetric cryptographic key.
- Skills to consult: `research`, `prototype`, `grilling`, `codebase-design`.

## Decisions so far

<!-- the index: one line per closed ticket, enough to judge relevance, then zoom the link for the detail the ticket holds -->

- [01 PDF Portfolio Engine Spike](./issues/01-pdf-portfolio-engine-spike.md): Standardize on pure Python `pypdf` (>= 5.1.0) using low-level dictionary manipulation (`/Collection`, `/CollectionSchema`, `/CI`) to construct compliant ISO 32000-1 portfolios with zero C++ DLL bundling friction.
- [02 PySide6 UI Table Architecture](./issues/02-pyside6-ui-table-architecture.md): Validated in `prototype_app.py` with multi-column table model, Explorer drag-and-drop, inline metadata editing, and non-blocking `QThread` portfolio builder.
- [03 Offline License Verification Scheme](./issues/03-offline-license-verification-scheme.md): Use Ed25519 asymmetric signatures (`PPM1.<payload>.<sig>`) verified offline against a bundled 32-byte public key with perpetual maintenance checks against `APP_BUILD_DATE`.
- [04 Desktop Packaging and Installer Pipeline](./issues/04-desktop-packaging-and-installer-pipeline.md): Package with PyInstaller `--onedir` + pruned `PySide6-Essentials` (~70 MB) and Inno Setup dual-mode installer (`PrivilegesRequired=lowest` to `%LOCALAPPDATA%\Programs`) signed via Microsoft Trusted Signing.
- [05 Commercial Pricing and Store Setup](./issues/05-commercial-pricing-and-store-setup.md): Sell via Lemon Squeezy ($49 Solo / $149 Firm) on a perpetual 1-year maintenance license with unwatermarked Cover Sheet unlock and 30-day refund guarantee.
- [06 Commercial Launch Spec Synthesis](./issues/06-commercial-launch-spec-synthesis.md): Canonical Commercial Launch Spec and implementation roadmap completed at `spec.md`.







## Not yet specified

- Code signing certificate acquisition (EV cert vs cloud HSM vs standard cert / SmartScreen reputation buildup).
- Handling encrypted or password-protected source PDFs during portfolio assembly.
- In-app update check mechanism (offline/privacy-respecting update notifications).
- Post-launch v1.1 features (Bates stamping on embedded PDFs, user-customizable schema column definitions, dark/light theme switching).

## Out of scope

- Cloud / SaaS web application (strictly offline local desktop application).
- Mobile applications (iOS / Android).
- Full PDF reader / editor functionality (the application is a portfolio creator and packager, not an Acrobat editor).
- Online subscription billing / DRM phone-home servers (strictly offline asymmetric key verification).
