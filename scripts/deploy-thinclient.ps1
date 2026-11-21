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
    Write-Host "[1/4] Creating temporary update archive..." -ForegroundColor Yellow
    Push-Location $ProjectDir
    tar -czf "$TempArchive" `
        --exclude="__pycache__" `
        --exclude="*.pyc" `
        --exclude=".pytest_cache" `
        --exclude=".git" `
        app scripts src static systemd templates tests install.sh CHANGELOG.md
    Pop-Location

    Write-Host "[2/4] Transferring archive to thin client via SCP..." -ForegroundColor Yellow
    scp -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new "$TempArchive" "${User}@${TargetHost}:/tmp/thinclient-update.tar.gz"

    Write-Host "[3/4] Applying update to /opt/thinclient (RW remount)..." -ForegroundColor Yellow
    $RemoteScript = @'
set -e
mount -o remount,rw /
tar -xzf /tmp/thinclient-update.tar.gz -C /opt/thinclient
rm -f /tmp/thinclient-update.tar.gz
find /opt/thinclient -path /opt/thinclient/config -prune -o -path "*/__pycache__*" -prune -o -type f \( -name "*.sh" -o -name "xinitrc" -o -name "*.py" -o -name "*.service" -o -name "*.html" -o -name "*.yaml" -o -name "*.css" -o -name "*.js" -o -name "Makefile" -o -name "*.c" \) -exec sed -i 's/\r$//' {} + 2>/dev/null || true
chmod +x /opt/thinclient/scripts/* /opt/thinclient/app/*.py 2>/dev/null || true
if [ -d /opt/thinclient/src ] && command -v make >/dev/null 2>&1; then
    echo "Compiling native hidathin-rdp client..."
    make -C /opt/thinclient/src clean && make -C /opt/thinclient/src && make -C /opt/thinclient/src install || echo "[WARN] hidathin-rdp compilation failed, kept fallback xfreerdp3."
fi
sync
echo "Update applied successfully to /opt/thinclient."
'@.Replace("`r`n", "`n")

    $RemoteScript | ssh -o ConnectTimeout=15 "${User}@${TargetHost}" "cat > /tmp/do-update.sh && bash /tmp/do-update.sh && rm -f /tmp/do-update.sh"

    if (-not $NoReboot) {
        Write-Host "[4/4] Rebooting thin client..." -ForegroundColor Green
        try {
            ssh -o ConnectTimeout=5 "${User}@${TargetHost}" "nohup reboot >/dev/null 2>&1 &"
        } catch {
            # Connection drop during reboot is expected
        }
        Write-Host "Thin client rebooted! Read-Only filesystem and new services running." -ForegroundColor Green
    } else {
        Write-Host "[4/4] Reboot skipped (-NoReboot specified). Reboot manually to apply." -ForegroundColor Cyan
    }
}
finally {
    if (Test-Path "$TempArchive") {
        Remove-Item "$TempArchive" -Force -ErrorAction SilentlyContinue
    }
}
