import os
import sys
import subprocess
import shutil
import logging
import yaml
import collections
import threading
import time

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

def is_ro_filesystem(path="/"):
    """Checks if a given mount path is currently mounted read-only."""
    if sys.platform != "linux":
        return False
    try:
        if os.path.exists("/proc/mounts"):
            with open("/proc/mounts", "r") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 4 and parts[1] == path:
                        opts = parts[3].split(",")
                        return "ro" in opts
        stat = os.statvfs(path)
        return bool(stat.f_flag & getattr(os, "ST_RDONLY", 1))
    except Exception as e:
        logger.error(f"Error checking fs status for {path}: {e}")
        return False

def get_fs_status():
    """Returns filesystem read-only/read-write status for root, boot, and data partitions."""
    root_ro = is_ro_filesystem("/")
    boot_path = "/boot/firmware" if os.path.exists("/boot/firmware") else "/boot"
    boot_ro = is_ro_filesystem(boot_path) if os.path.exists(boot_path) else None
    data_mounted = os.path.ismount("/data") if os.path.exists("/data") else False
    data_ro = is_ro_filesystem("/data") if data_mounted else False

    return {
        "root_ro": root_ro,
        "boot_path": boot_path,
        "boot_ro": boot_ro,
        "data_mounted": data_mounted,
        "data_ro": data_ro,
        "mode_label": "SOLA LETTURA (Protetto)" if root_ro else "SCRITTURA (RW)"
    }

def remount_fs(ro=True):
    """Safely remounts / and /boot as ro or rw."""
    mode = "ro" if ro else "rw"
    if sys.platform != "linux":
        logger.info(f"Simulating fs remount to {mode} on non-linux platform")
        return True, f"[Simulazione {sys.platform}] Filesystem impostato a {mode.upper()}"
    try:
        boot_path = "/boot/firmware" if os.path.exists("/boot/firmware") else "/boot"
        if not ro:
            subprocess.run(["mount", "-o", f"remount,{mode}", "/"], check=True)
            if os.path.exists(boot_path):
                subprocess.run(["mount", "-o", f"remount,{mode}", boot_path], check=False)
        else:
            subprocess.run(["sync"], check=False)
            if os.path.exists(boot_path):
                subprocess.run(["mount", "-o", f"remount,{mode}", boot_path], check=False)
            subprocess.run(["mount", "-o", f"remount,{mode}", "/"], check=True)
        logger.info(f"Filesystem remounted to {mode.upper()} successfully")
        return True, f"Filesystem rimontato in {mode.upper()}"
    except Exception as e:
        logger.error(f"Failed to remount filesystem as {mode}: {e}")
        return False, str(e)

def save_settings(settings):
    """Saves settings to config file, handling auto-remount if root is read-only."""
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(SETTINGS_FILE, "w") as f:
            yaml.safe_dump(settings, f, default_flow_style=False)
        return True, "Impostazioni salvate"
    except OSError as e:
        # Check if read-only filesystem error (errno 30)
        if getattr(e, 'errno', None) == 30 or "Read-only file system" in str(e):
            logger.warning("Filesystem is Read-Only. Performing temporary remount RW to save settings...")
            remount_fs(ro=False)
            try:
                os.makedirs(CONFIG_DIR, exist_ok=True)
                with open(SETTINGS_FILE, "w") as f:
                    yaml.safe_dump(settings, f, default_flow_style=False)
                return True, "Impostazioni salvate con successo"
            finally:
                remount_fs(ro=True)
        logger.error(f"Error saving settings: {e}")
        return False, str(e)
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

# --- Debian OS Update Manager (Read-Only Remount Aware) ---

_update_lock = threading.Lock()
_update_state = {
    "status": "idle",       # idle, running, completed, error
    "progress": 0,          # 0 - 100
    "step": "",             # Human-readable current step
    "logs": collections.deque(maxlen=300),
    "started_at": None,
    "completed_at": None,
    "error_message": None,
    "reboot_recommended": False
}

def get_os_update_status():
    """Returns the current state and logs of the OS update process."""
    with _update_lock:
        return {
            "status": _update_state["status"],
            "progress": _update_state["progress"],
            "step": _update_state["step"],
            "logs": list(_update_state["logs"]),
            "started_at": _update_state["started_at"],
            "completed_at": _update_state["completed_at"],
            "error_message": _update_state["error_message"],
            "reboot_recommended": _update_state["reboot_recommended"]
        }

def _run_cmd_logged(cmd, env=None):
    """Executes a command and streams output lines directly to logs deque."""
    logger.info(f"Running command: {' '.join(cmd)}")
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        env=env or os.environ.copy()
    )
    for line in iter(process.stdout.readline, ''):
        line_clean = line.strip()
        if line_clean:
            with _update_lock:
                _update_state["logs"].append(line_clean)
            logger.info(f"[APT] {line_clean}")
    process.stdout.close()
    return process.wait()

