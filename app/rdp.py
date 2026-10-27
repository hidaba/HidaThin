import os
import sys
import subprocess
import threading
import logging
import time
import shutil
from app.system import get_settings, get_system_metrics

logger = logging.getLogger("thinclient.rdp")

FREERDP_ERROR_MESSAGES = {
    23: "Errore nei parametri di avvio FreeRDP (argomento riga di comando non valido).",
    133: "Negoziazione sicurezza fallita: il server richiede Autenticazione a livello di rete (NLA).",
    134: "Autenticazione fallita: Nome Utente o Password errati.",
    136: "Inizializzazione grafica fallita: verifica la sessione del server X.",
    140: "Impossibile risolvere il nome del PC remoto (errore DNS): verifica il nome host o specifica l'indirizzo IP.",
    141: "Host remoto non raggiungibile: verifica che il PC sia acceso, connesso a Tailscale e che la porta 3389 sia accessibile.",
    142: "Errore di connessione iniziale MCS al server RDP.",
    143: "Connessione TLS/SSL fallita verso il server remoto.",
    144: "Privilegi insufficienti per la connessione al PC remoto.",
    145: "Autenticazione NLA richiesta. Inserisci Nome Utente e Password nelle Opzioni di accesso Windows.",
    147: "Connessione di trasporto fallita verso il PC remoto.",
    148: "La password dell'account Windows è scaduta.",
    154: "Autenticazione fallita: password Windows errata.",
    155: "Accesso negato: l'utente non dispone dei permessi per il Desktop Remoto su Windows.",
}

def get_freerdp_error_description(retcode):
    return FREERDP_ERROR_MESSAGES.get(retcode, f"Sessione terminata con errore (codice: {retcode})")

def get_runtime_log_dir():
    """
    Returns a writable directory for runtime/session logs.
    Prioritizes volatile tmpfs paths: /run/thinclient, /tmp/thinclient-logs, then project logs.
    """
    candidates = [
        "/run/thinclient",
        "/tmp/thinclient-logs",
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    ]
    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            test_file = os.path.join(candidate, f".write_test_{os.getpid()}")
            with open(test_file, "w") as f:
                f.write("ok")
            os.remove(test_file)
            return candidate
        except Exception:
            continue
    return "/tmp"

def open_runtime_log(filename):
    """
    Opens a log file in the runtime directory.
    Falls back gracefully to os.devnull if directory is unwritable (e.g. strict EROFS).
    """
    log_dir = get_runtime_log_dir()
    filepath = os.path.join(log_dir, filename)
    try:
        f = open(filepath, "a")
        return f, filepath
    except OSError as e:
        logger.warning(f"Unable to open runtime log {filepath} ({e}). Falling back to null device.")
        return open(os.devnull, "w"), os.devnull

def coordinate_kiosk_browser(action="stop"):
    """
    Coordinates kiosk browser suspension/resumption without affecting unrelated processes.
    Only signals chromium processes running with kiosk/app flags.
    """
    if sys.platform != "linux":
        return
    sig = "-STOP" if action == "stop" else "-CONT"
    try:
        subprocess.run(["pkill", sig, "-f", "chromium.*--kiosk"], check=False)
        subprocess.run(["pkill", sig, "-f", "chromium.*--app="], check=False)
        logger.info(f"Kiosk browser signaled with {sig}")
    except Exception as ce:
        logger.warning(f"Could not signal kiosk browser ({action}): {ce}")

class RDPSession:
    """Encapsulates a distinct RDP session and all related subprocesses and state."""
    def __init__(self, session_id, host_entry, effective_user, target_address):
        self.session_id = session_id
        self.host_entry = host_entry
        self.effective_user = effective_user
        self.target_address = target_address
        self.host_name = host_entry.get("name") or target_address
        self.process = None
        self.overlay_process = None
        self.log_file = None
        self.state = "CONNECTING"  # CONNECTING, CONNECTED, DISCONNECTING, ERROR, IDLE
        self.user_cancelled = False
        self.error_message = None
        self.start_mono = time.monotonic()

