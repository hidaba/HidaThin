#!/usr/bin/env python3
"""
HidaThin Native Kiosk Launcher (WTware-Style)
Faithful 1:1 reproduction of the original HidaThin Web Kiosk Dashboard.
Ultra-lightweight native Tkinter: ~25 MB RAM, sub-second boot (< 250 ms).
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
from tkinter import ttk, font as tkfont, messagebox

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import __version__

logging.basicConfig(level=logging.INFO, format="%(asctime)s [launcher] %(levelname)s: %(message)s")
logger = logging.getLogger("launcher")

# --- Exact Color Palette from style.css & screen_clean.png ---
COLOR_BG = "#0b1120"            # Deep slate / navy background
COLOR_CARD = "#1e293b"          # Slate 800 (Card background)
COLOR_CARD_BORDER = "#334155"   # Slate 700 (Card border)
COLOR_INNER_BOX = "#0f172a"     # Slate 900 (Inner box / input background)
COLOR_INNER_BORDER = "#334155"  # Inner border
COLOR_TEXT_MAIN = "#f8fafc"     # Slate 50 (Main text)
COLOR_TEXT_MUTED = "#94a3b8"    # Slate 400 (Secondary / labels)
COLOR_TITLE_CYAN = "#60a5fa"    # Sky / Blue (Title text)
COLOR_ACCENT_BLUE = "#3b82f6"   # Blue 500 (Focus borders / highlights)
COLOR_SUCCESS = "#4ade80"       # Green 400 (Status connected / SSID)
COLOR_BTN_CONNECT = "#16a34a"   # Green 600 (Connect button)
COLOR_BTN_CONNECT_HOVER = "#15803d" # Green 700
COLOR_BTN_SECONDARY = "#334155" # Slate 700 (Nav buttons)
COLOR_BTN_SECONDARY_HOVER = "#475569" # Slate 600
COLOR_BTN_DANGER = "#7f1d1d"    # Red 900 (Spegni soft)
COLOR_BTN_DANGER_HOVER = "#991b1b" # Red 800
COLOR_BTN_CANCEL = "#dc2626"    # Red 600 (Cancel connection)
COLOR_LINK = "#93c5fd"          # Light sky blue (Links)

class NativeLauncherApp:
    def __init__(self, server_url="http://127.0.0.1:8080", windowed=False):
        self.server_url = server_url.rstrip("/")
        self.windowed = windowed

        self.root = tk.Tk()
        self.root.title(f"HiDaThin - Thin Client RDP v{__version__}")
        self.root.configure(bg=COLOR_BG)

        # State data
        self.hosts_data = {}
        self.default_host_key = ""
        self.host_keys_order = []
        self.selected_host_key = ""
        self.transient_drafts = {}
        self.system_status = {}
        self.is_connected_rdp = False
        self.direct_rdp_cancelled = False
        self.direct_rdp_timer = None
        self.auto_connect_remaining = 3
        self.credentials_expanded = False
        self._active_connect_params = {}

        # Configure geometry / fullscreen
        if not self.windowed:
            try:
                self.root.attributes("-fullscreen", True)
            except Exception:
                self.root.geometry(f"{self.root.winfo_screenwidth()}x{self.root.winfo_screenheight()}+0+0")
        else:
            self.root.geometry("1100x750")

        # Key bindings
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.on_escape)
        self.root.bind("<F5>", lambda e: self.refresh_all(force=True))

        # Typography
        self.font_header_title = tkfont.Font(family="DejaVu Sans", size=17, weight="bold")
        self.font_badge = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")
        self.font_status_label = tkfont.Font(family="DejaVu Sans", size=8, weight="bold")
        self.font_status_val = tkfont.Font(family="DejaVu Sans", size=14, weight="bold")
        self.font_status_sub = tkfont.Font(family="DejaVu Sans", size=8)
        self.font_selector_label = tkfont.Font(family="DejaVu Sans", size=11, weight="bold")
        self.font_dropdown = tkfont.Font(family="DejaVu Sans", size=12, weight="bold")
        self.font_link = tkfont.Font(family="DejaVu Sans", size=9)
        self.font_btn_connect = tkfont.Font(family="DejaVu Sans", size=16, weight="bold")
        self.font_btn_action = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")
        self.font_footer = tkfont.Font(family="DejaVu Sans", size=9)
        self.font_modal_title = tkfont.Font(family="DejaVu Sans", size=13, weight="bold")

        # TTK Style configuration for dark dropdown
        self._setup_ttk_styles()

        # Build UI layout (Top Header, Bottom Footer, Centered Main Card)
        self._build_header_ui()
        self._build_footer_ui()
        self._build_center_card_ui()

        # Initial data load
        self.refresh_all(initial=True)

        # Timers
        self.root.after(5000, self._periodic_status_poll)

    def _setup_ttk_styles(self):
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        self.style.configure(
            "Dark.TCombobox",
            fieldbackground=COLOR_INNER_BOX,
            background=COLOR_CARD,
            foreground=COLOR_TEXT_MAIN,
            arrowcolor=COLOR_TITLE_CYAN,
            bordercolor=COLOR_ACCENT_BLUE,
            lightcolor=COLOR_ACCENT_BLUE,
            darkcolor=COLOR_ACCENT_BLUE,
            relief="flat",
            padding=8
        )
        self.style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", COLOR_INNER_BOX)],
            selectbackground=[("readonly", COLOR_INNER_BOX)],
            selectforeground=[("readonly", COLOR_TEXT_MAIN)],
            foreground=[("readonly", COLOR_TEXT_MAIN)]
        )

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

    # --- 1. Top Header (Identical to screen_clean.png) ---

    def _build_header_ui(self):
        self.header_frame = tk.Frame(self.root, bg=COLOR_BG, padx=28, pady=18)
        self.header_frame.pack(side=tk.TOP, fill=tk.X)

        # Title: THIN CLIENT RDP
        self.lbl_app_title = tk.Label(
            self.header_frame,
            text="THIN CLIENT RDP",
            font=self.font_header_title,
            fg=COLOR_TITLE_CYAN,
            bg=COLOR_BG
        )
        self.lbl_app_title.pack(side=tk.LEFT)

        # Badges (Top Right)
        self.header_badges_frame = tk.Frame(self.header_frame, bg=COLOR_BG)
        self.header_badges_frame.pack(side=tk.RIGHT)

        # Badge Wi-Fi
        self.badge_wifi_frame = tk.Frame(
            self.header_badges_frame,
            bg=COLOR_CARD,
            highlightbackground=COLOR_CARD_BORDER,
            highlightthickness=1,
            padx=12,
            pady=5
        )
        self.badge_wifi_frame.pack(side=tk.LEFT, padx=(0, 10))

        self.lbl_badge_wifi = tk.Label(
            self.badge_wifi_frame,
            text="● Wi-Fi: Verifica...",
            font=self.font_badge,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD
        )
        self.lbl_badge_wifi.pack()

        # Badge Tailscale
        self.badge_ts_frame = tk.Frame(
            self.header_badges_frame,
            bg=COLOR_CARD,
            highlightbackground=COLOR_CARD_BORDER,
            highlightthickness=1,
            padx=12,
            pady=5
        )
        self.badge_ts_frame.pack(side=tk.LEFT)

        self.lbl_badge_ts = tk.Label(
            self.badge_ts_frame,
            text="● Tailscale: Verifica...",
            font=self.font_badge,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD
        )
        self.lbl_badge_ts.pack()

    # --- 2. Central Card UI (Faithful 1:1 match to screen_clean.png) ---

    def _build_center_card_ui(self):
        # Outer screen centering container with subtle cyberpunk background
        self.center_container = tk.Canvas(self.root, bg=COLOR_BG, highlightthickness=0)
        self.center_container.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.bg_image = None
        self.bg_img_id = None
        bg_path = os.path.join(BASE_DIR, "static", "img", "cyberpunk_bg.png")
        if os.path.exists(bg_path):
            try:
                self.bg_image = tk.PhotoImage(file=bg_path)
                self.bg_img_id = self.center_container.create_image(0, 0, image=self.bg_image, anchor=tk.CENTER)
            except Exception as e:
                logger.warning(f"Could not load cyberpunk background image: {e}")

        # Central Card Container (max-width ~620px)
        self.card_main = tk.Frame(
            self.center_container,
            bg=COLOR_CARD,
            highlightbackground=COLOR_CARD_BORDER,
            highlightthickness=1,
            padx=32,
            pady=28
        )
        self.card_window_id = self.center_container.create_window(0, 0, window=self.card_main, anchor=tk.CENTER, width=620)

        self.center_container.bind("<Configure>", self._on_canvas_resize)

        # A. Status Grid (2 Columns: STATO WI-FI & STATO TAILSCALE)
        self.status_grid = tk.Frame(self.card_main, bg=COLOR_CARD)
        self.status_grid.pack(fill=tk.X, pady=(0, 20))
        self.status_grid.columnconfigure(0, weight=1, uniform="status")
        self.status_grid.columnconfigure(1, weight=1, uniform="status")

        # Col 1: Stato Wi-Fi Box
        self.box_wifi = tk.Frame(
            self.status_grid,
            bg=COLOR_INNER_BOX,
            highlightbackground=COLOR_INNER_BORDER,
            highlightthickness=1,
            padx=16,
            pady=14
        )
        self.box_wifi.grid(row=0, column=0, padx=(0, 10), sticky="nsew")

        lbl_wf_title = tk.Label(self.box_wifi, text="STATO WI-FI", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX)
        lbl_wf_title.pack()

        self.lbl_wifi_val = tk.Label(self.box_wifi, text="--", font=self.font_status_val, fg=COLOR_SUCCESS, bg=COLOR_INNER_BOX)
        self.lbl_wifi_val.pack(pady=(2, 2))

        self.lbl_wifi_sub = tk.Label(self.box_wifi, text="IP: --", font=self.font_status_sub, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX)
        self.lbl_wifi_sub.pack()

        # Col 2: Stato Tailscale Box
        self.box_ts = tk.Frame(
            self.status_grid,
            bg=COLOR_INNER_BOX,
            highlightbackground=COLOR_INNER_BORDER,
            highlightthickness=1,
            padx=16,
            pady=14
        )
        self.box_ts.grid(row=0, column=1, padx=(10, 0), sticky="nsew")

        lbl_ts_title = tk.Label(self.box_ts, text="STATO TAILSCALE", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX)
        lbl_ts_title.pack()

        self.lbl_ts_val = tk.Label(self.box_ts, text="--", font=self.font_status_val, fg=COLOR_SUCCESS, bg=COLOR_INNER_BOX)
        self.lbl_ts_val.pack(pady=(2, 2))

        self.lbl_ts_sub = tk.Label(self.box_ts, text="IP: --", font=self.font_status_sub, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX)
        self.lbl_ts_sub.pack()

        # Divider line
        div1 = tk.Frame(self.card_main, height=1, bg=COLOR_CARD_BORDER)
        div1.pack(fill=tk.X, pady=(0, 20))

        # B. Host Selector Box
        self.selector_box = tk.Frame(self.card_main, bg=COLOR_CARD)
        self.selector_box.pack(fill=tk.X, pady=(0, 16))

        sel_header = tk.Frame(self.selector_box, bg=COLOR_CARD)
        sel_header.pack(fill=tk.X, pady=(0, 8))

        lbl_sel = tk.Label(
            sel_header,
            text="Seleziona Computer Remoto:",
            font=self.font_selector_label,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_CARD
        )
        lbl_sel.pack(side=tk.LEFT)

        self.btn_set_default = tk.Button(
            sel_header,
            text="★ Imposta come predefinito",
            font=self.font_link,
            fg=COLOR_LINK,
            bg=COLOR_CARD,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_CARD,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            command=self.set_current_host_as_default
        )
        self.btn_set_default.pack(side=tk.RIGHT)

        # Host Dropdown
        self.combo_var = tk.StringVar()
        self.host_combo = ttk.Combobox(
            self.selector_box,
            textvariable=self.combo_var,
            style="Dark.TCombobox",
            state="readonly",
            font=self.font_dropdown
        )
        self.host_combo.pack(fill=tk.X, ipady=6)
        self.host_combo.bind("<<ComboboxSelected>>", self._on_host_selected)

        # C. Windows Options Toggle Link (Collapsible)
        self.btn_toggle_cred = tk.Button(
            self.card_main,
            text="Opzioni accesso Windows (opzionale) ▼",
            font=self.font_link,
            fg=COLOR_LINK,
            bg=COLOR_CARD,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_CARD,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            command=self.toggle_credentials_box
        )
        self.btn_toggle_cred.pack(pady=(0, 14))

        # Collapsible Credentials Container
        self.cred_container = tk.Frame(
            self.card_main,
            bg=COLOR_INNER_BOX,
            highlightbackground=COLOR_INNER_BORDER,
            highlightthickness=1,
            padx=16,
            pady=12
        )
        # Not packed initially

        self.entry_user = tk.Entry(
            self.cred_container,
            font=self.font_dropdown,
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MAIN,
            insertbackground=COLOR_TEXT_MAIN,
            bd=1,
            relief=tk.FLAT
        )
        self.entry_user.pack(fill=tk.X, pady=(0, 8), ipady=4)
        self._set_placeholder(self.entry_user, "Nome Utente Windows (opzionale)")

        self.entry_pwd = tk.Entry(
            self.cred_container,
            font=self.font_dropdown,
            bg=COLOR_CARD,
            fg=COLOR_TEXT_MAIN,
            insertbackground=COLOR_TEXT_MAIN,
            bd=1,
            relief=tk.FLAT,
            show="●"
        )
        self.entry_pwd.pack(fill=tk.X, pady=(0, 8), ipady=4)

        self.var_save_pass = tk.BooleanVar(value=False)
        self.chk_save_pass = tk.Checkbutton(
            self.cred_container,
            text="Salva la password sul thin client",
            variable=self.var_save_pass,
            font=self.font_link,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_INNER_BOX,
            activebackground=COLOR_INNER_BOX,
            activeforeground=COLOR_TEXT_MAIN,
            selectcolor=COLOR_CARD
        )
        self.chk_save_pass.pack(anchor="w")

        # D. Giant Green "CONNETTI" Button
        self.btn_connect = tk.Button(
            self.card_main,
            text="CONNETTI",
            font=self.font_btn_connect,
            fg="#ffffff",
            bg=COLOR_BTN_CONNECT,
            activeforeground="#ffffff",
            activebackground=COLOR_BTN_CONNECT_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            pady=14,
            command=self.start_connection
        )
        self.btn_connect.pack(fill=tk.X, pady=(0, 18))

        # Divider line
        div2 = tk.Frame(self.card_main, height=1, bg=COLOR_CARD_BORDER)
        div2.pack(fill=tk.X, pady=(0, 18))

        # E. Quick Navigation Grid (2 rows matching style.css)
        self.nav_grid = tk.Frame(self.card_main, bg=COLOR_CARD)
        self.nav_grid.pack(fill=tk.X)
        self.nav_grid.columnconfigure(0, weight=1, uniform="nav")
        self.nav_grid.columnconfigure(1, weight=1, uniform="nav")
        self.nav_grid.columnconfigure(2, weight=1, uniform="nav")

        # Row 1: Configura Wi-Fi, Gestisci PC, Diagnostica
        btn_w = tk.Button(
            self.nav_grid,
            text="Configura Wi-Fi",
            font=self.font_btn_action,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            pady=9,
            command=self.open_wifi_dialog
        )
        btn_w.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")

        btn_h = tk.Button(
            self.nav_grid,
            text="Gestisci PC",
            font=self.font_btn_action,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            pady=9,
            command=self.open_hosts_manager
        )
        btn_h.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")

        btn_d = tk.Button(
            self.nav_grid,
            text="Diagnostica",
            font=self.font_btn_action,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            pady=9,
            command=self.open_diagnostics_dialog
        )
        btn_d.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")

        # Row 2: Riavvia, Spegni (spanning cols)
        btn_r = tk.Button(
            self.nav_grid,
            text="Riavvia",
            font=self.font_btn_action,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            pady=9,
            command=self.confirm_reboot
        )
        btn_r.grid(row=1, column=0, columnspan=1, padx=4, pady=(4, 0), sticky="nsew")

        btn_s = tk.Button(
            self.nav_grid,
            text="Spegni",
            font=self.font_btn_action,
            fg="#ffffff",
            bg=COLOR_BTN_DANGER,
            activeforeground="#ffffff",
            activebackground=COLOR_BTN_DANGER_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            pady=9,
            command=self.confirm_poweroff
        )
        btn_s.grid(row=1, column=1, columnspan=2, padx=4, pady=(4, 0), sticky="nsew")

        # F. Connection Overlay (Hidden by default, shown during connection)
        self.conn_overlay = tk.Frame(
            self.card_main,
            bg=COLOR_INNER_BOX,
            highlightbackground=COLOR_ACCENT_BLUE,
            highlightthickness=2
        )
        # Not packed initially

        self.lbl_conn_title = tk.Label(
            self.conn_overlay,
            text="Connessione in corso...",
            font=self.font_modal_title,
            fg=COLOR_TITLE_CYAN,
            bg=COLOR_INNER_BOX
        )
        self.lbl_conn_title.pack(pady=(28, 4))

        self.lbl_conn_sub = tk.Label(
            self.conn_overlay,
            text="Avvio FreeRDP via Tailscale",
            font=self.font_link,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_INNER_BOX
        )
        self.lbl_conn_sub.pack(pady=(0, 20))

        self.btn_conn_cancel = tk.Button(
            self.conn_overlay,
            text="Annulla",
            font=self.font_btn_action,
            fg="#ffffff",
            bg=COLOR_BTN_CANCEL,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=20,
            pady=8,
            command=self.cancel_active_connection
        )
        self.btn_conn_cancel.pack(pady=(0, 24))

    # --- 3. Bottom Footer (Matching screen_clean.png) ---

    def _build_footer_ui(self):
        self.footer_frame = tk.Frame(
            self.root,
            bg=COLOR_BG,
            highlightbackground=COLOR_CARD_BORDER,
            highlightthickness=1,
            padx=28,
            pady=12
        )
        self.footer_frame.pack(side=tk.BOTTOM, fill=tk.X)

        # Left Info
        self.lbl_footer_info = tk.Label(
            self.footer_frame,
            text="IP Locale: -- | Tailscale IP: --",
            font=self.font_footer,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG
        )
        self.lbl_footer_info.pack(side=tk.LEFT)

        # Right Navigation links
        self.footer_nav_frame = tk.Frame(self.footer_frame, bg=COLOR_BG)
        self.footer_nav_frame.pack(side=tk.RIGHT)

        nav_items = [
            ("Home", lambda: self.refresh_all(force=True)),
            ("Wi-Fi", self.open_wifi_dialog),
            ("Gestisci PC", self.open_hosts_manager),
            ("Diagnostica", self.open_diagnostics_dialog),
            ("⚙ Impostazioni", self.open_settings_dialog)
        ]

        for label, cmd in nav_items:
            btn_n = tk.Button(
                self.footer_nav_frame,
                text=label,
                font=self.font_footer,
                fg=COLOR_TEXT_MAIN,
                bg=COLOR_CARD,
                activeforeground=COLOR_TITLE_CYAN,
                activebackground=COLOR_CARD,
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                padx=10,
                pady=4,
                command=cmd
            )
            btn_n.pack(side=tk.LEFT, padx=3)

    def _on_canvas_resize(self, event):
        cx = event.width // 2
        cy = event.height // 2
        if self.bg_img_id and self.bg_image:
            self.center_container.coords(self.bg_img_id, cx, cy)
        if hasattr(self, "card_window_id"):
            self.center_container.coords(self.card_window_id, cx, cy)

    # --- UI Helpers & Placeholder logic ---

    def _set_placeholder(self, entry, text):
        entry.insert(0, text)
        entry.config(fg=COLOR_TEXT_MUTED)

        def on_focus_in(event):
            if entry.get() == text:
                entry.delete(0, tk.END)
                entry.config(fg=COLOR_TEXT_MAIN)

        def on_focus_out(event):
            if not entry.get().strip():
                entry.insert(0, text)
                entry.config(fg=COLOR_TEXT_MUTED)

        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def toggle_credentials_box(self):
        self.credentials_expanded = not self.credentials_expanded
        if self.credentials_expanded:
            self.cred_container.pack(fill=tk.X, pady=(0, 16), before=self.btn_connect)
            self.btn_toggle_cred.config(text="Opzioni accesso Windows (opzionale) ▲")
        else:
            self.cred_container.pack_forget()
            self.btn_toggle_cred.config(text="Opzioni accesso Windows (opzionale) ▼")

    # --- Data Refresh Worker ---

    def refresh_all(self, initial=False, force=False):
        threading.Thread(target=self._fetch_worker, args=(initial, force), daemon=True).start()

    def _fetch_worker(self, initial=False, force=False):
        status = self._api_get(f"/api/boot/status?force={'1' if force else '0'}") or {}
        
        hosts_info = {}
        default_host = ""
        try:
            from app.main import load_hosts_data
            raw = load_hosts_data(include_passwords=False)
            hosts_info = raw.get("hosts", {})
            default_host = raw.get("default_host", "")
        except Exception:
            pass

        self.root.after(0, lambda: self._apply_data(status, hosts_info, default_host, initial))

    def _apply_data(self, status, hosts_info, default_host, initial):
        self.system_status = status
        self.hosts_data = hosts_info
        self.default_host_key = default_host

        net = status.get("network", {})
        wf = net.get("wifi", {})
        eth = net.get("ethernet", {})
        ts = status.get("tailscale", {})

        # Top Right Badges & Center Boxes
        lan_ip = eth.get("ip") or wf.get("ip") or net.get("primary_ip") or "--"
        ts_ip = ts.get("ip") or "--"

        # Wi-Fi Status
        if wf.get("connected") and wf.get("ssid"):
            ssid = wf.get("ssid")
            sig = wf.get("signal", 50)
            self.lbl_wifi_val.config(text=ssid, fg=COLOR_SUCCESS)
            self.lbl_wifi_sub.config(text=f"Segnale: {sig}% | IP: {lan_ip}")
            self.lbl_badge_wifi.config(text=f"● Wi-Fi: {ssid} ({lan_ip})", fg=COLOR_SUCCESS)
            self.badge_wifi_frame.config(highlightbackground=COLOR_BTN_CONNECT)
        elif eth.get("connected"):
            self.lbl_wifi_val.config(text="Ethernet Cablata", fg=COLOR_SUCCESS)
            self.lbl_wifi_sub.config(text=f"IP: {lan_ip}")
            self.lbl_badge_wifi.config(text=f"● Ethernet: {lan_ip}", fg=COLOR_SUCCESS)
            self.badge_wifi_frame.config(highlightbackground=COLOR_BTN_CONNECT)
        else:
            self.lbl_wifi_val.config(text="Disconnesso", fg=COLOR_TEXT_MUTED)
            self.lbl_wifi_sub.config(text="Nessuna rete collegata")
            self.lbl_badge_wifi.config(text="○ Rete: Disconnessa", fg=COLOR_BTN_CANCEL)
            self.badge_wifi_frame.config(highlightbackground=COLOR_BTN_CANCEL)

        # Tailscale Status
        if ts.get("connected") and ts.get("ip"):
            self.lbl_ts_val.config(text="CONNESSO", fg=COLOR_SUCCESS)
            self.lbl_ts_sub.config(text=f"IP: {ts_ip}")
            self.lbl_badge_ts.config(text=f"● Tailscale: {ts_ip}", fg=COLOR_SUCCESS)
            self.badge_ts_frame.config(highlightbackground=COLOR_BTN_CONNECT)
        else:
            self.lbl_ts_val.config(text="NON ATTIVO", fg=COLOR_TEXT_MUTED)
            self.lbl_ts_sub.config(text="Verifica collegamento...")
            self.lbl_badge_ts.config(text="○ Tailscale: Non attivo", fg=COLOR_TEXT_MUTED)
            self.badge_ts_frame.config(highlightbackground=COLOR_CARD_BORDER)

        # Footer Status Info
        self.lbl_footer_info.config(text=f"IP Locale: {lan_ip} | Tailscale IP: {ts_ip} • v{__version__}")

        # Update Host Combobox
        combo_values = []
        self.host_keys_order = []

        for key, h in self.hosts_data.items():
            display_name = f"{h.get('name') or key} ({h.get('hostname') or h.get('ip')})"
            combo_values.append(display_name)
            self.host_keys_order.append(key)

        # Selection stability:
        # On initial startup: pick default host if present
        # On periodic poll/refresh: PRESERVE user's currently selected host!
        target_key = None
        if initial or not self.selected_host_key:
            if self.default_host_key in self.host_keys_order:
                target_key = self.default_host_key
            elif self.host_keys_order:
                target_key = self.host_keys_order[0]
            self.selected_host_key = target_key or ""
        else:
            if self.selected_host_key in self.host_keys_order:
                target_key = self.selected_host_key
            elif self.default_host_key in self.host_keys_order:
                target_key = self.default_host_key
                self.selected_host_key = target_key
            elif self.host_keys_order:
                target_key = self.host_keys_order[0]
                self.selected_host_key = target_key
            else:
                target_key = ""
                self.selected_host_key = ""

        selected_index = self.host_keys_order.index(target_key) if target_key and target_key in self.host_keys_order else 0

        self.host_combo["values"] = combo_values
        if combo_values and (self.host_combo.current() != selected_index or initial):
            self.host_combo.current(selected_index)
        self._update_default_button_state()

        # Load credentials into inputs only on initial startup or if empty
        if initial and target_key:
            self._load_host_credentials_into_ui(target_key)

        # Check Direct RDP Auto-connect on cold startup
        if initial:
            startup = status.get("startup", {})
            if startup.get("mode") == "direct_rdp" and self.default_host_key:
                self._start_direct_rdp_countdown()

    def _load_host_credentials_into_ui(self, host_key):
        h_info = self.hosts_data.get(host_key, {})
        has_saved_pwd = bool(h_info.get("has_password"))

        if host_key in self.transient_drafts:
            draft = self.transient_drafts[host_key]
            user_val = draft.get("user", "")
            pwd_val = draft.get("pwd", "")
            save_val = draft.get("save", False)
        else:
            user_val = (h_info.get("username") or "").strip()
            pwd_val = ""
            save_val = False

        self.entry_user.delete(0, tk.END)
        if user_val:
            self.entry_user.insert(0, user_val)
            self.entry_user.config(fg=COLOR_TEXT_MAIN)
        else:
            self.entry_user.insert(0, "Nome Utente Windows (opzionale)")
            self.entry_user.config(fg=COLOR_TEXT_MUTED)

        self.entry_pwd.delete(0, tk.END)
        if pwd_val:
            self.entry_pwd.insert(0, pwd_val)

        self.var_save_pass.set(save_val)

        suffix = "▲" if self.credentials_expanded else "▼"
        if has_saved_pwd:
            self.btn_toggle_cred.config(text=f"Opzioni accesso Windows (🔒 password salvata) {suffix}")
        else:
            self.btn_toggle_cred.config(text=f"Opzioni accesso Windows (opzionale) {suffix}")

    def _on_host_selected(self, event=None):
        sel_idx = self.host_combo.current()
        if 0 <= sel_idx < len(self.host_keys_order):
            new_key = self.host_keys_order[sel_idx]
            if new_key == self.selected_host_key:
                self._update_default_button_state()
                return

            # Save draft for previously selected host
            if self.selected_host_key:
                cur_u = self.entry_user.get().strip()
                if cur_u == "Nome Utente Windows (opzionale)":
                    cur_u = ""
                cur_p = self.entry_pwd.get()
                cur_s = self.var_save_pass.get()
                self.transient_drafts[self.selected_host_key] = {
                    "user": cur_u,
                    "pwd": cur_p,
                    "save": cur_s
                }

            self.selected_host_key = new_key
            self._load_host_credentials_into_ui(new_key)
            self._update_default_button_state()

    def _get_selected_host_key(self):
        if self.selected_host_key and self.selected_host_key in self.hosts_data:
            return self.selected_host_key
        sel_idx = self.host_combo.current()
        if 0 <= sel_idx < len(self.host_keys_order):
            return self.host_keys_order[sel_idx]
        return self.default_host_key or (self.host_keys_order[0] if self.host_keys_order else "")

    def _update_default_button_state(self):
        cur_key = self._get_selected_host_key()
        if cur_key == self.default_host_key:
            self.btn_set_default.config(text="★ Predefinito all'avvio", fg=COLOR_SUCCESS, state=tk.DISABLED)
        else:
            self.btn_set_default.config(text="★ Imposta come predefinito", fg=COLOR_LINK, state=tk.NORMAL)

    def set_current_host_as_default(self):
        cur_key = self._get_selected_host_key()
        if not cur_key:
            return

        def worker():
            res = self._api_post("/api/hosts/set-default", {"key": cur_key})
            self.root.after(0, lambda: self._on_default_host_saved(res, cur_key))

        threading.Thread(target=worker, daemon=True).start()

    def _on_default_host_saved(self, res, key):
        if res.get("success"):
            self.default_host_key = key
            self._update_default_button_state()
            logger.info(f"Host '{key}' set as default.")
        else:
            messagebox.showerror("Errore", f"Impossibile impostare l'host predefinito:\n{res.get('message')}")

    # --- Connection Execution ---

    def start_connection(self):
        host_key = self._get_selected_host_key()
        if not host_key:
            messagebox.showwarning("Avviso", "Nessun host selezionato.")
            return

        host_info = self.hosts_data.get(host_key, {})
        has_pwd = bool(host_info.get("has_password"))

        # Check credentials from options box
        custom_user = self.entry_user.get().strip()
        if custom_user == "Nome Utente Windows (opzionale)":
            custom_user = ""
        custom_pwd = self.entry_pwd.get()
        save_pwd = self.var_save_pass.get()

        effective_user = custom_user or (host_info.get("username") or "").strip()

        # Caso A: Credenziali fornite o salvate
        if custom_pwd:
            self._do_connect(host_key, username=effective_user, password=custom_pwd, save_password=save_pwd, is_uncredentialed=False, attempt=1)
            return

        if has_pwd:
            self._do_connect(host_key, username=effective_user or None, password=None, save_password=False, is_uncredentialed=False, attempt=1)
            return

        # Caso B: Username e password non configurati
        # 1. Tentare comunque la connessione RDP senza credenziali preimpostate
        self._do_connect(host_key, username=effective_user or None, password=None, save_password=False, is_uncredentialed=True, attempt=1)

    def _do_connect(self, host_key, username=None, password=None, save_password=False, is_uncredentialed=False, attempt=1):
        host_name = self.hosts_data.get(host_key, {}).get("name") or host_key
        self._active_connect_params = {
            "host_key": host_key,
            "host_name": host_name,
            "username": username,
            "password": password,
            "save_password": save_password,
            "is_uncredentialed": is_uncredentialed,
            "attempt": attempt
        }

        # Show connection overlay
        self.lbl_conn_title.config(text=f"Connessione a {host_name}...")
        sub_text = "Avvio sessione FreeRDP via Tailscale" if is_uncredentialed else f"Verifica credenziali e avvio sessione (Tentativo {attempt} di 3)"
        self.lbl_conn_sub.config(text=sub_text)
        self.conn_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.conn_overlay.lift()

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
            self.conn_overlay.place_forget()
            err_msg = res.get("message", "Errore sconosciuto")
            params = getattr(self, "_active_connect_params", {}) or {}
            host_key = params.get("host_key") or self._get_selected_host_key()
            host_info = self.hosts_data.get(host_key, {})
            is_uncred = params.get("is_uncredentialed", False)
            attempt = params.get("attempt", 1)

            err_lower = err_msg.lower()
            is_auth = any(k in err_lower for k in ["autenticazione", "password", "credenziali", "nla", "logon", "credentials", "auth"])
            if is_auth or is_uncred:
                alert_msg = None if (is_uncred and attempt == 1) else "Nome utente o password non corretti. Riprova."
                cur_user = params.get("username") or host_info.get("username") or ""
                self.open_credentials_dialog(host_key, host_info, alert_msg=alert_msg, prefill_user=cur_user, attempt=attempt)
            else:
                messagebox.showerror("Errore Connessione RDP", f"Impossibile connettersi a {host_name}:\n{err_msg}")
            return

        # Session connecting in background: keep overlay active, do not withdraw launcher prematurely
        self.is_connected_rdp = True
        self._start_rdp_session_monitor(host_name)

    def cancel_active_connection(self):
        self._api_post("/api/rdp/disconnect")
        self.conn_overlay.place_forget()

    def _start_rdp_session_monitor(self, host_name):
        def monitor_worker():
            has_withdrawn = False
            time.sleep(1.0)
            while True:
                status = self._api_get("/api/rdp/status") or {}
                state = status.get("state", "IDLE")
                if state == "CONNECTED" and not has_withdrawn:
                    has_withdrawn = True
                    self.root.after(0, self.root.withdraw)
                elif state in ("IDLE", "ERROR"):
                    self.root.after(0, lambda: self._on_rdp_session_ended(status, host_name))
                    break
                time.sleep(1.2)

        threading.Thread(target=monitor_worker, daemon=True).start()

    def _on_rdp_session_ended(self, final_status, host_name):
        self.is_connected_rdp = False
        self.conn_overlay.place_forget()
        self.root.deiconify()
        self.root.lift()

        params = getattr(self, "_active_connect_params", {}) or {}
        host_key = params.get("host_key") or self._get_selected_host_key()
        host_info = self.hosts_data.get(host_key, {})
        is_uncred = params.get("is_uncredentialed", False)
        attempt = params.get("attempt", 1)

        err = final_status.get("error") or final_status.get("error_message")
        is_auth = final_status.get("is_auth_error", False)

        if is_auth or (is_uncred and err):
            # Caso B.3: Schermata locale per inserire credenziali
            if attempt < 3:
                alert_msg = None if (is_uncred and attempt == 1) else "Nome utente o password non corretti. Riprova."
                cur_user = params.get("username") or host_info.get("username") or ""
                self.open_credentials_dialog(host_key, host_info, alert_msg=alert_msg, prefill_user=cur_user, attempt=attempt)
            else:
                messagebox.showerror(
                    "Autenticazione Fallita",
                    f"Numero massimo di tentativi raggiunto per {host_name} (3 di 3). Verifica nome utente e password."
                )
        elif err:
            messagebox.showwarning("Sessione Terminata", f"Sessione con {host_name} chiusa:\n{err}")

        # If credentials were saved successfully, clear draft
        if not err and params.get("save_password"):
            if host_key in self.transient_drafts:
                del self.transient_drafts[host_key]

        self.refresh_all(force=True)

    # --- Direct-RDP Countdown Handling ---

    def _start_direct_rdp_countdown(self):
        if self.direct_rdp_cancelled:
            return

        self.auto_connect_remaining = 3
        default_name = self.hosts_data.get(self.default_host_key, {}).get("name") or self.default_host_key

        self.lbl_conn_title.config(text=f"Avvio automatico verso '{default_name}' in {self.auto_connect_remaining}s...")
        self.lbl_conn_sub.config(text="Premi 'Annulla' o Spazio per aprire il menu locale")
        self.conn_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.conn_overlay.lift()

        self._countdown_tick()

    def _countdown_tick(self):
        if self.direct_rdp_cancelled:
            return

        if self.auto_connect_remaining > 0:
            default_name = self.hosts_data.get(self.default_host_key, {}).get("name") or self.default_host_key
            self.lbl_conn_title.config(text=f"Avvio automatico verso '{default_name}' in {self.auto_connect_remaining}s...")
            self.auto_connect_remaining -= 1
            self.direct_rdp_timer = self.root.after(1000, self._countdown_tick)
        else:
            self.conn_overlay.place_forget()
            self.start_connection()

    def cancel_direct_rdp(self):
        self.direct_rdp_cancelled = True
        if self.direct_rdp_timer:
            self.root.after_cancel(self.direct_rdp_timer)
            self.direct_rdp_timer = None
        self.conn_overlay.place_forget()

    # --- Sub-Dialogs (Wi-Fi, Gestisci PC, Diagnostica, Impostazioni) ---

    def open_wifi_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Configura Wi-Fi")
        dialog.geometry("520x460")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 520, 460)

        lbl_h = tk.Label(dialog, text="Configura Connessione Wi-Fi", font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD)
        lbl_h.pack(pady=(16, 6))

        status_lbl = tk.Label(dialog, text="Scansione reti Wi-Fi in corso...", font=self.font_link, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD)
        status_lbl.pack(pady=(0, 10))

        list_frame = tk.Frame(dialog, bg=COLOR_CARD, padx=20)
        list_frame.pack(fill=tk.BOTH, expand=True)

        listbox = tk.Listbox(
            list_frame,
            font=self.font_dropdown,
            bg=COLOR_INNER_BOX,
            fg=COLOR_TEXT_MAIN,
            selectbackground=COLOR_ACCENT_BLUE,
            selectforeground="#ffffff",
            bd=0,
            highlightthickness=1,
            highlightbackground=COLOR_INNER_BORDER
        )
        listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        listbox.config(yscrollcommand=scrollbar.set)

        form = tk.Frame(dialog, bg=COLOR_CARD, padx=20, pady=10)
        form.pack(fill=tk.X)

        tk.Label(form, text="Rete Wi-Fi Selezionata:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_ssid = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_ssid.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text="Password Wi-Fi:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_pwd = tk.Entry(form, font=self.font_dropdown, show="●", bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_pwd.pack(fill=tk.X, pady=(2, 8), ipady=3)

        def on_select(evt):
            sel = listbox.curselection()
            if sel:
                item = listbox.get(sel[0])
                ssid = item.split(" (")[0]
                entry_ssid.delete(0, tk.END)
                entry_ssid.insert(0, ssid)
                entry_pwd.focus_set()

        listbox.bind("<<ListboxSelect>>", on_select)

        def scan_worker():
            res = self._api_post("/api/wifi/scan")
            networks = res if isinstance(res, list) else []
            self.root.after(0, lambda: apply_scan(networks))

        def apply_scan(networks):
            listbox.delete(0, tk.END)
            if not networks:
                status_lbl.config(text="Nessuna rete trovata.", fg=COLOR_BTN_CANCEL)
                return
            status_lbl.config(text=f"Trovate {len(networks)} reti. Selezionane una:", fg=COLOR_TEXT_MUTED)
            for n in networks:
                sec = "[PROTETTA]" if n.get("security") else "[APERTA]"
                sig = f"{n.get('signal', 0)}%"
                listbox.insert(tk.END, f"{n.get('ssid')} ({sec} Segnale: {sig})")

        threading.Thread(target=scan_worker, daemon=True).start()

        def do_connect():
            s = entry_ssid.get().strip()
            p = entry_pwd.get()
            if not s:
                return
            status_lbl.config(text=f"Connessione a '{s}'...", fg=COLOR_TITLE_CYAN)

            def conn_worker():
                res = self._api_post("/api/wifi/connect", {"ssid": s, "password": p}, timeout=12.0)
                self.root.after(0, lambda: on_conn_done(res))

            def on_conn_done(res):
                if res.get("success"):
                    status_lbl.config(text="Connesso con successo!", fg=COLOR_SUCCESS)
                    self.root.after(1000, dialog.destroy)
                    self.refresh_all(force=True)
                else:
                    status_lbl.config(text=f"Errore: {res.get('message')}", fg=COLOR_BTN_CANCEL)

            threading.Thread(target=conn_worker, daemon=True).start()

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=20, pady=6)
        btn_box.pack(fill=tk.X)

        tk.Button(btn_box, text="Riscansiona", font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=12, pady=6, command=lambda: threading.Thread(target=scan_worker, daemon=True).start()).pack(side=tk.LEFT)
        tk.Button(btn_box, text="Connetti a Wi-Fi", font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=6, command=do_connect).pack(side=tk.RIGHT)

    def open_hosts_manager(self):
        """Displays configured hosts with options to set default or edit."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Gestisci Computer Remoti")
        dialog.geometry("560x420")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 560, 420)

        tk.Label(dialog, text="Computer Remoti Configurati", font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 10))

        hosts_frame = tk.Frame(dialog, bg=COLOR_CARD, padx=20)
        hosts_frame.pack(fill=tk.BOTH, expand=True)

        for key, h in self.hosts_data.items():
            h_card = tk.Frame(hosts_frame, bg=COLOR_INNER_BOX, highlightbackground=COLOR_INNER_BORDER, highlightthickness=1, padx=12, pady=10)
            h_card.pack(fill=tk.X, pady=4)

            is_def = (key == self.default_host_key)
            has_pwd = bool(h.get("has_password"))
            pwd_tag = " 🔒" if has_pwd else ""
            title = f"{h.get('name') or key}{pwd_tag} ({h.get('hostname') or h.get('ip')})"
            tk.Label(h_card, text=title, font=self.font_dropdown, fg=COLOR_TEXT_MAIN, bg=COLOR_INNER_BOX).pack(side=tk.LEFT)

            if is_def:
                tk.Label(h_card, text="★ PREDEFINITO", font=self.font_status_label, fg=COLOR_SUCCESS, bg=COLOR_INNER_BOX).pack(side=tk.RIGHT, padx=6)
            else:
                tk.Button(
                    h_card,
                    text="Imposta predefinito",
                    font=self.font_status_sub,
                    fg=COLOR_LINK,
                    bg=COLOR_CARD,
                    relief=tk.FLAT,
                    bd=0,
                    cursor="hand2",
                    command=lambda k=key: [self._api_post("/api/hosts/set-default", {"key": k}), dialog.destroy(), self.refresh_all(force=True)]
                ).pack(side=tk.RIGHT, padx=6)

            tk.Button(
                h_card,
                text="Modifica",
                font=self.font_status_sub,
                fg=COLOR_TEXT_MAIN,
                bg=COLOR_BTN_SECONDARY,
                relief=tk.FLAT,
                bd=0,
                cursor="hand2",
                command=lambda k=key, hinfo=h: [dialog.destroy(), self.open_host_edit_dialog(k, hinfo)]
            ).pack(side=tk.RIGHT, padx=6)

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=20, pady=12)
        btn_box.pack(fill=tk.X)
        tk.Button(btn_box, text="+ Aggiungi Nuovo PC", font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=14, pady=6, command=lambda: [dialog.destroy(), self.open_host_edit_dialog("", {})]).pack(side=tk.LEFT)
        tk.Button(btn_box, text="Chiudi", font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=6, command=dialog.destroy).pack(side=tk.RIGHT)

    def open_host_edit_dialog(self, key, host_info):
        """Allows configuring or modifying a remote host including saved credentials."""
        dialog = tk.Toplevel(self.root)
        is_new = not bool(key)
        dialog.title("Aggiungi Nuovo PC" if is_new else f"Modifica {host_info.get('name') or key}")
        dialog.geometry("500x480")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 500, 480)

        tk.Label(dialog, text="Aggiungi Nuovo PC" if is_new else f"Modifica {host_info.get('name') or key}", font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 12))

        form = tk.Frame(dialog, bg=COLOR_CARD, padx=24)
        form.pack(fill=tk.BOTH, expand=True)

        tk.Label(form, text="Nome Visualizzato:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_name = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_name.insert(0, host_info.get("name") or "")
        entry_name.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text="Hostname MagicDNS / Tailscale:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_host = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_host.insert(0, host_info.get("hostname") or "")
        entry_host.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text="Nome Utente Windows predefinito:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_user = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_user.insert(0, host_info.get("username") or "")
        entry_user.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text="Password Windows salvata:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_pass = tk.Entry(form, font=self.font_dropdown, show="●", bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_pass.pack(fill=tk.X, pady=(2, 6), ipady=3)

        var_clear_pwd = tk.BooleanVar(value=False)
        if host_info.get("has_password"):
            tk.Label(form, text="🔒 Password salvata presente. Lascia vuoto per mantenerla.", font=self.font_link, fg=COLOR_SUCCESS, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
            tk.Checkbutton(form, text="Elimina password salvata", variable=var_clear_pwd, font=self.font_link, fg="#f87171", bg=COLOR_CARD, selectcolor=COLOR_INNER_BOX).pack(anchor="w", pady=(2, 6))

        var_is_def = tk.BooleanVar(value=(key == self.default_host_key))
        tk.Checkbutton(form, text="Imposta come PC predefinito all'avvio", variable=var_is_def, font=self.font_link, fg=COLOR_TEXT_MAIN, bg=COLOR_CARD, selectcolor=COLOR_INNER_BOX).pack(anchor="w", pady=(6, 12))

        def save_host():
            nm = entry_name.get().strip()
            hn = entry_host.get().strip()
            un = entry_user.get().strip()
            pw = entry_pass.get()
            cp = var_clear_pwd.get()
            is_d = var_is_def.get()
            if not nm or not hn:
                messagebox.showwarning("Dati incompleti", "Inserisci Nome e Hostname del computer.")
                return

            host_key_val = key or hn.lower().replace(" ", "-")
            res = self._api_post("/api/hosts/save", {
                "key": host_key_val,
                "name": nm,
                "hostname": hn,
                "username": un,
                "password": pw,
                "clear_password": cp,
                "is_default": is_d
            })
            if res.get("success"):
                dialog.destroy()
                self.refresh_all(force=True)
            else:
                messagebox.showerror("Errore", f"Impossibile salvare:\n{res.get('message')}")

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=24, pady=12)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(btn_box, text="Annulla", font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=8, command=dialog.destroy).pack(side=tk.LEFT)
        tk.Button(btn_box, text="Salva Configurazione", font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=20, pady=8, command=save_host).pack(side=tk.RIGHT)

    def open_diagnostics_dialog(self):
        """Displays diagnostics: ping, system metrics, Tailscale, FS."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Diagnostica di Sistema")
        dialog.geometry("520x420")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 520, 420)

        tk.Label(dialog, text="Diagnostica e Stato Hardware", font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 12))

        box = tk.Frame(dialog, bg=COLOR_INNER_BOX, highlightbackground=COLOR_INNER_BORDER, highlightthickness=1, padx=16, pady=14)
        box.pack(fill=tk.BOTH, expand=True, padx=20)

        net = self.system_status.get("network", {})
        ts = self.system_status.get("tailscale", {})
        fs = self._api_get("/api/system/fs-status") or {}

        info_lines = [
            f"Versione HidaThin:        v{__version__}",
            f"Filesystem Root:         {'SOLA LETTURA (RO)' if fs.get('root_ro') else 'SCRITTURA (RW)'}",
            f"Interfaccia Primaria:    {net.get('primary_ip', '--')}",
            f"Tailscale WireGuard:     {ts.get('ip', 'Non attivo')} ({'Connesso' if ts.get('connected') else 'Disconnesso'})",
            f"Host Predefinito:        {self.default_host_key or '--'}",
            f"Porta Web Admin:         8080 (http://127.0.0.1:8080)"
        ]

        lbl = tk.Label(box, text="\n\n".join(info_lines), font=self.font_dropdown, fg=COLOR_TEXT_MAIN, bg=COLOR_INNER_BOX, justify=tk.LEFT)
        lbl.pack(anchor="w")

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=20, pady=12)
        btn_box.pack(fill=tk.X)
        tk.Button(btn_box, text="Chiudi", font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=6, command=dialog.destroy).pack(side=tk.RIGHT)

    def open_settings_dialog(self):
        """Displays interactive video quality / RDP settings and Web Admin remote access URL."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Impostazioni Qualità Video & RDP")
        dialog.geometry("560x470")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 560, 470)

        tk.Label(dialog, text="⚙  Qualità Video, Nitidezza Testi & RDP", font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 10))

        cur_settings = {}
        try:
            from app.system import get_settings
            cur_settings = get_settings()
        except Exception:
            cur_settings = {"profile": "balanced", "overscan": "none", "color_depth": 32}

        form = tk.Frame(dialog, bg=COLOR_CARD, padx=24)
        form.pack(fill=tk.X)

        # 1. RDP Profile
        tk.Label(form, text="Profilo Grafico RDP:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(4, 2))
        profile_map = [
            ("balanced", "Bilanciato (Consigliato - Testi nitidi ClearType Lossless 1:1)"),
            ("quality", "Qualità Massima (AVC444 Colore 4:4:4 + Effetti Completi)"),
            ("performance", "Prestazioni Elevate (Bassa banda, senza animazioni)"),
        ]
        prof_var = tk.StringVar()
        prof_combo = ttk.Combobox(form, textvariable=prof_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        prof_combo["values"] = [label for _, label in profile_map]
        cur_prof = cur_settings.get("profile", "balanced")
        prof_idx = next((i for i, (k, _) in enumerate(profile_map) if k == cur_prof), 0)
        prof_combo.current(prof_idx)
        prof_combo.pack(fill=tk.X, pady=(0, 10), ipady=4)

        # 2. Overscan / Pixel Mapping
        tk.Label(form, text="Mappatura Pixel Schermo / Overscan TV:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(4, 2))
        overscan_map = [
            ("none", "1:1 Pixel-Perfect (Consigliata - Massima nitidezza caratteri)"),
            ("light", "Overscan Leggero (~2.5% - Solo per TV che tagliano i bordi)"),
            ("medium", "Overscan Medio (~5.0% - Solo per TV con zoom fisso)"),
            ("heavy", "Overscan Massimo (~7.5% - Solo per TV con zoom elevato)"),
        ]
        over_var = tk.StringVar()
        over_combo = ttk.Combobox(form, textvariable=over_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        over_combo["values"] = [label for _, label in overscan_map]
        cur_over = cur_settings.get("overscan", "none")
        if cur_over == "auto":
            cur_over = "none"
        over_idx = next((i for i, (k, _) in enumerate(overscan_map) if k == cur_over), 0)
        over_combo.current(over_idx)
        over_combo.pack(fill=tk.X, pady=(0, 10), ipady=4)

        # 3. Color Depth
        tk.Label(form, text="Profondità Colore:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(4, 2))
        bpp_map = [
            (32, "32-bit TrueColor (Consigliato per antialiasing subpixel ClearType)"),
            (24, "24-bit Standard"),
            (16, "16-bit Risparmio Banda"),
        ]
        bpp_var = tk.StringVar()
        bpp_combo = ttk.Combobox(form, textvariable=bpp_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        bpp_combo["values"] = [label for _, label in bpp_map]
        cur_bpp = int(cur_settings.get("color_depth", 32))
        bpp_idx = next((i for i, (k, _) in enumerate(bpp_map) if k == cur_bpp), 0)
        bpp_combo.current(bpp_idx)
        bpp_combo.pack(fill=tk.X, pady=(0, 12), ipady=4)

        status_lbl = tk.Label(form, text="", font=self.font_link, fg=COLOR_SUCCESS, bg=COLOR_CARD)
        status_lbl.pack(pady=(0, 6))

        ts_ip = self.system_status.get("tailscale", {}).get("ip")
        lan_ip = self.system_status.get("network", {}).get("primary_ip") or "127.0.0.1"
        web_info = f"Pannello Web Admin completo:  http://{lan_ip}:8080"
        if ts_ip:
            web_info += f"  |  http://{ts_ip}:8080"
        tk.Label(dialog, text=web_info, font=self.font_status_sub, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(pady=(0, 10))

        def save_and_apply():
            sel_prof = profile_map[max(0, prof_combo.current())][0]
            sel_over = overscan_map[max(0, over_combo.current())][0]
            sel_bpp = bpp_map[max(0, bpp_combo.current())][0]
            status_lbl.config(text="Applicazione impostazioni in corso...", fg=COLOR_TITLE_CYAN)

            def worker():
                res = self._api_post("/api/settings/save", {
                    "profile": sel_prof,
                    "overscan": sel_over,
                    "color_depth": sel_bpp
                })
                self._api_post("/api/system/overscan/apply", {"mode": sel_over})
                self.root.after(0, lambda: on_saved(res))

            def on_saved(res):
                if res.get("success"):
                    status_lbl.config(text="✓ Impostazioni applicate con successo!", fg=COLOR_SUCCESS)
                    self.root.after(900, dialog.destroy)
                else:
                    status_lbl.config(text=f"Errore: {res.get('message')}", fg=COLOR_BTN_CANCEL)

            threading.Thread(target=worker, daemon=True).start()

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=24, pady=8)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(btn_box, text="Chiudi", font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=8, command=dialog.destroy).pack(side=tk.LEFT)
        tk.Button(btn_box, text="Salva e Applica", font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=20, pady=8, command=save_and_apply).pack(side=tk.RIGHT)

    def open_credentials_dialog(self, host_key, host_info, alert_msg=None, prefill_user=None, attempt=1):
        """Modal credentials prompt compliant with Section 4:
        Connessione RDP – [Nome PC selezionato]
        - Username: campo di testo
        - Password: campo protetto
        - Salva credenziali: checkbox, inizialmente non selezionata
        - Connetti: pulsante per avviare la sessione
        - Annulla: pulsante per tornare alla schermata precedente
        """
        dialog = tk.Toplevel(self.root)
        host_name = host_info.get("name") or host_key
        dialog.title(f"Connessione RDP – {host_name}")
        dialog.geometry("480x380")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 480, 380)

        tk.Label(
            dialog,
            text=f"Connessione RDP – {host_name}",
            font=self.font_modal_title,
            fg=COLOR_TITLE_CYAN,
            bg=COLOR_CARD
        ).pack(pady=(16, 4))

        if alert_msg:
            tk.Label(
                dialog,
                text=f"⚠️ {alert_msg}",
                font=self.font_link,
                fg="#f87171",
                bg=COLOR_CARD
            ).pack(pady=(0, 10))
        else:
            tk.Label(
                dialog,
                text="Inserisci le credenziali Windows per connetterti",
                font=self.font_link,
                fg=COLOR_TEXT_MUTED,
                bg=COLOR_CARD
            ).pack(pady=(0, 12))

        form = tk.Frame(dialog, bg=COLOR_CARD, padx=28)
        form.pack(fill=tk.X)

        tk.Label(
            form,
            text="Username:",
            font=self.font_status_label,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            anchor="w"
        ).pack(fill=tk.X)

        entry_u = tk.Entry(
            form,
            font=self.font_dropdown,
            bg=COLOR_INNER_BOX,
            fg=COLOR_TEXT_MAIN,
            insertbackground=COLOR_TEXT_MAIN,
            bd=1,
            relief=tk.FLAT
        )
        init_user = prefill_user or host_info.get("username") or ""
        if init_user:
            entry_u.insert(0, init_user)
        entry_u.pack(fill=tk.X, pady=(2, 10), ipady=4)

        tk.Label(
            form,
            text="Password:",
            font=self.font_status_label,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            anchor="w"
        ).pack(fill=tk.X)

        entry_p = tk.Entry(
            form,
            font=self.font_dropdown,
            show="●",
            bg=COLOR_INNER_BOX,
            fg=COLOR_TEXT_MAIN,
            insertbackground=COLOR_TEXT_MAIN,
            bd=1,
            relief=tk.FLAT
        )
        entry_p.pack(fill=tk.X, pady=(2, 10), ipady=4)

        # Salva credenziali: checkbox, inizialmente NON selezionata (False)
        var_s = tk.BooleanVar(value=False)
        chk_s = tk.Checkbutton(
            form,
            text="Salva credenziali",
            variable=var_s,
            font=self.font_link,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_CARD,
            activebackground=COLOR_CARD,
            activeforeground=COLOR_TEXT_MAIN,
            selectcolor=COLOR_INNER_BOX
        )
        chk_s.pack(anchor="w", pady=(0, 16))

        def submit():
            u = entry_u.get().strip()
            p = entry_p.get()
            s = var_s.get()
            dialog.destroy()
            self._do_connect(
                host_key,
                username=u,
                password=p,
                save_password=s,
                is_uncredentialed=False,
                attempt=attempt + 1
            )

        def cancel():
            dialog.destroy()

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=28)
        btn_box.pack(fill=tk.X, pady=(4, 0))

        tk.Button(
            btn_box,
            text="Annulla",
            font=self.font_btn_action,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY,
            activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=18,
            pady=8,
            command=cancel
        ).pack(side=tk.LEFT)

        tk.Button(
            btn_box,
            text="Connetti",
            font=self.font_btn_action,
            fg="#ffffff",
            bg=COLOR_BTN_CONNECT,
            activeforeground="#ffffff",
            activebackground=COLOR_BTN_CONNECT_HOVER,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=22,
            pady=8,
            command=submit
        ).pack(side=tk.RIGHT)

        entry_p.bind("<Return>", lambda e: submit())
        entry_u.bind("<Return>", lambda e: entry_p.focus_set())
        dialog.bind("<Escape>", lambda e: cancel())

        if init_user:
            entry_p.focus_set()
        else:
            entry_u.focus_set()

    # --- System Actions (Reboot / Poweroff) ---

    def confirm_reboot(self):
        if messagebox.askyesno("Riavvio", "Sei sicuro di voler riavviare il thin client?"):
            threading.Thread(target=lambda: self._api_post("/api/system/reboot"), daemon=True).start()

    def confirm_poweroff(self):
        if messagebox.askyesno("Spegnimento", "Sei sicuro di voler spegnere completamente il thin client?"):
            threading.Thread(target=lambda: self._api_post("/api/system/poweroff"), daemon=True).start()

    def _center_window(self, win, w, h):
        win.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")

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
            try:
                self.root.attributes("-fullscreen", False)
            except Exception:
                pass

    def _periodic_status_poll(self):
        if not self.is_connected_rdp:
            self.refresh_all(force=False)
        self.root.after(8000, self._periodic_status_poll)

    def run(self):
        self.root.mainloop()

def main():
    parser = argparse.ArgumentParser(description="HidaThin Native Kiosk Launcher (WTware-Style)")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="Flask backend base URL")
    parser.add_argument("--windowed", action="store_true", help="Launch in windowed mode")
    args = parser.parse_args()

    app = NativeLauncherApp(server_url=args.server, windowed=args.windowed)
    app.run()

if __name__ == "__main__":
    main()
