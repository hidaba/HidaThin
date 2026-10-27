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
    "overscan": "auto",
    "color_depth": 24,
    "sound": True,
    "auto_reconnect": True,
    "max_reconnect_retries": 3,
    "fullscreen": True,
    "vnc": {
        "enabled": True,
        "port": 5900,
        "bind_tailscale_only": True
    },
    "web_admin": {
        "bind": "127.0.0.1",
        "port": 8080,
        "remote_enabled": False,
        "admin_token": ""
    },
    "startup": {
        "mode": "dashboard",              # dashboard | direct_rdp
        "connect_timeout_seconds": 20,
        "max_initial_attempts": 1,
        "fallback_to_dashboard": True,
        "splash_min_duration_seconds": 2
    }
}

VALID_PROFILES = {"performance", "balanced", "quality"}
VALID_COLOR_DEPTHS = {16, 24, 32}
VALID_STARTUP_MODES = {"dashboard", "direct_rdp"}
VALID_OVERSCAN_MODES = {"none", "auto", "light", "medium", "heavy"}

OVERSCAN_PCT = {
    "none": 0.0,
    "light": 0.025,
    "medium": 0.05,
    "heavy": 0.075,
}

OVERSCAN_PRESETS = {
    "none": {"underscan": "off", "hborder": 0, "vborder": 0, "pct": 0.0},
    "auto": {"underscan": "auto", "hborder": 0, "vborder": 0, "pct": None},
    "light": {"underscan": "on", "hborder": 24, "vborder": 16, "pct": 0.025},
    "medium": {"underscan": "on", "hborder": 48, "vborder": 32, "pct": 0.05},
    "heavy": {"underscan": "on", "hborder": 72, "vborder": 40, "pct": 0.075},
}

def _deep_merge_dict(base, override):
    """Recursively merges override into a copy of base."""
    merged = dict(base)
    for k, v in override.items():
        if k in merged and isinstance(merged[k], dict) and isinstance(v, dict):
            merged[k] = _deep_merge_dict(merged[k], v)
        else:
            merged[k] = v
    return merged

def validate_settings(settings):
    """Validates settings against the expected schema."""
    if not isinstance(settings, dict):
        return False, "La configurazione deve essere un oggetto."

    if "overscan" in settings and settings["overscan"] not in VALID_OVERSCAN_MODES:
        return False, f"Modalità overscan non valida: {settings['overscan']}. Valori ammessi: {', '.join(sorted(VALID_OVERSCAN_MODES))}"

    if "profile" in settings and settings["profile"] not in VALID_PROFILES:
        return False, f"Profilo non valido: {settings['profile']}. Valori ammessi: {', '.join(VALID_PROFILES)}"

    if "color_depth" in settings:
        try:
            cd = int(settings["color_depth"])
            if cd not in VALID_COLOR_DEPTHS:
                return False, f"Profondità colore non valida: {cd}. Valori ammessi: {', '.join(map(str, VALID_COLOR_DEPTHS))}"
        except (ValueError, TypeError):
            return False, "Profondità colore non valida."

    if "vnc" in settings and isinstance(settings["vnc"], dict):
        vnc = settings["vnc"]
        if "port" in vnc:
            try:
                port = int(vnc["port"])
                if not (1 <= port <= 65535):
                    return False, f"Porta VNC non valida: {port} (deve essere compresa tra 1 e 65535)."
            except (ValueError, TypeError):
                return False, "Porta VNC non valida."

    if "web_admin" in settings and isinstance(settings["web_admin"], dict):
        wa = settings["web_admin"]
        if "port" in wa:
            try:
                port = int(wa["port"])
                if not (1 <= port <= 65535):
                    return False, f"Porta web admin non valida: {port}."
            except (ValueError, TypeError):
                return False, "Porta web admin non valida."

    if "startup" in settings and isinstance(settings["startup"], dict):
        st = settings["startup"]
        if "mode" in st and st["mode"] not in VALID_STARTUP_MODES:
            return False, f"Modalità avvio non valida: {st['mode']}. Valori ammessi: {', '.join(VALID_STARTUP_MODES)}"
        if "connect_timeout_seconds" in st:
            try:
                ct = int(st["connect_timeout_seconds"])
                if ct < 1 or ct > 300:
                    return False, "connect_timeout_seconds deve essere compreso tra 1 e 300."
            except (ValueError, TypeError):
                return False, "connect_timeout_seconds deve essere numerico."
        if "splash_min_duration_seconds" in st:
            try:
                smd = float(st["splash_min_duration_seconds"])
                if smd < 0 or smd > 60:
                    return False, "splash_min_duration_seconds deve essere compreso tra 0 e 60."
            except (ValueError, TypeError):
                return False, "splash_min_duration_seconds deve essere numerico."

    return True, ""

