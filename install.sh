#!/bin/bash
# ==============================================================================
# HidaThin - Automated Installer for Raspberry Pi OS (Raspbian / Debian)
# ==============================================================================
# Single-command installation script for HidaThin RDP Thin Client.
# Can be run locally or piped directly from curl:
#   curl -sSL https://raw.githubusercontent.com/hidaba/HidaThin/main/install.sh | sudo bash
# ==============================================================================

set -e

# Terminal colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${CYAN}${BOLD}"
echo "  ██╗  ██╗██╗██████╗  █████╗ ████████╗██╗  ██╗██╗███╗   ██╗"
echo "  ██║  ██║██║██╔══██╗██╔══██╗╚══██╔══╝██║  ██║██║████╗  ██║"
echo "  ███████║██║██║  ██║███████║   ██║   ███████║██║██╔██╗ ██║"
echo "  ██╔══██║██║██║  ██║██╔══██║   ██║   ██╔══██║██║██║╚██╗██║"
echo "  ██║  ██║██║██████╔╝██║  ██║   ██║   ██║  ██║██║██║ ╚████║"
echo "  ╚═╝  ╚═╝╚═╝╚═════╝ ╚═╝  ╚═╝   ╚═╝   ╚═╝  ╚═╝╚═╝╚═╝  ╚═══╝"
echo "      High-Performance Raspberry Pi Thin Client for RDP via Tailscale"
echo -e "${NC}\n"

# ------------------------------------------------------------------------------
# 1. Privileges check
# ------------------------------------------------------------------------------
if [ "$(id -u)" -ne 0 ]; then
    echo -e "${RED}[ERROR] Questo script richiede privilegi di amministratore (root).${NC}" >&2
    echo -e "Rilancialo con: ${BOLD}sudo bash $0${NC} o ${BOLD}curl -sSL ... | sudo bash${NC}" >&2
    exit 1
fi

export DEBIAN_FRONTEND=noninteractive
REPO_URL="https://github.com/hidaba/HidaThin.git"
INSTALL_DIR="/opt/thinclient"
SCRIPT_SOURCE_DIR=""

# Check if script is executed from a local clone of the repository
if [ -n "$BASH_SOURCE" ] && [ -f "$BASH_SOURCE" ]; then
    CANDIDATE_DIR="$(cd "$(dirname "$BASH_SOURCE")" && pwd)"
    if [ -f "$CANDIDATE_DIR/app/main.py" ] && [ -d "$CANDIDATE_DIR/systemd" ]; then
        SCRIPT_SOURCE_DIR="$CANDIDATE_DIR"
    elif [ -f "$CANDIDATE_DIR/../app/main.py" ] && [ -d "$CANDIDATE_DIR/../systemd" ]; then
        SCRIPT_SOURCE_DIR="$(cd "$CANDIDATE_DIR/.." && pwd)"
    fi
fi

# ------------------------------------------------------------------------------
# 2. System Architecture & Distribution Verification
# ------------------------------------------------------------------------------
echo -e "${BLUE}[1/8] Verifica dell'ambiente di sistema...${NC}"

if [ ! -f /etc/os-release ]; then
    echo -e "${RED}[ERROR] Impossibile rilevare la distribuzione (/etc/os-release assente).${NC}" >&2
    exit 1
fi

. /etc/os-release
echo -e "      OS Rilevato: ${BOLD}${PRETTY_NAME:-$ID}${NC}"
echo -e "      Architettura: ${BOLD}$(uname -m)${NC}"

# Check for Debian / Raspberry Pi OS family
if [[ "$ID" != "raspbian" && "$ID" != "debian" && "$ID_LIKE" != *"debian"* ]]; then
    echo -e "${YELLOW}[WARN] Il sistema rilevato non è Raspbian/Debian standard. Procedo comunque con cautela...${NC}"
fi

# ------------------------------------------------------------------------------
# 3. APT Dependencies Installation
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[2/8] Aggiornamento sorgenti APT e installazione pacchetti di sistema...${NC}"
apt-get update -y