def _os_update_worker():
    """Background worker for OS update sequence with guaranteed RO restore."""
    start_time = time.time()
    def log(msg):
        with _update_lock:
            _update_state["logs"].append(f">>> {msg}")
        logger.info(f"[OS-UPDATE] {msg}")

    with _update_lock:
        _update_state["status"] = "running"
        _update_state["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _update_state["completed_at"] = None
        _update_state["error_message"] = None
        _update_state["reboot_recommended"] = False
        _update_state["logs"].clear()

    try:
        # Step 1: Remount filesystem to RW
        with _update_lock:
            _update_state["step"] = "1/5: Sblocco filesystem in modalità Scrittura (RW)..."
            _update_state["progress"] = 10
        log("Sblocco scheda SD: rimontaggio partizioni in Read-Write (RW)...")
        ok, msg = remount_fs(ro=False)
        if not ok:
            log(f"Avviso rimontaggio RW: {msg} (si tenta comunque l'aggiornamento)")
        else:
            log("Filesystem rimontato in RW. Procedura di scrittura abilitata.")

        if sys.platform != "linux":
            # Simulation for development/testing platforms
            log("[SIMULAZIONE NON-LINUX] Simulazione apt update & dist-upgrade...")
            for i in range(1, 5):
                time.sleep(1)
                log(f"[SIMULAZIONE] Download pacchetti fittizi ({i*25}%)...")
            with _update_lock:
                _update_state["progress"] = 90
                _update_state["reboot_recommended"] = True
        else:
            # Debian environment flags
            env = os.environ.copy()
            env["DEBIAN_FRONTEND"] = "noninteractive"
            env["NEEDRESTART_MODE"] = "a"

            # Step 2: apt-get update
            with _update_lock:
                _update_state["step"] = "2/5: Aggiornamento indici repository (apt update)..."
                _update_state["progress"] = 25
            log("Esecuzione: apt-get update...")
            rc = _run_cmd_logged(["apt-get", "update"], env=env)
            if rc != 0:
                raise RuntimeError(f"apt-get update è fallito con codice {rc}")

            # Step 3: apt-get dist-upgrade
            with _update_lock:
                _update_state["step"] = "3/5: Installazione aggiornamenti (apt dist-upgrade)..."
                _update_state["progress"] = 55
            log("Esecuzione: apt-get dist-upgrade...")
            upgrade_cmd = [
                "apt-get", "dist-upgrade", "-y",
                "-o", "Dpkg::Options::=--force-confdef",
                "-o", "Dpkg::Options::=--force-confold"
            ]
            rc = _run_cmd_logged(upgrade_cmd, env=env)
            if rc != 0:
                raise RuntimeError(f"apt-get dist-upgrade è fallito con codice {rc}")

            # Step 4: Clean up packages
            with _update_lock:
                _update_state["step"] = "4/5: Pulizia pacchetti obsoleti (autoremove & clean)..."
                _update_state["progress"] = 80
            log("Esecuzione: apt-get autoremove & clean...")
            _run_cmd_logged(["apt-get", "autoremove", "-y"], env=env)
            _run_cmd_logged(["apt-get", "clean"], env=env)

            # Step 5: Sync disk
            with _update_lock:
                _update_state["step"] = "5/5: Sincronizzazione dati su disco fisico..."
                _update_state["progress"] = 92
            log("Sincronizzazione buffer di scrittura (sync)...")
            subprocess.run(["sync"], check=False)

            with _update_lock:
                _update_state["reboot_recommended"] = True
            log("Aggiornamento Debian completato con successo!")

        with _update_lock:
            _update_state["status"] = "completed"
    except Exception as e:
        logger.error(f"Error during OS update: {e}", exc_info=True)
        with _update_lock:
            _update_state["status"] = "error"
            _update_state["error_message"] = str(e)
        log(f"ERRORE CRITICO: {e}")
    finally:
        # Crucial: Always restore RO filesystem even if error occurred!
        log("Protezione finale scheda SD: rimontaggio in Sola Lettura (RO)...")
        subprocess.run(["sync"], check=False)
        ro_ok, ro_msg = remount_fs(ro=True)
        if ro_ok:
            log("Filesystem ripristinato in SOLA LETTURA (RO). Protezione attiva.")
        else:
            log(f"Attenzione ripristino RO: {ro_msg}")

        elapsed = round(time.time() - start_time, 1)
        with _update_lock:
            _update_state["progress"] = 100
            _update_state["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        log(f"Operazione terminata in {elapsed} secondi.")

def start_os_update():
    """Starts the OS update in a separate background thread if not already running."""
    with _update_lock:
        if _update_state["status"] == "running":
            return False, "Un aggiornamento di sistema è già in corso."

    t = threading.Thread(target=_os_update_worker, daemon=True)
    t.start()
    return True, "Aggiornamento sistema operativo avviato in background."
