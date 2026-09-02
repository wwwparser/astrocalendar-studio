<#
    Сборка AstroCalendar Studio под Windows.

    .\scripts\build_windows.ps1
    .\scripts\build_windows.ps1 -OneFile
    .\scripts\build_windows.ps1 -Clean
#>
param(
    [switch]$OneFile,
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$arguments = @("scripts/build_windows.py")
if ($OneFile) { $arguments += "--onefile" }
if ($Clean)   { $arguments += "--clean" }

Write-Host "AstroCalendar Studio: сборка" -ForegroundColor Cyan
python @arguments
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$exe = if ($OneFile) { "dist\AstroCalendarStudio.exe" }
       else { "dist\AstroCalendarStudio\AstroCalendarStudio.exe" }
if (Test-Path $exe) {
    Write-Host "Готово: $exe" -ForegroundColor Green
} else {
    Write-Host "Исполняемый файл не найден: $exe" -ForegroundColor Red
    exit 1
}
