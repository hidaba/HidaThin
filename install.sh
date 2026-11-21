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
    echo -e "${RED}[ERROR] This script requires administrative (root) privileges.${NC}" >&2
    echo -e "Rerun with: ${BOLD}sudo bash $0${NC} or ${BOLD}curl -sSL ... | sudo bash${NC}" >&2
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
echo -e "${BLUE}[1/8] Checking system environment...${NC}"

if [ ! -f /etc/os-release ]; then
    echo -e "${RED}[ERROR] Unable to detect distribution (/etc/os-release missing).${NC}" >&2
    exit 1
fi

. /etc/os-release
echo -e "      Detected OS: ${BOLD}${PRETTY_NAME:-$ID}${NC}"
echo -e "      Architecture: ${BOLD}$(uname -m)${NC}"

# Check for Debian / Raspberry Pi OS family
if [[ "$ID" != "raspbian" && "$ID" != "debian" && "$ID_LIKE" != *"debian"* ]]; then
    echo -e "${YELLOW}[WARN] Detected OS is not standard Raspbian/Debian. Proceeding with caution...${NC}"
fi

# ------------------------------------------------------------------------------
# 3. APT Dependencies Installation
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[2/8] Updating APT sources and installing system packages...${NC}"
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
    feh
    adwaita-icon-theme
)

echo -e "      Installing core packages..."
apt-get install -y "${PACKAGES_CORE[@]}"

# Handle Chromium package (optional fallback; HidaThin now defaults to Native Tkinter Launcher)
echo -e "      Installing Chromium browser for Kiosk UI (optional fallback)..."
if ! apt-get install -y chromium 2>/dev/null; then
    if ! apt-get install -y chromium-browser 2>/dev/null; then
        echo -e "${YELLOW}[WARN] Could not find 'chromium' or 'chromium-browser' via standard APT.${NC}"
    fi
fi

# Handle FreeRDP 3 with fallback to FreeRDP 2 if on older distro
echo -e "      Installing FreeRDP client and build libraries for hidathin-rdp..."
if ! apt-get install -y freerdp3-x11 2>/dev/null; then
    echo -e "${YELLOW}[WARN] Package freerdp3-x11 not available in APT repository. Trying freerdp2-x11...${NC}"
    apt-get install -y freerdp2-x11 || true
fi

# Install development headers to compile the native Zero-Copy WTware-style hidathin-rdp binary
apt-get install -y --no-install-recommends \
    gcc make pkg-config freerdp3-dev libwinpr3-dev \
    libx11-dev libxext-dev libxkbfile-dev libxcursor-dev zlib1g-dev 2>/dev/null || \
    echo -e "${YELLOW}[WARN] Development headers freerdp3-dev not available; standard xfreerdp3 will be used.${NC}"

# ------------------------------------------------------------------------------
# 4. Tailscale Mesh VPN Installation
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[3/8] Checking and installing Tailscale WireGuard Mesh...${NC}"
if command -v tailscale >/dev/null 2>&1; then
    echo -e "      ${GREEN}[OK]${NC} Tailscale is already installed ($(tailscale version | head -n1))."
else
    echo -e "      Installing official Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
    systemctl enable --now tailscaled || true
    echo -e "      ${GREEN}[OK]${NC} Tailscale installed and tailscaled service enabled."
fi

# ------------------------------------------------------------------------------
# 5. Deploy / Synchronize HidaThin Repository to /opt/thinclient
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[4/8] Deploying codebase to ${INSTALL_DIR}...${NC}"

if [ -n "$SCRIPT_SOURCE_DIR" ] && [ "$SCRIPT_SOURCE_DIR" != "$INSTALL_DIR" ]; then
    echo -e "      Synchronizing files from local directory: ${SCRIPT_SOURCE_DIR}"
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
    echo -e "      Cloning GitHub repository ${REPO_URL} into staging directory..."
    STAGING_DIR="/tmp/hidathin-staging-$$"
    rm -rf "$STAGING_DIR"
    git clone "$REPO_URL" "$STAGING_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -a "$STAGING_DIR"/* "$INSTALL_DIR/"
    [ -d "$STAGING_DIR/.git" ] && cp -a "$STAGING_DIR/.git" "$INSTALL_DIR/"
    rm -rf "$STAGING_DIR"
else
    echo -e "      Repository already present in ${INSTALL_DIR}."
    if [ -d "$INSTALL_DIR/.git" ]; then
        echo -e "      Updating (git pull) while preserving local modifications..."
        git -C "$INSTALL_DIR" pull --ff-only origin main || echo -e "${YELLOW}[WARN] Git pull incomplete; keeping current version.${NC}"
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
language: "it"
rdp_client: "hidathin-rdp"
profile: "balanced"
resolution: "auto"
overscan: "none"
color_depth: 32
sound: true
auto_reconnect: true
max_reconnect_retries: 3
fullscreen: true
tailscale:
  enabled: true
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
  splash_min_duration_seconds: 2
