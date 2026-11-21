import json
import subprocess
import shutil
import logging
import time
import threading
import re

logger = logging.getLogger("thinclient.tailscale")

_tailscale_lock = threading.Lock()
_tailscale_cache = None
_tailscale_cache_mono = 0.0
TAILSCALE_CACHE_TTL = 15.0


def is_tailscale_enabled():
    """Checks whether Tailscale is enabled in system settings (defaults to True)."""
    try:
        from app.system import get_settings
        settings = get_settings()
        return bool(settings.get("tailscale", {}).get("enabled", True))
    except Exception as e:
        logger.error(f"Error reading tailscale enabled setting: {e}")
        return True


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

    enabled = is_tailscale_enabled()

    if not shutil.which("tailscale"):
        res = {
            "installed": False,
            "enabled": enabled,
            "connected": False,
            "status": "Non installato",
            "raw_state": "Not installed",
            "ip": None,
            "ipv6": None,
            "hostname": None,
            "tailnet": None,
            "magic_dns_suffix": None,
            "auth_url": None,
            "peers": [],
            "error": "Tailscale non trovato nel sistema"
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
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Stopped"
            is_stopped = ("stopped" in err_msg.lower() or "not running" in err_msg.lower() or not enabled)
            status_label = "Disabilitato" if not enabled else ("Disconnesso" if is_stopped else "Errore")
            res = {
                "installed": True,
                "enabled": enabled,
                "connected": False,
                "status": status_label,
                "raw_state": err_msg,
                "ip": None,
                "ipv6": None,
                "hostname": None,
                "tailnet": None,
                "magic_dns_suffix": None,
                "auth_url": None,
                "peers": [],
                "error": None if is_stopped else err_msg
            }
            with _tailscale_lock:
                _tailscale_cache = res
                _tailscale_cache_mono = now
            return res

        data = json.loads(proc.stdout)
        backend_state = data.get("BackendState", "Unknown")
        self_node = data.get("Self", {})
        ips = self_node.get("TailscaleIPs", [])
        ipv4 = ips[0] if len(ips) > 0 else None
        ipv6 = ips[1] if len(ips) > 1 else None
        magic_dns = data.get("MagicDNSSuffix", "")
        hostname = self_node.get("HostName")

        current_tailnet = data.get("CurrentTailnet", {})
        tailnet = None
        if isinstance(current_tailnet, dict) and current_tailnet.get("Name"):
            tailnet = current_tailnet.get("Name")
        elif magic_dns:
            tailnet = magic_dns.replace(".ts.net", "").rstrip(".")

        auth_url = data.get("AuthURL")
        connected = (backend_state == "Running" and enabled)

        if not enabled:
            status_str = "Disabilitato"
        elif backend_state == "Running":
            status_str = "Connesso"
        elif backend_state in ("Starting", "Connecting"):
            status_str = "Connessione in corso"
        elif backend_state == "NeedsLogin":
            status_str = "Autenticazione richiesta"
        elif backend_state in ("Stopped", "NoState"):
            status_str = "Disconnesso"
        else:
            status_str = backend_state

        peer_list = []
        for peer_id, peer in (data.get("Peer") or {}).items():
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
            "enabled": enabled,
            "connected": connected,
            "status": status_str,
            "raw_state": backend_state,
            "ip": ipv4,
            "ipv6": ipv6,
            "hostname": hostname,
            "tailnet": tailnet,
            "magic_dns_suffix": magic_dns,
            "auth_url": auth_url,
            "peers": peer_list,
            "error": None
        }
        with _tailscale_lock:
            _tailscale_cache = res
            _tailscale_cache_mono = now
        return res
    except Exception as e:
        logger.error(f"Error fetching Tailscale status: {e}")
        res = {
            "installed": True,
            "enabled": enabled,
            "connected": False,
            "status": "Errore",
            "raw_state": str(e),
            "ip": None,
            "ipv6": None,
            "hostname": None,
            "tailnet": None,
            "magic_dns_suffix": None,
            "auth_url": None,
            "peers": [],
            "error": str(e)
        }
        with _tailscale_lock:
            _tailscale_cache = res
            _tailscale_cache_mono = now
        return res


def set_tailscale_enabled(enabled: bool):
    """
    Enables or disables Tailscale, persists the choice, and applies connection state.
    Returns (success: bool, message: str).
    """
    from app.system import save_settings
    ok, msg = save_settings({"tailscale": {"enabled": bool(enabled)}})
    if not ok:
        return False, f"Impossibile salvare impostazioni Tailscale: {msg}"

    invalidate_tailscale_cache()
    if enabled:
        ok_conn, msg_conn, _ = connect_tailscale()
        invalidate_tailscale_cache()
        return ok_conn, msg_conn
    else:
        ok_disc, msg_disc = disconnect_tailscale()
        invalidate_tailscale_cache()
        return ok_disc, msg_disc


