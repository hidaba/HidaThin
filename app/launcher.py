#!/usr/bin/env python3
"""
HidaThin Native Kiosk Launcher (WTware-Style)
Ultra-lightweight native Tkinter launcher for Raspberry Pi thin client.
Footprint: ~25 MB RAM, sub-second boot time (< 250 ms).
Replaces heavy Chromium kiosk while keeping the Flask backend for remote administration.
"""

import sys
import os
import time
import json
import socket
import argparse
import logging
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import font as tkfont

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import __version__

logging.basicConfig(level=logging.INFO, format="%(asctime)s [launcher] %(levelname)s: %(message)s")
logger = logging.getLogger("launcher")

# --- Visual Theme (Dark Slate / Cyberpunk - 1:1 match with HidaThin OSD & Web) ---
COLOR_BG = "#0f172a"            # Slate 900
COLOR_SURFACE = "#1e293b"       # Slate 800
COLOR_SURFACE_HOVER = "#243248" # Slate 750
COLOR_SURFACE_LIGHT = "#334155" # Slate 700
COLOR_BORDER = "#334155"        # Slate 700
COLOR_BORDER_FOCUS = "#38bdf8"  # Sky 400
COLOR_TEXT_MAIN = "#f8fafc"     # Slate 50
COLOR_TEXT_MUTED = "#94a3b8"    # Slate 400
COLOR_ACCENT = "#0284c7"        # Sky 600
COLOR_ACCENT_HOVER = "#0369a1"  # Sky 700
COLOR_ACCENT_LIGHT = "#38bdf8"  # Sky 400
COLOR_SUCCESS = "#4ade80"       # Green 400
COLOR_WARNING = "#facc15"       # Yellow 400
COLOR_DANGER = "#dc2626"        # Red 600
COLOR_DANGER_HOVER = "#b91c1c"  # Red 700

