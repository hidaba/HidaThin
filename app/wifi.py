import subprocess
import shutil
import logging
import re
import time
import threading

logger = logging.getLogger("thinclient.wifi")

_wifi_lock = threading.Lock()
_network_status_cache = None
_network_status_cache_mono = 0.0
NETWORK_CACHE_TTL = 15.0

def parse_nmcli_terse_line(line):
    r"""
    Parses a colon-delimited line from 'nmcli -t', properly unescaping '\:' and '\\'.
    """
    fields = []
    current = []
    escaped = False
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(char)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields

def invalidate_network_cache():
    """Forces next get_network_status() call to re-query system status."""
    global _network_status_cache, _network_status_cache_mono
    with _wifi_lock:
        _network_status_cache = None
        _network_status_cache_mono = 0.0

def get_network_status(force=False):
    """
    Returns current networking status for Wi-Fi and Ethernet.
    Uses monotonic time cache to prevent excessive nmcli/dbus calls on Raspberry Pi.
    """
    global _network_status_cache, _network_status_cache_mono

    now = time.monotonic()
    with _wifi_lock:
        if not force and _network_status_cache is not None and (now - _network_status_cache_mono) < NETWORK_CACHE_TTL:
            return dict(_network_status_cache)

    status = {
        "wifi": {
            "connected": False,
            "ssid": None,
            "signal": 0,
            "ip": None,
            "gateway": None,
            "interface": "wlan0"
        },
        "ethernet": {
            "connected": False,
            "ip": None,
            "interface": "eth0"
        },
        "primary_ip": None,
        "default_gateway": None
    }

    if not shutil.which("nmcli"):
        with _wifi_lock:
            _network_status_cache = status
            _network_status_cache_mono = now
        return status

    try:
        # Check active connections
        res = subprocess.run(
            ["nmcli", "-t", "-f", "NAME,TYPE,DEVICE,STATE", "connection", "show", "--active"],
            capture_output=True, text=True, timeout=5
        )
        for line in res.stdout.strip().splitlines():
            parts = parse_nmcli_terse_line(line)
            if len(parts) >= 4:
                c_name, c_type, c_dev, c_state = parts[0], parts[1], parts[2], parts[3]
                if "wireless" in c_type or c_dev.startswith("wl"):
                    status["wifi"]["connected"] = True
                    status["wifi"]["ssid"] = c_name
                    status["wifi"]["interface"] = c_dev
                elif "ethernet" in c_type or c_dev.startswith("eth"):
                    status["ethernet"]["connected"] = True
                    status["ethernet"]["interface"] = c_dev

        # Get IP addresses and signal for wlan0
        res_ip = subprocess.run(
            ["ip", "-br", "addr", "show"],
            capture_output=True, text=True, timeout=5
        )
        for line in res_ip.stdout.strip().splitlines():
            tokens = line.split()
            if len(tokens) >= 3:
                dev = tokens[0]
                ip_cidr = tokens[2]
                ip = ip_cidr.split("/")[0]
                if dev.startswith("wl"):
                    status["wifi"]["ip"] = ip
                elif dev.startswith("eth"):
                    status["ethernet"]["ip"] = ip

        # Get default route
        res_route = subprocess.run(
            ["ip", "route", "show", "default"],
            capture_output=True, text=True, timeout=5
        )
        for line in res_route.stdout.strip().splitlines():
            tokens = line.split()
            if "via" in tokens:
                idx = tokens.index("via")
                gw = tokens[idx + 1]
                status["default_gateway"] = gw
                if "wlan0" in tokens or "wl" in str(tokens):
                    status["wifi"]["gateway"] = gw

        # Get Wi-Fi signal percentage if connected via /proc/net/wireless (0 CPU overhead)
        if status["wifi"]["connected"]:
            signal_set = False
            try:
                with open("/proc/net/wireless", "r") as f:
                    for wline in f:
                        if "wlan0:" in wline or status["wifi"]["interface"] in wline:
                            wparts = wline.split()
                            if len(wparts) >= 3:
                                link_qual = float(wparts[2].replace(".", ""))
                                status["wifi"]["signal"] = int(min(100, max(0, (link_qual / 70.0) * 100)))
                                signal_set = True
            except Exception:
                pass

            if not signal_set:
                res_sig = subprocess.run(
                    ["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL", "dev", "wifi"],
                    capture_output=True, text=True, timeout=3
                )
                for line in res_sig.stdout.strip().splitlines():
                    parts = parse_nmcli_terse_line(line)
                    if len(parts) >= 3 and parts[0] == "*":
                        try:
                            status["wifi"]["signal"] = int(parts[2])
                        except ValueError:
                            pass

        status["primary_ip"] = status["ethernet"]["ip"] or status["wifi"]["ip"]
        with _wifi_lock:
            _network_status_cache = status
            _network_status_cache_mono = now
    except Exception as e:
        logger.error(f"Error fetching network status: {e}")

    return status

