#!/bin/bash
# HidaThin - Aggressive Systemd Services Pruning & Masking Script
# Reduces Raspberry Pi OS boot time by disabling blocking timers and unneeded daemons.

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Error: This script must be run as root (use sudo)." >&2
    exit 1
fi

ACTION="mask"
if [ "$1" == "--undo" ] || [ "$1" == "--unmask" ]; then
    ACTION="unmask"
fi

# List of unneeded background services & timers for a dedicated RDP thin client
SERVICES_TO_PRUNE=(
    # Automatic package updates and man database indexing (heavy I/O on MicroSD)
    "apt-daily.timer"
    "apt-daily.service"
    "apt-daily-upgrade.timer"
    "apt-daily-upgrade.service"
    "man-db.timer"
    "man-db.service"

    # Printing subsystem (RDP redirection handles printing or not needed on thinclient)
    "cups.service"
    "cups-browsed.service"
    "cups.socket"
    "cups.path"

    # mDNS/Zeroconf (Tailscale MagicDNS handles all hostname and peer resolution)
    "avahi-daemon.service"
    "avahi-daemon.socket"

    # Cellular / GSM modems
    "ModemManager.service"

    # Hardware hotkey / media buttons daemon
    "triggerhappy.service"
    "triggerhappy.socket"

    # Splash screen daemons (HidaThin uses immediate X11 kiosk)
    "plymouth.service"
    "plymouth-start.service"
    "plymouth-read-write.service"
    "plymouth-quit.service"
    "plymouth-quit-wait.service"

    # Bluetooth daemons (thin clients typically use wired or 2.4GHz USB wireless dongles)
    "bluetooth.service"
    "hciuart.service"

    # Boot-blocking synchronizations
    "systemd-udev-settle.service"     # Avoid waiting for all hardware events to settle
    "systemd-time-wait-sync.service"  # Do not block graphical startup waiting for NTP sync
)

if [ "$ACTION" == "mask" ]; then
    echo "=========================================================="
    echo "  HidaThin: Masking Non-Essential Systemd Services        "
    echo "=========================================================="
    for unit in "${SERVICES_TO_PRUNE[@]}"; do
        if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
            echo -n "[PRUNING] Stopping and masking $unit... "
            systemctl stop "$unit" >/dev/null 2>&1 || true
            systemctl disable "$unit" >/dev/null 2>&1 || true
            systemctl mask "$unit" >/dev/null 2>&1 || true
            echo "DONE"
        else
            echo "[SKIPPED] $unit (not installed)"
        fi
    done

    echo ""
    echo "Reloading systemd daemon..."
    systemctl daemon-reload
    echo "Systemd service pruning completed! Boot overhead significantly reduced."
    echo "To restore original status at any time, run: sudo bash $0 --undo"
else
    echo "=========================================================="
    echo "  HidaThin: Unmasking Pruned Systemd Services             "
    echo "=========================================================="
    for unit in "${SERVICES_TO_PRUNE[@]}"; do
        if systemctl list-unit-files "$unit" >/dev/null 2>&1; then
            echo -n "[RESTORE] Unmasking $unit... "
            systemctl unmask "$unit" >/dev/null 2>&1 || true
            echo "DONE"
        fi
    done

    echo ""
    echo "Reloading systemd daemon..."
    systemctl daemon-reload
    echo "Services unmasked. You can re-enable required ones with 'systemctl enable'."
fi
