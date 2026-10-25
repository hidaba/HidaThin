import json
import subprocess
import shutil
import logging
import time
import threading

logger = logging.getLogger("thinclient.tailscale")

_tailscale_lock = threading.Lock()
_tailscale_cache = None
_tailscale_cache_mono = 0.0
TAILSCALE_CACHE_TTL = 15.0

def invalidate_tailscale_cache():
    """Invalidates the in-memory Tailscale status cache."""
    global _tailscale_cache, _tailscale_cache_mono
    with _tailscale_lock:
        _tailscale_cache = None
        _tailscale_cache_mono = 0.0

def get_tailscale_status(force=False):
    """
    Returns a dictionary with Tailscale connection status.
    Uses monotonic time cache to avoid frequent tailscale subprocess execution.
    """
    global _tailscale_cache, _tailscale_cache_mono

    now = time.monotonic()
    with _tailscale_lock:
        if not force and _tailscale_cache is not None and (now - _tailscale_cache_mono) < TAILSCALE_CACHE_TTL:
            return dict(_tailscale_cache)

    if not shutil.which("tailscale"):
        res = {
            "installed": False,
            "connected": False,
            "ip": None,
            "ipv6": None,
            "magic_dns_suffix": None,
            "peers": [],
            "raw_state": "Not installed"
        }
        with _tailscale_lock:
            _tailscale_cache = res
            _tailscale_cache_mono = now
        return res

    try:
        proc = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if proc.returncode != 0:
            err_msg = proc.stderr.strip() or "Stopped"
            res = {
                "installed": True,
                "connected": False,
                "ip": None,
                "ipv6": None,
                "magic_dns_suffix": None,
                "peers": [],
                "raw_state": err_msg
            }
            with _tailscale_lock:
                _tailscale_cache = res
                _tailscale_cache_mono = now
            return res

        data = json.loads(proc.stdout)
        backend_state = data.get("BackendState", "Unknown")
        connected = (backend_state == "Running")

        self_node = data.get("Self", {})
        ips = self_node.get("TailscaleIPs", [])
        ipv4 = ips[0] if len(ips) > 0 else None
        ipv6 = ips[1] if len(ips) > 1 else None
        magic_dns = data.get("MagicDNSSuffix", "")

        peer_list = []
        for peer_id, peer in data.get("Peer", {}).items():
            peer_ips = peer.get("TailscaleIPs", [])
            peer_list.append({
                "hostname": peer.get("HostName"),
                "dns_name": peer.get("DNSName", "").rstrip("."),
                "ip": peer_ips[0] if peer_ips else None,
                "os": peer.get("OS"),
                "online": peer.get("Online", False),
                "active": peer.get("Active", False)
            })

        res = {
            "installed": True,
            "connected": connected,
            "ip": ipv4,
            "ipv6": ipv6,
            "magic_dns_suffix": magic_dns,
            "peers": peer_list,
            "raw_state": backend_state
        }
        with _tailscale_lock:
            _tailscale_cache = res
            _tailscale_cache_mono = now
        return res
    except Exception as e:
        logger.error(f"Error fetching Tailscale status: {e}")
        res = {
            "installed": True,
            "connected": False,
            "ip": None,
            "ipv6": None,
            "magic_dns_suffix": None,
            "peers": [],
            "raw_state": str(e)
        }
        with _tailscale_lock:
            _tailscale_cache = res
            _tailscale_cache_mono = now
        return res

def restart_tailscale():
    """Restarts tailscaled service and invalidates status cache."""
    invalidate_tailscale_cache()
    try:
        proc = subprocess.run(["systemctl", "restart", "tailscaled"], capture_output=True, text=True, timeout=10)
        invalidate_tailscale_cache()
        return proc.returncode == 0, proc.stderr or proc.stdout
    except Exception as e:
        invalidate_tailscale_cache()
        return False, str(e)

def ping_host(host, fallback_ip=None):
    """Pings a Tailscale host using tailscale ping with optional fallback to IP."""
    try:
        proc = subprocess.run(["tailscale", "ping", "-c", "1", host], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return True, proc.stdout.strip()
    except Exception as e:
        logger.warning(f"Tailscale ping to {host} failed: {e}")

    if fallback_ip and fallback_ip != host:
        logger.info(f"Retrying tailscale ping using fallback IP {fallback_ip}")
        try:
            proc = subprocess.run(["tailscale", "ping", "-c", "1", fallback_ip], capture_output=True, text=True, timeout=5)
            if proc.returncode == 0:
                return True, proc.stdout.strip()
            return False, proc.stderr or proc.stdout
        except Exception as e:
            return False, str(e)

    return False, "Host non raggiungibile via Tailscale ping"
