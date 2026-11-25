# Baut PanePilot für Windows (v3.0, L-4001 ff.): Programmordner, portables ZIP und Setup (Inno Setup).
#   Aufruf (im Repository-Hauptordner):  pwsh packaging/windows/build.ps1
# Ergebnis in dist\:  PanePilot-<Version>-windows-x64.zip  und  PanePilot-<Version>-windows-x64-setup.exe
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
$version = python -c "import sys; sys.path.insert(0, 'src'); import panepilot; print(panepilot.__version__)"
Write-Host "PanePilot $version"

Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
"BUILD_DATE = `"$(Get-Date -AsUTC -Format yyyy-MM-dd)`"" | Out-File -Encoding ascii src\panepilot\_build.py

# Programmsymbol: SVG → PNG → ICO (mehrere Größen)
python packaging/windows/make_icon.py src/panepilot/icons/panepilot.svg build_icon.png
python -c "from PIL import Image; Image.open('build_icon.png').save('panepilot.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"

python -m PyInstaller --noconfirm --clean --onedir --windowed `
  --name PanePilot --icon panepilot.ico --paths src `
  --add-data "src/panepilot/i18n/*.json;panepilot/i18n" `
  --add-data "src/panepilot/icons;panepilot/icons" `
  --add-data "src/panepilot/help;panepilot/help" `
  --collect-all pyexiv2 --collect-all pillow_heif --collect-all pypdfium2 --collect-all pypdfium2_raw `
  --exclude-module tkinter --exclude-module pytest `
  packaging/launcher.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller fehlgeschlagen" }

# Portables ZIP (Markierung „winzip“: Updates laden das neue ZIP)
"winzip" | Out-File -Encoding ascii -NoNewline dist\PanePilot\PACKAGE
Copy-Item packaging\windows\LIESMICH.txt dist\PanePilot\
$zip = "dist\PanePilot-$version-windows-x64.zip"
Compress-Archive -Path dist\PanePilot -DestinationPath $zip -Force

# Setup (Markierung „winsetup“: Updates laden das neue Setup und starten es)
"winsetup" | Out-File -Encoding ascii -NoNewline dist\PanePilot\PACKAGE
Remove-Item dist\PanePilot\LIESMICH.txt
$iscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
if (-not (Test-Path $iscc)) { $iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source }
if (-not $iscc) { throw "Inno Setup (ISCC.exe) nicht gefunden" }
& $iscc "/DAppVersion=$version" "/DSourceDir=$PWD\dist\PanePilot" "/DIconFile=$PWD\panepilot.ico" `
  "/O$PWD\dist" packaging\windows\panepilot.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup fehlgeschlagen" }
Get-ChildItem dist | Format-Table Name, Length
