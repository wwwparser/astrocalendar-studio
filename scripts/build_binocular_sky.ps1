# Сборка Windows-приложения Binocular Sky.
#
#   .\scripts\build_binocular_sky.ps1
#   .\scripts\build_binocular_sky.ps1 -Clean
#   .\scripts\build_binocular_sky.ps1 -OneFile
#
# Вся логика сборки лежит в build_binocular_sky.py — здесь только запуск,
# чтобы не держать два расходящихся списка зависимостей.

param(
    [switch]$Clean,
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root "..\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$arguments = @(Join-Path $PSScriptRoot "build_binocular_sky.py")
if ($Clean)   { $arguments += "--clean" }
if ($OneFile) { $arguments += "--onefile" }

& $python @arguments
if ($LASTEXITCODE -ne 0) {
    Write-Host "Сборка не удалась (код $LASTEXITCODE)" -ForegroundColor Red
    exit $LASTEXITCODE
}

$exe = Join-Path $root "dist\BinocularSky\BinocularSky.exe"
if (Test-Path $exe) {
    Write-Host "Готово: $exe" -ForegroundColor Green
    Write-Host "Не забудьте положить рядом каталог data\ с эфемеридами."
}
