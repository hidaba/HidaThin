import os
import sys

# Ensure root package directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import socket
import logging
import yaml
from flask import Flask, render_template, request, jsonify

from app import __version__
from app.wifi import get_network_status, scan_wifi_networks, connect_wifi, forget_wifi
from app.tailscale import get_tailscale_status, restart_tailscale, ping_host
from app.system import (
    get_settings, save_settings, get_system_metrics, reboot_system, poweroff_system,
    get_fs_status, remount_fs, start_os_update, get_os_update_status
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

def load_hosts_data():
    """Reads hosts from config/hosts.yaml."""
    if os.path.exists(HOSTS_FILE):
        try:
            with open(HOSTS_FILE, "r") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.error(f"Error loading hosts.yaml: {e}")
    return {
        "version": 1,
        "default_host": "pc-mimmo",
        "hosts": {
            "pc-mimmo": {"name": "PC Mimmo", "hostname": "pc-mimmo", "ip": "100.64.0.7", "port": 3389},
            "pc-officina": {"name": "PC Officina", "hostname": "pc-officina", "ip": "100.64.0.9", "port": 3389},
            "pc-studio": {"name": "PC Studio", "hostname": "pc-studio", "ip": "100.64.0.1", "port": 3389}
        }
    }

def save_hosts_data(data):
    """Writes hosts to config/hosts.yaml with auto-remount fallback if read-only."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(HOSTS_FILE, "w") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        return True, "Configurazione salvata con successo"
    except OSError as e:
        if getattr(e, 'errno', None) == 30 or "Read-only file system" in str(e):
            logger.warning("Filesystem is Read-Only. Performing temporary remount RW to save hosts...")
            remount_fs(ro=False)
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                with open(HOSTS_FILE, "w") as f:
                    yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
                return True, "Configurazione salvata con successo"
            finally:
                remount_fs(ro=True)
        logger.error(f"Error saving hosts.yaml: {e}")
        return False, str(e)
    except Exception as e:
        logger.error(f"Error saving hosts.yaml: {e}")
        return False, str(e)

# --- Web UI Routes ---

@app.route("/")
def index():
    data = load_hosts_data()
    return render_template(
        "index.html",
        hosts=data.get("hosts", {}),
        default_host=data.get("default_host", "pc-mimmo")
    )

@app.route("/wifi")
def wifi_page():
    return render_template("wifi.html")

@app.route("/hosts")
def hosts_page():
    data = load_hosts_data()
    return render_template(
        "hosts.html",
        hosts=data.get("hosts", {}),
        default_host=data.get("default_host", "pc-mimmo")
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
    data = load_hosts_data()
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
    net = get_network_status(force=force)
    ts = get_tailscale_status(force=force)
    vnc = get_vnc_status()
    return jsonify({
        "version": __version__,
        "network": net,
        "tailscale": ts,
        "vnc": vnc
    })

def get_system_boot_id():
    """Reads Linux kernel boot_id, guaranteed unique on every reboot."""
    try:
        with open("/proc/sys/kernel/random/boot_id", "r") as f:
            return f.read().strip()
    except Exception:
        return "boot-static"

@app.route("/api/boot/status")
def api_boot_status():
    force = request.args.get("force", "true").lower() in ("true", "1")
    net = get_network_status(force=force)
    ts = get_tailscale_status(force=force)
    data = load_hosts_data()
    default_key = data.get("default_host")
    host_info = data.get("hosts", {}).get(default_key, {})

    # Quick check for default host reachability if tailscale is connected
    host_reachable = None
    if ts.get("connected") and host_info:
        target = host_info.get("hostname") or host_info.get("ip")
        if target:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(0.5)
                port = int(host_info.get("port", 3389))
                s.connect((target, port))
                s.close()
                host_reachable = True
            except Exception:
                host_reachable = False

    return jsonify({
        "version": __version__,
        "boot_id": get_system_boot_id(),
        "network": net,
        "tailscale": ts,
        "default_host": {
            "key": default_key,
            "name": host_info.get("name") if host_info else None,
            "target": (host_info.get("hostname") or host_info.get("ip")) if host_info else None,
            "reachable": host_reachable
        }
    })

@app.route("/api/rdp/connect", methods=["POST"])
def api_rdp_connect():
    req = request.get_json() or {}
    host_key = req.get("host_key")
    username = req.get("username")
    password = req.get("password")
    save_password = req.get("save_password")

    data = load_hosts_data()
    hosts = data.get("hosts", {})
    if host_key not in hosts:
        return jsonify({"success": False, "message": f"Host '{host_key}' non trovato"}), 404

    host_entry = hosts[host_key]
    
    # Check Tailscale readiness
    ts_status = get_tailscale_status()
    if not ts_status.get("connected"):
        # Try restarting tailscale once
        restart_tailscale()
        ts_status = get_tailscale_status()
        if not ts_status.get("connected"):
            return jsonify({
                "success": False,
                "message": "Connessione Tailscale non disponibile. Verifica lo stato di rete."
            })

    # Persist or remove credentials according to save_password flag
    if save_password is True:
        changed = False
        if password is not None:
            if password != "":
                if host_entry.get("password") != password:
                    host_entry["password"] = password
                    changed = True
            elif "password" in host_entry:
                del host_entry["password"]
                changed = True
        if username is not None:
            u_clean = username.strip()
            if u_clean and host_entry.get("username") != u_clean:
                host_entry["username"] = u_clean
                changed = True
            elif not u_clean and "username" in host_entry:
                del host_entry["username"]
                changed = True
        if changed:
            save_hosts_data(data)
    elif save_password is False:
        if "password" in host_entry:
            del host_entry["password"]
            save_hosts_data(data)

    success, msg = rdp_manager.connect(host_entry, username=username, password=password)
    return jsonify({"success": success, "message": msg})

@app.route("/api/rdp/disconnect", methods=["POST"])
def api_rdp_disconnect():
    success, msg = rdp_manager.disconnect()
    return jsonify({"success": success, "message": msg})

@app.route("/api/rdp/status")
def api_rdp_status():
    return jsonify(rdp_manager.get_status())

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
    is_default = req.get("is_default", False)

    if not key or not name or not hostname:
        return jsonify({"success": False, "message": "Dati incompleti"}), 400

    data = load_hosts_data()
    existing_entry = data.get("hosts", {}).get(key, {})
    host_entry = {
        "name": name,
        "hostname": hostname,
        "ip": ip if ip else None,
        "port": port
    }
    if username:
        host_entry["username"] = username
    if password is not None:
        if password:
            host_entry["password"] = password
        elif "password" in existing_entry and password == "":
            pass # explicitly cleared
    elif "password" in existing_entry:
        host_entry["password"] = existing_entry["password"]

    data.setdefault("hosts", {})[key] = host_entry
    if is_default:
        data["default_host"] = key

    success, msg = save_hosts_data(data)
    return jsonify({"success": success, "message": msg})

@app.route("/api/hosts/delete", methods=["POST"])
def api_hosts_delete():
    req = request.get_json() or {}
    key = req.get("key")
    if not key:
        return jsonify({"success": False, "message": "Chiave host mancante"}), 400

    data = load_hosts_data()
    hosts = data.get("hosts", {})
    if key in hosts:
        del hosts[key]
        if data.get("default_host") == key:
            data["default_host"] = next(iter(hosts.keys()), "")
        success, msg = save_hosts_data(data)
        return jsonify({"success": success, "message": msg})
    return jsonify({"success": False, "message": "Host non trovato"}), 404

@app.route("/api/hosts/set-default", methods=["POST"])
def api_hosts_set_default():
    req = request.get_json() or {}
    key = req.get("key")
    data = load_hosts_data()
    if key in data.get("hosts", {}):
        data["default_host"] = key
        success, msg = save_hosts_data(data)
        return jsonify({"success": success, "message": msg})
    return jsonify({"success": False, "message": "Host non trovato"}), 404

@app.route("/api/settings/save", methods=["POST"])
def api_settings_save():
    req = request.get_json() or {}
    success, msg = save_settings(req)
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
    success, msg = ping_host(host)
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

    # Ping test
    ping_ok, ping_out = ping_host(host)

    # Port 3389 test
    port_open = False
    try:
        s = socket.socket()
        s.settimeout(2.5)
        target = resolved_ip or host
        res = s.connect_ex((target, 3389))
        port_open = (res == 0)
        s.close()
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
    success, msg = save_vnc_settings(enabled, bind_tailscale_only, password)
    return jsonify({"success": success, "message": msg})

@app.route("/api/vnc/restart", methods=["POST"])
def api_vnc_restart():
    success, msg = restart_vnc()
    return jsonify({"success": success, "message": msg})

# --- OSD Hot-Corner Overlay Test API ---

@app.route("/api/overlay/test", methods=["POST"])
def api_overlay_test():
    try:
        rdp_manager._start_overlay("PC Test (Diagnostica)")
        return jsonify({"success": True, "message": "Overlay OSD avviato nell'angolo in alto a sinistra. Porta il mouse in alto a sinistra per 1s per aprirlo."})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)

