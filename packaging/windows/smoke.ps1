# Probe nach dem Bau: Setup still installieren, PanePilot kurz starten, wieder deinstallieren.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..\..")
$setup = Get-ChildItem dist\*-windows-x64-setup.exe | Select-Object -First 1
if (-not $setup) { throw "Setup fehlt" }
$p = Start-Process -FilePath $setup.FullName -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-" -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "Setup-Fehler $($p.ExitCode)" }
$exe = Join-Path $env:ProgramFiles "PanePilot\PanePilot.exe"
if (-not (Test-Path $exe)) { throw "PanePilot.exe nicht installiert" }
$marker = Get-Content (Join-Path $env:ProgramFiles "PanePilot\PACKAGE")
if ($marker -ne "winsetup") { throw "PACKAGE-Markierung fehlt ($marker)" }
if (-not (Test-Path (Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\PanePilot.lnk"))) {
  throw "Startmenü-Eintrag fehlt" }
$app = Start-Process -FilePath $exe -PassThru
Start-Sleep -Seconds 15
if ($app.HasExited) { throw "PanePilot ist beim Start abgebrochen (Code $($app.ExitCode))" }
Stop-Process -Id $app.Id -Force
Start-Sleep -Seconds 2
$un = Join-Path $env:ProgramFiles "PanePilot\unins000.exe"
$p = Start-Process -FilePath $un -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART" -Wait -PassThru
Start-Sleep -Seconds 3
if (Test-Path $exe) { throw "Deinstallation hat PanePilot.exe nicht entfernt" }
# portables ZIP: entpacken und starten
$zip = Get-ChildItem dist\*-windows-x64.zip | Select-Object -First 1
Expand-Archive $zip.FullName -DestinationPath "$env:RUNNER_TEMP\pp-zip" -Force
$z = Start-Process -FilePath "$env:RUNNER_TEMP\pp-zip\PanePilot\PanePilot.exe" -PassThru
Start-Sleep -Seconds 12
if ($z.HasExited) { throw "Portable Version ist beim Start abgebrochen (Code $($z.ExitCode))" }
Stop-Process -Id $z.Id -Force
Write-Host "Probe in Ordnung"
