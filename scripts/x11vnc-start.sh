#!/bin/bash
# Minimal, low-overhead x11vnc launcher for Raspberry Pi 3 Thin Client
# Desktop Shadowing on physical DISPLAY :0 (Kiosk UI + FreeRDP 3)

CONFIG_DIR="/opt/thinclient/config"
PASS_FILE="$CONFIG_DIR/x11vnc.pass"
SETTINGS_FILE="$CONFIG_DIR/settings.yaml"

echo "[x11vnc-start] Initializing VNC remote assistance service on DISPLAY :0..."

# 1. Check if VNC is enabled in settings.yaml
VNC_ENABLED="true"
VNC_PORT="5900"
BIND_TS="true"

if [ -f "$SETTINGS_FILE" ]; then
    VALS=$(python3 -c '
import yaml
try:
    with open("'"$SETTINGS_FILE"'", "r") as f:
        d = yaml.safe_load(f) or {}
        vnc = d.get("vnc", {})
        print(f"{vnc.get(\"enabled\", True)}|{vnc.get(\"port\", 5900)}|{vnc.get(\"bind_tailscale_only\", True)}")
except Exception:
    print("true|5900|true")
' 2>/dev/null || echo "true|5900|true")
    IFS='|' read -r VNC_ENABLED VNC_PORT BIND_TS <<< "$VALS"
fi

if [ "$VNC_ENABLED" = "False" ] || [ "$VNC_ENABLED" = "false" ]; then
    echo "[x11vnc-start] VNC service is disabled in settings.yaml. Exiting cleanly."
    exit 0
fi

# 2. Ensure VNC password file exists (never run unauthenticated or create default password)
if [ ! -f "$PASS_FILE" ]; then
    echo "[x11vnc-start] ERROR: Password file '$PASS_FILE' missing." >&2
    echo "[x11vnc-start] An explicit password must be set before starting VNC. Refusing unauthenticated listener." >&2
    exit 1
fi
chmod 600 "$PASS_FILE" 2>/dev/null || true

# 3. Wait for Xorg server on :0 to be ready and accepting connections
X_READY=0
for i in $(seq 1 30); do
    if [ -e "/tmp/.X11-unix/X0" ] || xset -q -display :0 >/dev/null 2>&1; then
        echo "[x11vnc-start] X11 display :0 is ready (after ${i}s)."
        X_READY=1
        break
    fi
    sleep 1
done

if [ "$X_READY" -eq 0 ]; then
    echo "[x11vnc-start] Warning: DISPLAY :0 probe timed out, attempting start anyway..."
fi

# 4. Base performance arguments for Raspberry Pi 3
ARGS=(
    -display :0
    -forever
    -shared
    -rfbport "${VNC_PORT:-5900}"
    -repeat
    -noxdamage
    -wait 50
    -defer 40
    -rfbauth "$PASS_FILE"
)

# Detect Xauthority file if present (root kiosk without display manager runs directly on :0)
if [ -f "/root/.Xauthority" ]; then
    ARGS+=(-auth "/root/.Xauthority")
elif [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
    ARGS+=(-auth "$XAUTHORITY")
fi

# 5. Tailscale binding logic: strict enforcement
if [ "$BIND_TS" = "true" ] || [ "$BIND_TS" = "True" ]; then
    echo "[x11vnc-start] Tailscale-only mode enabled. Resolving Tailscale IPv4..."
    TS_IP=""
    for i in $(seq 1 10); do
        if command -v tailscale >/dev/null 2>&1; then
            TS_IP=$(tailscale ip -4 2>/dev/null || true)
            if [ -n "$TS_IP" ]; then
                break
            fi
        fi
        sleep 1
    done

    if [ -n "$TS_IP" ]; then
        echo "[x11vnc-start] Binding strictly to Tailscale IP: $TS_IP"
        ARGS+=(-listen "$TS_IP")
    else
        echo "[x11vnc-start] ERROR: Tailscale VPN unavailable and bind_tailscale_only is true." >&2
        echo "[x11vnc-start] Refusing to bind to 0.0.0.0 or LAN to preserve security. Exiting." >&2
        exit 1
    fi
else
    echo "[x11vnc-start] Binding to all network interfaces (0.0.0.0:${VNC_PORT:-5900})"
fi

echo "[x11vnc-start] Executing x11vnc with parameters: ${ARGS[*]}"
exec /usr/bin/x11vnc "${ARGS[@]}"
