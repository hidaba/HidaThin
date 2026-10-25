#!/bin/bash
# Minimal, low-overhead x11vnc launcher for Raspberry Pi 3 Thin Client
# Desktop Shadowing on physical DISPLAY :0 (Kiosk UI + FreeRDP 3)

CONFIG_DIR="/opt/thinclient/config"
PASS_FILE="$CONFIG_DIR/x11vnc.pass"
SETTINGS_FILE="$CONFIG_DIR/settings.yaml"

echo "[x11vnc-start] Initializing VNC remote assistance service on DISPLAY :0..."

# 1. Wait for Xorg server on :0 to be ready and accepting connections
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

# 2. Ensure VNC password file exists (default password: thinclient)
mkdir -p "$CONFIG_DIR"
if [ ! -f "$PASS_FILE" ]; then
    echo "[x11vnc-start] No password file found. Creating default VNC password ('thinclient')..."
    if command -v x11vnc >/dev/null 2>&1; then
        x11vnc -storepasswd "thinclient" "$PASS_FILE" 2>/dev/null || true
        chmod 600 "$PASS_FILE" 2>/dev/null || true
    fi
fi

# 3. Base performance arguments for Raspberry Pi 3:
# -forever: keep listening across disconnects
# -shared: allows reconnection without killing current session
# -repeat: smooth keyboard repeat handling
# -noxdamage: avoids driver conflicts with Glamor / VC4 2D acceleration
# -wait 50 -defer 40: throttles polling & batches frame updates to keep CPU <10%
ARGS=(
    -display :0
    -forever
    -shared
    -rfbport 5900
    -repeat
    -noxdamage
    -wait 50
    -defer 40
)

# Detect Xauthority file if present (root kiosk without display manager runs directly on :0)
if [ -f "/root/.Xauthority" ]; then
    ARGS+=(-auth "/root/.Xauthority")
elif [ -n "$XAUTHORITY" ] && [ -f "$XAUTHORITY" ]; then
    ARGS+=(-auth "$XAUTHORITY")
fi

if [ -f "$PASS_FILE" ]; then
    ARGS+=(-rfbauth "$PASS_FILE")
fi

# 4. Check Tailscale-only binding preference
BIND_TS="true"
if [ -f "$SETTINGS_FILE" ]; then
    VAL=$(grep -E '^\s*bind_tailscale_only:\s*' "$SETTINGS_FILE" 2>/dev/null | awk '{print $2}' | tr -d ' "\r\n')
    if [ -n "$VAL" ]; then
        BIND_TS="$VAL"
    fi
fi

if [ "$BIND_TS" = "true" ] || [ "$BIND_TS" = "True" ]; then
    echo "[x11vnc-start] Tailscale-only mode enabled. Resolving Tailscale IPv4..."
    TS_IP=""
    for i in $(seq 1 15); do
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
    elif ip link show tailscale0 >/dev/null 2>&1; then
        echo "[x11vnc-start] Tailscale IP not yet available, falling back to interface tailscale0"
        ARGS+=(-interface tailscale0)
    else
        echo "[x11vnc-start] Warning: Tailscale not available or interface missing. Binding to 0.0.0.0 fallback."
    fi
else
    echo "[x11vnc-start] Binding to all network interfaces (0.0.0.0:5900)"
fi

echo "[x11vnc-start] Executing x11vnc with parameters: ${ARGS[*]}"
exec /usr/bin/x11vnc "${ARGS[@]}"
