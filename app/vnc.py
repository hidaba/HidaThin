import os
import shutil
import subprocess
import socket
import logging
from app.system import get_settings, save_settings
from app.tailscale import get_tailscale_status
from app.wifi import get_network_status

logger = logging.getLogger("thinclient.vnc")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
PASS_FILE = os.path.join(CONFIG_DIR, "x11vnc.pass")
DEFAULT_VNC_PORT = 5900

def get_connected_vnc_clients(port=DEFAULT_VNC_PORT):
    """Detects active established VNC connections on the specified port."""
    clients = []
    # Try using ss first
    if shutil.which("ss"):
        try:
            res = subprocess.run(
                ["ss", "-t", "-H", "-n", f"( sport = :{port} )", "state", "established"],
                capture_output=True,
                text=True,
                timeout=2
            )
            for line in res.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 4:
                    clients.append(parts[3])
            return clients
        except Exception:
            pass

    # Fallback to netstat
    if shutil.which("netstat"):
        try:
            res = subprocess.run(
                ["netstat", "-tn"],
                capture_output=True,
                text=True,
                timeout=2
            )
            for line in res.stdout.splitlines():
                if f":{port} " in line and "ESTABLISHED" in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        clients.append(parts[4])
        except Exception:
            pass

    return clients

def get_vnc_status():
    """
    Returns complete status of the VNC remote assistance service,
    including network endpoints, client sessions, and configuration.
    """
    settings = get_settings()
    vnc_conf = settings.get("vnc", {})
    enabled = vnc_conf.get("enabled", True)
    bind_tailscale_only = vnc_conf.get("bind_tailscale_only", True)
    port = vnc_conf.get("port", DEFAULT_VNC_PORT)

    installed = shutil.which("x11vnc") is not None
    active = False

    if shutil.which("systemctl"):
        try:
            res = subprocess.run(
                ["systemctl", "is-active", "thinclient-vnc"],
                capture_output=True,
                text=True,
                timeout=2
            )
            active = (res.stdout.strip() == "active")
        except Exception:
            pass

    has_password = os.path.exists(PASS_FILE)
    connected_clients = get_connected_vnc_clients(port)

    # Network information
    ts_status = get_tailscale_status()
    ts_ip = ts_status.get("ip")
    ts_connected = ts_status.get("connected", False)

    net_status = get_network_status()
    lan_ip = net_status.get("primary_ip")

    # Determine recommended connection strings
    hostname = socket.gethostname()
    magic_dns = ts_status.get("magic_dns_suffix", "")
    full_dns_name = f"{hostname}.{magic_dns}" if (hostname and magic_dns) else hostname

    connect_host = f"{hostname}:{port}"
    connect_ip = f"{ts_ip}:{port}" if ts_ip else (f"{lan_ip}:{port}" if lan_ip else None)

    return {
        "installed": installed,
        "active": active,
        "enabled": enabled,
        "port": port,
        "bind_tailscale_only": bind_tailscale_only,
        "has_password": has_password,
        "clients_count": len(connected_clients),
        "clients": connected_clients,
        "tailscale_ip": ts_ip,
        "tailscale_connected": ts_connected,
        "lan_ip": lan_ip,
        "hostname": hostname,
        "full_dns_name": full_dns_name,
        "connect_host": connect_host,
        "connect_ip": connect_ip
    }

def set_vnc_password(password):
    """
    Encrypts and saves the VNC password using x11vnc -storepasswd.
    Restricts file permissions to 0600.
    """
    if not password or len(password.strip()) == 0:
        return False, "La password VNC non può essere vuota."

    pwd = password.strip()
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if shutil.which("x11vnc"):
            res = subprocess.run(
                ["x11vnc", "-storepasswd", pwd, PASS_FILE],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode != 0:
                # Alternative via stdin in case CLI arguments are restricted
                subprocess.run(
                    ["x11vnc", "-storepasswd", "-", PASS_FILE],
                    input=f"{pwd}\n{pwd}\n",
                    capture_output=True,
                    text=True,
                    timeout=5,
                    check=True
                )
        else:
            # Fallback for development / mock environments
            with open(PASS_FILE, "wb") as f:
                f.write(pwd.encode("utf-8")[:8])

        try:
            os.chmod(PASS_FILE, 0o600)
        except Exception:
            pass

        logger.info(f"VNC password updated successfully in {PASS_FILE}")
        return True, "Password VNC aggiornata con successo."
    except Exception as e:
        logger.error(f"Failed to set VNC password: {e}")
        return False, f"Errore impostazione password VNC: {e}"

def save_vnc_settings(enabled, bind_tailscale_only, new_password=None, port=None):
    """
    Persists VNC configuration to settings.yaml and starts/stops/restarts
    the thinclient-vnc systemd service accordingly.
    Requires an explicit password before VNC can be enabled.
    """
    settings = get_settings()
    if "vnc" not in settings or not isinstance(settings["vnc"], dict):
        settings["vnc"] = {}

    target_port = port if port is not None else settings["vnc"].get("port", DEFAULT_VNC_PORT)
    try:
        target_port = int(target_port)
    except (ValueError, TypeError):
        target_port = DEFAULT_VNC_PORT

    # If user wants to enable VNC, ensure a password file exists or is being set
    if enabled:
        if new_password and len(new_password.strip()) > 0:
            pw_ok, pw_msg = set_vnc_password(new_password)
            if not pw_ok:
                return False, pw_msg
        elif not os.path.exists(PASS_FILE):
            return False, "Impossibile attivare VNC senza aver impostato una password. Inserisci una password sicura."
    elif new_password and len(new_password.strip()) > 0:
        pw_ok, pw_msg = set_vnc_password(new_password)
        if not pw_ok:
            return False, pw_msg

    vnc_update = {
        "vnc": {
            "enabled": bool(enabled),
            "bind_tailscale_only": bool(bind_tailscale_only),
            "port": target_port
        }
    }

    ok, msg = save_settings(vnc_update)
    if not ok:
        return False, msg

    # Manage systemd service
    if shutil.which("systemctl"):
        try:
            if enabled:
                subprocess.run(["systemctl", "enable", "thinclient-vnc"], check=False)
                subprocess.run(["systemctl", "restart", "thinclient-vnc"], check=False)
            else:
                subprocess.run(["systemctl", "stop", "thinclient-vnc"], check=False)
                subprocess.run(["systemctl", "disable", "thinclient-vnc"], check=False)
        except Exception as e:
            logger.warning(f"Failed to apply systemctl action for thinclient-vnc: {e}")

    return True, "Configurazione VNC salvata con successo."

def restart_vnc():
    """Restarts thinclient-vnc systemd service."""
    if shutil.which("systemctl"):
        try:
            res = subprocess.run(["systemctl", "restart", "thinclient-vnc"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return True, "Servizio VNC riavviato."
            return False, res.stderr.strip() or "Errore riavvio servizio VNC"
        except Exception as e:
            return False, str(e)
    return False, "systemctl non disponibile nel sistema"