class RDPManager:
    """
    Manages active FreeRDP sessions, OSD overlay, and kiosk browser coordination.
    Ensures that stale session monitors do not interfere with new active sessions.
    """
    def __init__(self):
        self.active_session = None
        self.lock = threading.Lock()
        self.session_counter = 0
        self.last_error = None

    def _start_overlay(self, session):
        """Launches the lightweight Tkinter hot-corner overlay on DISPLAY=:0 for the session."""
        try:
            overlay_script = os.path.join(os.path.dirname(__file__), "overlay.py")
            env = dict(os.environ)
            env["DISPLAY"] = ":0"
            env["HOME"] = "/root"
            for auth in ["/root/.Xauthority", os.path.expanduser("~/.Xauthority")]:
                if os.path.exists(auth):
                    env["XAUTHORITY"] = auth
                    break

            log_f, _ = open_runtime_log("overlay.log")
            try:
                log_f.write(f"\n--- Starting overlay [Session {session.session_id}] at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                log_f.flush()
            except Exception:
                pass

            session.overlay_process = subprocess.Popen(
                [sys.executable, overlay_script, "--host", str(session.host_name or "PC Remoto")],
                env=env,
                stdout=log_f,
                stderr=subprocess.STDOUT,
                start_new_session=True
            )
            logger.info(f"Started overlay for session {session.session_id} (PID {session.overlay_process.pid})")
        except Exception as oe:
            logger.warning(f"Could not start overlay for session {session.session_id}: {oe}")
            session.overlay_process = None

    def _stop_overlay(self, session):
        """Stops the hot-corner overlay process associated with this session."""
        if session.overlay_process and session.overlay_process.poll() is None:
            try:
                session.overlay_process.terminate()
                try:
                    session.overlay_process.wait(timeout=0.6)
                except subprocess.TimeoutExpired:
                    session.overlay_process.kill()
                logger.info(f"Stopped overlay for session {session.session_id}")
            except Exception as oe:
                logger.warning(f"Error terminating overlay: {oe}")
            session.overlay_process = None

    def get_status(self):
        """Returns the current RDP manager status snapshot."""
        with self.lock:
            if self.active_session is not None:
                return {
                    "state": self.active_session.state,
                    "host": self.active_session.host_name,
                    "error": self.active_session.error_message or self.last_error,
                    "session_id": self.active_session.session_id
                }
            return {
                "state": "IDLE",
                "host": None,
                "error": self.last_error,
                "session_id": None
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
            if self.active_session is not None and self.active_session.process is not None:
                if self.active_session.process.poll() is None:
                    return False, "Una sessione RDP è già attiva."

            bin_path = self._find_freerdp_binary()
            if not bin_path:
                self.last_error = "FreeRDP (xfreerdp3 / xfreerdp) non trovato nel sistema."
                return False, self.last_error

            self.session_counter += 1
            session_id = self.session_counter

            settings = get_settings()
            profile = settings.get("profile", "balanced")
            color_depth = str(settings.get("color_depth", 24))
            sound_enabled = settings.get("sound", True)
            fullscreen = settings.get("fullscreen", True)

            # Target host: prioritize IP if present to prevent DNS failures; auto-resolve via Tailscale peers if needed
            target_ip = (host_entry.get("ip") or "").strip()
            target_host = (host_entry.get("hostname") or "").strip()
            target_address = target_ip or target_host

            if not target_ip and target_host:
                try:
                    from app.tailscale import get_tailscale_status
                    ts = get_tailscale_status(force=False)
                    for peer in ts.get("peers", []):
                        if peer.get("hostname") == target_host or peer.get("dns_name") == target_host:
                            if peer.get("ip"):
                                target_address = peer.get("ip")
                                logger.info(f"Auto-resolved '{target_host}' to Tailscale IP '{target_address}'")
                                break
                except Exception as te:
                    logger.debug(f"Could not auto-resolve peer IP for {target_host}: {te}")
            port = str(host_entry.get("port", 3389))
            if port and port != "3389":
                target_address = f"{target_address}:{port}"

            effective_user = (username.strip() if username else "") or (host_entry.get("username") or "").strip()
            effective_password = password if (password is not None and password != "") else host_entry.get("password")

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

            if fullscreen:
                cmd.append("/f")
            else:
                res_setting = settings.get("resolution", "auto")
                if res_setting == "auto":
                    metrics = get_system_metrics()
                    res_setting = metrics.get("resolution", "1920x1080")
                cmd.append(f"/size:{res_setting}")

            if profile == "performance":
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
            else:  # balanced
                cmd.extend([
                    "/network:broadband",
                    "/compression",
                    "/gfx:progressive,thin-client:on,small-cache:on",
                    "-wallpaper",
                    "-menu-anims",
                    "-window-drag"
                ])

            if sound_enabled:
                cmd.append("/sound:sys:alsa")
            else:
                cmd.append("-sound")

            if settings.get("auto_reconnect", True):
                cmd.extend([
                    "+auto-reconnect",
                    f"/auto-reconnect-max-retries:{settings.get('max_reconnect_retries', 3)}"
                ])

            logger.info(f"Starting FreeRDP [Session {session_id}] for {target_address}")

            session = RDPSession(session_id, host_entry, effective_user, target_address)
            self.active_session = session
            self.last_error = None

            log_file, _ = open_runtime_log("rdp.log")
            session.log_file = log_file

            try:
                log_file.write(f"\n--- Nuova sessione RDP [ID: {session_id}] verso {session.host_name} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
                log_file.flush()
            except Exception:
                pass

            env = dict(os.environ)
            env["DISPLAY"] = ":0"

            try:
                session.process = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if effective_password else None,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    env=env,
                    start_new_session=True
                )
            except Exception as e:
                self.active_session = None
                session.state = "ERROR"
                self.last_error = str(e)
                try:
                    log_file.close()
                except Exception:
                    pass
                logger.error(f"Failed to start FreeRDP: {e}")
                return False, str(e)

            if effective_password and session.process.stdin:
                try:
                    session.process.stdin.write(f"{effective_password}\n".encode("utf-8"))
                    session.process.stdin.flush()
                    session.process.stdin.close()
                except Exception as pe:
                    logger.error(f"Error passing password to FreeRDP: {pe}")

            self._start_overlay(session)

            # Watchdog thread: sets CONNECTED state if process survives initial startup
            threading.Thread(target=self._watchdog_connected, args=(session,), daemon=True).start()

            # Session monitor thread: waits on process exit and cleans up
            threading.Thread(target=self._monitor_session, args=(session,), daemon=True).start()

            return True, "Connessione RDP avviata"

    def _watchdog_connected(self, session):
        """Transitions state to CONNECTED after 1.5s if session process is still running."""
        time.sleep(1.5)
        with self.lock:
            if self.active_session is session and session.state == "CONNECTING":
                if session.process and session.process.poll() is None:
                    session.state = "CONNECTED"
                    coordinate_kiosk_browser("stop")

    def _monitor_session(self, session):
        """Monitors FreeRDP process termination with session isolation."""
        retcode = session.process.wait()

        self._stop_overlay(session)
        coordinate_kiosk_browser("cont")

        with self.lock:
            try:
                if session.log_file and not session.log_file.closed:
                    session.log_file.write(f"\n--- Sessione RDP [ID: {session.session_id}] terminata con codice {retcode} ({time.strftime('%Y-%m-%d %H:%M:%S')}) ---\n")
                    session.log_file.close()
            except Exception:
                pass

            # Only update shared manager state if this session is still the active session!
            if self.active_session is session:
                self.active_session = None
                session.state = "IDLE"
                if session.user_cancelled:
                    self.last_error = None
                elif retcode not in (0, 130, 143):  # 130=SIGINT, 143=SIGTERM
                    session.error_message = get_freerdp_error_description(retcode)
                    self.last_error = session.error_message
                    logger.warning(f"FreeRDP [Session {session.session_id}] exited with code {retcode}: {session.error_message}")
                else:
                    self.last_error = None
            else:
                logger.info(f"Old session {session.session_id} monitor completed; active session is {getattr(self.active_session, 'session_id', None)}")

    def disconnect(self):
        """Terminates the active RDP session and overlay cleanly."""
        with self.lock:
            session = self.active_session
            if session and session.process and session.process.poll() is None:
                session.user_cancelled = True
                session.state = "DISCONNECTING"
                self._stop_overlay(session)
                coordinate_kiosk_browser("cont")
                try:
                    session.process.terminate()
                    try:
                        session.process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        session.process.kill()
                        session.process.wait(timeout=0.5)
                except Exception as e:
                    logger.warning(f"Error terminating FreeRDP: {e}")
                self.active_session = None
                return True, "Sessione interrotta"
            return True, "Nessuna sessione attiva"

rdp_manager = RDPManager()
