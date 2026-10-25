#!/bin/bash
# Wrapper to launch the main root install.sh script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_INSTALL="$SCRIPT_DIR/../install.sh"

if [ -f "$ROOT_INSTALL" ]; then
    exec bash "$ROOT_INSTALL" "$@"
elif [ -f "/opt/thinclient/install.sh" ]; then
    exec bash "/opt/thinclient/install.sh" "$@"
else
    echo "Errore: install.sh non trovato." >&2
    exit 1
fi