def scan_wifi_networks():
    """
    Scans available Wi-Fi networks and returns a sorted list of unique SSIDs with signal and security info.
    """
    networks = []
    if not shutil.which("nmcli"):
        return networks

    try:
        res = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY,IN-USE", "device", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=12
        )
        seen = {}
        for line in res.stdout.strip().splitlines():
            parts = parse_nmcli_terse_line(line)
            if len(parts) >= 4:
                ssid = parts[0].strip()
                if not ssid:
                    continue  # skip hidden networks
                try:
                    signal = int(parts[1])
                except ValueError:
                    signal = 0
                security = parts[2].strip() or "Open"
                in_use = (parts[3].strip() == "*")

                if ssid not in seen or signal > seen[ssid]["signal"]:
                    seen[ssid] = {
                        "ssid": ssid,
                        "signal": signal,
                        "security": security,
                        "is_secure": (security != "Open" and security != "--"),
                        "in_use": in_use
                    }

        networks = sorted(seen.values(), key=lambda x: x["signal"], reverse=True)
    except Exception as e:
        logger.error(f"Error scanning Wi-Fi: {e}")

    return networks

def _find_connection_uuids_for_ssid(ssid):
    """
    Returns a list of NetworkManager connection UUIDs associated with the given SSID.
    """
    uuids = set()
    if not shutil.which("nmcli"):
        return []

    try:
        res = subprocess.run(
            ["nmcli", "-t", "-f", "UUID,NAME,TYPE", "connection", "show"],
            capture_output=True, text=True, timeout=5
        )
        for line in res.stdout.strip().splitlines():
            parts = parse_nmcli_terse_line(line)
            if len(parts) >= 3:
                uuid = parts[0]
                name = parts[1]
                conn_type = parts[2]
                if "wireless" in conn_type or "wifi" in conn_type:
                    if name == ssid:
                        uuids.add(uuid)
                    else:
                        ssid_check = subprocess.run(
                            ["nmcli", "-g", "802-11-wireless.ssid", "connection", "show", uuid],
                            capture_output=True, text=True, timeout=2
                        )
                        if ssid_check.stdout.strip() == ssid:
                            uuids.add(uuid)
    except Exception as e:
        logger.warning(f"Error finding connections for SSID '{ssid}': {e}")

    return list(uuids)

def _delete_existing_wifi_profiles(ssid):
    """
    Deletes connection profiles matching the SSID (used when explicitly forgetting a network).
    """
    if not shutil.which("nmcli") or not ssid:
        return

    uuids = _find_connection_uuids_for_ssid(ssid)
    for u in uuids:
        try:
            logger.info(f"Removing profile {u} for SSID '{ssid}'")
            subprocess.run(["nmcli", "connection", "delete", u], capture_output=True, timeout=5)
        except Exception as e:
            logger.warning(f"Failed to delete profile {u}: {e}")

    try:
        subprocess.run(["nmcli", "connection", "delete", ssid], capture_output=True, timeout=3)
    except Exception:
        pass

