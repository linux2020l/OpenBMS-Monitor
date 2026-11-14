# Build dist\JkBmsWidget.exe (single file, no console window).
# Run from the project folder:
#   powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"

& $py -m pip install -q -r requirements-dev.txt
& $py -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed - not building." }

& $py tools\make_icon.py assets\icon.ico
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
    --name JkBmsWidget --icon assets\icon.ico `
    jkbms_widget_app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

Get-Item dist\JkBmsWidget.exe | Select-Object Name, @{n="MB"; e={[math]::Round($_.Length / 1MB, 1)}}
