#!/usr/bin/env python3
"""
HidaThin Direct-to-RDP Coordinator
Attempts direct connection to the default RDP host without starting Chromium first.
If the connection is cancelled, times out, or fails, falls back gracefully to dashboard.
"""

import sys
import os
import time
import json
import socket
import logging
import urllib.request
import urllib.error

# Ensure root package directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.system import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [direct-rdp] %(message)s")
logger = logging.getLogger("direct-rdp")

BACKEND_URL = "http://127.0.0.1:8080"

def check_backend_ready(timeout_sec=15):
    """Waits until /healthz responds with 200 OK."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_sec:
        try:
            req = urllib.request.Request(f"{BACKEND_URL}/healthz")
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def get_boot_status():
    """Queries /api/boot/status."""
    try:
        req = urllib.request.Request(f"{BACKEND_URL}/api/boot/status?force=0")
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Error fetching boot status: {e}")
        return {}

def wait_for_connectivity(timeout_sec=20):
    """Waits for network and Tailscale connection within overall timeout."""
    start = time.monotonic()
    while time.monotonic() - start < timeout_sec:
        status = get_boot_status()
        wf = status.get("network", {}).get("wifi", {})
        eth = status.get("network", {}).get("ethernet", {})
        net_ok = wf.get("connected") or eth.get("connected")
        ts_ok = status.get("tailscale", {}).get("connected", False)

        if net_ok and ts_ok:
            return True, status

        time.sleep(1.0)
    return False, get_boot_status()

def trigger_rdp_connect(default_host_key):
    """Triggers RDP connection via backend API."""
    try:
        payload = json.dumps({"host_key": default_host_key}).encode("utf-8")
        req = urllib.request.Request(
            f"{BACKEND_URL}/api/rdp/connect",
            data=payload,
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to trigger RDP connect: {e}")
        return {"success": False, "message": str(e)}

def wait_rdp_session_end():
    """Monitors session until it exits."""
    time.sleep(2.0)
    while True:
        try:
            req = urllib.request.Request(f"{BACKEND_URL}/api/rdp/status")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("state") in ("IDLE", "ERROR"):
                    logger.info("RDP session ended.")
                    break
        except Exception:
            pass
        time.sleep(1.5)

def main():
    logger.info("Starting Direct-to-RDP coordinator...")
    settings = get_settings()
    startup_cfg = settings.get("startup", {})
    mode = startup_cfg.get("mode", "dashboard")

    if mode != "direct_rdp":
        logger.info(f"Startup mode is '{mode}' (not direct_rdp). Exiting coordinator.")
        return 0

    timeout = int(startup_cfg.get("connect_timeout_seconds", 20))

    if not check_backend_ready(timeout_sec=15):
        logger.error("Backend healthz timeout. Falling back to dashboard.")
        return 1

    logger.info(f"Waiting up to {timeout}s for network and Tailscale connectivity...")
    ready, status = wait_for_connectivity(timeout_sec=timeout)

    default_host_info = status.get("default_host", {})
    default_key = default_host_info.get("key")

    if not default_key:
        logger.warning("No default host configured. Falling back to dashboard.")
        return 1

    if not ready:
        logger.warning(f"Connectivity timeout after {timeout}s. Falling back to dashboard.")
        return 1

    logger.info(f"Connecting directly to default host: {default_key} ({default_host_info.get('name')})")
    res = trigger_rdp_connect(default_key)

    if not res.get("success"):
        logger.warning(f"RDP connection initiation failed: {res.get('message')}. Falling back to dashboard.")
        return 1

    logger.info("RDP connection launched successfully. Monitoring session lifecycle...")
    wait_rdp_session_end()
    logger.info("Direct RDP session terminated. Handing over to dashboard.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
