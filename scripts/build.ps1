# Build ALLES: exe (PyInstaller), installer (Inno Setup, if installed) and portable zip.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (python -c "import alles; print(alles.__version__)").Trim()
Write-Host "== ALLES $version =="

python scripts/fetch_sdk.py
if ($LASTEXITCODE -ne 0) { throw "fetch_sdk failed" }
python scripts/make_version_info.py
python -m PyInstaller ALLES.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# portable zip: an 'ALLES-Daten' folder next to the exe switches on portable mode
$portable = "dist\portable"
Remove-Item $portable -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force "$portable\ALLES-Daten" | Out-Null
Copy-Item dist\ALLES.exe, LICENSE $portable
Set-Content "$portable\ALLES-Daten\LIESMICH.txt" -Encoding utf8 -Value @(
  "Dieser Ordner aktiviert den portablen Modus:",
  "Einstellungen und Suchindex werden hier statt in %APPDATA% gespeichert.")
Compress-Archive -Path "$portable\*" -DestinationPath "dist\ALLES-$version-portable.zip" -Force
Remove-Item $portable -Recurse -Force

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
if (-not $iscc) {
  foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                   "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path $p) { $iscc = $p; break }
  }
}
if ($iscc) {
  & $iscc "/DAppVersion=$version" installer\alles.iss
  if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
} else {
  Write-Warning "Inno Setup (iscc) not found - installer skipped"
}
Get-ChildItem dist | Format-Table Name, Length