def get_settings():
    """Loads settings merged with defaults."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = yaml.safe_load(f)
                if isinstance(data, dict):
                    return _deep_merge_dict(DEFAULT_SETTINGS, data)
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
    return _deep_merge_dict(DEFAULT_SETTINGS, {})

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

def write_secure_yaml(filepath, data):
    """Writes data to a YAML file with 0600 permissions atomically."""
    dir_path = os.path.dirname(filepath)
    os.makedirs(dir_path, exist_ok=True)
    try:
        os.chmod(dir_path, 0o700)
    except Exception:
        pass

    tmp_path = f"{filepath}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
    try:
        os.chmod(tmp_path, 0o600)
    except Exception:
        pass
    os.replace(tmp_path, filepath)


def compute_transform_matrix(width=1920, height=1080, pct=0.0):
    """
    Computes xrandr coordinate transformation matrix for shrinking the desktop
    inside the physical display raster to compensate for TV overscan cropping.
    """
    if pct <= 0.0:
        return "none"
    margin_h = round(width * pct / 2)
    margin_v = round(height * pct / 2)
    visible_w = width - 2 * margin_h
    visible_h = height - 2 * margin_v
    if visible_w <= 0 or visible_h <= 0:
        return "none"
    sx = width / visible_w
    sy = height / visible_h
    tx = -sx * margin_h
    ty = -sy * margin_v
    return f"{sx:.6f},0,{tx:.6f},0,{sy:.6f},{ty:.6f},0,0,1"

def parse_connected_outputs_with_props(xrandr_prop_output):
    """Parses xrandr --prop output into a dict of {output_name: [prop_lines]}."""
    outputs = {}
    current_out = None
    for line in xrandr_prop_output.splitlines():
        if " connected" in line and not line.startswith(("\t", " ")):
            parts = line.split()
            current_out = parts[0]
            outputs[current_out] = []
        elif current_out:
            if line.startswith(("\t", " ")):
                outputs[current_out].append(line.strip())
            else:
                current_out = None
    return outputs

def is_display_television(props_list):
    """Detects whether a connected display is a TV (likely to have hardware overscan)."""
    text = " ".join(props_list).upper()
    tv_vendors = ["SAMSUNG", "LG", "SONY", "PHILIPS", "PANASONIC", "TOSHIBA", "HISENSE", "TCL", "SHARP"]
    for v in tv_vendors:
        if v in text:
            return True
    if "1080I" in text or "576I" in text or "480I" in text:
        return True
    return False

def apply_overscan(mode=None):
    """
    Applies overscan compensation to all active connected displays via xrandr.
    Supports:
      - Core X11 RANDR affine transform matrices (CRTC scaling, universal across all drivers)
      - DRM Broadcast RGB (Full) for automatic PC mode negotiation on TV
      - DRM hardware margins / underscan where supported
    Modes:
      - 'none': 1:1 pixel mapping for PC monitors
      - 'auto': Automatically detects TVs vs PC monitors (applies 5% on TV, 0% on monitor)
      - 'light': ~2.5% margin reduction (~24px H / 14px V on 1080p)
      - 'medium': ~5.0% margin reduction (~48px H / 27px V on 1080p)
      - 'heavy': ~7.5% margin reduction (~72px H / 40px V on 1080p)
    """
    if mode is None:
        settings = get_settings()
        mode = settings.get("overscan", "auto")

    if mode not in OVERSCAN_PRESETS:
        mode = "auto"

    preset = OVERSCAN_PRESETS[mode]
    if not shutil.which("xrandr"):
        logger.info("xrandr not available, skipping overscan adjustment.")
        return False, "xrandr non disponibile"

    env = dict(os.environ, DISPLAY=os.environ.get("DISPLAY", ":0"))
    try:
        res = subprocess.run(["xrandr", "--prop"], env=env, capture_output=True, text=True, timeout=3)
        if res.returncode != 0:
            return False, f"xrandr fallito con codice {res.returncode}"

        outputs_props = parse_connected_outputs_with_props(res.stdout)
        if not outputs_props:
            logger.info("Nessuna uscita video connessa rilevata da xrandr.")
            return True, "Nessuna uscita video attiva"

        # Determine active resolution from xrandr output
        width, height = 1920, 1080
        for line in res.stdout.splitlines():
            if "*" in line:
                res_match = line.strip().split()[0]
                if "x" in res_match:
                    try:
                        w, h = map(int, res_match.split("x"))
                        width, height = w, h
                        break
                    except Exception:
                        pass

        applied = []
        for out, props in outputs_props.items():
            props_str = " ".join(props)

            # Determine percentage for this display
            pct = preset["pct"]
            if pct is None:  # auto mode
                is_tv = is_display_television(props)
                pct = 0.05 if is_tv else 0.0
                logger.info(f"Overscan auto-detection for {out}: is_tv={is_tv} -> pct={pct}")

            # 1. Apply core X11 transform matrix (guaranteed scaling across all drivers)
            matrix = compute_transform_matrix(width, height, pct)
            cmd_transform = ["xrandr", "--output", out, "--transform", matrix]
            cmd_res = subprocess.run(cmd_transform, env=env, capture_output=True, text=True, timeout=3)
            if cmd_res.returncode == 0:
                applied.append(f"{out}: {mode} ({pct*100:.1f}%)")
                logger.info(f"Overscan transform matrix applicata su {out}: matrix='{matrix}'")
            else:
                logger.warning(f"Errore transform matrix su {out}: {cmd_res.stderr}")

            # 2. Set Broadcast RGB Full if supported to signal PC mode to TV
            if "Broadcast RGB" in props_str:
                subprocess.run(
                    ["xrandr", "--output", out, "--set", "Broadcast RGB", "Full"],
                    env=env, capture_output=True, text=True, timeout=2
                )

            # 3. Apply DRM margins or underscan if driver supports it
            margin_h = round(width * pct / 2)
            margin_v = round(height * pct / 2)
            if "left margin" in props_str:
                subprocess.run([
                    "xrandr", "--output", out,
                    "--set", "left margin", str(min(100, margin_h)),
                    "--set", "right margin", str(min(100, margin_h)),
                    "--set", "top margin", str(min(100, margin_v)),
                    "--set", "bottom margin", str(min(100, margin_v))
                ], env=env, capture_output=True, text=True, timeout=2)
            elif "underscan" in props_str:
                underscan_val = "off" if pct <= 0 else "on"
                cmd_under = ["xrandr", "--output", out, "--set", "underscan", underscan_val]
                if "underscan hborder" in props_str:
                    cmd_under.extend([
                        "--set", "underscan hborder", str(min(128, margin_h)),
                        "--set", "underscan vborder", str(min(128, margin_v))
                    ])
                subprocess.run(cmd_under, env=env, capture_output=True, text=True, timeout=2)

        return True, f"Applicato a: {', '.join(applied) if applied else 'nessuna porta video'}"
    except Exception as e:
        logger.error(f"Errore durante applicazione overscan: {e}")
        return False, str(e)

def _trigger_live_overscan(merged):
    try:
        threading.Thread(
            target=apply_overscan,
            args=(merged.get("overscan", "auto"),),
            daemon=True
        ).start()
    except Exception as e:
        logger.warning(f"Could not spawn apply_overscan thread: {e}")

def save_settings(settings):
    """
    Saves settings by performing a controlled merge with existing settings,
    validating the schema, applying 0600 permissions, and handling auto-remount if read-only.
    """
    valid, err_msg = validate_settings(settings)
    if not valid:
        return False, err_msg

    current = get_settings()
    merged = _deep_merge_dict(current, settings)

    valid, err_msg = validate_settings(merged)
    if not valid:
        return False, err_msg

    try:
        write_secure_yaml(SETTINGS_FILE, merged)
        _trigger_live_overscan(merged)
        return True, "Impostazioni salvate"
    except OSError as e:
        # Check if read-only filesystem error (errno 30)
        if getattr(e, 'errno', None) == 30 or "Read-only file system" in str(e):
            logger.warning("Filesystem is Read-Only. Performing temporary remount RW to save settings...")
            remount_fs(ro=False)
            try:
                write_secure_yaml(SETTINGS_FILE, merged)
                _trigger_live_overscan(merged)
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
        "resolution": "1920x1080",
        "overscan": get_settings().get("overscan", "auto")
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

def _os_update_worker(initial_root_ro=None, initial_boot_ro=None):
    """Background worker for OS update sequence with state-preserving mount restore."""
    start_time = time.time()
    def log(msg):
        with _update_lock:
            _update_state["logs"].append(f">>> {msg}")
        logger.info(f"[OS-UPDATE] {msg}")

    boot_path = "/boot/firmware" if os.path.exists("/boot/firmware") else "/boot"
    root_was_ro = is_ro_filesystem("/") if initial_root_ro is None else initial_root_ro
    boot_was_ro = (is_ro_filesystem(boot_path) if os.path.exists(boot_path) else False) if initial_boot_ro is None else initial_boot_ro

    apt_success = False
    try:
        # Step 1: Remount filesystem to RW if it was RO
        with _update_lock:
            _update_state["step"] = "1/5: Sblocco filesystem in modalità Scrittura (RW)..."
            _update_state["progress"] = 10
        if root_was_ro or boot_was_ro:
            log("Sblocco scheda SD: rimontaggio partizioni in Read-Write (RW)...")
            ok, msg = remount_fs(ro=False)
            if not ok:
                raise RuntimeError(f"Impossibile sbloccare il filesystem in scrittura: {msg}")
            # Verify root is indeed RW on Linux
            if sys.platform == "linux" and is_ro_filesystem("/"):
                raise RuntimeError("Verifica fallita: la partizione root è rimasta in sola lettura.")
            log("Filesystem rimontato in RW con successo.")
        else:
            log("Filesystem già in modalità Scrittura (RW).")

        if sys.platform != "linux":
            # Simulation for development/testing platforms
            log("[SIMULAZIONE NON-LINUX] Simulazione apt update & dist-upgrade...")
            for i in range(1, 5):
                time.sleep(0.5)
                log(f"[SIMULAZIONE] Download pacchetti ({i*25}%)...")
            with _update_lock:
                _update_state["progress"] = 90
                _update_state["reboot_recommended"] = True
            apt_success = True
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
            apt_success = True

    except Exception as e:
        logger.error(f"Error during OS update: {e}", exc_info=True)
        with _update_lock:
            _update_state["status"] = "error"
            _update_state["error_message"] = str(e)
        log(f"ERRORE CRITICO: {e}")
    finally:
        # Step 6: Restore initial mount state
        subprocess.run(["sync"], check=False)
        remount_error = None
        if root_was_ro:
            log("Ripristino stato iniziale: rimontaggio in Sola Lettura (RO)...")
            ro_ok, ro_msg = remount_fs(ro=True)
            if ro_ok:
                log("Filesystem ripristinato in SOLA LETTURA (RO). Protezione attiva.")
            else:
                remount_error = f"Ripristino RO fallito: {ro_msg}"
                log(f"ATTENZIONE: {remount_error}")
        else:
            log("Filesystem era originariamente in RW: mantenuto in Read-Write.")

        elapsed = round(time.time() - start_time, 1)
        with _update_lock:
            _update_state["progress"] = 100
            _update_state["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            if apt_success:
                if remount_error:
                    _update_state["status"] = "completed_ro_failed"
                    _update_state["error_message"] = remount_error
                else:
                    _update_state["status"] = "completed"
        log(f"Operazione terminata in {elapsed} secondi.")

def start_os_update():
    """Starts the OS update in a separate background thread if not already running."""
    boot_path = "/boot/firmware" if os.path.exists("/boot/firmware") else "/boot"
    with _update_lock:
        if _update_state["status"] == "running":
            return False, "Un aggiornamento di sistema è già in corso."

        # Atomically set status to running inside lock before creating thread
        _update_state["status"] = "running"
        _update_state["started_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _update_state["completed_at"] = None
        _update_state["error_message"] = None
        _update_state["reboot_recommended"] = False
        _update_state["logs"].clear()
        _update_state["progress"] = 5
        _update_state["step"] = "Avvio sequenza di aggiornamento..."

        root_was_ro = is_ro_filesystem("/")
        boot_was_ro = is_ro_filesystem(boot_path) if os.path.exists(boot_path) else False

    try:
        t = threading.Thread(target=_os_update_worker, args=(root_was_ro, boot_was_ro), daemon=True)
        t.start()
        return True, "Aggiornamento sistema operativo avviato in background."
    except Exception as e:
        with _update_lock:
            _update_state["status"] = "idle"
            _update_state["error_message"] = f"Impossibile avviare thread di aggiornamento: {e}"
        return False, str(e)
