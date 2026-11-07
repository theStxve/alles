# Smoke test for the installer (used in CI): silent per-user install, checks, silent uninstall.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$setup = Get-ChildItem dist\ALLES-Setup-*.exe | Select-Object -First 1
if (-not $setup) { throw "no installer in dist\" }
$dir = Join-Path $env:RUNNER_TEMP "ALLES-install-test"
if (-not $env:RUNNER_TEMP) { $dir = Join-Path $env:TEMP "ALLES-install-test" }

Write-Host "Installing $($setup.Name) to $dir"
$p = Start-Process $setup.FullName -Wait -PassThru -ArgumentList @(
  "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CURRENTUSER", "/DIR=`"$dir`"",
  "/TASKS=explorer")
if ($p.ExitCode -ne 0) { throw "setup exit code $($p.ExitCode)" }

if (-not (Test-Path "$dir\ALLES.exe")) { throw "ALLES.exe not installed" }
$cmd = (Get-ItemProperty "HKCU:\Software\Classes\Directory\shell\ALLES\command")."(default)"
if ($cmd -notlike "*ALLES.exe*--folder*") { throw "Explorer integration missing: $cmd" }
$uninst = Get-ChildItem "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall" |
  Where-Object { (Get-ItemProperty $_.PSPath).DisplayName -eq "ALLES" }
if (-not $uninst) { throw "no 'Apps & Features' entry" }
Write-Host "Install OK: $cmd"

$p = Start-Process "$dir\unins000.exe" -Wait -PassThru -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES"
if ($p.ExitCode -ne 0) { throw "uninstall exit code $($p.ExitCode)" }
Start-Sleep -Seconds 2
if (Test-Path "$dir\ALLES.exe") { throw "ALLES.exe still present after uninstall" }
if (Test-Path "HKCU:\Software\Classes\Directory\shell\ALLES") { throw "Explorer key left behind" }
Write-Host "Uninstall OK"
