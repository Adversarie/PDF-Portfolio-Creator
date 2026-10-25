# 06 Commercial Launch Spec Synthesis

Type: task
Status: resolved
Blocked by: 01, 02, 03, 04, 05

## Question

Synthesize all resolved decisions, spikes, and prototypes into the canonical Commercial Launch Spec (`.scratch/commercial-launch/spec.md`) and implementation backlog.

Deliverables:
1. Product Specification Document covering:
   - Value proposition, target audience, and anti-goals.
   - Core architecture: Engine interface, PySide6 GUI layer, Offline Licensing.
   - v1.0 Feature scope boundary and acceptance criteria.
   - Build, packaging, and release runbook.
2. Implementation task breakdown ready for execution.

## Answer

Commercial Launch Specification synthesized and published at [.scratch/commercial-launch/spec.md](../spec.md).

### Summary of Completed Synthesis:
1. **Target Market & Value Wedge**: Compliance professionals (legal, accounting, healthcare) requiring 100% offline air-gapped ISO 32000-1 document packaging with zero subscription fees.
2. **Technical Architecture**: Pure Python `pypdf` engine (ISO 32000-1 `/Collection` with Details view, schema, and fallback vector Cover Sheet) + PySide6 desktop UI with non-blocking `QThread` execution.
3. **Security & Licensing**: Strictly offline Ed25519 asymmetric signatures (`PPM1.<payload>.<sig>`) verified against compile-time `APP_BUILD_DATE`. Free evaluation mode stamps a watermark banner on Page 1; license entry unlocks clean export.
4. **Distribution Pipeline**: PyInstaller `--onedir` + pruned `PySide6-Essentials` (~70 MB) packaged into an Inno Setup dual-mode installer (`PrivilegesRequired=lowest` to `%LOCALAPPDATA%\Programs`) yielding a ~25–30 MB setup executable.
5. **Store & Terms**: Lemon Squeezy Merchant of Record ($49 Solo / $149 Firm) with 30-day money-back guarantee and 48-hour email support.
6. **Execution Backlog**: 4 ordered build phases ready for implementation.