PACKAGES_CORE=(
    xorg
    xinit
    openbox
    x11-xserver-utils
    xterm
    python3
    python3-pip
    python3-flask
    python3-yaml
    python3-tk
    x11vnc
    network-manager
    curl
    iproute2
    git
    wireless-tools
)

echo -e "      Installazione pacchetti base..."
apt-get install -y "${PACKAGES_CORE[@]}"

# Handle Chromium package naming difference (chromium vs chromium-browser)
echo -e "      Installazione browser Chromium per Kiosk UI..."
if ! apt-get install -y chromium 2>/dev/null; then
    if ! apt-get install -y chromium-browser 2>/dev/null; then
        echo -e "${YELLOW}[WARN] Impossibile trovare 'chromium' o 'chromium-browser' via APT standard.${NC}"
    fi
fi

# Handle FreeRDP 3 with fallback to FreeRDP 2 if on older distro
echo -e "      Installazione client FreeRDP..."
if ! apt-get install -y freerdp3-x11 2>/dev/null; then
    echo -e "${YELLOW}[WARN] Pacchetto freerdp3-x11 non disponibile nel repository APT. Provo freerdp2-x11...${NC}"
    apt-get install -y freerdp2-x11 || true
fi

# ------------------------------------------------------------------------------
# 4. Tailscale Mesh VPN Installation
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[3/8] Controllo e installazione di Tailscale WireGuard Mesh...${NC}"
if command -v tailscale >/dev/null 2>&1; then
    echo -e "      ${GREEN}[OK]${NC} Tailscale è già installato ($(tailscale version | head -n1))."
else
    echo -e "      Installazione ufficiale Tailscale in corso..."
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl enable --now tailscaled || true
    echo -e "      ${GREEN}[OK]${NC} Tailscale installato e servizio tailscaled abilitato."
fi

# ------------------------------------------------------------------------------
# 5. Deploy / Synchronize HidaThin Repository to /opt/thinclient
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[4/8] Distribuzione del codice in ${INSTALL_DIR}...${NC}"