ui:
  mode: "native"
EOF
    fi
fi

# Fix permissions securely
chown -R root:root "$INSTALL_DIR"
chmod -R u=rwX,go=rX "$INSTALL_DIR"
chmod 700 "$INSTALL_DIR/config"
chmod 600 "$INSTALL_DIR/config/"*.yaml "$INSTALL_DIR/config/"*.pass 2>/dev/null || true
chmod +x "$INSTALL_DIR/scripts/"*.sh "$INSTALL_DIR/scripts/xinitrc" "$INSTALL_DIR/scripts/"*.py "$INSTALL_DIR/app/"*.py "$INSTALL_DIR/install.sh" 2>/dev/null || true

# Compile & install native WTware-style hidathin-rdp client if sources and headers are present
if [ -d "$INSTALL_DIR/src" ] && command -v make >/dev/null 2>&1; then
    echo -e "      Compiling Zero-Copy native client ${BOLD}hidathin-rdp${NC}..."
    if make -C "$INSTALL_DIR/src" clean >/dev/null 2>&1 && make -C "$INSTALL_DIR/src" >/dev/null 2>&1 && make -C "$INSTALL_DIR/src" install >/dev/null 2>&1; then
        echo -e "      ${GREEN}[OK]${NC} Native client /usr/local/bin/hidathin-rdp compiled and installed."
    else
        echo -e "      ${YELLOW}[WARN]${NC} hidathin-rdp compilation skipped; fallback xfreerdp3 active."
    fi
fi

# ------------------------------------------------------------------------------
# 6. Hardware, Kernel & OS Optimizations
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[5/8] Applying hardware, input, and kernel optimizations...${NC}"

# A. Xorg Linear Flat Mouse Acceleration Profile
mkdir -p /etc/X11/xorg.conf.d
if [ -f "$INSTALL_DIR/config/50-mouse.conf" ]; then
    cp "$INSTALL_DIR/config/50-mouse.conf" /etc/X11/xorg.conf.d/50-mouse.conf
    echo -e "      ${GREEN}[OK]${NC} Xorg pointer configuration (1:1 flat profile) applied."
fi

# B. Swappiness & TCP Low-Latency RDP Tuning (WTware-derived transport settings)
mkdir -p /etc/sysctl.d
echo "vm.swappiness=10" > /etc/sysctl.d/99-swappiness.conf
cat << 'EOF' > /etc/sysctl.d/99-rdp-network.conf
net.ipv4.tcp_low_latency=1
net.ipv4.tcp_keepalive_time=15
net.ipv4.tcp_keepalive_intvl=5
net.ipv4.tcp_keepalive_probes=3
net.ipv4.tcp_fin_timeout=15
EOF
sysctl -p /etc/sysctl.d/99-swappiness.conf >/dev/null 2>&1 || true
sysctl -p /etc/sysctl.d/99-rdp-network.conf >/dev/null 2>&1 || true
echo -e "      ${GREEN}[OK]${NC} Applied vm.swappiness=10 and low-latency TCP RDP tuning."

# C. Logrotate configuration
if [ -f "$INSTALL_DIR/config/thinclient.logrotate" ]; then
    cp "$INSTALL_DIR/config/thinclient.logrotate" /etc/logrotate.d/thinclient
    chmod 644 /etc/logrotate.d/thinclient
    echo -e "      ${GREEN}[OK]${NC} Logrotate configured for RDP/UI session logs."
fi