class NativeLauncherApp:
    def __init__(self, server_url="http://127.0.0.1:8080", windowed=False):
        self.server_url = server_url.rstrip("/")
        self.windowed = windowed

        self.root = tk.Tk()
        self.root.title(f"HidaThin Launcher v{__version__}")
        self.root.configure(bg=COLOR_BG)

        # State data
        self.hosts_data = {}
        self.default_host_key = ""
        self.system_status = {}
        self.is_connected_rdp = False
        self.rdp_monitor_active = False
        self.direct_rdp_cancelled = False
        self.direct_rdp_timer = None
        self.auto_connect_remaining = 3

        # Configure geometry / fullscreen
        if not self.windowed:
            try:
                self.root.attributes("-fullscreen", True)
            except Exception:
                self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        else:
            self.root.geometry("1024x700")

        # Key bindings
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.on_escape)
        self.root.bind("<F5>", lambda e: self.refresh_all(force=True))

        # Typography
        self.font_title = tkfont.Font(family="DejaVu Sans", size=15, weight="bold")
        self.font_badge = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")
        self.font_subtitle = tkfont.Font(family="DejaVu Sans", size=9)
        self.font_card_title = tkfont.Font(family="DejaVu Sans", size=13, weight="bold")
        self.font_card_desc = tkfont.Font(family="DejaVu Sans", size=9)
        self.font_btn = tkfont.Font(family="DejaVu Sans", size=10, weight="bold")
        self.font_btn_sm = tkfont.Font(family="DejaVu Sans", size=8, weight="bold")
        self.font_clock = tkfont.Font(family="DejaVu Sans", size=10, weight="bold")

        # Build UI containers
        self._build_header_ui()
        self._build_banner_ui()
        self._build_content_ui()
        self._build_footer_ui()

        # Initial data load
        self.refresh_all(initial=True)

        # Timers
        self._tick_clock()
        self.root.after(5000, self._periodic_status_poll)

    # --- HTTP API Helpers (Non-blocking) ---

    def _api_get(self, endpoint, timeout=2.0):
        try:
            req = urllib.request.Request(
                f"{self.server_url}{endpoint}",
                headers={"User-Agent": "HidaThin-Launcher"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.debug(f"API GET {endpoint} failed: {e}")
            return None

    def _api_post(self, endpoint, data=None, timeout=4.0):
        try:
            payload = json.dumps(data or {}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.server_url}{endpoint}",
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "HidaThin-Launcher"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"API POST {endpoint} failed: {e}")
            return {"success": False, "message": str(e)}

    # --- UI Building ---

    def _build_header_ui(self):
        self.header_frame = tk.Frame(self.root, bg=COLOR_SURFACE, height=64, padx=16, pady=10)
        self.header_frame.pack(side=tk.TOP, fill=tk.X)
        self.header_frame.pack_propagate(False)

        # Brand / Logo (Left)
        brand_frame = tk.Frame(self.header_frame, bg=COLOR_SURFACE)
        brand_frame.pack(side=tk.LEFT, fill=tk.Y)

        title_lbl = tk.Label(
            brand_frame,
            text="⚡ HIDATHIN",
            font=self.font_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE
        )
        title_lbl.pack(side=tk.LEFT)

        ver_badge = tk.Label(
            brand_frame,
            text=f"v{__version__}",
            font=self.font_badge,
            fg=COLOR_ACCENT_LIGHT,
            bg=COLOR_SURFACE_LIGHT,
            padx=6,
            pady=2
        )
        ver_badge.pack(side=tk.LEFT, padx=(8, 0))

        # Status Pill (Center)
        self.status_pill = tk.Frame(
            self.header_frame,
            bg=COLOR_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=12,
            pady=4
        )
        self.status_pill.pack(side=tk.LEFT, expand=True)

        self.lbl_net_status = tk.Label(
            self.status_pill,
            text="● Rete: Connessione in corso...",
            font=self.font_subtitle,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG
        )
        self.lbl_net_status.pack(side=tk.LEFT, padx=(0, 10))

        sep = tk.Label(self.status_pill, text="|", font=self.font_subtitle, fg=COLOR_BORDER, bg=COLOR_BG)
        sep.pack(side=tk.LEFT, padx=(0, 10))

        self.lbl_ts_status = tk.Label(
            self.status_pill,
            text="● Tailscale: Inizializzazione...",
            font=self.font_subtitle,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG
        )
        self.lbl_ts_status.pack(side=tk.LEFT)

        # Quick Actions (Right)
        actions_frame = tk.Frame(self.header_frame, bg=COLOR_SURFACE)
        actions_frame.pack(side=tk.RIGHT, fill=tk.Y)

        btn_wifi = tk.Button(
            actions_frame,
            text="Wi-Fi",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BORDER_FOCUS,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=self.open_wifi_dialog
        )
        btn_wifi.pack(side=tk.LEFT, padx=4)

        btn_admin = tk.Button(
            actions_frame,
            text="Web Admin",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BORDER_FOCUS,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=self.open_web_admin_info
        )
        btn_admin.pack(side=tk.LEFT, padx=4)

        btn_reboot = tk.Button(
            actions_frame,
            text="Riavvia",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_WARNING,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=self.confirm_reboot
        )
        btn_reboot.pack(side=tk.LEFT, padx=4)

        btn_power = tk.Button(
            actions_frame,
            text="Spegni",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_DANGER,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_DANGER_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=4,
            command=self.confirm_poweroff
        )
        btn_power.pack(side=tk.LEFT, padx=(4, 0))

    def _build_banner_ui(self):
        """Notification & Auto-Connect Countdown Banner."""
        self.banner_frame = tk.Frame(self.root, bg=COLOR_SURFACE_LIGHT, padx=16, pady=8)
        # Hidden by default, packed when needed

        self.banner_label = tk.Label(
            self.banner_frame,
            text="",
            font=self.font_btn,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT
        )
        self.banner_label.pack(side=tk.LEFT, expand=True)

        self.banner_btn = tk.Button(
            self.banner_frame,
            text="Annulla",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_DANGER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=12,
            pady=4,
            command=self.cancel_direct_rdp
        )
        self.banner_btn.pack(side=tk.RIGHT)

    def _build_content_ui(self):
        """Central hosts grid area with scrolling canvas."""
        self.content_container = tk.Frame(self.root, bg=COLOR_BG, padx=24, pady=16)
        self.content_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        # Section Header
        sec_header = tk.Frame(self.content_container, bg=COLOR_BG)
        sec_header.pack(fill=tk.X, pady=(0, 12))

        lbl_sec = tk.Label(
            sec_header,
            text="POSTAZIONI REMOTE DISPONIBILI",
            font=self.font_card_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BG
        )
        lbl_sec.pack(side=tk.LEFT)

        self.lbl_refresh_status = tk.Label(
            sec_header,
            text="Aggiornato",
            font=self.font_subtitle,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG
        )
        self.lbl_refresh_status.pack(side=tk.RIGHT)

        # Scrollable Canvas
        self.canvas = tk.Canvas(self.content_container, bg=COLOR_BG, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self.content_container, orient=tk.VERTICAL, command=self.canvas.yview)
        self.cards_frame = tk.Frame(self.canvas, bg=COLOR_BG)

        self.cards_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.cards_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

    def _on_frame_configure(self, event):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        canvas_width = event.width
        self.canvas.itemconfig(self.canvas_window, width=canvas_width)

    def _build_footer_ui(self):
        self.footer_frame = tk.Frame(self.root, bg=COLOR_SURFACE, height=36, padx=16, pady=6)
        self.footer_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.footer_frame.pack_propagate(False)

        # Clock (Left)
        self.lbl_clock = tk.Label(
            self.footer_frame,
            text="--:--:--",
            font=self.font_clock,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE
        )
        self.lbl_clock.pack(side=tk.LEFT)

        # Filesystem Status (Center)
        self.lbl_fs_status = tk.Label(
            self.footer_frame,
            text="● Filesystem: Verifica...",
            font=self.font_subtitle,
            fg=COLOR_SUCCESS,
            bg=COLOR_SURFACE
        )
        self.lbl_fs_status.pack(side=tk.LEFT, expand=True)

        # Web Admin URL hint (Right)
        self.lbl_web_hint = tk.Label(
            self.footer_frame,
            text=f"Pannello Web: {self.server_url}",
            font=self.font_subtitle,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_SURFACE
        )
        self.lbl_web_hint.pack(side=tk.RIGHT)

    # --- Data Fetching & Refresh ---

    def refresh_all(self, initial=False, force=False):
        """Fetches fresh boot/status, hosts, and settings in background."""
        self.lbl_refresh_status.config(text="Aggiornamento in corso...")
        threading.Thread(target=self._fetch_worker, args=(initial, force), daemon=True).start()

    def _fetch_worker(self, initial=False, force=False):
        # 1. Fetch system status from API
        status = self._api_get(f"/api/boot/status?force={'1' if force else '0'}") or {}
        
        # 2. Fetch hosts data directly from backend if available or local file
        hosts_info = {}
        default_host = ""
        try:
            from app.main import load_hosts_data
            raw = load_hosts_data(include_passwords=False)
            hosts_info = raw.get("hosts", {})
            default_host = raw.get("default_host", "")
        except Exception:
            pass

        # 3. Fetch filesystem status
        fs_info = self._api_get("/api/system/fs-status") or {}

        # 4. Dispatch to UI thread
        self.root.after(0, lambda: self._apply_data(status, hosts_info, default_host, fs_info, initial))

    def _apply_data(self, status, hosts_info, default_host, fs_info, initial):
        self.system_status = status
        self.hosts_data = hosts_info
        self.default_host_key = default_host

        # Update Network Pill
        net = status.get("network", {})
        wf = net.get("wifi", {})
        eth = net.get("ethernet", {})
        ts = status.get("tailscale", {})

        if wf.get("connected") and wf.get("ip"):
            net_text = f"● Wi-Fi: {wf.get('ssid') or 'Connesso'} ({wf.get('ip')})"
            net_fg = COLOR_SUCCESS
        elif eth.get("connected") and eth.get("ip"):
            net_text = f"● Ethernet: {eth.get('ip')}"
            net_fg = COLOR_SUCCESS
        elif net.get("primary_ip"):
            net_text = f"● Rete: {net.get('primary_ip')}"
            net_fg = COLOR_SUCCESS
        else:
            net_text = "✕ Rete: Disconnesso"
            net_fg = COLOR_DANGER

        self.lbl_net_status.config(text=net_text, fg=net_fg)

        if ts.get("connected") and ts.get("ip"):
            ts_text = f"● Tailscale: {ts.get('ip')}"
            ts_fg = COLOR_SUCCESS
        else:
            ts_text = "○ Tailscale: Non attivo"
            ts_fg = COLOR_WARNING

        self.lbl_ts_status.config(text=ts_text, fg=ts_fg)

        # Update FS Status
        if fs_info.get("root_ro"):
            self.lbl_fs_status.config(text="● Filesystem: Sola Lettura (RO - Protetto)", fg=COLOR_SUCCESS)
        else:
            self.lbl_fs_status.config(text="● Filesystem: Scrittura (RW - Modificabile)", fg=COLOR_WARNING)

        # Update Web Hint with Tailscale or primary IP
        primary_ip = ts.get("ip") or net.get("primary_ip") or "127.0.0.1"
        self.lbl_web_hint.config(text=f"Pannello Web: http://{primary_ip}:8080")

        # Render Host Cards
        self._render_host_cards()
        self.lbl_refresh_status.config(text=f"Aggiornato alle {time.strftime('%H:%M:%S')}")

        # Check Direct RDP Auto-connect on startup
        if initial:
            startup = status.get("startup", {})
            if startup.get("mode") == "direct_rdp" and self.default_host_key:
                self._start_direct_rdp_countdown()

    def _render_host_cards(self):
        """Renders grid of host cards."""
        for widget in self.cards_frame.winfo_children():
            widget.destroy()

        if not self.hosts_data:
            empty_lbl = tk.Label(
                self.cards_frame,
                text="Nessun host configurato. Accedi al Pannello Web per aggiungere postazioni remote.",
                font=self.font_subtitle,
                fg=COLOR_TEXT_MUTED,
                bg=COLOR_BG,
                pady=40
            )
            empty_lbl.pack()
            return

        cols = 2
        col_idx = 0
        row_idx = 0

        # Grid column weights
        for c in range(cols):
            self.cards_frame.grid_columnconfigure(c, weight=1, uniform="hosts")

        for key, host in self.hosts_data.items():
            card = self._create_host_card(key, host)
            card.grid(row=row_idx, column=col_idx, padx=10, pady=10, sticky="nsew")

            col_idx += 1
            if col_idx >= cols:
                col_idx = 0
                row_idx += 1

    def _create_host_card(self, key, host):
        is_default = (key == self.default_host_key)
        has_pwd = bool(host.get("has_password"))

        card = tk.Frame(
            self.cards_frame,
            bg=COLOR_SURFACE,
            highlightbackground=COLOR_BORDER_FOCUS if is_default else COLOR_BORDER,
            highlightthickness=1,
            padx=16,
            pady=14
        )

        # Header Row
        header = tk.Frame(card, bg=COLOR_SURFACE)
        header.pack(fill=tk.X, pady=(0, 6))

        title = tk.Label(
            header,
            text=f"◆  {host.get('name') or key}",
            font=self.font_card_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE,
            anchor="w"
        )
        title.pack(side=tk.LEFT)

        if is_default:
            badge_def = tk.Label(
                header,
                text="★ PREDEFINITO",
                font=self.font_badge,
                fg=COLOR_ACCENT_LIGHT,
                bg=COLOR_SURFACE_LIGHT,
                padx=6,
                pady=1
            )
            badge_def.pack(side=tk.RIGHT)
        else:
            btn_def = tk.Button(
                header,
                text="★ Imposta predefinito",
                font=self.font_badge,
                fg=COLOR_ACCENT_LIGHT,
                bg=COLOR_SURFACE,
                activeforeground=COLOR_TEXT_MAIN,
                activebackground=COLOR_SURFACE_LIGHT,
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                command=lambda k=key: self.set_default_host(k)
            )
            btn_def.pack(side=tk.RIGHT)

        # Host details
        target = host.get("hostname") or host.get("ip") or "--"
        port = host.get("port", 3389)
        user = host.get("username") or "default"

        lbl_target = tk.Label(
            card,
            text=f"Destinazione: {target}:{port}  •  Utente: {user}",
            font=self.font_card_desc,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_SURFACE,
            anchor="w"
        )
        lbl_target.pack(fill=tk.X, pady=(0, 10))

        # Action Buttons Container
        btn_bar = tk.Frame(card, bg=COLOR_SURFACE)
        btn_bar.pack(fill=tk.X, pady=(4, 0))

        connect_text = "CONNETTI" if has_pwd else "CONNETTI (Password...)"
        btn_connect = tk.Button(
            btn_bar,
            text=connect_text,
            font=self.font_btn,
            fg="#ffffff",
            bg=COLOR_ACCENT,
            activeforeground="#ffffff",
            activebackground=COLOR_ACCENT_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=14,
            pady=8,
            command=lambda k=key, h=host: self.on_connect_clicked(k, h)
        )
        btn_connect.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_cred = tk.Button(
            btn_bar,
            text="Opzioni...",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BORDER_FOCUS,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=8,
            command=lambda k=key, h=host: self.open_credentials_dialog(k, h)
        )
        btn_cred.pack(side=tk.RIGHT)

        return card

    def set_default_host(self, host_key):
        """Sets selected host as default via backend API and updates UI."""
        def worker():
            res = self._api_post("/api/hosts/set-default", {"key": host_key})
            if res.get("success"):
                msg = res.get("message") or "Host predefinito aggiornato con successo."
                self.root.after(0, lambda: self.show_banner(f"✓ {msg}", bg="#15803d", dismissable=True, auto_hide=3500))
                self.root.after(0, lambda: self.refresh_all(force=True))
            else:
                err = res.get("message") or "Impossibile impostare host predefinito."
                self.root.after(0, lambda: self.show_banner(f"⚠️ Errore: {err}", bg=COLOR_DANGER, dismissable=True))

        threading.Thread(target=worker, daemon=True).start()

    # --- Direct RDP Auto-Connect Handling ---

    def _start_direct_rdp_countdown(self):
        if self.direct_rdp_cancelled:
            return

        self.auto_connect_remaining = 3
        default_name = self.hosts_data.get(self.default_host_key, {}).get("name") or self.default_host_key

        self.banner_frame.pack(side=tk.TOP, fill=tk.X, before=self.content_container)
        self.banner_frame.config(bg="#0369a1")
        self.banner_label.config(
            text=f"Avvio automatico verso '{default_name}' tra {self.auto_connect_remaining} secondi...",
            bg="#0369a1"
        )
        self.banner_btn.config(text="✖ Annulla Avvio Automatico", state=tk.NORMAL)

        self._countdown_tick()

    def _countdown_tick(self):
        if self.direct_rdp_cancelled:
            return

        if self.auto_connect_remaining > 0:
            default_name = self.hosts_data.get(self.default_host_key, {}).get("name") or self.default_host_key
            self.banner_label.config(
                text=f"Avvio automatico verso '{default_name}' tra {self.auto_connect_remaining} secondi..."
            )
            self.auto_connect_remaining -= 1
            self.direct_rdp_timer = self.root.after(1000, self._countdown_tick)
        else:
            # Trigger auto-connection
            self.banner_label.config(text="Avvio connessione remota...")
            self.banner_btn.config(state=tk.DISABLED)
            host_info = self.hosts_data.get(self.default_host_key, {})
            self.on_connect_clicked(self.default_host_key, host_info)

    def cancel_direct_rdp(self):
        self.direct_rdp_cancelled = True
        if self.direct_rdp_timer:
            self.root.after_cancel(self.direct_rdp_timer)
            self.direct_rdp_timer = None
        self.banner_frame.pack_forget()
        logger.info("Direct RDP countdown cancelled by user.")

    # --- Connection & Session Management ---

    def on_connect_clicked(self, host_key, host_info):
        """Handles connect click. Prompts for password if missing."""
        has_pwd = bool(host_info.get("has_password"))
        if not has_pwd:
            self.open_credentials_dialog(host_key, host_info)
        else:
            self._do_connect(host_key, username=host_info.get("username"), password=None, save_password=False)

    def _do_connect(self, host_key, username=None, password=None, save_password=False):
        """Initiates RDP connection via REST API and monitors lifecycle."""
        host_name = self.hosts_data.get(host_key, {}).get("name") or host_key
        self.show_banner(f"Connessione a {host_name} in corso...", bg=COLOR_ACCENT)

        def connect_worker():
            payload = {
                "host_key": host_key,
                "username": username,
                "password": password,
                "save_password": save_password
            }
            res = self._api_post("/api/rdp/connect", payload, timeout=6.0)
            self.root.after(0, lambda: self._handle_connect_result(res, host_name))

        threading.Thread(target=connect_worker, daemon=True).start()

    def _handle_connect_result(self, res, host_name):
        if not res.get("success"):
            err_msg = res.get("message", "Errore sconosciuto")
            self.show_banner(f"⚠️ Errore connessione a {host_name}: {err_msg}", bg=COLOR_DANGER, dismissable=True)
            logger.warning(f"Connection failed: {err_msg}")
            return

        # FreeRDP launched successfully!
        # Hide launcher window to release display to FreeRDP fullscreen
        logger.info(f"RDP session initiated for {host_name}. Hiding launcher window...")
        self.is_connected_rdp = True
        self.banner_frame.pack_forget()

        # Hide window
        self.root.withdraw()

        # Start background monitor for RDP session end
        self._start_rdp_session_monitor(host_name)

    def _start_rdp_session_monitor(self, host_name):
        """Polls /api/rdp/status until session terminates, then brings launcher back."""
        def monitor_worker():
            time.sleep(2.0)
            while True:
                status = self._api_get("/api/rdp/status") or {}
                state = status.get("state", "IDLE")

                if state in ("IDLE", "ERROR"):
                    logger.info(f"RDP session ended with state: {state}")
                    self.root.after(0, lambda: self._on_rdp_session_ended(status, host_name))
                    break
                time.sleep(1.5)

        threading.Thread(target=monitor_worker, daemon=True).start()

    def _on_rdp_session_ended(self, final_status, host_name):
        """Brings launcher back instantly when FreeRDP exits."""
        self.is_connected_rdp = False
        self.root.deiconify()
        self.root.lift()

        # Check for error
        err = final_status.get("error_message")
        if err:
            self.show_banner(f"Sessione con {host_name} terminata: {err}", bg=COLOR_DANGER, dismissable=True)
        else:
            self.show_banner(f"Sessione con {host_name} terminata.", bg=COLOR_SURFACE_LIGHT, dismissable=True, auto_hide=4000)

        # Refresh host reachability and status
        self.refresh_all(force=True)

    def show_banner(self, text, bg=COLOR_SURFACE_LIGHT, dismissable=False, auto_hide=None):
        self.banner_frame.pack(side=tk.TOP, fill=tk.X, before=self.content_container)
        self.banner_frame.config(bg=bg)
        self.banner_label.config(text=text, bg=bg)

        if dismissable:
            self.banner_btn.config(text="✖ Chiudi", state=tk.NORMAL, command=self.banner_frame.pack_forget)
        else:
            self.banner_btn.config(text="", state=tk.DISABLED)

        if auto_hide:
            self.root.after(auto_hide, self.banner_frame.pack_forget)

    # --- Modals and Dialogs ---

    def open_credentials_dialog(self, host_key, host_info):
        """Modal dialog to enter/modify credentials for a host."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Credenziali Postazione")
        dialog.geometry("450x360")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        # Center over parent
        self._center_window(dialog, 450, 360)

        # Header
        lbl_h = tk.Label(
            dialog,
            text=f"Credenziali per {host_info.get('name') or host_key}",
            font=self.font_card_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE
        )
        lbl_h.pack(pady=(16, 4))

        target = host_info.get("hostname") or host_info.get("ip") or "--"
        lbl_sub = tk.Label(
            dialog,
            text=f"Destinazione: {target}:{host_info.get('port', 3389)}",
            font=self.font_subtitle,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_SURFACE
        )
        lbl_sub.pack(pady=(0, 16))

        # Form fields
        form = tk.Frame(dialog, bg=COLOR_SURFACE, padx=24)
        form.pack(fill=tk.X)

        tk.Label(form, text="Nome Utente:", font=self.font_btn_sm, fg=COLOR_TEXT_MUTED, bg=COLOR_SURFACE, anchor="w").pack(fill=tk.X)
        entry_user = tk.Entry(form, font=self.font_btn, bg=COLOR_SURFACE_LIGHT, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_user.insert(0, host_info.get("username") or "")
        entry_user.pack(fill=tk.X, pady=(2, 10), ipady=4)

        tk.Label(form, text="Password:", font=self.font_btn_sm, fg=COLOR_TEXT_MUTED, bg=COLOR_SURFACE, anchor="w").pack(fill=tk.X)
        entry_pwd = tk.Entry(form, font=self.font_btn, show="●", bg=COLOR_SURFACE_LIGHT, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_pwd.pack(fill=tk.X, pady=(2, 10), ipady=4)

        var_save = tk.BooleanVar(value=True)
        chk_save = tk.Checkbutton(
            form,
            text="Salva password su questo dispositivo per i prossimi accessi",
            variable=var_save,
            font=self.font_subtitle,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE,
            activebackground=COLOR_SURFACE,
            activeforeground=COLOR_TEXT_MAIN,
            selectcolor=COLOR_SURFACE_LIGHT
        )
        chk_save.pack(anchor="w", pady=(0, 16))

        # Buttons
        btn_box = tk.Frame(dialog, bg=COLOR_SURFACE, padx=24)
        btn_box.pack(fill=tk.X, pady=(0, 16))

        def submit():
            u = entry_user.get().strip()
            p = entry_pwd.get()
            s = var_save.get()
            dialog.destroy()
            self._do_connect(host_key, username=u, password=p, save_password=s)

        btn_cancel = tk.Button(
            btn_box,
            text="Annulla",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=16,
            pady=8,
            command=dialog.destroy
        )
        btn_cancel.pack(side=tk.LEFT)

        btn_go = tk.Button(
            btn_box,
            text="Connetti Subito",
            font=self.font_btn,
            fg="#ffffff",
            bg=COLOR_ACCENT,
            activebackground=COLOR_ACCENT_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=20,
            pady=8,
            command=submit
        )
        btn_go.pack(side=tk.RIGHT)

        entry_pwd.bind("<Return>", lambda e: submit())
        entry_pwd.focus_set()

    def open_wifi_dialog(self):
        """Modal dialog to scan and connect to Wi-Fi networks."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Configurazione Wi-Fi")
        dialog.geometry("520x460")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        self._center_window(dialog, 520, 460)

        lbl_h = tk.Label(
            dialog,
            text="Reti Wi-Fi Disponibili",
            font=self.font_card_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE
        )
        lbl_h.pack(pady=(16, 6))

        status_lbl = tk.Label(
            dialog,
            text="Scansione reti in corso...",
            font=self.font_subtitle,
            fg=COLOR_ACCENT_LIGHT,
            bg=COLOR_SURFACE
        )
        status_lbl.pack(pady=(0, 10))

        # Listbox for SSIDs
        list_frame = tk.Frame(dialog, bg=COLOR_SURFACE, padx=20)
        list_frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(
            list_frame,
            font=self.font_btn,
            bg=COLOR_SURFACE_LIGHT,
            fg=COLOR_TEXT_MAIN,
            selectbackground=COLOR_ACCENT,
            selectforeground="#ffffff",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_BORDER
        )
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)

        # Form for selected SSID & Password
        form = tk.Frame(dialog, bg=COLOR_SURFACE, padx=20, pady=10)
        form.pack(fill=tk.X)

        tk.Label(form, text="Rete selezionata:", font=self.font_btn_sm, fg=COLOR_TEXT_MUTED, bg=COLOR_SURFACE, anchor="w").pack(fill=tk.X)
        entry_ssid = tk.Entry(form, font=self.font_btn, bg=COLOR_SURFACE_LIGHT, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_ssid.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text="Password Wi-Fi:", font=self.font_btn_sm, fg=COLOR_TEXT_MUTED, bg=COLOR_SURFACE, anchor="w").pack(fill=tk.X)
        entry_pwd = tk.Entry(form, font=self.font_btn, show="●", bg=COLOR_SURFACE_LIGHT, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_pwd.pack(fill=tk.X, pady=(2, 8), ipady=3)

        def on_select(evt):
            sel = listbox.curselection()
            if sel:
                item = listbox.get(sel[0])
                # Format: "SSID (Segnale: 85% - Protetto)"
                ssid = item.split(" (")[0]
                entry_ssid.delete(0, tk.END)
                entry_ssid.insert(0, ssid)
                entry_pwd.focus_set()

        listbox.bind("<<ListboxSelect>>", on_select)

        # Background scan worker
        def scan_worker():
            res = self._api_post("/api/wifi/scan")
            networks = res if isinstance(res, list) else []
            self.root.after(0, lambda: apply_scan(networks))

        def apply_scan(networks):
            listbox.delete(0, tk.END)
            if not networks:
                status_lbl.config(text="Nessuna rete Wi-Fi trovata.", fg=COLOR_WARNING)
                return
            status_lbl.config(text=f"Trovate {len(networks)} reti. Selezionane una:", fg=COLOR_TEXT_MUTED)
            for n in networks:
                sec = "[PROTETTA]" if n.get("security") else "[APERTA]"
                sig = f"{n.get('signal', 0)}%"
                listbox.insert(tk.END, f"{n.get('ssid')} ({sec} Segnale: {sig})")

        threading.Thread(target=scan_worker, daemon=True).start()

        # Connect action
        def do_connect():
            ssid = entry_ssid.get().strip()
            pwd = entry_pwd.get()
            if not ssid:
                return
            status_lbl.config(text=f"Connessione a '{ssid}' in corso...", fg=COLOR_ACCENT_LIGHT)

            def conn_worker():
                res = self._api_post("/api/wifi/connect", {"ssid": ssid, "password": pwd}, timeout=12.0)
                self.root.after(0, lambda: on_conn_done(res))

            def on_conn_done(res):
                if res.get("success"):
                    status_lbl.config(text="Connesso con successo!", fg=COLOR_SUCCESS)
                    self.root.after(1200, dialog.destroy)
                    self.refresh_all(force=True)
                else:
                    status_lbl.config(text=f"Errore: {res.get('message')}", fg=COLOR_DANGER)

            threading.Thread(target=conn_worker, daemon=True).start()

        btn_box = tk.Frame(dialog, bg=COLOR_SURFACE, padx=20, pady=6)
        btn_box.pack(fill=tk.X)

        btn_rescan = tk.Button(
            btn_box,
            text="Riscansiona",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=12,
            pady=6,
            command=lambda: threading.Thread(target=scan_worker, daemon=True).start()
        )
        btn_rescan.pack(side=tk.LEFT)

        btn_conn = tk.Button(
            btn_box,
            text="Connetti a Wi-Fi",
            font=self.font_btn,
            fg="#ffffff",
            bg=COLOR_ACCENT,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=16,
            pady=6,
            command=do_connect
        )
        btn_conn.pack(side=tk.RIGHT)

    def open_web_admin_info(self):
        """Information popup displaying how to connect to the Web Admin UI."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Pannello Web Admin")
        dialog.geometry("480x280")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        self._center_window(dialog, 480, 280)

        lbl_h = tk.Label(
            dialog,
            text="Amministrazione e Diagnostica Avanzata",
            font=self.font_card_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE
        )
        lbl_h.pack(pady=(20, 10))

        ts_ip = self.system_status.get("tailscale", {}).get("ip")
        lan_ip = self.system_status.get("network", {}).get("primary_ip") or "127.0.0.1"

        msg = (
            "Il backend Flask è attivo e consente la configurazione remota completa\n"
            "(diagnostica, parametri FreeRDP, overscan display, aggiornamento OS Debian).\n\n"
            f"Indirizzo LAN Locale:    http://{lan_ip}:8080\n"
        )
        if ts_ip:
            msg += f"Indirizzo Tailscale VPN:  http://{ts_ip}:8080\n"

        lbl_info = tk.Label(
            dialog,
            text=msg,
            font=self.font_subtitle,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE,
            justify=tk.LEFT,
            padx=20
        )
        lbl_info.pack(fill=tk.BOTH, expand=True)

        btn_close = tk.Button(
            dialog,
            text="Chiudi",
            font=self.font_btn,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=16,
            pady=6,
            command=dialog.destroy
        )
        btn_close.pack(pady=(0, 16))

    def confirm_reboot(self):
        self._confirm_system_action(
            title="Riavvio del Sistema",
            prompt="Sei sicuro di voler riavviare il thin client?",
            api_endpoint="/api/system/reboot"
        )

    def confirm_poweroff(self):
        self._confirm_system_action(
            title="Spegnimento Dispositivo",
            prompt="Sei sicuro di voler spegnere completamente il thin client?",
            api_endpoint="/api/system/poweroff"
        )

    def _confirm_system_action(self, title, prompt, api_endpoint):
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.geometry("400x180")
        dialog.configure(bg=COLOR_SURFACE)
        dialog.transient(self.root)
        dialog.grab_set()

        self._center_window(dialog, 400, 180)

        lbl_t = tk.Label(dialog, text=title, font=self.font_card_title, fg=COLOR_WARNING, bg=COLOR_SURFACE)
        lbl_t.pack(pady=(16, 8))

        lbl_m = tk.Label(dialog, text=prompt, font=self.font_subtitle, fg=COLOR_TEXT_MAIN, bg=COLOR_SURFACE)
        lbl_m.pack(pady=(0, 16))

        btn_box = tk.Frame(dialog, bg=COLOR_SURFACE, padx=20)
        btn_box.pack(fill=tk.X)

        btn_no = tk.Button(
            btn_box,
            text="Annulla",
            font=self.font_btn_sm,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_SURFACE_LIGHT,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=16,
            pady=6,
            command=dialog.destroy
        )
        btn_no.pack(side=tk.LEFT)

        def do_action():
            dialog.destroy()
            self.show_banner("Comando inviato al sistema...", bg=COLOR_WARNING)
            threading.Thread(target=lambda: self._api_post(api_endpoint), daemon=True).start()

        btn_yes = tk.Button(
            btn_box,
            text="Conferma",
            font=self.font_btn,
            fg="#ffffff",
            bg=COLOR_DANGER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=16,
            pady=6,
            command=do_action
        )
        btn_yes.pack(side=tk.RIGHT)

    def _center_window(self, win, w, h):
        win.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")

    # --- Window State & Hotkeys ---

    def toggle_fullscreen(self, event=None):
        cur = self.root.attributes("-fullscreen")
        self.root.attributes("-fullscreen", not cur)

    def on_escape(self, event=None):
        if self.direct_rdp_timer and not self.direct_rdp_cancelled:
            self.cancel_direct_rdp()
            return
        if self.windowed:
            self.root.destroy()
        else:
            # In kiosk mode, toggle off fullscreen for local development
            try:
                self.root.attributes("-fullscreen", False)
            except Exception:
                pass

    def _tick_clock(self):
        self.lbl_clock.config(text=time.strftime("%a %d %b %Y  %H:%M:%S"))
        self.root.after(1000, self._tick_clock)

    def _periodic_status_poll(self):
        if not self.is_connected_rdp:
            self.refresh_all(force=False)
        self.root.after(10000, self._periodic_status_poll)

    def run(self):
        self.root.mainloop()

def main():
    parser = argparse.ArgumentParser(description="HidaThin Native Kiosk Launcher (WTware-Style)")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="Flask backend base URL")
    parser.add_argument("--windowed", action="store_true", help="Launch in windowed mode (non-fullscreen)")
    args = parser.parse_args()

    app = NativeLauncherApp(server_url=args.server, windowed=args.windowed)
    app.run()

if __name__ == "__main__":
    main()
