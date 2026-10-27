import os
import sys

# Ensure root package directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import socket
import logging
import time
import threading
import yaml
from flask import Flask, render_template, request, jsonify

from app import __version__
from app.wifi import get_network_status, scan_wifi_networks, connect_wifi, forget_wifi
from app.tailscale import get_tailscale_status, restart_tailscale, ping_host
from app.system import (
    get_settings, save_settings, get_system_metrics, reboot_system, poweroff_system,
    get_fs_status, remount_fs, start_os_update, get_os_update_status, write_secure_yaml,
    apply_overscan, VALID_OVERSCAN_MODES
)
from app.rdp import rdp_manager
from app.vnc import get_vnc_status, save_vnc_settings, restart_vnc

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("thinclient")

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
HOSTS_FILE = os.path.join(CONFIG_DIR, "hosts.yaml")

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)

@app.context_processor
def inject_globals():
    return {
        "app_version": __version__
    }

def load_hosts_data(include_passwords=False):
    """
    Reads hosts from config/hosts.yaml.
    By default (include_passwords=False), strips saved passwords and adds 'has_password': True/False.
    """
    data = None
    if os.path.exists(HOSTS_FILE):
        try:
            with open(HOSTS_FILE, "r") as f:
                content = yaml.safe_load(f)
                if isinstance(content, dict):
                    data = content
        except Exception as e:
            logger.error(f"Error loading hosts.yaml: {e}")

    if not data:
        data = {
            "version": 1,
            "default_host": "pc-mimmo",
            "hosts": {
                "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "ip": "100.64.0.7", "port": 3389},
                "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "ip": "100.64.0.9", "port": 3389},
                "pc-studio": {"name": "PC Studio", "hostname": "pc-studio", "ip": "100.64.0.1", "port": 3389}
            }
        }

    sanitized = {
        "version": data.get("version", 1),
        "default_host": data.get("default_host", ""),
        "hosts": {}
    }
    for k, v in data.get("hosts", {}).items():
        host_copy = dict(v)
        has_pwd = bool(host_copy.get("password"))
        host_copy["has_password"] = has_pwd
        if not include_passwords:
            host_copy.pop("password", None)
        sanitized["hosts"][k] = host_copy

    return sanitized

