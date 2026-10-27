# ====================================================================
# HidaThin — Script di Ottimizzazione Host Windows per RDP ad Alte Prestazioni
# Eseguire come Amministratore sul PC Windows a cui ci si connette.
# ====================================================================

$ErrorActionPreference = "Stop"

# Verifica privilegi di amministratore
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERRORE: Questo script richiede privilegi di Amministratore." -ForegroundColor Red
    Write-Host "Fai clic destro su PowerShell e seleziona 'Esegui come amministratore'." -ForegroundColor Yellow
    exit 1
}

Write-Host "=== HidaThin: Ottimizzazione RDP Host Windows ===" -ForegroundColor Cyan

# 1. Sblocco framerate a 60 FPS
$winstationsPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations"
if (-not (Test-Path $winstationsPath)) {
    New-Item -Path $winstationsPath -Force | Out-Null
}
Set-ItemProperty -Path $winstationsPath -Name "DWMFRAMEINTERVAL" -Value 15 -Type DWord
Write-Host "[OK] Framerate RDP sbloccato a 60 FPS (DWMFRAMEINTERVAL = 15)" -ForegroundColor Green

# 2. Accelerazione Hardware GPU per Desktop Remoto
$tsPolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services"
if (-not (Test-Path $tsPolicyPath)) {
    New-Item -Path $tsPolicyPath -Force | Out-Null
}
Set-ItemProperty -Path $tsPolicyPath -Name "bEnumerateHWUsingImages" -Value 1 -Type DWord
Set-ItemProperty -Path $tsPolicyPath -Name "bUseHardwareGraphicsAdapter" -Value 1 -Type DWord
Set-ItemProperty -Path $tsPolicyPath -Name "SelectTransport" -Value 1 -Type DWord
Write-Host "[OK] Accelerazione hardware GPU per RDP abilitata" -ForegroundColor Green

# 3. Modalità grafica hardware / AVC444
$tsClientPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services\Client"
if (-not (Test-Path $tsClientPath)) {
    New-Item -Path $tsClientPath -Force | Out-Null
}
Set-ItemProperty -Path $tsClientPath -Name "EnableHardwareMode" -Value 1 -Type DWord
Write-Host "[OK] Supporto hardware AVC444 prioritario abilitato" -ForegroundColor Green

Write-Host ""
Write-Host "Ottimizzazione completata con successo!" -ForegroundColor Cyan
Write-Host "NOTA: Riavviare il PC Windows oppure riavviare il servizio 'TermService' per applicare tutte le modifiche." -ForegroundColor Yellow
