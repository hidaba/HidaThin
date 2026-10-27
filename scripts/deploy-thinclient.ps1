param (
    [string]$TargetHost = "100.68.91.18",
    [string]$User = "root",
    [switch]$NoReboot
)

$ErrorActionPreference = "Stop"

Write-Host "=== HidaThin: Deploy & Update Thin Client ===" -ForegroundColor Cyan
Write-Host "Target: ${User}@${TargetHost}" -ForegroundColor DarkGray

$TempArchive = Join-Path $env:TEMP "thinclient-update-$([System.Guid]::NewGuid().ToString('N').Substring(0,8)).tar.gz"
$ProjectDir = (Get-Item $PSScriptRoot).Parent.FullName

try {
    Write-Host "[1/4] Creazione archivio temporaneo di aggiornamento..." -ForegroundColor Yellow
    Push-Location $ProjectDir
    tar -czf "$TempArchive" `
        --exclude="__pycache__" `
        --exclude="*.pyc" `
        --exclude=".pytest_cache" `
        --exclude=".git" `
        app scripts static systemd templates tests
    Pop-Location

    Write-Host "[2/4] Trasferimento archivio su thin client via SCP..." -ForegroundColor Yellow
    scp -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$TempArchive" "${User}@${TargetHost}:/tmp/thinclient-update.tar.gz"

    Write-Host "[3/4] Applicazione aggiornamento su /opt/thinclient (RW remount)..." -ForegroundColor Yellow
    $RemoteCommands = @'
set -e
mount -o remount,rw /
tar -xzf /tmp/thinclient-update.tar.gz -C /opt/thinclient
rm -f /tmp/thinclient-update.tar.gz
chmod +x /opt/thinclient/scripts/* 2>/dev/null || true
sync
echo "Aggiornamento applicato con successo su /opt/thinclient."
'@
    ssh -o ConnectTimeout=10 "${User}@${TargetHost}" "$RemoteCommands"

    if (-not $NoReboot) {
        Write-Host "[4/4] Riavvio del thin client in corso..." -ForegroundColor Green
        try {
            ssh -o ConnectTimeout=5 "${User}@${TargetHost}" "nohup reboot >/dev/null 2>&1 &"
        } catch {
            # Connection drop during reboot is expected
        }
        Write-Host "Thin client riavviato! Filesystem Read-Only e nuovi servizi in esecuzione." -ForegroundColor Green
    } else {
        Write-Host "[4/4] Riavvio saltato (-NoReboot specificato). Riavviare manualmente per applicare." -ForegroundColor Cyan
    }
}
finally {
    if (Test-Path "$TempArchive") {
        Remove-Item "$TempArchive" -Force -ErrorAction SilentlyContinue
    }
}
