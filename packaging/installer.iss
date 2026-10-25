; =====================================================================
; PDF Portfolio Maker - Inno Setup Script
; Compiler: Inno Setup 6.1+
; =====================================================================

#define MyAppName "PDF Portfolio Maker"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "PDF Portfolio Maker Team"
#define MyAppURL "https://pdfportfoliomaker.com"
#define MyAppExeName "PDFPortfolioMaker.exe"
#define MyAppAssocName "PDF Portfolio Document"
#define MyAppAssocExt ".pdfportfolio"
#define MyAppAssocKey StringChange(MyAppAssocName, " ", "") + MyAppAssocExt

[Setup]
; App Identity
AppId={{9F6D14C3-7E1A-49F1-8B0C-E62D037D71C9}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; 64-Bit System Targeting (x64 and Windows 11 Arm64 emulation)
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

; Dual-Mode Scope: Default to per-user AppData; allow elevation to Program Files
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}

; Output configuration
OutputDir=..\dist-installer
OutputBaseFilename=PDFPortfolioMaker-Setup-{#MyAppVersion}
Compression=lzma2/ultra64
SolidCompression=yes

; Modern Wizard Styling
WizardStyle=modern
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE.txt
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\assets\app_icon.ico

; Shell association dynamic refresh
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Copy PyInstaller --onedir output directory recursively
Source: "..\dist\PDFPortfolioMaker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu Shortcut
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
; Desktop Shortcut (optional task)
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
; ---------------------------------------------------------------------
; 1. Register "Open With" for .pdf without hijacking default viewer
; ---------------------------------------------------------------------
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\SupportedTypes"; ValueType: string; ValueName: ".pdf"; ValueData: ""; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\Applications\{#MyAppExeName}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

; ---------------------------------------------------------------------
; 2. Register Custom Portfolio Project Extension (.pdfportfolio)
; ---------------------------------------------------------------------
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocExt}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocKey}"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}"; ValueType: string; ValueName: ""; ValueData: "{#MyAppAssocName}"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\{#MyAppAssocKey}\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Flags: uninsdeletekey

[Run]
; Launch application option upon installation completion
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
