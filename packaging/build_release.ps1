# =====================================================================
# PDF Portfolio Maker - Production Build & Packaging Script
# =====================================================================
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $ProjectRoot

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "   PDF Portfolio Maker - Release Packaging Pipeline       " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

# 1. Clean previous build artifacts
Write-Host "`n>>> [1/4] Cleaning previous build directories..." -ForegroundColor Yellow
Remove-Item -Recurse -Force build, dist, dist-installer -ErrorAction SilentlyContinue

# 2. PyInstaller Packaging
Write-Host "`n>>> [2/4] Executing PyInstaller (--onedir spec)..." -ForegroundColor Yellow
$VenvPyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
if (Test-Path $VenvPyInstaller) {
    & $VenvPyInstaller --clean --noconfirm packaging/pdf_portfolio_maker.spec
} elseif (Get-Command uv -ErrorAction SilentlyContinue) {
    uv run --python 3.11 --with pyinstaller --with PySide6-Essentials --with pypdf --with cryptography `
        pyinstaller --clean --noconfirm packaging/pdf_portfolio_maker.spec
} else {
    pyinstaller --clean --noconfirm packaging/pdf_portfolio_maker.spec
}

$ExePath = Join-Path $ProjectRoot "dist\PDFPortfolioMaker\PDFPortfolioMaker.exe"
if (-not (Test-Path $ExePath)) {
    Write-Error "PyInstaller build failed: Executable not found at $ExePath"
    exit 1
}

$DistSizeMB = [math]::Round(((Get-ChildItem -Recurse (Join-Path $ProjectRoot "dist\PDFPortfolioMaker") | Measure-Object -Property Length -Sum).Sum / 1MB), 2)
Write-Host ">>> PyInstaller build succeeded! Distribution size: $DistSizeMB MB" -ForegroundColor Green

# 3. Optional Authenticode Code Signing
Write-Host "`n>>> [3/4] Checking Code Signing Environment..." -ForegroundColor Yellow
if ($env:SIGNTOOL_ARGS -and (Get-Command signtool -ErrorAction SilentlyContinue)) {
    Write-Host "SIGNTOOL_ARGS detected. Signing executable..." -ForegroundColor Cyan
    Invoke-Expression "signtool sign $env:SIGNTOOL_ARGS `"$ExePath`""
} else {
    Write-Host "SIGNTOOL_ARGS not set. Skipping binary code signing (Unsigned release build)." -ForegroundColor Gray
}

# 4. Inno Setup Compilation
Write-Host "`n>>> [4/4] Compiling Windows Installer (Inno Setup 7 / 6)..." -ForegroundColor Yellow
$InnoPaths = @(
    "C:\Program Files\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 7\ISCC.exe",
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
)
$Iscc = $InnoPaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Iscc) {
    Write-Host "Inno Setup compiler found at: $Iscc" -ForegroundColor Cyan
    & $Iscc "packaging\installer.iss"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Inno Setup compilation failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
    
    $InstallerExe = Join-Path $ProjectRoot "dist-installer\PDFPortfolioMaker-Setup-1.0.0.exe"
    if ($env:SIGNTOOL_ARGS -and (Get-Command signtool -ErrorAction SilentlyContinue) -and (Test-Path $InstallerExe)) {
        Write-Host "Signing installer executable..." -ForegroundColor Cyan
        Invoke-Expression "signtool sign $env:SIGNTOOL_ARGS `"$InstallerExe`""
    }

    $InstallerOutput = Join-Path $ProjectRoot "dist-installer"
    Write-Host "`n==========================================================" -ForegroundColor Green
    Write-Host "   BUILD SUCCESSFUL! Installer output in:" -ForegroundColor Green
    Write-Host "   $InstallerExe" -ForegroundColor Green
    Write-Host "==========================================================" -ForegroundColor Green
} else {
    Write-Host "Inno Setup 6 (ISCC.exe) not found at standard paths." -ForegroundColor Yellow
    Write-Host "To compile the final .exe installer:" -ForegroundColor White
    Write-Host "  1. Download Inno Setup from https://jrsoftware.org/isdl.php" -ForegroundColor White
    Write-Host "  2. Open packaging\installer.iss in Inno Setup and click 'Compile'." -ForegroundColor White
    Write-Host "`nUncompressed application directory ready at:" -ForegroundColor Cyan
    Write-Host "  $ProjectRoot\dist\PDFPortfolioMaker\" -ForegroundColor Cyan
}
