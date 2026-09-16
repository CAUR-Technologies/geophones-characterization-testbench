# =============================================================================
# build.ps1  —  Script de build Geophones Characterization Testbench
#
# Produit dans dist\geophones-characterization-testbench\ :
#   geophones-characterization-testbench.exe   (GUI 64-bit)
#   bridge32.exe             (bridge 32-bit, lance par l'exe principal)
#   bridge\phi_binaries\     (binaires PHI embarques)
#   config.ini               (cree au premier lancement si absent)
#
# Prerequis :
#   1. Python 64-bit dans PATH avec PyInstaller installe
#        pip install pyinstaller
#   2. Python 32-bit (par defaut C:\Python311-32\python.exe) avec PyInstaller
#        C:\Python311-32\python.exe -m pip install pyinstaller
#   3. Tous les packages Python 64-bit installes (requirements.txt)
# =============================================================================

param(
    [string]$Python32 = "C:\Python311-32\python.exe",
    [string]$Python64 = "python"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# -----------------------------------------------------------------------
# Etape 1 : bridge32.exe (32-bit)
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "=== Etape 1/3 : Build bridge32.exe (32-bit) ===" -ForegroundColor Cyan

if (-not (Test-Path $Python32)) {
    Write-Host "ERREUR : Python 32-bit introuvable : $Python32" -ForegroundColor Red
    Write-Host "Modifiez le parametre -Python32 ou installez Python 32-bit."
    exit 1
}

& $Python32 -m PyInstaller bridge32.spec `
    --distpath dist_bridge32 `
    --workpath build_bridge32 `
    --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERREUR : build bridge32.exe echoue." -ForegroundColor Red
    exit 1
}
Write-Host "bridge32.exe construit avec succes." -ForegroundColor Green

# -----------------------------------------------------------------------
# Etape 2 : geophones-characterization-testbench.exe (64-bit)
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "=== Etape 2/3 : Build geophones-characterization-testbench.exe (64-bit) ===" -ForegroundColor Cyan

& $Python64 -m PyInstaller geophones_characterization_testbench.spec `
    --distpath dist `
    --workpath build `
    --noconfirm

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERREUR : build geophones-characterization-testbench.exe echoue." -ForegroundColor Red
    exit 1
}
Write-Host "geophones-characterization-testbench.exe construit avec succes." -ForegroundColor Green

# -----------------------------------------------------------------------
# Etape 3 : Assembler le dossier final
# -----------------------------------------------------------------------
Write-Host ""
Write-Host "=== Etape 3/3 : Assemblage du dossier de distribution ===" -ForegroundColor Cyan

$DistDir = Join-Path $ScriptDir "dist\geophones-characterization-testbench"

# Copier bridge32.exe dans le dossier de l'exe principal
$Bridge32Src = Join-Path $ScriptDir "dist_bridge32\bridge32.exe"
$Bridge32Dst = Join-Path $DistDir "bridge32.exe"
Copy-Item $Bridge32Src $Bridge32Dst -Force
Write-Host "  bridge32.exe -> $Bridge32Dst"

# Nettoyer les dossiers temporaires
Remove-Item -Recurse -Force "build"        -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "build_bridge32" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "dist_bridge32"  -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=== Build termine ! ===" -ForegroundColor Green
Write-Host "Distribution : $DistDir"
Write-Host ""
Write-Host "Contenu :"
Get-ChildItem $DistDir -Name | Sort-Object
Write-Host ""
Write-Host "Pour deployer : copiez le dossier '$DistDir' entier sur la machine cible."
Write-Host "Prerequis machine cible :"
Write-Host "  - NI-DAQmx Runtime  (si accelerometre NI utilise)"
Write-Host "  - Pilote USB TI ADS1285 EVM  (installe tiPHIChar.dll)"
Write-Host "  - Pilotes COM (RS-232 ou USB-Serie) pour Wavetek et APS"