def save_hosts_data(data):
    """Writes hosts to config/hosts.yaml with 0600 permissions and auto-remount fallback if read-only."""
    try:
        write_secure_yaml(HOSTS_FILE, data)
        return True, "Configurazione salvata con successo"
    except OSError as e:
        if getattr(e, 'errno', None) == 30 or "Read-only file system" in str(e):
            logger.warning("Filesystem is Read-Only. Performing temporary remount RW to save hosts...")
            remount_fs(ro=False)
            try:
                write_secure_yaml(HOSTS_FILE, data)
                return True, "Configurazione salvata con successo"
            finally:
                remount_fs(ro=True)
        logger.error(f"Error saving hosts.yaml: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"Error saving hosts.yaml: {e}")
        return False, str(e)

# --- Security & Access Control Middleware (SEC-01) ---

@app.before_request
def check_access_control():
    # Health endpoint is always accessible
    if request.path == "/healthz":
        return None

    remote_ip = request.remote_addr or ""
    is_local = remote_ip in ("127.0.0.1", "::1", "localhost")

    settings = get_settings()
    web_admin = settings.get("web_admin", {})
    remote_enabled = bool(web_admin.get("remote_enabled", False))
    admin_token = (web_admin.get("admin_token") or "").strip()

    if not is_local:
        if not remote_enabled:
            logger.warning(f"Rejected remote request from {remote_ip} to {request.path}: remote access disabled.")
            return jsonify({"success": False, "message": "Accesso remoto non abilitato."}), 403

        # For remote administration, mutating methods require authentication
        if request.method in ("POST", "PUT", "DELETE", "PATCH"):
            token_header = request.headers.get("X-Admin-Token", "")
            auth_header = request.headers.get("Authorization", "")
            provided_token = ""
            if token_header:
                provided_token = token_header.strip()
            elif auth_header.startswith("Bearer "):
                provided_token = auth_header[7:].strip()

            if not admin_token or provided_token != admin_token:
                logger.warning(f"Unauthorized remote request from {remote_ip} to {request.path}")
                return jsonify({"success": False, "message": "Autenticazione richiesta per amministrazione remota."}), 401

    return None

# --- Background System Status Collector (BOOT-02) ---

_system_status_lock = threading.Lock()
_system_status_cache = None
_system_status_cache_mono = 0.0
_is_collecting_status = False
SYSTEM_STATUS_CACHE_TTL = 5.0

def get_system_boot_id():
    """Reads Linux kernel boot_id, guaranteed unique on every reboot."""
    try:
        with open("/proc/sys/kernel/random/boot_id", "r") as f:
            return f.read().strip()
    except Exception:
        return "boot-static"

def _refresh_system_status():
    global _system_status_cache, _system_status_cache_mono, _is_collecting_status
    try:
        net = get_network_status(force=False)
        ts = get_tailscale_status(force=False)
        vnc = get_vnc_status()

        data = load_hosts_data(include_passwords=False)
        default_key = data.get("default_host")
        host_info = data.get("hosts", {}).get(default_key, {})

        host_reachable = None
        if ts.get("connected") and host_info:
            target = host_info.get("hostname")
            fallback_target = host_info.get("ip")
            port = int(host_info.get("port", 3389))
            
            for candidate in filter(None, [target, fallback_target]):
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(0.8)
                    s.connect((candidate, port))
                    s.close()
                    host_reachable = True
                    break
                except Exception:
                    host_reachable = False

        status_snapshot = {
            "version": __version__,
            "boot_id": get_system_boot_id(),
            "network": net,
            "tailscale": ts,
            "vnc": vnc,
            "startup": get_settings().get("startup", {}),
            "default_host": {
                "key": default_key,
                "name": host_info.get("name") if host_info else None,
                "target": (host_info.get("hostname") or host_info.get("ip")) if host_info else None,
                "reachable": host_reachable
            },
            "timestamp_mono": time.monotonic()
        }

        with _system_status_lock:
            _system_status_cache = status_snapshot
            _system_status_cache_mono = time.monotonic()
    except Exception as e:
        logger.error(f"Error in background status collection: {e}")
    finally:
        with _system_status_lock:
            _is_collecting_status = False

def get_cached_system_status(force=False):
    """
    Returns a cached snapshot of network, Tailscale, VNC, and default host status.
    Spawns at most one background worker when cache expires, ensuring non-blocking fast response.
    """
    global _is_collecting_status
    now = time.monotonic()
    with _system_status_lock:
        cache_valid = (_system_status_cache is not None and (now - _system_status_cache_mono) < SYSTEM_STATUS_CACHE_TTL)
        if (not force and cache_valid) or _is_collecting_status:
            if _system_status_cache is not None:
                return dict(_system_status_cache)

        if not _is_collecting_status:
            _is_collecting_status = True
            threading.Thread(target=_refresh_system_status, daemon=True).start()

        if _system_status_cache is not None:
            return dict(_system_status_cache)

    _refresh_system_status()
    with _system_status_lock:
        return dict(_system_status_cache) if _system_status_cache else {}

# --- Lightweight Health Endpoint (BOOT-02) ---

@app.route("/healthz")
def healthz():
    """Ultra-lightweight local health check; never performs external network or DNS queries."""
    return jsonify({
        "status": "ok",
        "version": __version__,
        "timestamp": time.time()
    }), 200

# --- Web UI Routes ---

@app.route("/")
def index():
    data = load_hosts_data(include_passwords=False)
    return render_template(
        "index.html",
        hosts=data.get("hosts", {}),
        default_host=data.get("default_host", "pc-mimmo"),
        startup_settings=get_settings().get("startup", {})
    )

@app.route("/wifi")
def wifi_page():
    return render_template("wifi.html")

@app.route("/hosts")
def hosts_page():
    data = load_hosts_data(include_passwords=False)
    return render_template(
        "hosts.html",
        hosts=data.get("hosts", {}),
        default_host=data.get("default_host", "pc-mimmo"),
        startup_settings=get_settings().get("startup", {})
    )

@app.route("/settings")
def settings_page():
    settings = get_settings()
    metrics = get_system_metrics()
    vnc = get_vnc_status()
    fs = get_fs_status()
    return render_template("settings.html", settings=settings, metrics=metrics, vnc=vnc, fs=fs)

@app.route("/diagnostics")
def diagnostics_page():
    net = get_network_status()
    ts = get_tailscale_status()
    metrics = get_system_metrics()
    data = load_hosts_data(include_passwords=False)
    vnc = get_vnc_status()
    fs = get_fs_status()
    return render_template(
        "diagnostics.html",
        network=net,
        tailscale=ts,
        metrics=metrics,
        hosts=data.get("hosts", {}),
        vnc=vnc,
        fs=fs
    )

# --- REST APIs ---

@app.route("/api/status")
def api_status():
    force = request.args.get("force", "false").lower() in ("true", "1")
    cached = get_cached_system_status(force=force)
    return jsonify({
        "version": __version__,
        "network": cached.get("network", {}),
        "tailscale": cached.get("tailscale", {}),
        "vnc": cached.get("vnc", {})
    })

@app.route("/api/boot/status")
def api_boot_status():
    force = request.args.get("force", "true").lower() in ("true", "1")
    cached = get_cached_system_status(force=force)
    return jsonify(cached)

@app.route("/api/rdp/connect", methods=["POST"])
def api_rdp_connect():
    req = request.get_json() or {}
    host_key = req.get("host_key")
    username = req.get("username")
    password = req.get("password")
    save_password = req.get("save_password")

    raw_data = load_hosts_data(include_passwords=True)
    hosts = raw_data.get("hosts", {})
    if host_key not in hosts:
        return jsonify({"success": False, "message": f"Host '{host_key}' non trovato"}), 404

    host_entry = hosts[host_key]
    stored_password = host_entry.get("password")

    # Check Tailscale readiness
    ts_status = get_tailscale_status()
    if not ts_status.get("connected"):
        restart_tailscale()
        ts_status = get_tailscale_status(force=True)
        if not ts_status.get("connected"):
            return jsonify({
                "success": False,
                "message": "Connessione Tailscale non disponibile. Verifica lo stato di rete."
            })

    # Password semantics:
    effective_password = None
    if password is not None and password != "":
        effective_password = password
        if save_password is True:
            host_entry["password"] = password
            if username is not None:
                u_clean = username.strip()
                if u_clean:
                    host_entry["username"] = u_clean
            save_hosts_data(raw_data)
        # If save_password is False, it's a transient password: do NOT touch stored credential
    else:
        # Use stored password
        effective_password = stored_password

    effective_user = username if (username is not None and username != "") else host_entry.get("username")

    success, msg = rdp_manager.connect(host_entry, username=effective_user, password=effective_password)
    return jsonify({"success": success, "message": msg})

@app.route("/api/rdp/disconnect", methods=["POST"])
def api_rdp_disconnect():
    success, msg = rdp_manager.disconnect()
    return jsonify({"success": success, "message": msg})

@app.route("/api/rdp/status")
def api_rdp_status():
    return jsonify(rdp_manager.get_status())

@app.route("/api/rdp/reset-failed-credentials", methods=["POST"])
def api_rdp_reset_failed_credentials():
    req = request.get_json() or {}
    host_key = req.get("host_key")
    if not host_key:
        return jsonify({"success": False, "message": "Chiave host mancante"}), 400

    raw_data = load_hosts_data(include_passwords=True)
    hosts = raw_data.get("hosts", {})
    if host_key in hosts and "password" in hosts[host_key]:
        del hosts[host_key]["password"]
        save_hosts_data(raw_data)
        logger.info(f"Cleared invalid password for host '{host_key}' after failed attempts.")
        return jsonify({"success": True, "message": "Password non valida rimossa"})

    return jsonify({"success": True})

@app.route("/api/wifi/status")
def api_wifi_status():
    return jsonify(get_network_status())

@app.route("/api/wifi/scan", methods=["POST"])
def api_wifi_scan():
    networks = scan_wifi_networks()
    return jsonify(networks)

@app.route("/api/wifi/connect", methods=["POST"])
def api_wifi_connect():
    req = request.get_json() or {}
    ssid = req.get("ssid")
    password = req.get("password")
    if not ssid:
        return jsonify({"success": False, "message": "SSID obbligatorio"}), 400

    success, msg = connect_wifi(ssid, password)
    return jsonify({"success": success, "message": msg})

@app.route("/api/wifi/forget", methods=["POST"])
def api_wifi_forget():
    req = request.get_json() or {}
    ssid = req.get("ssid")
    if not ssid:
        return jsonify({"success": False, "message": "SSID obbligatorio"}), 400

    success, msg = forget_wifi(ssid)
    return jsonify({"success": success, "message": msg})

@app.route("/api/hosts/save", methods=["POST"])
def api_hosts_save():
    req = request.get_json() or {}
    key = req.get("key") or req.get("hostname")
    name = req.get("name")
    hostname = req.get("hostname")
    ip = req.get("ip")
    port = req.get("port", 3389)
    username = (req.get("username") or "").strip()
    password = req.get("password")
    clear_password = req.get("clear_password", False)
    is_default = req.get("is_default", False)

    if not key or not name or not hostname:
        return jsonify({"success": False, "message": "Dati incompleti"}), 400

    raw_data = load_hosts_data(include_passwords=True)
    existing_entry = raw_data.get("hosts", {}).get(key, {})

    host_entry = {
        "name": name,
        "hostname": hostname,
        "ip": ip if ip else None,
        "port": int(port) if port else 3389
    }
    if username:
        host_entry["username"] = username

    # Password preservation & modification semantics
    if clear_password:
        pass  # Explicit removal: omitted from host_entry
    elif password is not None and password != "":
        host_entry["password"] = password  # Explicit replacement
    elif "password" in existing_entry:
        host_entry["password"] = existing_entry["password"]  # Preserve existing

    raw_data.setdefault("hosts", {})[key] = host_entry
    if is_default:
        raw_data["default_host"] = key

    success, msg = save_hosts_data(raw_data)
    return jsonify({"success": success, "message": msg})

@app.route("/api/hosts/delete", methods=["POST"])
def api_hosts_delete():
    req = request.get_json() or {}
    key = req.get("key")
    if not key:
        return jsonify({"success": False, "message": "Chiave host mancante"}), 400

    raw_data = load_hosts_data(include_passwords=True)
    hosts = raw_data.get("hosts", {})
    if key in hosts:
        del hosts[key]
        if raw_data.get("default_host") == key:
            raw_data["default_host"] = next(iter(hosts.keys()), "")
        success, msg = save_hosts_data(raw_data)
        return jsonify({"success": success, "message": msg})
    return jsonify({"success": False, "message": "Host non trovato"}), 404

@app.route("/api/hosts/set-default", methods=["POST"])
def api_hosts_set_default():
    req = request.get_json() or {}
    key = req.get("key")
    raw_data = load_hosts_data(include_passwords=True)
    if key in raw_data.get("hosts", {}):
        raw_data["default_host"] = key
        success, msg = save_hosts_data(raw_data)
        return jsonify({"success": success, "message": msg})
    return jsonify({"success": False, "message": "Host non trovato"}), 404

@app.route("/api/settings/save", methods=["POST"])
def api_settings_save():
    req = request.get_json() or {}
    success, msg = save_settings(req)
    return jsonify({"success": success, "message": msg})

@app.route("/api/system/overscan/apply", methods=["POST"])
def api_system_overscan_apply():
    req = request.get_json() or {}
    mode = req.get("mode", "auto")
    if mode not in VALID_OVERSCAN_MODES:
        return jsonify({"success": False, "message": f"Modalità non valida: {mode}"}), 400
    success, msg = apply_overscan(mode)
    return jsonify({"success": success, "message": msg})


@app.route("/api/system/reboot", methods=["POST"])
def api_system_reboot():
    success, msg = reboot_system()
    return jsonify({"success": success, "message": msg})

@app.route("/api/system/poweroff", methods=["POST"])
def api_system_poweroff():
    success, msg = poweroff_system()
    return jsonify({"success": success, "message": msg})

@app.route("/api/system/fs-status")
def api_system_fs_status():
    return jsonify(get_fs_status())

@app.route("/api/system/fs-remount", methods=["POST"])
def api_system_fs_remount():
    req = request.get_json() or {}
    mode = req.get("mode", "ro").lower()
    ro = (mode == "ro")
    success, msg = remount_fs(ro=ro)
    return jsonify({"success": success, "message": msg, "fs": get_fs_status()})

@app.route("/api/system/update-os", methods=["POST"])
def api_system_update_os():
    success, msg = start_os_update()
    return jsonify({"success": success, "message": msg})

@app.route("/api/system/update-os/status")
def api_system_update_os_status():
    return jsonify(get_os_update_status())

@app.route("/api/tailscale/restart", methods=["POST"])
def api_tailscale_restart():
    success, msg = restart_tailscale()
    return jsonify({"success": success, "message": msg})

@app.route("/api/tailscale/ping")
def api_tailscale_ping():
    host = request.args.get("host", "")
    if not host:
        return jsonify({"success": False, "message": "Host non specificato"}), 400
    fallback_ip = request.args.get("ip")
    success, msg = ping_host(host, fallback_ip=fallback_ip)
    return jsonify({"success": success, "message": msg})

@app.route("/api/diagnostics/test-host")
def api_diagnostics_test_host():
    host = request.args.get("host", "")
    if not host:
        return jsonify({"success": False, "message": "Host non specificato"}), 400

    resolved_ip = None
    try:
        resolved_ip = socket.gethostbyname(host)
    except Exception:
        pass

    fallback_ip = request.args.get("ip")
    ping_ok, ping_out = ping_host(host, fallback_ip=fallback_ip)

    port_open = False
    for target in filter(None, [resolved_ip, host, fallback_ip]):
        try:
            s = socket.socket()
            s.settimeout(1.5)
            res = s.connect_ex((target, 3389))
            s.close()
            if res == 0:
                port_open = True
                break
        except Exception:
            pass

    return jsonify({
        "host": host,
        "resolved_ip": resolved_ip,
        "ping_success": ping_ok,
        "ping_output": ping_out,
        "port_open": port_open
    })

# --- VNC Remote Assistance APIs ---

@app.route("/api/vnc/status")
def api_vnc_status():
    return jsonify(get_vnc_status())

@app.route("/api/vnc/save", methods=["POST"])
def api_vnc_save():
    req = request.get_json() or {}
    enabled = req.get("enabled", True)
    bind_tailscale_only = req.get("bind_tailscale_only", True)
    password = req.get("password")
    port = req.get("port")
    success, msg = save_vnc_settings(enabled, bind_tailscale_only, password, port=port)
    return jsonify({"success": success, "message": msg})

@app.route("/api/vnc/restart", methods=["POST"])
def api_vnc_restart():
    success, msg = restart_vnc()
    return jsonify({"success": success, "message": msg})

# --- OSD Hot-Corner Overlay Test API ---

@app.route("/api/overlay/test", methods=["POST"])
def api_overlay_test():
    try:
        data = load_hosts_data(include_passwords=False)
        default_host = data.get("hosts", {}).get(data.get("default_host"), {})
        host_name = default_host.get("name", "PC Test (Diagnostica)")
        # create a dummy session object for test
        from app.rdp import RDPSession
        dummy = RDPSession(9999, default_host, "test", "127.0.0.1")
        rdp_manager._start_overlay(dummy)
        return jsonify({"success": True, "message": "Overlay OSD avviato nell'angolo in alto a sinistra. Porta il mouse in alto a sinistra per 1s per aprirlo."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    settings = get_settings()
    web_conf = settings.get("web_admin", {})
    bind_ip = web_conf.get("bind", "127.0.0.1")
    port = int(web_conf.get("port", 8080))
    logger.info(f"Starting HidaThin backend on {bind_ip}:{port} (remote_enabled={web_conf.get('remote_enabled', False)})")
    app.run(host=bind_ip, port=port, debug=False)
