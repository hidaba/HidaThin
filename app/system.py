import os
import subprocess
import shutil
import logging
import yaml

logger = logging.getLogger("thinclient.system")

CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config")
SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.yaml")

DEFAULT_SETTINGS = {
    "version": 1,
    "profile": "balanced",
    "resolution": "auto",
    "color_depth": 24,
    "sound": True,
    "auto_reconnect": True,
    "max_reconnect_retries": 3,
    "fullscreen": True,
    "vnc": {
        "enabled": True,
        "port": 5900,
        "bind_tailscale_only": True
    }
}

def get_settings():
    """Loads settings or returns defaults."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    settings = DEFAULT_SETTINGS.copy()
                    settings["vnc"] = DEFAULT_SETTINGS["vnc"].copy()
                    for k, v in data.items():
                        if k == "vnc" and isinstance(v, dict):
                            settings["vnc"].update(v)
                        else:
                            settings[k] = v
                    return settings
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    """Saves settings to config file."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            yaml.safe_dump(settings, f, default_flow_style=False)
        return True, "Impostazioni salvate"
    except Exception as e:
        logger.error(f"Error saving settings: {e}")
        return False, str(e)

def parse_throttled(hex_str):
    """Interprets vcgencmd get_throttled hex string."""
    try:
        val = int(hex_str, 16)
        flags = []
        if val & 0x1:
            flags.append("Sottotensione attiva")
        if val & 0x2:
            flags.append("Frequenza ARM ridotta")
        if val & 0x4:
            flags.append("Throttling attivo")
        if val & 0x8:
            flags.append("Limite termico attivo")
        if val & 0x10000:
            flags.append("Sottotensione pregressa")
        if val & 0x20000:
            flags.append("Frequenza ridotta pregressa")
        if val & 0x40000:
            flags.append("Throttling pregresso")
        if val & 0x80000:
            flags.append("Limite termico pregresso")
        return {
            "raw": hex_str,
            "is_throttled": (val != 0),
            "description": ", ".join(flags) if flags else "OK (Nessun problema)"
        }
    except Exception:
        return {"raw": hex_str, "is_throttled": False, "description": hex_str}

def get_system_metrics():
    """Gathers CPU, RAM, temperature, throttled status, and display resolution."""
    metrics = {
        "cpu_usage": 0,
        "temp": "N/D",
        "throttled": {"raw": "0x0", "is_throttled": False, "description": "OK"},
        "ram_total": 0,
        "ram_used": 0,
        "ram_free": 0,
        "ram_percent": 0,
        "swap_total": 0,
        "swap_used": 0,
        "resolution": "1920x1080"
    }

    # RAM and Swap
    try:
        with open("/proc/meminfo", "r") as f:
            mem = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    k = parts[0].strip()
                    v = int(parts[1].strip().split()[0])
                    mem[k] = v
            total = mem.get("MemTotal", 1)
            avail = mem.get("MemAvailable", mem.get("MemFree", 0))
            used = total - avail
            metrics["ram_total"] = round(total / 1024)
            metrics["ram_used"] = round(used / 1024)
            metrics["ram_free"] = round(avail / 1024)
            metrics["ram_percent"] = round((used / total) * 100)
            sw_total = mem.get("SwapTotal", 0)
            sw_free = mem.get("SwapFree", 0)
            metrics["swap_total"] = round(sw_total / 1024)
            metrics["swap_used"] = round((sw_total - sw_free) / 1024)
    except Exception as e:
        logger.error(f"Error reading meminfo: {e}")

    # Temperature and throttling
    if shutil.which("vcgencmd"):
        try:
            res = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                metrics["temp"] = res.stdout.strip().replace("temp=", "")
        except Exception:
            pass

        try:
            res = subprocess.run(["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0:
                raw_hex = res.stdout.strip().replace("throttled=", "")
                metrics["throttled"] = parse_throttled(raw_hex)
        except Exception:
            pass

    # Screen resolution detection via xrandr
    if shutil.which("xrandr"):
        try:
            res = subprocess.run(
                ["xrandr"],
                env=dict(os.environ, DISPLAY=":0"),
                capture_output=True, text=True, timeout=2
            )
            for line in res.stdout.splitlines():
                if "*" in line:
                    res_match = line.strip().split()[0]
                    if "x" in res_match:
                        metrics["resolution"] = res_match
                        break
        except Exception:
            pass

    return metrics

def reboot_system():
    """Issues a system reboot command."""
    try:
        subprocess.run(["systemctl", "reboot"], check=True)
        return True, "Riavvio in corso..."
    except Exception as e:
        return False, str(e)

def poweroff_system():
    """Issues a system poweroff command."""
    try:
        subprocess.run(["systemctl", "poweroff"], check=True)
        return True, "Spegnimento in corso..."
    except Exception as e:
        return False, str(e)