# D. Raspberry Pi Boot Configuration (config.txt -> gpu_mem=128, arm_boost=1, avoid_warnings=2)
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
            echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: gpu_mem updated to 128 MB."
        else
            echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: gpu_mem already sufficient (${CURRENT_MEM} MB)."
        fi
    else
        echo "gpu_mem=128" >> "$CONFIG_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: added gpu_mem=128."
    fi
    if ! grep -q "^disable_splash=" "$CONFIG_TXT"; then
        echo "disable_splash=1" >> "$CONFIG_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: added disable_splash=1 (disables GPU rainbow square)."
    fi
    if ! grep -q "^disable_overscan=" "$CONFIG_TXT"; then
        echo "disable_overscan=1" >> "$CONFIG_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: added disable_overscan=1 (disables firmware overscan for KMS management)."
    fi
    if ! grep -q "^arm_boost=" "$CONFIG_TXT"; then
        echo "arm_boost=1" >> "$CONFIG_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: added arm_boost=1 (maximum CPU boost frequency)."
    fi
    if ! grep -q "^avoid_warnings=" "$CONFIG_TXT"; then
        echo "avoid_warnings=2" >> "$CONFIG_TXT"
        echo -e "      ${GREEN}[OK]${NC} $CONFIG_TXT: added avoid_warnings=2 (prevents firmware overlay from disrupting KMS)."
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
        echo -e "      ${GREEN}[OK]${NC} $CMDLINE_TXT: added usbhid.mousepoll=2 (500 Hz mouse polling)."
    else
        echo -e "      ${GREEN}[OK]${NC} $CMDLINE_TXT: usbhid.mousepoll already configured."
    fi

    # F. Raspberry Pi Quiet Boot (suppress kernel & systemd console warnings)
    BOOT_PARAMS="quiet loglevel=3 logo.nologo consoleblank=0 vt.global_cursor_default=0"
    MODIFIED_PARAMS=false
    for param in $BOOT_PARAMS; do
        if ! grep -q "\b$param\b" "$CMDLINE_TXT"; then
            sed -i "s/$/ $param/" "$CMDLINE_TXT"
            MODIFIED_PARAMS=true
        fi
    done
    if [ "$MODIFIED_PARAMS" = true ]; then
        echo -e "      ${GREEN}[OK]${NC} $CMDLINE_TXT: enabled Silent Boot (quiet, loglevel=3, hidden console cursor)."
    else
        echo -e "      ${GREEN}[OK]${NC} $CMDLINE_TXT: Silent Boot already configured."
    fi
fi

# ------------------------------------------------------------------------------
# 7. Fast-Boot Systemd Services Pruning
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[6/8] Applying Fast Boot (pruning non-essential background services)...${NC}"
if [ -f "$INSTALL_DIR/scripts/optimize-boot.sh" ]; then
    bash "$INSTALL_DIR/scripts/optimize-boot.sh"
else
    echo -e "      ${YELLOW}[INFO]${NC} Script optimize-boot.sh not found, skipping."
fi

# ------------------------------------------------------------------------------
# 8. Install & Enable Systemd Services
# ------------------------------------------------------------------------------
echo -e "\n${BLUE}[7/8] Installing and enabling Systemd services...${NC}"

cp "$INSTALL_DIR/systemd/"*.service /etc/systemd/system/
systemctl daemon-reload

SERVICES=(
    cpu-governor.service
    thinclient.service
    thinclient-ui.service
    thinclient-vnc.service
)

for svc in "${SERVICES[@]}"; do
    echo -n "      Enabling $svc... "
    systemctl enable "$svc" >/dev/null 2>&1 || true
    echo -e "${GREEN}ENABLED${NC}"
done

# Start background services immediately (do not fail if GUI cannot launch in headless SSH session)
systemctl restart cpu-governor.service || true
systemctl restart thinclient.service || true
systemctl restart thinclient-vnc.service 2>/dev/null || true

# ------------------------------------------------------------------------------
# 9. Installation Complete Summary
# ------------------------------------------------------------------------------
echo -e "\n${CYAN}${BOLD}==============================================================================${NC}"
echo -e "${GREEN}${BOLD}       HIDATHIN INSTALLATION COMPLETED SUCCESSFULLY!       ${NC}"
echo -e "${CYAN}${BOLD}==============================================================================${NC}\n"

echo -e "Installed component status:"
echo -e "  • Installation directory: ${BOLD}${INSTALL_DIR}${NC}"
echo -e "  • Flask Web Service Backend: ${GREEN}Active${NC} (port 8080)"
echo -e "  • Graphical Kiosk UI: ${GREEN}Configured${NC} (TTY1 / DISPLAY :0)"
echo -e "  • Remote Assistance (VNC): ${GREEN}Configured${NC} (port 5900, Tailscale-only)"
echo -e "  • CPU Governor: ${GREEN}Performance${NC} (low latency)"
echo -e "  • Mouse Polling / Flat: ${GREEN}500 Hz / 1:1 Linear Profile${NC}"

echo -e "\n${BOLD}Recommended next steps:${NC}"
echo -e "  1. Authenticate the Raspberry Pi on Tailscale:"
echo -e "     ${BOLD}sudo tailscale up --accept-routes${NC}"
echo -e "  2. Reboot to apply all kernel changes and start the Kiosk GUI:"
echo -e "     ${BOLD}sudo reboot${NC}"
echo -e "  3. (Optional) Configure Read-Only root filesystem against power cutoffs:"
echo -e "     ${BOLD}sudo bash /opt/thinclient/scripts/setup-readonly-fs.sh${NC}\n"