if [ -n "$SCRIPT_SOURCE_DIR" ] && [ "$SCRIPT_SOURCE_DIR" != "$INSTALL_DIR" ]; then
    echo -e "      Sincronizzazione file da directory locale: ${SCRIPT_SOURCE_DIR}"
    mkdir -p "$INSTALL_DIR"
    for item in "$SCRIPT_SOURCE_DIR"/*; do
        base="$(basename "$item")"
        if [ "$base" = "config" ]; then
            mkdir -p "$INSTALL_DIR/config"
            for cfg in "$item"/*; do
                [ -f "$cfg" ] || continue
                cfg_base="$(basename "$cfg")"
                if [ ! -f "$INSTALL_DIR/config/$cfg_base" ]; then
                    cp -a "$cfg" "$INSTALL_DIR/config/$cfg_base"
                fi
            done
        else
            cp -ru "$item" "$INSTALL_DIR/" 2>/dev/null || cp -r "$item" "$INSTALL_DIR/"
        fi
    done
elif [ ! -d "$INSTALL_DIR/.git" ] && [ ! -f "$INSTALL_DIR/app/main.py" ]; then
    echo -e "      Clonazione del repository GitHub ${REPO_URL} in directory di staging..."
    STAGING_DIR="/tmp/hidathin-staging-$$"
    rm -rf "$STAGING_DIR"
    git clone "$REPO_URL" "$STAGING_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -a "$STAGING_DIR"/* "$INSTALL_DIR/"
    [ -d "$STAGING_DIR/.git" ] && cp -a "$STAGING_DIR/.git" "$INSTALL_DIR/"
    rm -rf "$STAGING_DIR"
else
    echo -e "      Repository già presente in ${INSTALL_DIR}."
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo -e "      Aggiornamento (git pull) con salvaguardia delle modifiche locali..."
        git -C "$INSTALL_DIR" pull --ff-only origin main || echo -e "${YELLOW}[WARN] Git pull non completato; mantenuta versione corrente.${NC}"
    fi
fi

mkdir -p "$INSTALL_DIR/config"

# Ensure default configs exist if not present (never overwrite user config)
if [ ! -f "$INSTALL_DIR/config/hosts.yaml" ]; then
    if [ -f "$INSTALL_DIR/config/hosts.yaml.example" ]; then
        cp "$INSTALL_DIR/config/hosts.yaml.example" "$INSTALL_DIR/config/hosts.yaml"
    else
        cat << 'EOF' > "$INSTALL_DIR/config/hosts.yaml"
version: 1
default_host: pc-work

hosts:
  pc-work:
    name: "Workstation Office"
    hostname: "pc-work"
    ip: ""
    port: 3389
EOF
    fi
fi

if [ ! -f "$INSTALL_DIR/config/settings.yaml" ]; then
    if [ -f "$INSTALL_DIR/config/settings.yaml.example" ]; then
        cp "$INSTALL_DIR/config/settings.yaml.example" "$INSTALL_DIR/config/settings.yaml"
    else
        cat << 'EOF' > "$INSTALL_DIR/config/settings.yaml"
version: 1
profile: "balanced"
resolution: "auto"
color_depth: 24
sound: true
auto_reconnect: true
max_reconnect_retries: 3
fullscreen: true
vnc:
  enabled: true
  port: 5900
  bind_tailscale_only: true
web_admin:
  bind: "127.0.0.1"
  port: 8080
  remote_enabled: false
  admin_token: ""
startup:
  mode: "dashboard"
  connect_timeout_seconds: 20
  max_initial_attempts: 1
  fallback_to_dashboard: true
EOF
    fi
fi

# Fix permissions securely
chown -R root:root "$INSTALL_DIR"
chmod -R u=rwX,go=rX "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR/config"
chmod 600 "$INSTALL_DIR/config/"*.yaml "$INSTALL_DIR/config/"*.pass 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/"*.sh "$INSTALL_DIR/scripts/xinitrc" "$INSTALL_DIR/scripts/"*.py "$INSTALL_DIR/install.sh" 2>/dev/null || true

# ------------------------------------------------------------------------------
# 6. Hardware, Kernel & OS Optimizations
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[5/8] Applicazione ottimizzazioni hardware, input e kernel...${NC}"

# A. Xorg Linear Flat Mouse Acceleration Profile
mkdir -p /etc/X11/xorg.conf.d
if [ -f "$INSTALL_DIR/config/50-mouse.conf" ]; then
    cp "$INSTALL_DIR/config/50-mouse.conf" /etc/X11/xorg.conf.d/50-mouse.conf
    echo -e "      ${GREEN}[OK]${NC} Configurazione puntatore Xorg (flat profile 1:1) applicata."
fi

# B. Swappiness Tuning (protect MicroSD)
mkdir -p /etc/sysctl.d
echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf
sysctl -p /etc/sysctl.d/99-swappiness.conf >/dev/null 2>&1 || true
echo -e "      ${GREEN}[OK]${NC} vm.swappiness impostato a 10 (riduzione scritture MicroSD)."

# C. Logrotate configuration
if [ -f "$INSTALL_DIR/config/thinclient.logrotate" ]; then
    cp "$INSTALL_DIR/config/thinclient.logrotate" /etc/logrotate.d/thinclient
    chmod 644 /etc/logrotate.d/thinclient
    echo -e "      ${GREEN}[OK]${NC} Logrotate configurato per i log di sessione RDP/UI."
fi

# D. Raspberry Pi Boot Configuration (config.txt -> gpu_mem=128)
CONFIG_TXT=""
if [ -f /boot/firmware/config.txt ]; then
    CONFIG_TXT="/boot/firmware/config.txt"
elif [ -f /boot/config.txt ]; then
    CONFIG_TXT="/boot/config.txt"
fi

if [ -n "$CONFIG_TXT" ]; then
    if grep -q "^gpu_mem=" "$CONFIG_TXT"; then
        CURRENT_MEM=$(grep "^gpu_mem=" "$CONFIG_TXT" | head -n1 | cut -d'=' -f2)
        if [ "$CURRENT_MEM" -lt 128 ] 2>/dev/null; then
            sed -i 's/^gpu_mem=.*/gpu_mem=128/' "$CONFIG_TXT"
            echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: gpu_mem aggiornato a 128 MB."
        else
            echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: gpu_mem già adeguato (${CURRENT_MEM} MB)."
        fi
    else
        echo "gpu_mem=128" >> "$CONFIG_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: aggiunto gpu_mem=128."
    fi
