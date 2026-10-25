import os
import sys
import subprocess
import threading
import logging
import time
import shutil
from app.system import get_settings, get_system_metrics

logger = logging.getLogger("thinclient.rdp")

LOGS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
RDP_LOG = os.path.join(LOGS_DIR, "rdp.log")

FREERDP_ERROR_MESSAGES = {
    23: "Errore nei parametri di avvio FreeRDP (argomento riga di comando non valido).",
    145: "Autenticazione NLA richiesta. Inserisci Nome Utente e Password nelle Opzioni di accesso Windows.",
    134: "Autenticazione fallita: Nome Utente o Password errati.",
    141: "Host remoto non raggiungibile: verifica che il PC sia acceso e che la porta 3389 sia accessibile.",
    133: "Negoziazione sicurezza fallita: il server richiede Autenticazione a livello di rete (NLA).",
    136: "Inizializzazione grafica fallita: verifica la sessione del server X.",
}

def get_freerdp_error_description(retcode):
    return FREERDP_ERROR_MESSAGES.get(retcode, f"Sessione terminata con errore (codice: {retcode})")

class RDPManager:
    def __init__(self):
        self.process = None
        self.overlay_process = None
        self.state = "IDLE"  # IDLE, CONNECTING, CONNECTED, DISCONNECTED, ERROR
        self.current_host = None
        self.error_message = None
        self.user_cancelled = False
        self.lock = threading.Lock()
        self.monitor_thread = None
        os.makedirs(LOGS_DIR, exist_ok=True)

    def _start_overlay(self, host_label):
        """Launches the lightweight Tkinter hot-corner overlay on DISPLAY=:0."""
        try:
            overlay_script = os.path.join(os.path.dirname(__file__), "overlay.py")
            env = dict(os.environ)
            env["DISPLAY"] = ":0"
            env["HOME"] = "/root"
            for auth in ["/root/.Xauthority", os.path.expanduser("~/.Xauthority")]:
                if os.path.exists(auth):
                    env["XAUTHORITY"] = auth
                    break

            overlay_log = os.path.join(LOGS_DIR, "overlay.log")
            log_f = open(overlay_log, "a")
            log_f.write(f"\n--- Starting overlay at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
            log_f.flush()

            self.overlay_process = subprocess.Popen(
                [sys.executable, overlay_script, "--host", str(host_label or "PC Remoto")],
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid
            )
            logger.info(f"Started hot-corner overlay process (PID {self.overlay_process.pid})")
        except Exception as oe:
            logger.warning(f"Could not start hot-corner overlay: {oe}")
            self.overlay_process = None

    def _stop_overlay(self):
        """Stops the hot-corner overlay process."""
        if self.overlay_process and self.overlay_process.poll() is None:
            try:
                self.overlay_process.terminate()
                time.sleep(0.2)
                if self.overlay_process.poll() is None:
                    self.overlay_process.kill()
                logger.info("Stopped hot-corner overlay process")
            except Exception as oe:
                logger.warning(f"Error terminating overlay: {oe}")
            self.overlay_process = None

    def get_status(self):
        with self.lock:
            return {
                "state": self.state,
                "host": self.current_host,
                "error": self.error_message
            }

    def _find_freerdp_binary(self):
        for candidate in ["xfreerdp3", "xfreerdp"]:
            path = shutil.which(candidate)
            if path:
                return path
        return None

    def connect(self, host_entry, username=None, password=None):
        """
        Launches FreeRDP in a background subprocess.
        host_entry: dict with 'hostname', 'ip', 'port', 'name'
        username: optional Windows username
        password: optional Windows password (passed securely via stdin, never CLI)
        """
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return False, "Una sessione RDP è già attiva."

            bin_path = self._find_freerdp_binary()
            if not bin_path:
                self.state = "ERROR"
                self.error_message = "FreeRDP (xfreerdp3 / xfreerdp) non trovato nel sistema."
                return False, self.error_message

            settings = get_settings()
            profile = settings.get("profile", "balanced")
            color_depth = str(settings.get("color_depth", 24))
            sound_enabled = settings.get("sound", True)
            fullscreen = settings.get("fullscreen", True)

            # Target host: prioritize hostname (MagicDNS), fallback to ip
            target_address = host_entry.get("hostname") or host_entry.get("ip")
            port = str(host_entry.get("port", 3389))
            if port and port != "3389":
                target_address = f"{target_address}:{port}"

            # Effective username: explicitly provided or default from host entry
            effective_user = (username.strip() if username else "") or (host_entry.get("username") or "").strip()
            effective_password = password if (password is not None and password != "") else host_entry.get("password")

            # Base arguments for FreeRDP 3 with GPU/X11 Glamor acceleration
            cmd = [
                bin_path,
                f"/v:{target_address}",
                "/cert:ignore",
                f"/bpp:{color_depth}",
                "/gdi:hw",
                "/cache:bitmap:on,offscreen:on",
                "+clipboard"
            ]

            if effective_user:
                cmd.append(f"/u:{effective_user}")

            if effective_password:
                cmd.append("/from-stdin:force")

            # Resolution & Screen mode
            if fullscreen:
                cmd.append("/f")
            else:
                res_setting = settings.get("resolution", "auto")
                if res_setting == "auto":
                    metrics = get_system_metrics()
                    res_setting = metrics.get("resolution", "1920x1080")
                cmd.append(f"/size:{res_setting}")

            # Profile optimizations
            if profile == "performance":
                # Maximum responsiveness on RPi 3: RFX + thin client + no desktop effects
                cmd.extend([
                    "/network:broadband",
                    "/compression",
                    "/gfx:RFX,thin-client:on,small-cache:on",
                    "-themes",
                    "-wallpaper",
                    "-menu-anims",
                    "-window-drag"
                ])
            elif profile == "quality":
                cmd.extend([
                    "/network:lan",
                    "/compression",
                    "+themes",
                    "/gfx:AVC420"
                ])
            else:  # balanced (default)
                # Progressive rendering + thin client: fast initial response, crisp font, low latency
                cmd.extend([
                    "/network:broadband",
                    "/compression",
                    "/gfx:progressive,thin-client:on,small-cache:on",
                    "-wallpaper",
                    "-menu-anims",
                    "-window-drag"
                ])

            # Audio
            if sound_enabled:
                cmd.append("/sound:sys:alsa")
            else:
                cmd.append("-sound")

            # Reconnection policy
            if settings.get("auto_reconnect", True):
                cmd.extend([
                    "+auto-reconnect",
                    f"/auto-reconnect-max-retries:{settings.get('max_reconnect_retries', 3)}"
                ])

            logger.info(f"Starting FreeRDP with command: {' '.join(cmd)}")
            self.state = "CONNECTING"
            self.current_host = host_entry.get("name", target_address)
            self.error_message = None
            self.user_cancelled = False

            try:
                # Append session log
                log_file = open(RDP_LOG, "a")
                log_file.write(f"\n--- Nuova sessione RDP verso {self.current_host} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
                log_file.flush()

                env = dict(os.environ)
                env["DISPLAY"] = ":0"

                self.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if effective_password else None,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    preexec_fn=os.setsid
                )

                if effective_password:
                    try:
                        self.process.stdin.write(f"{effective_password}\n".encode("utf-8"))
                        self.process.stdin.flush()
                        self.process.stdin.close()
                    except Exception as pe:
                        logger.error(f"Error passing password to FreeRDP: {pe}")

                self.monitor_thread = threading.Thread(target=self._monitor_session, args=(log_file,), daemon=True)
                self.monitor_thread.start()
                self._start_overlay(self.current_host)
                return True, "Connessione RDP avviata"
            except Exception as e:
                self.state = "ERROR"
                self.error_message = str(e)
                logger.error(f"Failed to start FreeRDP: {e}")
                return False, str(e)

    def _monitor_session(self, log_file):
        """Monitors FreeRDP process termination and manages kiosk browser suspension."""
        # Watchdog: transition to CONNECTED after 1.5s if process is still running
        def check_connected():
            time.sleep(1.5)
            with self.lock:
                if self.process and self.process.poll() is None and self.state == "CONNECTING":
                    self.state = "CONNECTED"
                    # Suspend background Chromium to free 100% CPU and avoid swapping to MicroSD
                    try:
                        subprocess.run(["pkill", "-STOP", "-x", "chromium"], check=False)
                        logger.info("Suspended Chromium Kiosk during active RDP session")
                    except Exception as ce:
                        logger.warning(f"Could not suspend Chromium: {ce}")

        threading.Thread(target=check_connected, daemon=True).start()

        # Wait until process ends
        retcode = self.process.wait()

        # Stop hot-corner overlay
        self._stop_overlay()

        # Immediately resume background Chromium when RDP session ends
        try:
            subprocess.run(["pkill", "-CONT", "-x", "chromium"], check=False)
            logger.info("Resumed Chromium Kiosk after RDP session ended")
        except Exception as ce:
            logger.warning(f"Could not resume Chromium: {ce}")

        with self.lock:
            log_file.write(f"\n--- Sessione RDP terminata con codice {retcode} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
            log_file.close()
            self.process = None
            self.state = "IDLE"
            self.current_host = None
            if self.user_cancelled:
                self.error_message = None
                self.user_cancelled = False
            elif retcode not in (0, 130, 143):  # 130 is SIGINT, 143 is SIGTERM
                self.error_message = get_freerdp_error_description(retcode)
                logger.warning(f"FreeRDP exited with code {retcode}: {self.error_message}")
            else:
                self.error_message = None

    def disconnect(self):
        """Terminates active RDP process and overlay."""
        self._stop_overlay()
        try:
            subprocess.run(["pkill", "-CONT", "-x", "chromium"], check=False)
        except Exception:
            pass
        with self.lock:
            if self.process and self.process.poll() is None:
                try:
                    self.user_cancelled = True
                    self.process.terminate()
                    time.sleep(0.5)
                    if self.process.poll() is None:
                        self.process.kill()
                    self.state = "IDLE"
                    self.current_host = None
                    return True, "Sessione interrotta"
                except Exception as e:
                    return False, str(e)
            return True, "Nessuna sessione attiva"

rdp_manager = RDPManager()