def connect_wifi(ssid, password=None):
    """
    Connects to a Wi-Fi network cleanly without prematurely destroying existing profiles.
    Preserves existing working profile if authentication fails.
    """
    if not shutil.which("nmcli"):
        return False, "Strumento nmcli non disponibile nel sistema"

    if not ssid:
        return False, "SSID Wi-Fi non specificato"

    logger.info(f"Initiating Wi-Fi connection to '{ssid}'")

    # Record existing profiles for this SSID before connecting
    existing_uuids = set(_find_connection_uuids_for_ssid(ssid))

    cmd = ["nmcli", "device", "wifi", "connect", ssid]
    if password:
        cmd.extend(["password", password])

    net_status = get_network_status(force=False)
    wlan_iface = net_status.get("wifi", {}).get("interface") or "wlan0"
    cmd.extend(["ifname", wlan_iface])

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        success = (proc.returncode == 0)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()

        invalidate_network_cache()

        if success:
            logger.info(f"Successfully connected to Wi-Fi '{ssid}': {out}")
            try:
                subprocess.run(
                    ["nmcli", "connection", "modify", ssid, "connection.autoconnect", "yes"],
                    capture_output=True, timeout=3
                )
            except Exception:
                pass
            return True, f"Connesso con successo alla rete '{ssid}'"
        else:
            logger.warning(f"Failed to connect to Wi-Fi '{ssid}'. Exit code {proc.returncode}. Stderr: {err} Stdout: {out}")
            # Clean up only newly created broken profiles that were not present beforehand
            current_uuids = set(_find_connection_uuids_for_ssid(ssid))
            newly_created = current_uuids - existing_uuids
            for u in newly_created:
                try:
                    subprocess.run(["nmcli", "connection", "delete", u], capture_output=True, timeout=3)
                except Exception:
                    pass

            combined_err = f"{err} {out}".lower()
            if any(k in combined_err for k in ["secrets were required", "no secrets", "secret", "4-way", "psk", "wrong_key", "authenticat"]):
                msg = "Password errata o autenticazione non riuscita. La configurazione precedente è stata preservata."
            elif any(k in combined_err for k in ["no network with ssid", "not found", "scanning"]):
                msg = f"Rete Wi-Fi '{ssid}' non trovata o fuori portata. Aggiorna la scansione."
            elif "timeout" in combined_err:
                msg = "Tempo di negoziazione Wi-Fi scaduto. Il segnale potrebbe essere troppo debole."
            else:
                msg = f"Impossibile connettersi a '{ssid}': {err or out}"

            return False, msg

    except subprocess.TimeoutExpired:
        logger.error(f"Timeout while connecting to Wi-Fi '{ssid}'")
        current_uuids = set(_find_connection_uuids_for_ssid(ssid))
        for u in (current_uuids - existing_uuids):
            try:
                subprocess.run(["nmcli", "connection", "delete", u], capture_output=True, timeout=3)
            except Exception:
                pass
        invalidate_network_cache()
        return False, "Timeout durante la connessione Wi-Fi (il punto di accesso non ha risposto)."
    except Exception as e:
        logger.error(f"Unexpected error connecting to Wi-Fi '{ssid}': {e}")
        invalidate_network_cache()
        return False, f"Errore imprevisto: {str(e)}"

def forget_wifi(ssid):
    """
    Deletes all saved connection profiles for an SSID and invalidates network cache.
    """
    if not shutil.which("nmcli"):
        return False, "Strumento nmcli non disponibile"

    if not ssid:
        return False, "SSID non specificato"

    try:
        _delete_existing_wifi_profiles(ssid)
        invalidate_network_cache()
        logger.info(f"Forgot Wi-Fi network '{ssid}'")
        return True, f"Rete '{ssid}' rimossa con successo"
    except Exception as e:
        logger.error(f"Error forgetting Wi-Fi '{ssid}': {e}")
        return False, str(e)

def forget_wifi(ssid):
    """
    Deletes all saved connection profiles for an SSID and invalidates network cache.
    """
    if not shutil.which("nmcli"):
        return False, "Strumento nmcli non disponibile"

    if not ssid:
        return False, "SSID non specificato"

    try:
        _delete_existing_wifi_profiles(ssid)
        invalidate_network_cache()
        logger.info(f"Forgot Wi-Fi network '{ssid}'")
        return True, f"Rete '{ssid}' rimossa con successo"
    except Exception as e:
        logger.error(f"Error forgetting Wi-Fi '{ssid}': {e}")
        return False, str(e)