fi

# E. Raspberry Pi Mouse Polling Rate (500 Hz -> usbhid.mousepoll=2)
CMDLINE_TXT=""
if [ -f /boot/firmware/cmdline.txt ]; then
    CMDLINE_TXT="/boot/firmware/cmdline.txt"
elif [ -f /boot/cmdline.txt ]; then
    CMDLINE_TXT="/boot/cmdline.txt"
fi

if [ -n "$CMDLINE_TXT" ]; then
    if ! grep -q "usbhid.mousepoll=" "$CMDLINE_TXT"; then
        # Must preserve single line in cmdline.txt
        sed -i 's/$/ usbhid.mousepoll=2/' "$CMDLINE_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CMDLINE_TXT: aggiunto usbhid.mousepoll=2 (polling mouse a 500 Hz)."
    else
        echo -e "      ${GREEN}[OK]${NC} $CMDLINE_TXT: usbhid.mousepoll già configurato."
    fi
fi

# ------------------------------------------------------------------------------
# 7. Fast-Boot Systemd Services Pruning
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[6/8] Applicazione Fast Boot (pruning dei servizi di background non essenziali)...${NC}"
if [ -f "$INSTALL_DIR/scripts/optimize-boot.sh" ]; then
    bash "$INSTALL_DIR/scripts/optimize-boot.sh"
else
    echo -e "      ${YELLOW}[INFO]${NC} Script optimize-boot.sh non trovato, saltato."
fi

# ------------------------------------------------------------------------------
# 8. Install & Enable Systemd Services
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[7/8] Installazione e attivazione servizi Systemd...${NC}"

cp "$INSTALL_DIR/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload

SERVICES=(
    cpu-governor.service
    thinclient.service
    thinclient-ui.service
    thinclient-vnc.service
)

for svc in "${SERVICES[@]}"; do
    echo -n "      Abilitazione $svc... "
    systemctl enable "$svc" >/dev/null 2>&1 || true
    echo -e "${GREEN}ABILITATO${NC}"
done

# Start background services immediately (do not fail if GUI cannot launch in headless SSH session)
systemctl restart cpu-governor.service || true
systemctl restart thinclient.service || true
systemctl restart thinclient-vnc.service 2>/dev/null || true

# ------------------------------------------------------------------------------
# 9. Installation Complete Summary
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}       INSTALLAZIONE DI HIDATHIN COMPLETATA CON SUCCESSO!       ${NC}"
echo -e "${CYAN}${BOLD}==============================================================================${NC}\n"

echo -e "Stato componenti installati:"
echo -e "  • Percorso installazione: ${BOLD}${INSTALL_DIR}${NC}"
echo -e "  • Backend Flask Web Service: ${GREEN}Attivo${NC} (porta 8080)"
echo -e "  • Graphical Kiosk UI: ${GREEN}Configurato${NC} (TTY1 / DISPLAY :0)"
echo -e "  • Remote Assistance (VNC): ${GREEN}Configurato${NC} (porta 5900, Tailscale-only)"
echo -e "  • CPU Governor: ${GREEN}Performance${NC} (bassa latenza)"
echo -e "  • Mouse Polling / Flat: ${GREEN}500 Hz / Profilo Lineare 1:1${NC}"

echo -e "\n${BOLD}Prossimi passi consigliati:${NC}"
echo -e "  1. Autentica il Raspberry Pi su Tailscale con:"
echo -e "     ${BOLD}sudo tailscale up --accept-routes${NC}"
echo -e "  2. Riavvia per applicare tutte le modifiche del kernel e avviare la GUI Kiosk:"
echo -e "     ${BOLD}sudo reboot${NC}"
echo -e "  3. (Opzionale) Configura il filesystem in sola lettura contro lo spegnimento brutale:"
echo -e "     ${BOLD}sudo bash /opt/thinclient/scripts/setup-readonly-fs.sh${NC}\n"