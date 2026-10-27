#!/bin/bash
# ==============================================================================
# HidaThin - Read-Only Root Filesystem & Persistent Data Setup (Soluzione B)
# ==============================================================================
# Locks Debian root (/) and /boot into Read-Only (RO) to completely prevent
# MicroSD corruption from power cuts, while mounting /data in Read-Write (RW)
# for persistent configurations (hosts, settings, Wi-Fi, Tailscale).
#
# Usage:
#   sudo bash scripts/setup-readonly-fs.sh [optional_partition_device]
#   sudo bash scripts/setup-readonly-fs.sh --undo
# ==============================================================================

set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "Errore: Questo script deve essere eseguito come root (usa sudo)." >&2
    exit 1
fi

DATA_DEV="$1"
FSTAB="/etc/fstab"
FSTAB_BAK="/etc/fstab.bak.hidathin"
THINCLIENT_DIR="/opt/thinclient"
[ -d "$THINCLIENT_DIR" ] || THINCLIENT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# ------------------------------------------------------------------------------
# UNDO ROUTINE: Restore Read-Write filesystem
# ------------------------------------------------------------------------------
if [ "$1" == "--undo" ]; then
    echo "=========================================================="
    echo " RIPRISTINO FILESYSTEM IN READ-WRITE (RW)"
    echo "=========================================================="

    # Remount rw first
    mount -o remount,rw / 2>/dev/null || true
    mount -o remount,rw /boot/firmware 2>/dev/null || mount -o remount,rw /boot 2>/dev/null || true

    # Preserve any newer configurations modified on /data before rolling back fstab
    if [ -d "/data/thinclient-config" ] && [ -d "$THINCLIENT_DIR/config" ]; then
        echo "[UNDO] Preservazione configurazioni recenti da /data a $THINCLIENT_DIR/config..."
        cp -a /data/thinclient-config/* "$THINCLIENT_DIR/config/" 2>/dev/null || true
    fi
    if [ -d "/data/tailscale" ] && [ -d "/var/lib/tailscale" ]; then
        cp -a /data/tailscale/* /var/lib/tailscale/ 2>/dev/null || true
    fi
    if [ -d "/data/NetworkManager/system-connections" ] && [ -d "/etc/NetworkManager/system-connections" ]; then
        cp -a /data/NetworkManager/system-connections/* /etc/NetworkManager/system-connections/ 2>/dev/null || true
    fi

    if [ -f "$FSTAB_BAK" ]; then
        cp "$FSTAB_BAK" "$FSTAB"
        echo "[OK] /etc/fstab ripristinato dal backup ($FSTAB_BAK)."
    else
        sed -i 's/defaults,noatime,ro/defaults,noatime/g' "$FSTAB"
        sed -i 's/defaults,ro/defaults/g' "$FSTAB"
        echo "[OK] Opzioni 'ro' rimosse da /etc/fstab."
    fi

    rm -f /etc/profile.d/readonly-helpers.sh
    echo "[OK] Helper e alias rimossi."
    echo ""
    echo "Ripristino completato! Riavvia il Raspberry Pi con: sudo reboot"
    exit 0
fi

echo "=========================================================="
echo " CONFIGURAZIONE FILESYSTEM READ-ONLY + /data PERSISTENTE"
echo "=========================================================="

# 1. Backup /etc/fstab
if [ ! -f "$FSTAB_BAK" ]; then
    cp "$FSTAB" "$FSTAB_BAK"
    echo "[1/8] Creato backup di sicurezza di /etc/fstab in $FSTAB_BAK"
else
    echo "[1/8] Backup /etc/fstab già presente ($FSTAB_BAK)"
fi

# 2. Setup mount point /data and verify block device
mkdir -p /data

if [ -n "$DATA_DEV" ]; then
    if [ ! -b "$DATA_DEV" ]; then
        echo "[ERRORE] Il dispositivo specificato '$DATA_DEV' non è un block device valido." >&2
        exit 1
    fi

    ROOT_DEV="$(findmnt -n -o SOURCE / 2>/dev/null || true)"
    BOOT_DEV="$(findmnt -n -o SOURCE /boot/firmware 2>/dev/null || findmnt -n -o SOURCE /boot 2>/dev/null || true)"
    REAL_DATA="$(readlink -f "$DATA_DEV" 2>/dev/null || echo "$DATA_DEV")"

    if [ -n "$ROOT_DEV" ] && [ "$REAL_DATA" = "$(readlink -f "$ROOT_DEV" 2>/dev/null || echo "$ROOT_DEV")" ]; then
        echo "[ERRORE] Il dispositivo $DATA_DEV corrisponde alla partizione root (/)! Impossibile usarlo per /data." >&2
        exit 1
    fi

    if [ -n "$BOOT_DEV" ] && [ "$REAL_DATA" = "$(readlink -f "$BOOT_DEV" 2>/dev/null || echo "$BOOT_DEV")" ]; then
        echo "[ERRORE] Il dispositivo $DATA_DEV corrisponde alla partizione boot! Impossibile usarlo per /data." >&2
        exit 1
    fi

    echo "[2/8] Controllo filesystem su dispositivo dedicato $DATA_DEV..."
    FSTYPE="$(blkid -s TYPE -o value "$DATA_DEV" 2>/dev/null || true)"
    if [ -z "$FSTYPE" ]; then
        echo "      Nessun filesystem rilevato su $DATA_DEV. Formattazione ext4 (label: HidaData)..."
        mkfs.ext4 -F -L HidaData "$DATA_DEV"
    elif [ "$FSTYPE" != "ext4" ]; then
        echo "      [AVVISO] Filesystem esistente rilevato: $FSTYPE"
    else
        echo "      Filesystem ext4 esistente rilevato: preservazione dati esistenti senza formattazione."
    fi

    DATA_UUID="$(blkid -s UUID -o value "$DATA_DEV" 2>/dev/null || true)"
    if [ -n "$DATA_UUID" ]; then
        if ! grep -q "[[:space:]]/data[[:space:]]" "$FSTAB"; then
            echo "UUID=$DATA_UUID   /data   ext4   defaults,noatime,errors=remount-ro   0   2" >> "$FSTAB"
        fi
    else
        echo "[ERRORE] Impossibile recuperare l'UUID di $DATA_DEV." >&2
        exit 1
    fi

    # Mount and check
    mount /data
    if ! mountpoint -q /data; then
        echo "[ERRORE CRITICO] Impossibile montare /data su $DATA_DEV. Operazione interrotta prima di attivare RO." >&2
        exit 1
    fi

    # Test writability
    if ! (touch /data/.write_test 2>/dev/null && rm -f /data/.write_test 2>/dev/null); then
        echo "[ERRORE CRITICO] Il mount point /data non è scrivibile. Operazione interrotta prima di attivare RO." >&2
        exit 1
    fi
elif grep -q "[[:space:]]/data[[:space:]]" "$FSTAB"; then
    echo "[2/8] Partizione /data già registrata in /etc/fstab."
    mount /data 2>/dev/null || true
    if ! mountpoint -q /data; then
        echo "[ERRORE CRITICO] Il mount point /data presente in fstab non è montabile." >&2
        exit 1
    fi
else
    echo "[ERRORE] Nessun dispositivo specificato per la partizione dati /data." >&2
    echo "         La modalità Root Read-Only (Soluzione B) richiede una partizione indipendente scrivibile" >&2
    echo "         (es. /dev/mmcblk0p3 o dispositivo di archiviazione dedicato) per salvare credenziali e configurazioni." >&2
    echo "         Una cartella ordinaria su / non garantisce persistenza quando la root viene bloccata in RO." >&2
    echo "         Esegui: sudo bash $0 <partizione_dati>" >&2
    exit 1
fi

# 3. Create persistent directories on /data
echo "[3/8] Creazione struttura cartelle persistenti in /data..."
mkdir -p /data/thinclient-config
mkdir -p /data/tailscale
mkdir -p /data/NetworkManager/system-connections
chmod 700 /data/NetworkManager/system-connections
chmod 700 /data/tailscale
chmod 700 /data/thinclient-config

# 4. Migrate configurations preserving permissions
echo "[4/8] Migrazione delle configurazioni attuali in /data..."

# Thinclient config
if [ -d "$THINCLIENT_DIR/config" ]; then
    cp -a "$THINCLIENT_DIR/config/"* /data/thinclient-config/ 2>/dev/null || true
    chmod 600 /data/thinclient-config/*.yaml /data/thinclient-config/*.pass 2>/dev/null || true
fi

# Tailscale state
if [ -d "/var/lib/tailscale" ]; then
    cp -a /var/lib/tailscale/* /data/tailscale/ 2>/dev/null || true
fi

# NetworkManager Wi-Fi profiles
if [ -d "/etc/NetworkManager/system-connections" ]; then
    cp -a /etc/NetworkManager/system-connections/* /data/NetworkManager/system-connections/ 2>/dev/null || true
fi

# 5. Configure persistent mounts in /etc/fstab
echo "[5/8] Configurazione bind-mount persistenti in /etc/fstab..."

add_fstab_entry() {
    local SRC="$1"
    local DST="$2"
    if ! grep -q "[[:space:]]$DST[[:space:]]" "$FSTAB"; then
        echo "$SRC   $DST   none   bind   0   0" >> "$FSTAB"
    fi
}

add_fstab_entry "/data/tailscale" "/var/lib/tailscale"
add_fstab_entry "/data/NetworkManager/system-connections" "/etc/NetworkManager/system-connections"
if [ -d "$THINCLIENT_DIR/config" ]; then
    add_fstab_entry "/data/thinclient-config" "$THINCLIENT_DIR/config"
fi

# 6. Configure tmpfs (RAM) in /etc/fstab
echo "[6/8] Configurazione partizioni RAM volatili (tmpfs)..."

add_tmpfs_entry() {
    local MNT="$1"
    local OPTS="$2"
    if ! grep -q "[[:space:]]$MNT[[:space:]]" "$FSTAB"; then
        echo "tmpfs   $MNT   tmpfs   $OPTS   0   0" >> "$FSTAB"
    fi
}

add_tmpfs_entry "/tmp" "defaults,noatime,nosuid,size=128m"
add_tmpfs_entry "/var/tmp" "defaults,noatime,nosuid,size=64m"
add_tmpfs_entry "/var/log" "defaults,noatime,nosuid,mode=0755,size=64m"
add_tmpfs_entry "/var/spool" "defaults,noatime,nosuid,size=32m"

# 7. Configure systemd journald and services for Read-Only
echo "[7/8] Configurazione systemd-journald e disabilitazione swap su disco..."
mkdir -p /etc/systemd/journald.conf.d/
cat << 'EOF' > /etc/systemd/journald.conf.d/readonly.conf
[Journal]
Storage=volatile
RuntimeMaxUse=32M
EOF

# Disable SD-card swap services and configure in-RAM zram swap
echo "[7b/8] Configurazione swap nativo in RAM (zram) e rimozione swapfile SD..."
if [ -d /etc/rpi ]; then
    cat << 'EOF' > /etc/rpi/swap.conf
[Main]
Mechanism=zram
EOF
fi
rm -f /var/swap
systemctl mask rpi-resize-swap-file.service 2>/dev/null || true
systemctl mask rpi-setup-loop@var-swap.service 2>/dev/null || true
systemctl mask rpi-remove-swap-file@.service 2>/dev/null || true
systemctl mask rpi-remove-swap-file@var-swap.service 2>/dev/null || true
systemctl mask dphys-swapfile.service 2>/dev/null || true

# Symlink random-seed to tmpfs to avoid boot error on RO root
if [ -f /var/lib/systemd/random-seed ]; then
    rm -f /var/lib/systemd/random-seed
    ln -sf /tmp/random-seed /var/lib/systemd/random-seed
fi

# 8. Set root (/) and /boot to RO in /etc/fstab
echo "[8/8] Attivazione flag Read-Only ('ro') su / e /boot in /etc/fstab..."

# Replace root mount options idempotently
if ! grep -E '[[:space:]]/[[:space:]]+ext4[[:space:]]+.*ro' "$FSTAB" >/dev/null 2>&1; then
    sed -i -E 's/([[:space:]]\/[[:space:]]+ext4[[:space:]]+defaults),noatime/\1,noatime,ro/' "$FSTAB"
    sed -i -E 's/([[:space:]]\/[[:space:]]+ext4[[:space:]]+defaults)([^,])/\1,ro\2/' "$FSTAB"
fi

# Replace boot mount options idempotently
if ! grep -E '[[:space:]]/boot(/firmware)?[[:space:]]+vfat[[:space:]]+.*ro' "$FSTAB" >/dev/null 2>&1; then
    sed -i -E 's/([[:space:]]\/boot(\/firmware)?[[:space:]]+vfat[[:space:]]+defaults)/\1,ro/' "$FSTAB"
fi

# 9. Install terminal helpers (ro, rw, fs-status)
cat << 'EOF' > /etc/profile.d/readonly-helpers.sh
# HidaThin Read-Only Quick Maintenance Aliases
alias ro='sync && mount -o remount,ro,bind /opt/thinclient/config 2>/dev/null; mount -o remount,ro,bind /etc/NetworkManager/system-connections 2>/dev/null; mount -o remount,ro,bind /var/lib/tailscale 2>/dev/null; (mount -o remount,ro /boot/firmware 2>/dev/null || mount -o remount,ro /boot 2>/dev/null); sync && mount -o remount,ro / && echo "[OK] Filesystem bloccato in SOLA LETTURA (RO)"'
alias rw='mount -o remount,rw / && (mount -o remount,rw /boot/firmware 2>/dev/null || mount -o remount,rw /boot 2>/dev/null); mount -o remount,rw,bind /opt/thinclient/config 2>/dev/null; mount -o remount,rw,bind /etc/NetworkManager/system-connections 2>/dev/null; mount -o remount,rw,bind /var/lib/tailscale 2>/dev/null; echo "[ATTENZIONE] Filesystem sbloccato in SCRITTURA (RW)"'

fs-status() {
    echo "--- STATO FILESYSTEM HIDATHIN ---"
    grep -E " / |/boot|/data" /proc/mounts | awk '{print $2 " (" $3 ") -> " $4}'
}
EOF
chmod +x /etc/profile.d/readonly-helpers.sh

echo ""
echo "=========================================================="
echo " [SUCCESSO] CONFIGURAZIONE SOLUZIONE B COMPLETATA!"
echo "=========================================================="
echo "Al prossimo riavvio:"
echo " - La scheda SD (Root e Boot) sarà protetta al 100% in Sola Lettura."
echo " - I salvataggi dei PC, Wi-Fi e Tailscale scriveranno su /data in modo persistente."
echo " - Dall'interfaccia web ('Impostazioni') potrai cliccare:"
echo "   'Aggiorna Sistema Operativo (Debian)' per aggiornare in totale sicurezza."
echo ""
echo "Per applicare subito, riavvia il sistema:"
echo "   sudo reboot"
echo "=========================================================="