def connect_tailscale():
    """
    Connects the thin client to Tailscale (tailscale up --reset=false).
    Returns (success: bool, message: str, auth_url: str | None).
    """
    if not shutil.which("tailscale"):
        return False, "Tailscale non trovato nel sistema", None

    if shutil.which("systemctl"):
        try:
            subprocess.run(["systemctl", "start", "tailscaled"], capture_output=True, text=True, timeout=5)
        except Exception as e:
            logger.warning(f"Error starting tailscaled service: {e}")

    try:
        proc = subprocess.run(
            ["tailscale", "up", "--reset=false"],
            capture_output=True,
            text=True,
            timeout=10
        )
        combined_out = f"{proc.stdout}\n{proc.stderr}"
        match = re.search(r"https://login\.tailscale\.com/\S+", combined_out)
        auth_url = match.group(0) if match else None

        invalidate_tailscale_cache()
        status = get_tailscale_status(force=True)
        if not auth_url and status.get("auth_url"):
            auth_url = status["auth_url"]

        if status.get("connected"):
            return True, "Tailscale connesso con successo", None
        elif auth_url or status.get("status") == "Autenticazione richiesta":
            return True, "Autenticazione richiesta per completare la connessione", auth_url
        elif proc.returncode == 0:
            return True, "Connessione avviata", auth_url
        else:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Errore durante connessione Tailscale"
            return False, err_msg, auth_url
    except Exception as e:
        invalidate_tailscale_cache()
        logger.error(f"Error connecting Tailscale: {e}")
        return False, str(e), None


def disconnect_tailscale():
    """
    Disconnects the thin client from Tailscale (tailscale down).
    Preserves credentials and configuration for future activation.
    Returns (success: bool, message: str).
    """
    if not shutil.which("tailscale"):
        return False, "Tailscale non trovato nel sistema"

    try:
        proc = subprocess.run(
            ["tailscale", "down"],
            capture_output=True,
            text=True,
            timeout=8
        )
        invalidate_tailscale_cache()
        if proc.returncode == 0:
            return True, "Tailscale disconnesso"
        else:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Errore durante disconnessione Tailscale"
            return False, err_msg
    except Exception as e:
        invalidate_tailscale_cache()
        logger.error(f"Error disconnecting Tailscale: {e}")
        return False, str(e)


def login_tailscale():
    """
    Initiates the Tailscale login flow to pair the device with a Tailnet.
    Returns (success: bool, message: str, auth_url: str | None).
    """
    if not shutil.which("tailscale"):
        return False, "Tailscale non trovato nel sistema", None

    try:
        proc = subprocess.run(
            ["tailscale", "login"],
            capture_output=True,
            text=True,
            timeout=10
        )
        combined_out = f"{proc.stdout}\n{proc.stderr}"
        match = re.search(r"https://login\.tailscale\.com/\S+", combined_out)
        auth_url = match.group(0) if match else None

        invalidate_tailscale_cache()
        status = get_tailscale_status(force=True)
        if not auth_url and status.get("auth_url"):
            auth_url = status["auth_url"]

        if auth_url:
            return True, "Flusso autenticazione avviato", auth_url
        elif proc.returncode == 0:
            return True, "Flusso autenticazione avviato", None
        else:
            err_msg = proc.stderr.strip() or proc.stdout.strip() or "Errore durante login"
            return False, err_msg, None
    except Exception as e:
        invalidate_tailscale_cache()
        logger.error(f"Error logging into Tailscale: {e}")
        return False, str(e), None


def apply_boot_tailscale_state():
    """
    Applies the configured Tailscale state on system startup.
    Runs in a background thread so as not to block boot.
    Returns (success: bool, message: str).
    """
    try:
        if not is_tailscale_enabled():
            logger.info("Tailscale is disabled in settings; ensuring connection is down.")
            return disconnect_tailscale()
        else:
            logger.info("Tailscale is enabled in settings; initiating connection.")
            ok, msg, _ = connect_tailscale()
            return ok, msg
    except Exception as e:
        logger.error(f"Error applying boot tailscale state: {e}")
        return False, str(e)


def is_tailscale_ip(ip_str):
    """
    Checks if an IP address belongs to the Tailscale CGNAT subnet (100.64.0.0/10)
    or Tailscale IPv6 prefix (fd7a:115c:a1e0::/48).
    """
    if not ip_str or not isinstance(ip_str, str):
        return False

    ip_str = ip_str.strip()

    # IPv4 CGNAT check (100.64.0.0/10: 100.64.0.0 - 100.127.255.255)
    ipv4_match = re.match(r"^100\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$", ip_str)
    if ipv4_match:
        second_octet = int(ipv4_match.group(1))
        return 64 <= second_octet <= 127

    # IPv6 Tailscale unique local address check
    if ip_str.lower().startswith("fd7a:115c:a1e0:"):
        return True

    return False


def is_tailscale_target(host_entry):
    """
    Checks if a host configuration requires Tailscale connectivity to be reached.
    Inspects IP address, MagicDNS suffixes, and known Tailnet peers.
    """
    if not host_entry:
        return False

    ip = None
    hostname = None

    if isinstance(host_entry, dict):
        ip = host_entry.get("ip")
        hostname = host_entry.get("hostname") or host_entry.get("host") or host_entry.get("name")
    elif isinstance(host_entry, str):
        target = host_entry.strip()
        if is_tailscale_ip(target):
            ip = target
        else:
            hostname = target

    if ip and is_tailscale_ip(ip):
        return True

    if hostname and isinstance(hostname, str):
        h = hostname.strip().rstrip(".").lower()
        if h.endswith(".ts.net"):
            return True

        try:
            status = get_tailscale_status(force=False)
            magic_dns = status.get("magic_dns_suffix")
            if magic_dns and h.endswith(magic_dns.lower().strip(".")):
                return True
            for peer in status.get("peers", []):
                p_host = (peer.get("hostname") or "").strip().rstrip(".").lower()
                p_dns = (peer.get("dns_name") or "").strip().rstrip(".").lower()
                if h == p_host or h == p_dns:
                    return True
        except Exception:
            pass

    return False


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
