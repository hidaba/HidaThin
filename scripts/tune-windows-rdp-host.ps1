# ====================================================================
# HidaThin — Windows Host Optimization Script for High-Performance RDP
# Run as Administrator on the target Windows PC you connect to.
# ====================================================================

$ErrorActionPreference = "Stop"

# Administrator privileges check
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "ERROR: This script requires Administrator privileges." -ForegroundColor Red
    Write-Host "Right-click on PowerShell and select 'Run as Administrator'." -ForegroundColor Yellow
    exit 1
}

Write-Host "=== HidaThin: Windows Host RDP Optimization ===" -ForegroundColor Cyan

# 1. Unlock framerate to 60 FPS
$winstationsPath = "HKLM:\SYSTEM\CurrentControlSet\Control\Terminal Server\WinStations"
if (-not (Test-Path $winstationsPath)) {
    New-Item -Path $winstationsPath -Force | Out-Null
}
Set-ItemProperty -Path $winstationsPath -Name "DWMFRAMEINTERVAL" -Value 15 -Type DWord
Write-Host "[OK] RDP framerate unlocked to 60 FPS (DWMFRAMEINTERVAL = 15)" -ForegroundColor Green

# 2. GPU Hardware Acceleration for Remote Desktop
$tsPolicyPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services"
if (-not (Test-Path $tsPolicyPath)) {
    New-Item -Path $tsPolicyPath -Force | Out-Null
}
Set-ItemProperty -Path $tsPolicyPath -Name "bEnumerateHWUsingImages" -Value 1 -Type DWord
Set-ItemProperty -Path $tsPolicyPath -Name "bUseHardwareGraphicsAdapter" -Value 1 -Type DWord
Set-ItemProperty -Path $tsPolicyPath -Name "SelectTransport" -Value 1 -Type DWord
Write-Host "[OK] GPU hardware acceleration for RDP enabled" -ForegroundColor Green

# 3. Hardware graphics mode / AVC444
$tsClientPath = "HKLM:\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services\Client"
if (-not (Test-Path $tsClientPath)) {
    New-Item -Path $tsClientPath -Force | Out-Null
}
Set-ItemProperty -Path $tsClientPath -Name "EnableHardwareMode" -Value 1 -Type DWord
Write-Host "[OK] AVC444 prioritized hardware support enabled" -ForegroundColor Green

Write-Host ""
Write-Host "Optimization completed successfully!" -ForegroundColor Cyan
Write-Host "NOTE: Reboot the Windows PC or restart the 'TermService' service to apply all changes." -ForegroundColor Yellow
