# Build the app and its Windows installer.
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File build.ps1
#
# Output:
#   dist\OpenBmsMonitor\OpenBmsMonitor.exe    the app (one folder, fast start)
#   dist\OpenBmsMonitor-Setup-<version>.exe   installer (needs Inno Setup 6:
#                                             winget install JRSoftware.InnoSetup)
$ErrorActionPreference = "Stop"
# Local builds use the project's venv; GitHub Actions sets BUILD_PYTHON=python.
$py = if ($env:BUILD_PYTHON) { $env:BUILD_PYTHON } else { ".\.venv\Scripts\python.exe" }

# pip writes notices to stderr; don't let PowerShell treat that as an error.
$ErrorActionPreference = "Continue"
& $py -m pip install -q -r requirements-dev.txt 2>$null
$ErrorActionPreference = "Stop"
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

$version = & $py -c "import jkbms_widget; print(jkbms_widget.__version__)"
Write-Host "Version $version"

# One-folder build: starts faster than --onefile (no unpacking to %TEMP% on
# every start) and antivirus tools flag it far less often.
& $py tools\make_icon.py assets\icon.ico
& $py -m PyInstaller --noconfirm --clean --onedir --windowed `
    --name OpenBmsMonitor --icon assets\icon.ico `
    jkbms_widget_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc -and $env:CI) {
    throw "Inno Setup 6 not found on the build machine."
} elseif (-not $iscc) {
    Write-Warning "Inno Setup 6 not found - skipping the installer (winget install JRSoftware.InnoSetup)."
} else {
    & $iscc /Q "/DAppVersion=$version" installer\OpenBmsMonitor.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed." }
}

Get-ChildItem dist -File -Filter "OpenBmsMonitor-Setup-*.exe" |
    Select-Object Name, @{n="MB"; e={[math]::Round($_.Length / 1MB, 1)}}
