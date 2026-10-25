# 04 Desktop Packaging and Installer Pipeline

Type: research
Status: resolved
Blocked by: 01, 02

## Question

What is the optimal PyInstaller and Inno Setup build configuration for packaging this PySide6 application into a production Windows installer?

1. What PyInstaller spec options (`--windowed`, `--onedir` vs `--onefile`, hidden imports, Qt plugin bundling) produce the fastest startup time and lowest risk of antivirus false positives?
2. How should the Inno Setup script (`.iss`) be structured to install into user local AppData (no UAC admin prompts required for standard users) or Program Files, create Start Menu shortcuts, and register file associations?
3. What are the requirements and workflow for signing the `.exe` and installer (authenticode code signing)?

## Answer

### 1. PyInstaller Architecture: `--onedir` Mode
- **Bundle Strategy**: Use `--onedir` mode via `COLLECT(...)`. Avoids the 3–8 second cold extraction delay and `%TEMP%` heuristic antivirus flags caused by `--onefile`. Startup time is instantaneous (<0.8s).
- **Qt Footprint Pruning**: Build with `PySide6-Essentials`. Explicitly exclude unused heavyweight modules (`QtWebEngine`, `QtQuick`, `QtMultimedia`, `Qt3D`, `QtPdf`), shrinking the distribution from >350 MB to ~65–75 MB uncompressed.
- **AV Heuristic Defense**: Set `upx=False` in PyInstaller (UPX triggers malware packer heuristics). Let Inno Setup handle solid compression using `lzma2/ultra64` for a ~25–30 MB installer download.

### 2. Inno Setup Architecture
- **Dual-Mode Scope**: `PrivilegesRequired=lowest` with `PrivilegesRequiredOverridesAllowed=dialog`. Installs by default to `%LOCALAPPDATA%\Programs\PDF Portfolio Maker` with **zero UAC prompts** (like VS Code/Slack), avoiding enterprise IT permission barriers. Can elevate to `Program Files` when run as administrator.
- **File Associations**: Does **not** hijack default `.pdf` viewing; registers under `HKA\Software\Classes\Applications\PDFPortfolioMaker.exe\SupportedTypes` so it appears in the right-click "Open With" menu, and registers `.pdfportfolio` custom projects.
- **Modern Auto Constants**: Uses `{autopf}`, `{autoprograms}`, and `{autodesktop}` with `Root: HKA`.

### 3. Authenticode Code Signing & SmartScreen Strategy
- **Cloud HSM Signing**: Under June 2023 CA/B Forum rules, code signing requires hardware protection. Use **Microsoft Trusted Signing** ($9.99/mo via Azure Artifact Signing) for cloud-native signing without hardware USB tokens.
- **Initial Reputation Buildup**: Submit release candidates to Microsoft Security Intelligence Developer Portal for automated whitelist processing within 2–24 hours before public download.

