<#
.SYNOPSIS
    Enterprise MSI & Group Policy (GPO / Intune / SCCM) Provisioning Script for PDF Portfolio Maker.
    Supports pre-staging %LOCALAPPDATA%\PDFPortfolioMaker\license.lic, %PROGRAMDATA%\PDFPortfolioMaker\license.lic,
    Windows Registry GPO keys, silent installer execution, and optional WiX MSI compilation.

.PARAMETER LicenseKey
    Signed offline PPM1 License Key string to pre-stage across workstation paths.

.PARAMETER LicenseFilePath
    Path to a license.lic file containing a signed offline PPM1 License Key.

.PARAMETER StageMachineWide
    Also stages the license into %PROGRAMDATA%\PDFPortfolioMaker\license.lic and HKLM\SOFTWARE\Policies\PDFPortfolioMaker.

.PARAMETER RunSilentInstaller
    Runs dist-installer\PDFPortfolioMaker-Setup-1.0.0.exe silently (/VERYSILENT /SUPPRESSMSGBOXES /NORESTART).

.PARAMETER BuildMsi
    Compiles packaging\enterprise.wxs into dist-installer\PDFPortfolioMaker-Enterprise-1.0.0.msi if WiX Toolset is installed.
#>

[CmdletBinding()]
param(
    [string]$LicenseKey = "",
    [string]$LicenseFilePath = "",
    [switch]$StageMachineWide,
    [switch]$RunSilentInstaller,
    [switch]$BuildMsi
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")

# 1. Resolve License Key Content if provided
$ResolvedKey = ""
if (-not [string]::IsNullOrWhiteSpace($LicenseKey)) {
    $ResolvedKey = $LicenseKey.Trim()
} elseif (-not [string]::IsNullOrWhiteSpace($LicenseFilePath) -and (Test-Path $LicenseFilePath)) {
    $ResolvedKey = [System.IO.File]::ReadAllText((Resolve-Path $LicenseFilePath).Path, [System.Text.Encoding]::UTF8).Trim()
}

if (-not [string]::IsNullOrWhiteSpace($ResolvedKey)) {
    # Pre-stage %LOCALAPPDATA%\PDFPortfolioMaker\license.lic
    $LocalStageDir = Join-Path $env:LOCALAPPDATA "PDFPortfolioMaker"
    if (-not (Test-Path $LocalStageDir)) {
        New-Item -ItemType Directory -Path $LocalStageDir -Force | Out-Null
    }
    $LocalLicFile = Join-Path $LocalStageDir "license.lic"
    [System.IO.File]::WriteAllText($LocalLicFile, $ResolvedKey, $Utf8NoBom)
    Write-Host "[OK] Pre-staged per-user license at: $LocalLicFile" -ForegroundColor Green

    # Also stage into standard %APPDATA%\PDF Portfolio Maker\license.lic
    $RoamingStageDir = Join-Path $env:APPDATA "PDF Portfolio Maker"
    if (-not (Test-Path $RoamingStageDir)) {
        New-Item -ItemType Directory -Path $RoamingStageDir -Force | Out-Null
    }
    $RoamingLicFile = Join-Path $RoamingStageDir "license.lic"
    [System.IO.File]::WriteAllText($RoamingLicFile, $ResolvedKey, $Utf8NoBom)
    Write-Host "[OK] Pre-staged roaming user license at: $RoamingLicFile" -ForegroundColor Green

    if ($StageMachineWide) {
        $ProgDataDir = Join-Path $env:PROGRAMDATA "PDFPortfolioMaker"
        if (-not (Test-Path $ProgDataDir)) {
            New-Item -ItemType Directory -Path $ProgDataDir -Force | Out-Null
        }
        $ProgDataLic = Join-Path $ProgDataDir "license.lic"
        [System.IO.File]::WriteAllText($ProgDataLic, $ResolvedKey, $Utf8NoBom)
        Write-Host "[OK] Pre-staged machine-wide license at: $ProgDataLic" -ForegroundColor Green

        $GpoRegPath = "HKCU:\SOFTWARE\Policies\PDFPortfolioMaker"
        if (-not (Test-Path $GpoRegPath)) {
            New-Item -Path $GpoRegPath -Force | Out-Null
        }
        Set-ItemProperty -Path $GpoRegPath -Name "LicenseKey" -Value $ResolvedKey -Type String
        Write-Host "[OK] Configured Group Policy registry key at: $GpoRegPath\LicenseKey" -ForegroundColor Green
    }
}

# 2. Optional WiX MSI Compilation
if ($BuildMsi) {
    $WxsPath = Join-Path $PSScriptRoot "enterprise.wxs"
    $OutDir = Join-Path $ProjectRoot "dist-installer"
    if (-not (Test-Path $OutDir)) {
        New-Item -ItemType Directory -Path $OutDir -Force | Out-Null
    }
    $MsiOut = Join-Path $OutDir "PDFPortfolioMaker-Enterprise-1.0.0.msi"

    if (Get-Command candle.exe -ErrorAction SilentlyContinue) {
        $WixObj = Join-Path $ProjectRoot "build\enterprise.wixobj"
        & candle.exe -nologo -arch x64 -out $WixObj $WxsPath
        & light.exe -nologo -out $MsiOut $WixObj
        Write-Host "[OK] Enterprise MSI compiled at: $MsiOut" -ForegroundColor Green
    } elseif (Get-Command wix.exe -ErrorAction SilentlyContinue) {
        & wix.exe build -arch x64 -o $MsiOut $WxsPath
        Write-Host "[OK] Enterprise MSI compiled via WiX v4 at: $MsiOut" -ForegroundColor Green
    } else {
        Write-Host "[INFO] WiX Toolset (candle.exe / wix.exe) not installed. Use packaging\enterprise.wxs on a build agent with WiX, or deploy PDFPortfolioMaker-Setup-1.0.0.exe with /VERYSILENT /LICENSEKEY=..." -ForegroundColor Yellow
    }
}

# 3. Optional Silent Installer Execution
if ($RunSilentInstaller) {
    $SetupExe = Join-Path $ProjectRoot "dist-installer\PDFPortfolioMaker-Setup-1.0.0.exe"
    if (-not (Test-Path $SetupExe)) {
        throw "Installer binary not found at $SetupExe. Run packaging\build_release.ps1 first."
    }
    $ArgsList = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART")
    if (-not [string]::IsNullOrWhiteSpace($ResolvedKey)) {
        $ArgsList += "/LICENSEKEY=`"$ResolvedKey`""
    }
    Start-Process -FilePath $SetupExe -ArgumentList $ArgsList -Wait -NoNewWindow
    Write-Host "[OK] Silent enterprise installation completed." -ForegroundColor Green
}
