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
import webbrowser
import tkinter as tk
from tkinter import ttk, font as tkfont, messagebox

# Ensure project root is in sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app import __version__
from app.i18n import t, get_current_language, LANGUAGE_OPTIONS, DEFAULT_LANGUAGE

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
        self.lang = get_current_language()
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

    def tr(self, key, **kwargs):
        """Translates a key into the launcher's current active language."""
        return t(key, lang=self.lang, **kwargs)

    def update_ui_language(self):
        """Updates all visible label and button texts across the main window."""
        if hasattr(self, 'lbl_badge_wifi'):
            lan_ip = self.system_status.get("network", {}).get("primary_ip") or "--"
            wf = self.system_status.get("network", {}).get("wifi", {})
            if not wf.get("connected"):
                self.lbl_badge_wifi.config(text=f"● Wi-Fi: {self.tr('badge_disconnected')}")
        if hasattr(self, 'lbl_badge_ts'):
            ts = self.system_status.get("tailscale", {})
            if not ts.get("connected"):
                self.lbl_badge_ts.config(text=f"● Tailscale: {self.tr('badge_disconnected')}")
        if hasattr(self, 'lbl_wf_title'):
            self.lbl_wf_title.config(text=self.tr("status_wifi_caps"))
        if hasattr(self, 'lbl_ts_title'):
            self.lbl_ts_title.config(text=self.tr("status_ts_caps"))
        if hasattr(self, 'lbl_sel'):
            self.lbl_sel.config(text=self.tr("select_remote_pc"))
        if hasattr(self, 'btn_set_default'):
            self._update_default_button_state()
        if hasattr(self, 'btn_toggle_cred'):
            self.btn_toggle_cred.config(
                text=self.tr("cred_toggle_up") if self.credentials_expanded else self.tr("cred_toggle_down")
            )
        if hasattr(self, 'chk_save_pass'):
            self.chk_save_pass.config(text=self.tr("save_pass_thinclient"))
        if hasattr(self, 'btn_connect'):
            self.btn_connect.config(text=self.tr("btn_connect_caps"))
        if hasattr(self, 'btn_nav_wifi'):
            self.btn_nav_wifi.config(text=self.tr("boot_btn_wifi"))
        if hasattr(self, 'btn_nav_hosts'):
            self.btn_nav_hosts.config(text=self.tr("nav_hosts"))
        if hasattr(self, 'btn_nav_diag'):
            self.btn_nav_diag.config(text=self.tr("nav_diagnostics"))
        if hasattr(self, 'btn_nav_reboot'):
            self.btn_nav_reboot.config(text=self.tr("btn_reboot"))
        if hasattr(self, 'btn_nav_poweroff'):
            self.btn_nav_poweroff.config(text=self.tr("btn_poweroff"))
        if hasattr(self, 'lbl_conn_title') and not self.direct_rdp_timer:
            self.lbl_conn_title.config(text=self.tr("connecting_title"))
        if hasattr(self, 'lbl_conn_sub'):
            self.lbl_conn_sub.config(text=self.tr("connecting_sub"))
        if hasattr(self, 'btn_conn_cancel'):
            self.btn_conn_cancel.config(text=self.tr("btn_cancel"))
        if hasattr(self, 'footer_nav_buttons'):
            nav_keys = ["nav_home", "nav_wifi", "nav_hosts", "nav_diagnostics", "nav_settings"]
            for btn, k in zip(self.footer_nav_buttons, nav_keys):
                btn.config(text=self.tr(k))
        if self.system_status:
            self._apply_data(self.system_status, self.hosts_data, self.default_host_key, initial=False)

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
            text=f"● Wi-Fi: {self.tr('badge_checking')}",
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
        self.badge_ts_frame.config(cursor="hand2")
        self.badge_ts_frame.bind("<Button-1>", lambda e: self.open_settings_dialog(initial_tab="tailscale"))

        self.lbl_badge_ts = tk.Label(
            self.badge_ts_frame,
            text=f"● Tailscale: {self.tr('badge_checking')}",
            font=self.font_badge,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            cursor="hand2"
        )
        self.lbl_badge_ts.pack()
        self.lbl_badge_ts.bind("<Button-1>", lambda e: self.open_settings_dialog(initial_tab="tailscale"))

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

        self.lbl_wf_title = tk.Label(self.box_wifi, text=self.tr("status_wifi_caps"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX)
        self.lbl_wf_title.pack()

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
        self.box_ts.config(cursor="hand2")
        self.box_ts.bind("<Button-1>", lambda e: self.open_settings_dialog(initial_tab="tailscale"))

        self.lbl_ts_title = tk.Label(self.box_ts, text=self.tr("status_ts_caps"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX, cursor="hand2")
        self.lbl_ts_title.pack()
        self.lbl_ts_title.bind("<Button-1>", lambda e: self.open_settings_dialog(initial_tab="tailscale"))

        self.lbl_ts_val = tk.Label(self.box_ts, text="--", font=self.font_status_val, fg=COLOR_SUCCESS, bg=COLOR_INNER_BOX, cursor="hand2")
        self.lbl_ts_val.pack(pady=(2, 2))
        self.lbl_ts_val.bind("<Button-1>", lambda e: self.open_settings_dialog(initial_tab="tailscale"))

        self.lbl_ts_sub = tk.Label(self.box_ts, text="IP: --", font=self.font_status_sub, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX, cursor="hand2")
        self.lbl_ts_sub.pack()
        self.lbl_ts_sub.bind("<Button-1>", lambda e: self.open_settings_dialog(initial_tab="tailscale"))

        # Divider line
        div1 = tk.Frame(self.card_main, height=1, bg=COLOR_CARD_BORDER)
        div1.pack(fill=tk.X, pady=(0, 20))

        # B. Host Selector Box
        self.selector_box = tk.Frame(self.card_main, bg=COLOR_CARD)
        self.selector_box.pack(fill=tk.X, pady=(0, 16))

        sel_header = tk.Frame(self.selector_box, bg=COLOR_CARD)
        sel_header.pack(fill=tk.X, pady=(0, 8))

        self.lbl_sel = tk.Label(
            sel_header,
            text=self.tr("select_remote_pc"),
            font=self.font_selector_label,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_CARD
        )
        self.lbl_sel.pack(side=tk.LEFT)

        self.btn_set_default = tk.Button(
            sel_header,
            text=self.tr("set_as_default"),
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
            text=self.tr("cred_toggle_down"),
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
        self._set_placeholder(self.entry_user, self.tr("cred_user_placeholder"))

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
            text=self.tr("save_pass_thinclient"),
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
            text=self.tr("btn_connect_caps"),
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
        self.btn_nav_wifi = tk.Button(
            self.nav_grid,
            text=self.tr("boot_btn_wifi"),
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
        self.btn_nav_wifi.grid(row=0, column=0, padx=4, pady=4, sticky="nsew")

        self.btn_nav_hosts = tk.Button(
            self.nav_grid,
            text=self.tr("nav_hosts"),
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
        self.btn_nav_hosts.grid(row=0, column=1, padx=4, pady=4, sticky="nsew")

        self.btn_nav_diag = tk.Button(
            self.nav_grid,
            text=self.tr("nav_diagnostics"),
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
        self.btn_nav_diag.grid(row=0, column=2, padx=4, pady=4, sticky="nsew")

        # Row 2: Riavvia, Spegni (spanning cols)
        self.btn_nav_reboot = tk.Button(
            self.nav_grid,
            text=self.tr("btn_reboot"),
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
        self.btn_nav_reboot.grid(row=1, column=0, columnspan=1, padx=4, pady=(4, 0), sticky="nsew")

        self.btn_nav_poweroff = tk.Button(
            self.nav_grid,
            text=self.tr("btn_poweroff"),
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
        self.btn_nav_poweroff.grid(row=1, column=1, columnspan=2, padx=4, pady=(4, 0), sticky="nsew")

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
            text=self.tr("connecting_title"),
            font=self.font_modal_title,
            fg=COLOR_TITLE_CYAN,
            bg=COLOR_INNER_BOX
        )
        self.lbl_conn_title.pack(pady=(28, 4))

        self.lbl_conn_sub = tk.Label(
            self.conn_overlay,
            text=self.tr("connecting_sub"),
            font=self.font_link,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_INNER_BOX
        )
        self.lbl_conn_sub.pack(pady=(0, 20))

        self.btn_conn_cancel = tk.Button(
            self.conn_overlay,
            text=self.tr("btn_cancel"),
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
            text=f"{self.tr('local_ip')}: -- | {self.tr('ts_ip')}: --",
            font=self.font_footer,
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_BG
        )
        self.lbl_footer_info.pack(side=tk.LEFT)

        # Right Navigation links
        self.footer_nav_frame = tk.Frame(self.footer_frame, bg=COLOR_BG)
        self.footer_nav_frame.pack(side=tk.RIGHT)

        nav_items = [
            (self.tr("nav_home"), lambda: self.refresh_all(force=True)),
            (self.tr("nav_wifi"), self.open_wifi_dialog),
            (self.tr("nav_hosts"), self.open_hosts_manager),
            (self.tr("nav_diagnostics"), self.open_diagnostics_dialog),
            (self.tr("nav_settings"), self.open_settings_dialog)
        ]

        self.footer_nav_buttons = []
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
            self.footer_nav_buttons.append(btn_n)

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
        suffix = "▲" if self.credentials_expanded else "▼"
        host_key = self._get_selected_host_key()
        h_info = self.hosts_data.get(host_key, {})
        has_saved_pwd = bool(h_info.get("has_password"))
        if self.credentials_expanded:
            self.cred_container.pack(fill=tk.X, pady=(0, 16), before=self.btn_connect)
        else:
            self.cred_container.pack_forget()

        base_lbl = self.tr("cred_toggle_down").replace(" ▼", "")
        if has_saved_pwd:
            saved_label = "password salvata" if self.lang == "it" else "saved password"
            self.btn_toggle_cred.config(text=f"{base_lbl} (🔒 {saved_label}) {suffix}")
        else:
            self.btn_toggle_cred.config(text=f"{base_lbl} {suffix}")

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
            self.lbl_wifi_sub.config(text=f"{self.tr('status_signal')} {sig}% | IP: {lan_ip}")
            self.lbl_badge_wifi.config(text=f"● Wi-Fi: {ssid} ({lan_ip})", fg=COLOR_SUCCESS)
            self.badge_wifi_frame.config(highlightbackground=COLOR_BTN_CONNECT)
        elif eth.get("connected"):
            eth_lbl = "Ethernet Cablata" if self.lang == "it" else "Wired Ethernet"
            self.lbl_wifi_val.config(text=eth_lbl, fg=COLOR_SUCCESS)
            self.lbl_wifi_sub.config(text=f"IP: {lan_ip}")
            self.lbl_badge_wifi.config(text=f"● Ethernet: {lan_ip}", fg=COLOR_SUCCESS)
            self.badge_wifi_frame.config(highlightbackground=COLOR_BTN_CONNECT)
        else:
            self.lbl_wifi_val.config(text=self.tr("badge_disconnected"), fg=COLOR_TEXT_MUTED)
            self.lbl_wifi_sub.config(text=self.tr("status_no_local_net"))
            self.lbl_badge_wifi.config(text=f"○ {self.tr('badge_disconnected')}", fg=COLOR_BTN_CANCEL)
            self.badge_wifi_frame.config(highlightbackground=COLOR_BTN_CANCEL)

        # Tailscale Status
        if ts.get("connected") and ts.get("ip"):
            self.lbl_ts_val.config(text=self.tr("status_connected_caps"), fg=COLOR_SUCCESS)
            self.lbl_ts_sub.config(text=f"IP: {ts_ip}")
            self.lbl_badge_ts.config(text=f"● Tailscale: {ts_ip}", fg=COLOR_SUCCESS)
            self.badge_ts_frame.config(highlightbackground=COLOR_BTN_CONNECT)
        elif not ts.get("enabled", True):
            ts_dis_caps = "DISABILITATO" if self.lang == "it" else "DISABLED"
            ts_dis_sub = "Disattivato in Impostazioni" if self.lang == "it" else "Disabled in Settings"
            ts_dis_bdg = "Disabilitato" if self.lang == "it" else "Disabled"
            self.lbl_ts_val.config(text=ts_dis_caps, fg=COLOR_TEXT_MUTED)
            self.lbl_ts_sub.config(text=ts_dis_sub)
            self.lbl_badge_ts.config(text=f"○ Tailscale: {ts_dis_bdg}", fg=COLOR_TEXT_MUTED)
            self.badge_ts_frame.config(highlightbackground=COLOR_CARD_BORDER)
        elif ts.get("status") == "Autenticazione richiesta":
            ts_auth_caps = "ACCESSO RICHIESTO" if self.lang == "it" else "LOGIN REQUIRED"
            ts_auth_sub = "Apri Impostazioni per Login" if self.lang == "it" else "Open Settings to Log In"
            ts_auth_bdg = "Accedi" if self.lang == "it" else "Log In"
            self.lbl_ts_val.config(text=ts_auth_caps, fg="#f59e0b")
            self.lbl_ts_sub.config(text=ts_auth_sub)
            self.lbl_badge_ts.config(text=f"⚠ Tailscale: {ts_auth_bdg}", fg="#f59e0b")
            self.badge_ts_frame.config(highlightbackground="#f59e0b")
        elif ts.get("status") == "Connessione in corso":
            ts_prog_caps = "IN CORSO" if self.lang == "it" else "CONNECTING"
            ts_prog_sub = "Connessione alla Tailnet..." if self.lang == "it" else "Connecting to Tailnet..."
            ts_prog_bdg = "In corso" if self.lang == "it" else "Connecting"
            self.lbl_ts_val.config(text=ts_prog_caps, fg=COLOR_TITLE_CYAN)
            self.lbl_ts_sub.config(text=ts_prog_sub)
            self.lbl_badge_ts.config(text=f"◌ Tailscale: {ts_prog_bdg}", fg=COLOR_TITLE_CYAN)
            self.badge_ts_frame.config(highlightbackground=COLOR_TITLE_CYAN)
        else:
            ts_inact_caps = self.tr("status_disconnected_caps")
            ts_inact_sub = self.tr("status_check_conn")
            ts_inact_bdg = self.tr("badge_disconnected")
            self.lbl_ts_val.config(text=ts_inact_caps, fg=COLOR_BTN_CANCEL)
            self.lbl_ts_sub.config(text=ts_inact_sub)
            self.lbl_badge_ts.config(text=f"○ Tailscale: {ts_inact_bdg}", fg=COLOR_BTN_CANCEL)
            self.badge_ts_frame.config(highlightbackground=COLOR_CARD_BORDER)

        # Footer Status Info
        self.lbl_footer_info.config(text=f"{self.tr('local_ip')}: {lan_ip} | {self.tr('ts_ip')}: {ts_ip} • v{__version__}")

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
            self.entry_user.insert(0, self.tr("cred_user_placeholder"))
            self.entry_user.config(fg=COLOR_TEXT_MUTED)

        self.entry_pwd.delete(0, tk.END)
        if pwd_val:
            self.entry_pwd.insert(0, pwd_val)

        self.var_save_pass.set(save_val)

        suffix = "▲" if self.credentials_expanded else "▼"
        base_lbl = self.tr("cred_toggle_down").replace(" ▼", "")
        if has_saved_pwd:
            saved_label = "password salvata" if self.lang == "it" else "saved password"
            self.btn_toggle_cred.config(text=f"{base_lbl} (🔒 {saved_label}) {suffix}")
        else:
            self.btn_toggle_cred.config(text=f"{base_lbl} {suffix}")

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
                if cur_u in ("Nome Utente Windows (opzionale)", "Windows Username (optional)", self.tr("cred_user_placeholder")):
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
            def_text = "★ Predefinito all'avvio" if self.lang == "it" else "★ Default on boot"
            self.btn_set_default.config(text=def_text, fg=COLOR_SUCCESS, state=tk.DISABLED)
        else:
            self.btn_set_default.config(text=self.tr("set_as_default"), fg=COLOR_LINK, state=tk.NORMAL)

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
            err_lbl = self.tr("modal_error")
            fail_msg = f"Impossibile impostare l'host predefinito:\n{res.get('message')}" if self.lang == "it" else f"Could not set default host:\n{res.get('message')}"
            messagebox.showerror(err_lbl, fail_msg)

    # --- Connection Execution ---

    def start_connection(self):
        host_key = self._get_selected_host_key()
        if not host_key:
            notice_lbl = self.tr("modal_notice")
            no_host_msg = "Nessun host selezionato." if self.lang == "it" else "No host selected."
            messagebox.showwarning(notice_lbl, no_host_msg)
            return

        host_info = self.hosts_data.get(host_key, {})
        has_pwd = bool(host_info.get("has_password"))

        # Check credentials from options box
        custom_user = self.entry_user.get().strip()
        if custom_user in ("Nome Utente Windows (opzionale)", "Windows Username (optional)", self.tr("cred_user_placeholder")):
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
        conn_title = f"Connessione a {host_name}..." if self.lang == "it" else f"Connecting to {host_name}..."
        self.lbl_conn_title.config(text=conn_title)
        if is_uncredentialed:
            sub_text = "Avvio sessione FreeRDP via Tailscale" if self.lang == "it" else "Launching FreeRDP session via Tailscale"
        else:
            sub_text = f"Verifica credenziali e avvio sessione (Tentativo {attempt} di 3)" if self.lang == "it" else f"Verifying credentials and launching session (Attempt {attempt} of 3)"
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
                alert_msg = None if (is_uncred and attempt == 1) else (
                    "Nome utente o password non corretti. Riprova." if self.lang == "it" else "Invalid username or password. Please try again."
                )
                cur_user = params.get("username") or host_info.get("username") or ""
                self.open_credentials_dialog(host_key, host_info, alert_msg=alert_msg, prefill_user=cur_user, attempt=attempt)
            else:
                err_title = "Errore Connessione RDP" if self.lang == "it" else "RDP Connection Error"
                err_text = f"Impossibile connettersi a {host_name}:\n{err_msg}" if self.lang == "it" else f"Unable to connect to {host_name}:\n{err_msg}"
                messagebox.showerror(err_title, err_text)
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
                alert_msg = None if (is_uncred and attempt == 1) else (
                    "Nome utente o password non corretti. Riprova." if self.lang == "it" else "Invalid username or password. Please try again."
                )
                cur_user = params.get("username") or host_info.get("username") or ""
                self.open_credentials_dialog(host_key, host_info, alert_msg=alert_msg, prefill_user=cur_user, attempt=attempt)
            else:
                fail_title = "Autenticazione Fallita" if self.lang == "it" else "Authentication Failed"
                fail_msg = (
                    f"Numero massimo di tentativi raggiunto per {host_name} (3 di 3). Verifica nome utente e password."
                    if self.lang == "it" else
                    f"Maximum attempts reached for {host_name} (3 of 3). Please verify username and password."
                )
                messagebox.showerror(fail_title, fail_msg)
        elif err:
            ended_title = "Sessione Terminata" if self.lang == "it" else "Session Ended"
            ended_msg = f"Sessione con {host_name} chiusa:\n{err}" if self.lang == "it" else f"Session with {host_name} closed:\n{err}"
            messagebox.showwarning(ended_title, ended_msg)

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

        auto_title = f"Avvio automatico verso '{default_name}' in {self.auto_connect_remaining}s..." if self.lang == "it" else f"Auto-connecting to '{default_name}' in {self.auto_connect_remaining}s..."
        auto_sub = "Premi 'Annulla' o Spazio per aprire il menu locale" if self.lang == "it" else "Press 'Cancel' or Space to open local menu"
        self.lbl_conn_title.config(text=auto_title)
        self.lbl_conn_sub.config(text=auto_sub)
        self.conn_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.conn_overlay.lift()

        self._countdown_tick()

    def _countdown_tick(self):
        if self.direct_rdp_cancelled:
            return

        if self.auto_connect_remaining > 0:
            default_name = self.hosts_data.get(self.default_host_key, {}).get("name") or self.default_host_key
            auto_title = f"Avvio automatico verso '{default_name}' in {self.auto_connect_remaining}s..." if self.lang == "it" else f"Auto-connecting to '{default_name}' in {self.auto_connect_remaining}s..."
            self.lbl_conn_title.config(text=auto_title)
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
        dialog.title(self.tr("wifi_title"))
        dialog.geometry("520x460")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 520, 460)

        lbl_h = tk.Label(dialog, text=self.tr("wifi_title"), font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD)
        lbl_h.pack(pady=(16, 6))

        status_lbl = tk.Label(dialog, text="Scansione reti Wi-Fi in corso..." if self.lang == "it" else "Scanning Wi-Fi networks...", font=self.font_link, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD)
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

        tk.Label(form, text="Rete Wi-Fi Selezionata:" if self.lang == "it" else "Selected Wi-Fi Network:", font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_ssid = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_ssid.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text=self.tr("modal_wifi_pwd"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
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
                status_lbl.config(text=self.tr("wifi_none_found"), fg=COLOR_BTN_CANCEL)
                return
            count_msg = f"Trovate {len(networks)} reti. Selezionane una:" if self.lang == "it" else f"Found {len(networks)} networks. Select one:"
            status_lbl.config(text=count_msg, fg=COLOR_TEXT_MUTED)
            sec_prot = "[PROTETTA]" if self.lang == "it" else "[SECURED]"
            sec_open = "[APERTA]" if self.lang == "it" else "[OPEN]"
            sig_lbl = self.tr("status_signal")
            for n in networks:
                sec = sec_prot if n.get("security") else sec_open
                sig = f"{n.get('signal', 0)}%"
                listbox.insert(tk.END, f"{n.get('ssid')} ({sec} {sig_lbl} {sig})")

        threading.Thread(target=scan_worker, daemon=True).start()

        def do_connect():
            s = entry_ssid.get().strip()
            p = entry_pwd.get()
            if not s:
                return
            status_lbl.config(text=f"Connessione a '{s}'..." if self.lang == "it" else f"Connecting to '{s}'...", fg=COLOR_TITLE_CYAN)

            def conn_worker():
                res = self._api_post("/api/wifi/connect", {"ssid": s, "password": p}, timeout=12.0)
                self.root.after(0, lambda: on_conn_done(res))

            def on_conn_done(res):
                if res.get("success"):
                    status_lbl.config(text="Connesso con successo!" if self.lang == "it" else "Connected successfully!", fg=COLOR_SUCCESS)
                    self.root.after(1000, dialog.destroy)
                    self.refresh_all(force=True)
                else:
                    err_lbl = self.tr("modal_error")
                    status_lbl.config(text=f"{err_lbl}: {res.get('message')}", fg=COLOR_BTN_CANCEL)

            threading.Thread(target=conn_worker, daemon=True).start()

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=20, pady=6)
        btn_box.pack(fill=tk.X)

        rescan_txt = "Riscansiona" if self.lang == "it" else "Rescan"
        conn_txt = "Connetti a Wi-Fi" if self.lang == "it" else "Connect to Wi-Fi"
        tk.Button(btn_box, text=rescan_txt, font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=12, pady=6, command=lambda: threading.Thread(target=scan_worker, daemon=True).start()).pack(side=tk.LEFT)
        tk.Button(btn_box, text=conn_txt, font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=6, command=do_connect).pack(side=tk.RIGHT)

    def open_hosts_manager(self):
        """Displays configured hosts with options to set default or edit."""
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("hosts_title"))
        dialog.geometry("560x420")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 560, 420)

        hdr_txt = "Computer Remoti Configurati" if self.lang == "it" else "Configured Remote Computers"
        tk.Label(dialog, text=hdr_txt, font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 10))

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
                def_tag = "★ PREDEFINITO" if self.lang == "it" else "★ DEFAULT"
                tk.Label(h_card, text=def_tag, font=self.font_status_label, fg=COLOR_SUCCESS, bg=COLOR_INNER_BOX).pack(side=tk.RIGHT, padx=6)
            else:
                set_def_txt = "Imposta predefinito" if self.lang == "it" else "Set default"
                tk.Button(
                    h_card,
                    text=set_def_txt,
                    font=self.font_status_sub,
                    fg=COLOR_LINK,
                    bg=COLOR_CARD,
                    relief=tk.FLAT,
                    bd=0,
                    cursor="hand2",
                    command=lambda k=key: [self._api_post("/api/hosts/set-default", {"key": k}), dialog.destroy(), self.refresh_all(force=True)]
                ).pack(side=tk.RIGHT, padx=6)

            edit_txt = self.tr("btn_edit")
            tk.Button(
                h_card,
                text=edit_txt,
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
        tk.Button(btn_box, text=self.tr("hosts_btn_add"), font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=14, pady=6, command=lambda: [dialog.destroy(), self.open_host_edit_dialog("", {})]).pack(side=tk.LEFT)
        tk.Button(btn_box, text=self.tr("modal_close"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=6, command=dialog.destroy).pack(side=tk.RIGHT)

    def open_host_edit_dialog(self, key, host_info):
        """Allows configuring or modifying a remote host including saved credentials."""
        dialog = tk.Toplevel(self.root)
        is_new = not bool(key)
        dialog_title = (
            self.tr("hosts_btn_add").replace("+ ", "") if is_new else f"{self.tr('btn_edit')} {host_info.get('name') or key}"
        )
        dialog.title(dialog_title)
        dialog.geometry("500x480")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 500, 480)

        tk.Label(dialog, text=dialog_title, font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 12))

        form = tk.Frame(dialog, bg=COLOR_CARD, padx=24)
        form.pack(fill=tk.BOTH, expand=True)

        tk.Label(form, text=self.tr("modal_host_name"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_name = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_name.insert(0, host_info.get("name") or "")
        entry_name.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text=self.tr("modal_host_hostname"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_host = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_host.insert(0, host_info.get("hostname") or "")
        entry_host.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text=self.tr("modal_host_username"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_user = tk.Entry(form, font=self.font_dropdown, bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_user.insert(0, host_info.get("username") or "")
        entry_user.pack(fill=tk.X, pady=(2, 8), ipady=3)

        tk.Label(form, text=self.tr("modal_host_password"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
        entry_pass = tk.Entry(form, font=self.font_dropdown, show="●", bg=COLOR_INNER_BOX, fg=COLOR_TEXT_MAIN, insertbackground=COLOR_TEXT_MAIN, bd=1, relief=tk.FLAT)
        entry_pass.pack(fill=tk.X, pady=(2, 6), ipady=3)

        var_clear_pwd = tk.BooleanVar(value=False)
        if host_info.get("has_password"):
            tk.Label(form, text=self.tr("modal_host_pwd_saved"), font=self.font_link, fg=COLOR_SUCCESS, bg=COLOR_CARD, anchor="w").pack(fill=tk.X)
            tk.Checkbutton(form, text=self.tr("modal_host_pwd_delete"), variable=var_clear_pwd, font=self.font_link, fg="#f87171", bg=COLOR_CARD, selectcolor=COLOR_INNER_BOX).pack(anchor="w", pady=(2, 6))

        var_is_def = tk.BooleanVar(value=(key == self.default_host_key))
        def_chk_lbl = "Imposta come PC predefinito all'avvio" if self.lang == "it" else "Set as default PC on boot"
        tk.Checkbutton(form, text=def_chk_lbl, variable=var_is_def, font=self.font_link, fg=COLOR_TEXT_MAIN, bg=COLOR_CARD, selectcolor=COLOR_INNER_BOX).pack(anchor="w", pady=(6, 12))

        def save_host():
            nm = entry_name.get().strip()
            hn = entry_host.get().strip()
            un = entry_user.get().strip()
            pw = entry_pass.get()
            cp = var_clear_pwd.get()
            is_d = var_is_def.get()
            if not nm or not hn:
                warn_title = self.tr("modal_notice")
                warn_msg = "Inserisci Nome e Hostname del computer." if self.lang == "it" else "Please enter PC Name and Hostname."
                messagebox.showwarning(warn_title, warn_msg)
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
                err_title = self.tr("modal_error")
                err_msg = f"Impossibile salvare:\n{res.get('message')}" if self.lang == "it" else f"Unable to save:\n{res.get('message')}"
                messagebox.showerror(err_title, err_msg)

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=24, pady=12)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(btn_box, text=self.tr("modal_cancel"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=8, command=dialog.destroy).pack(side=tk.LEFT)
        save_btn_lbl = "Salva Configurazione" if self.lang == "it" else "Save Configuration"
        tk.Button(btn_box, text=save_btn_lbl, font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=20, pady=8, command=save_host).pack(side=tk.RIGHT)

    def open_diagnostics_dialog(self):
        """Displays diagnostics: ping, system metrics, Tailscale, FS."""
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("diag_title"))
        dialog.geometry("520x420")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 520, 420)

        tk.Label(dialog, text=self.tr("diag_title"), font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(16, 12))

        box = tk.Frame(dialog, bg=COLOR_INNER_BOX, highlightbackground=COLOR_INNER_BORDER, highlightthickness=1, padx=16, pady=14)
        box.pack(fill=tk.BOTH, expand=True, padx=20)

        net = self.system_status.get("network", {})
        ts = self.system_status.get("tailscale", {})
        fs = self._api_get("/api/system/fs-status") or {}

        fs_ro_txt = self.tr("fs_status_ro") if fs.get("root_ro") else self.tr("fs_status_rw")
        ts_conn_txt = self.tr("badge_connected") if ts.get("connected") else self.tr("badge_disconnected")
        ts_ip_txt = ts.get("ip") or ("Non attivo" if self.lang == "it" else "Inactive")

        info_lines = [
            f"{'Versione HidaThin:' if self.lang == 'it' else 'HidaThin Version:'}        v{__version__}",
            f"{'Filesystem Root:' if self.lang == 'it' else 'Root Filesystem:'}         {fs_ro_txt}",
            f"{'Interfaccia Primaria:' if self.lang == 'it' else 'Primary Interface:'}    {net.get('primary_ip', '--')}",
            f"Tailscale WireGuard:     {ts_ip_txt} ({ts_conn_txt})",
            f"{'Host Predefinito:' if self.lang == 'it' else 'Default Host:'}        {self.default_host_key or '--'}",
            f"{'Porta Web Admin:' if self.lang == 'it' else 'Web Admin Port:'}         8080 (http://127.0.0.1:8080)"
        ]

        lbl = tk.Label(box, text="\n\n".join(info_lines), font=self.font_dropdown, fg=COLOR_TEXT_MAIN, bg=COLOR_INNER_BOX, justify=tk.LEFT)
        lbl.pack(anchor="w")

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=20, pady=12)
        btn_box.pack(fill=tk.X)
        tk.Button(btn_box, text=self.tr("modal_close"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=6, command=dialog.destroy).pack(side=tk.RIGHT)

    def open_settings_dialog(self, initial_tab="rdp"):
        """Displays interactive video quality / RDP settings and Tailscale VPN management."""
        dialog = tk.Toplevel(self.root)
        dialog.title(self.tr("settings_title"))
        dialog.geometry("580x640")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 580, 640)

        tk.Label(dialog, text=f"⚙  {self.tr('settings_title')}", font=self.font_modal_title, fg=COLOR_TITLE_CYAN, bg=COLOR_CARD).pack(pady=(14, 8))

        cur_settings = {}
        try:
            from app.system import get_settings
            cur_settings = get_settings()
        except Exception:
            cur_settings = {
                "language": self.lang, "rdp_client": "hidathin-rdp", "profile": "balanced",
                "overscan": "none", "color_depth": 32, "tailscale": {"enabled": True}
            }

        # Tab navigation bar
        tab_bar = tk.Frame(dialog, bg=COLOR_CARD, padx=24)
        tab_bar.pack(fill=tk.X, pady=(0, 10))
        tab_bar.columnconfigure(0, weight=1)
        tab_bar.columnconfigure(1, weight=1)

        btn_tab_rdp = tk.Button(
            tab_bar, text="⚙  RDP & Schermo" if self.lang == "it" else "⚙  RDP & Display", font=self.font_btn_action,
            relief=tk.FLAT, bd=0, cursor="hand2", padx=12, pady=6
        )
        btn_tab_rdp.grid(row=0, column=0, sticky="nsew", padx=(0, 4))

        btn_tab_ts = tk.Button(
            tab_bar, text="🌐  Tailscale VPN", font=self.font_btn_action,
            relief=tk.FLAT, bd=0, cursor="hand2", padx=12, pady=6
        )
        btn_tab_ts.grid(row=0, column=1, sticky="nsew", padx=(4, 0))

        # Main content container
        content_container = tk.Frame(dialog, bg=COLOR_CARD, padx=24)
        content_container.pack(fill=tk.BOTH, expand=True)

        # Tab 1: RDP & Display
        frame_rdp = tk.Frame(content_container, bg=COLOR_CARD)

        # 0. System Language Selector
        tk.Label(frame_rdp, text=self.tr("setting_language"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(2, 2))
        lang_map = [
            ("it", "🇮🇹 Italiano"),
            ("en", "🇬🇧 English"),
        ]
        lang_var = tk.StringVar()
        lang_combo = ttk.Combobox(frame_rdp, textvariable=lang_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        lang_combo["values"] = [label for _, label in lang_map]
        cur_lang = cur_settings.get("language", self.lang)
        lang_idx = next((i for i, (k, _) in enumerate(lang_map) if k == cur_lang), 0)
        lang_combo.current(lang_idx)
        lang_combo.pack(fill=tk.X, pady=(0, 8), ipady=3)

        # 1. RDP Client Program
        tk.Label(frame_rdp, text=self.tr("setting_rdp_client"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(2, 2))
        client_map = [
            ("hidathin-rdp", "hidathin-rdp (Consigliato - Nativo Zero-Copy WTware ARM64)" if self.lang == "it" else "hidathin-rdp (Recommended - Native Zero-Copy WTware ARM64)"),
            ("xfreerdp3", "xfreerdp3 (Standard FreeRDP 3.x upstream)"),
        ]
        client_var = tk.StringVar()
        client_combo = ttk.Combobox(frame_rdp, textvariable=client_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        client_combo["values"] = [label for _, label in client_map]
        cur_client = cur_settings.get("rdp_client", "hidathin-rdp")
        client_idx = next((i for i, (k, _) in enumerate(client_map) if k == cur_client), 0)
        client_combo.current(client_idx)
        client_combo.pack(fill=tk.X, pady=(0, 8), ipady=3)

        # 2. RDP Profile
        tk.Label(frame_rdp, text=self.tr("setting_profile"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(2, 2))
        profile_map = [
            ("balanced", "Bilanciato (Consigliato - Testi nitidi ClearType Lossless 1:1)" if self.lang == "it" else "Balanced (Recommended - Crisp ClearType text Lossless 1:1)"),
            ("quality", "Qualità Massima (AVC444 Colore 4:4:4 + Effetti Completi)" if self.lang == "it" else "Max Quality (AVC444 Color 4:4:4 + Full effects)"),
            ("performance", "Prestazioni Elevate (Bassa banda, senza animazioni)" if self.lang == "it" else "High Performance (Low bandwidth, animations off)"),
        ]
        prof_var = tk.StringVar()
        prof_combo = ttk.Combobox(frame_rdp, textvariable=prof_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        prof_combo["values"] = [label for _, label in profile_map]
        cur_prof = cur_settings.get("profile", "balanced")
        prof_idx = next((i for i, (k, _) in enumerate(profile_map) if k == cur_prof), 0)
        prof_combo.current(prof_idx)
        prof_combo.pack(fill=tk.X, pady=(0, 8), ipady=3)

        # 3. Overscan
        tk.Label(frame_rdp, text=self.tr("setting_overscan"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(2, 2))
        overscan_map = [
            ("none", "1:1 Pixel-Perfect (Consigliata - Massima nitidezza caratteri)" if self.lang == "it" else "1:1 Pixel-Perfect (Recommended - Sharpest text)"),
            ("light", "Overscan Leggero (~2.5% - Solo per TV che tagliano i bordi)" if self.lang == "it" else "Light Overscan (~2.5% margins)"),
            ("medium", "Overscan Medio (~5.0% - Solo per TV con zoom fisso)" if self.lang == "it" else "Medium Overscan (~5.0% margins)"),
            ("heavy", "Overscan Massimo (~7.5% - Solo per TV con zoom elevato)" if self.lang == "it" else "Heavy Overscan (~7.5% margins)"),
        ]
        over_var = tk.StringVar()
        over_combo = ttk.Combobox(frame_rdp, textvariable=over_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        over_combo["values"] = [label for _, label in overscan_map]
        cur_over = cur_settings.get("overscan", "none")
        if cur_over == "auto":
            cur_over = "none"
        over_idx = next((i for i, (k, _) in enumerate(overscan_map) if k == cur_over), 0)
        over_combo.current(over_idx)
        over_combo.pack(fill=tk.X, pady=(0, 8), ipady=3)

        # 4. Color Depth
        tk.Label(frame_rdp, text=self.tr("setting_color_depth"), font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w").pack(fill=tk.X, pady=(2, 2))
        bpp_map = [
            (32, "32-bit TrueColor (Consigliato per ClearType)" if self.lang == "it" else "32-bit TrueColor (Recommended for ClearType)"),
            (24, "24-bit Standard"),
            (16, "16-bit Risparmio Banda" if self.lang == "it" else "16-bit Low Bandwidth"),
        ]
        bpp_var = tk.StringVar()
        bpp_combo = ttk.Combobox(frame_rdp, textvariable=bpp_var, style="Dark.TCombobox", state="readonly", font=self.font_link)
        bpp_combo["values"] = [label for _, label in bpp_map]
        cur_bpp = int(cur_settings.get("color_depth", 32))
        bpp_idx = next((i for i, (k, _) in enumerate(bpp_map) if k == cur_bpp), 0)
        bpp_combo.current(bpp_idx)
        bpp_combo.pack(fill=tk.X, pady=(0, 10), ipady=3)

        ts_ip = self.system_status.get("tailscale", {}).get("ip")
        lan_ip = self.system_status.get("network", {}).get("primary_ip") or "127.0.0.1"
        web_info = f"Pannello Web Admin:  http://{lan_ip}:8080" if self.lang == "it" else f"Web Admin Panel:  http://{lan_ip}:8080"
        if ts_ip:
            web_info += f"  |  http://{ts_ip}:8080"
        tk.Label(frame_rdp, text=web_info, font=self.font_status_sub, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(pady=(4, 0))

        # Tab 2: Tailscale VPN
        frame_ts = tk.Frame(content_container, bg=COLOR_CARD)

        ts_enabled_init = cur_settings.get("tailscale", {}).get("enabled", True)
        ts_enabled_var = tk.BooleanVar(value=ts_enabled_init)

        # Toggle row with switch & badge
        ts_header = tk.Frame(frame_ts, bg=COLOR_CARD)
        ts_header.pack(fill=tk.X, pady=(0, 10))

        chk_ts = tk.Checkbutton(
            ts_header, text=self.tr("ts_enable"), variable=ts_enabled_var,
            font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_CARD,
            activeforeground=COLOR_TEXT_MAIN, activebackground=COLOR_CARD,
            selectcolor=COLOR_INNER_BOX, cursor="hand2"
        )
        chk_ts.pack(side=tk.LEFT)

        lbl_ts_badge = tk.Label(
            ts_header, text=f"● {self.tr('badge_checking')}", font=self.font_badge,
            fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX, padx=10, pady=4
        )
        lbl_ts_badge.pack(side=tk.RIGHT)

        # Tailscale details card
        card_ts_info = tk.Frame(frame_ts, bg=COLOR_INNER_BOX, highlightbackground=COLOR_INNER_BORDER, highlightthickness=1, padx=16, pady=12)
        card_ts_info.pack(fill=tk.X, pady=(0, 10))
        card_ts_info.columnconfigure(1, weight=1)

        def make_ts_info_row(row, label_text):
            tk.Label(card_ts_info, text=label_text, font=self.font_status_label, fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX, anchor="w").grid(row=row, column=0, sticky="w", pady=2)
            val_lbl = tk.Label(card_ts_info, text="--", font=self.font_link, fg=COLOR_TEXT_MAIN, bg=COLOR_INNER_BOX, anchor="w")
            val_lbl.grid(row=row, column=1, sticky="w", padx=(10, 0), pady=2)
            return val_lbl

        lbl_val_ip = make_ts_info_row(0, self.tr("ts_ip_label"))
        lbl_val_host = make_ts_info_row(1, self.tr("ts_hostname_label"))
        lbl_val_net = make_ts_info_row(2, self.tr("ts_tailnet_label"))

        # Auth URL Banner (hidden by default)
        auth_banner = tk.Frame(frame_ts, bg=COLOR_INNER_BOX, highlightbackground=COLOR_ACCENT_BLUE, highlightthickness=1, padx=12, pady=10)
        lbl_auth_msg = tk.Label(auth_banner, text=self.tr("ts_auth_required"), font=self.font_status_sub, fg=COLOR_TITLE_CYAN, bg=COLOR_INNER_BOX, anchor="w")
        lbl_auth_msg.pack(fill=tk.X, pady=(0, 6))

        current_auth_url = {"url": None}

        def open_auth_link():
            if current_auth_url["url"]:
                try:
                    webbrowser.open(current_auth_url["url"])
                except Exception as ex:
                    lbl_ts_msg.config(text=f"Errore apertura browser: {ex}", fg=COLOR_BTN_CANCEL)

        btn_open_auth = tk.Button(
            auth_banner, text=f"🌐 {self.tr('ts_complete_login')}", font=self.font_btn_action,
            fg="#ffffff", bg=COLOR_ACCENT_BLUE, activeforeground="#ffffff",
            activebackground=COLOR_TITLE_CYAN, relief=tk.FLAT, bd=0,
            cursor="hand2", padx=10, pady=4, command=open_auth_link
        )
        btn_open_auth.pack(anchor="w")

        # Action buttons (2x2 grid)
        actions = tk.Frame(frame_ts, bg=COLOR_CARD)
        actions.pack(fill=tk.X, pady=(0, 8))
        actions.columnconfigure(0, weight=1, uniform="tsact")
        actions.columnconfigure(1, weight=1, uniform="tsact")

        def run_ts_action(endpoint, wait_msg):
            lbl_ts_msg.config(text=wait_msg, fg=COLOR_TITLE_CYAN)
            def worker():
                res = self._api_post(endpoint)
                self.root.after(0, lambda: on_ts_action_done(res))
            threading.Thread(target=worker, daemon=True).start()

        def on_ts_action_done(res):
            if res.get("tailscale"):
                update_ts_display(res["tailscale"])
            lbl_ts_msg.config(
                text=res.get("message", "Operazione completata"),
                fg=COLOR_SUCCESS if res.get("success") else COLOR_BTN_CANCEL
            )

        btn_ts_conn = tk.Button(
            actions, text=self.tr("ts_btn_connect"), font=self.font_btn_action, fg="#ffffff",
            bg=COLOR_BTN_CONNECT, activeforeground="#ffffff",
            activebackground=COLOR_BTN_CONNECT_HOVER, relief=tk.FLAT, bd=0,
            cursor="hand2", padx=8, pady=6,
            command=lambda: run_ts_action("/api/tailscale/connect", "Connessione Tailscale in corso..." if self.lang == "it" else "Connecting to Tailnet...")
        )
        btn_ts_conn.grid(row=0, column=0, sticky="nsew", padx=(0, 4), pady=(0, 6), ipady=4)

        btn_ts_disc = tk.Button(
            actions, text=self.tr("ts_btn_disconnect"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY, activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER, relief=tk.FLAT, bd=0,
            cursor="hand2", padx=8, pady=6,
            command=lambda: run_ts_action("/api/tailscale/disconnect", "Disconnessione Tailscale in corso..." if self.lang == "it" else "Disconnecting Tailscale...")
        )
        btn_ts_disc.grid(row=0, column=1, sticky="nsew", padx=(4, 0), pady=(0, 6), ipady=4)

        btn_ts_ref = tk.Button(
            actions, text=self.tr("ts_btn_refresh"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY, activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER, relief=tk.FLAT, bd=0,
            cursor="hand2", padx=8, pady=6,
            command=lambda: refresh_ts_info(force=True)
        )
        btn_ts_ref.grid(row=1, column=0, sticky="nsew", padx=(0, 4), ipady=4)

        btn_ts_log = tk.Button(
            actions, text=self.tr("ts_btn_login"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN,
            bg=COLOR_BTN_SECONDARY, activeforeground=COLOR_TEXT_MAIN,
            activebackground=COLOR_BTN_SECONDARY_HOVER, relief=tk.FLAT, bd=0,
            cursor="hand2", padx=8, pady=6,
            command=lambda: run_ts_action("/api/tailscale/login", "Avvio autenticazione Tailscale..." if self.lang == "it" else "Starting Tailscale login...")
        )
        btn_ts_log.grid(row=1, column=1, sticky="nsew", padx=(4, 0), ipady=4)

        lbl_ts_msg = tk.Label(frame_ts, text="", font=self.font_link, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, anchor="w", justify=tk.LEFT, wraplength=520)
        lbl_ts_msg.pack(fill=tk.X, pady=(4, 0))

        def update_ts_display(ts_data):
            if not ts_data:
                return
            if isinstance(ts_data.get("enabled"), bool):
                ts_enabled_var.set(ts_data["enabled"])

            status_str = ts_data.get("status") or ("Disconnesso" if self.lang == "it" else "Disconnected")
            ip_val = ts_data.get("ip") or "--"
            host_val = ts_data.get("hostname") or "--"
            net_val = ts_data.get("tailnet") or "--"
            current_auth_url["url"] = ts_data.get("auth_url")

            lbl_val_ip.config(text=ip_val, fg=COLOR_SUCCESS if ts_data.get("connected") else COLOR_TEXT_MUTED)
            lbl_val_host.config(text=host_val)
            lbl_val_net.config(text=net_val)

            if ts_data.get("connected"):
                lbl_ts_badge.config(text=f"● {status_str}", fg=COLOR_SUCCESS, bg=COLOR_INNER_BOX)
            elif not ts_data.get("enabled", True):
                lbl_ts_badge.config(text=f"○ {'Disabilitato' if self.lang == 'it' else 'Disabled'}", fg=COLOR_TEXT_MUTED, bg=COLOR_INNER_BOX)
            elif status_str == "Autenticazione richiesta":
                lbl_ts_badge.config(text=f"⚠ {'Accedi' if self.lang == 'it' else 'Log In'}", fg="#f59e0b", bg=COLOR_INNER_BOX)
            elif status_str == "Connessione in corso":
                lbl_ts_badge.config(text=f"◌ {'In corso' if self.lang == 'it' else 'Connecting'}", fg=COLOR_TITLE_CYAN, bg=COLOR_INNER_BOX)
            else:
                lbl_ts_badge.config(text=f"○ {status_str}", fg=COLOR_BTN_CANCEL, bg=COLOR_INNER_BOX)

            if current_auth_url["url"]:
                auth_banner.pack(fill=tk.X, pady=(0, 10))
            else:
                auth_banner.pack_forget()

        def refresh_ts_info(force=False):
            wait_lbl = "Verifica stato in corso..." if self.lang == "it" else "Checking status..."
            lbl_ts_msg.config(text=wait_lbl, fg=COLOR_TITLE_CYAN)
            def worker():
                endpoint = "/api/tailscale/status?force=true" if force else "/api/tailscale/status"
                res = self._api_get(endpoint)
                self.root.after(0, lambda: on_refresh_done(res))
            def on_refresh_done(res):
                if res:
                    update_ts_display(res)
                    lbl_ts_msg.config(text="Stato aggiornato" if self.lang == "it" else "Status updated", fg=COLOR_SUCCESS)
                else:
                    lbl_ts_msg.config(text="Impossibile aggiornare lo stato" if self.lang == "it" else "Unable to update status", fg=COLOR_BTN_CANCEL)
            threading.Thread(target=worker, daemon=True).start()

        def on_ts_toggle():
            new_val = ts_enabled_var.get()
            lbl_ts_msg.config(text="Applicazione toggle Tailscale..." if self.lang == "it" else "Applying Tailscale toggle...", fg=COLOR_TITLE_CYAN)
            def worker():
                res = self._api_post("/api/tailscale/toggle", {"enabled": new_val})
                self.root.after(0, lambda: on_ts_action_done(res))
            threading.Thread(target=worker, daemon=True).start()

        chk_ts.config(command=on_ts_toggle)

        # Tab switching logic
        def show_tab(tab_name):
            if tab_name == "tailscale":
                frame_rdp.pack_forget()
                frame_ts.pack(fill=tk.BOTH, expand=True)
                btn_tab_ts.config(bg=COLOR_ACCENT_BLUE, fg="#ffffff")
                btn_tab_rdp.config(bg=COLOR_BTN_SECONDARY, fg=COLOR_TEXT_MAIN)
                refresh_ts_info(force=False)
            else:
                frame_ts.pack_forget()
                frame_rdp.pack(fill=tk.BOTH, expand=True)
                btn_tab_rdp.config(bg=COLOR_ACCENT_BLUE, fg="#ffffff")
                btn_tab_ts.config(bg=COLOR_BTN_SECONDARY, fg=COLOR_TEXT_MAIN)

        btn_tab_rdp.config(command=lambda: show_tab("rdp"))
        btn_tab_ts.config(command=lambda: show_tab("tailscale"))

        # Status label at bottom
        status_lbl = tk.Label(dialog, text="", font=self.font_link, fg=COLOR_SUCCESS, bg=COLOR_CARD)
        status_lbl.pack(side=tk.BOTTOM, pady=(0, 2))

        def save_and_apply():
            sel_lang = lang_map[max(0, lang_combo.current())][0]
            sel_client = client_map[max(0, client_combo.current())][0]
            sel_prof = profile_map[max(0, prof_combo.current())][0]
            sel_over = overscan_map[max(0, over_combo.current())][0]
            sel_bpp = bpp_map[max(0, bpp_combo.current())][0]
            sel_ts_enabled = ts_enabled_var.get()
            status_lbl.config(text="Applicazione impostazioni in corso..." if self.lang == "it" else "Applying settings...", fg=COLOR_TITLE_CYAN)

            def worker():
                res = self._api_post("/api/settings/save", {
                    "language": sel_lang,
                    "rdp_client": sel_client,
                    "profile": sel_prof,
                    "overscan": sel_over,
                    "color_depth": sel_bpp,
                    "tailscale": {"enabled": sel_ts_enabled}
                })
                self._api_post("/api/system/overscan/apply", {"mode": sel_over})
                self.root.after(0, lambda: on_saved(res, sel_lang))

            def on_saved(res, new_lang):
                if res.get("success"):
                    self.lang = new_lang
                    self.update_ui_language()
                    status_lbl.config(text="✓ Impostazioni applicate con successo!" if self.lang == "it" else "✓ Settings applied successfully!", fg=COLOR_SUCCESS)
                    self.root.after(900, dialog.destroy)
                else:
                    err_txt = self.tr("modal_error")
                    status_lbl.config(text=f"{err_txt}: {res.get('message')}", fg=COLOR_BTN_CANCEL)

            threading.Thread(target=worker, daemon=True).start()

        btn_box = tk.Frame(dialog, bg=COLOR_CARD, padx=24, pady=8)
        btn_box.pack(fill=tk.X, side=tk.BOTTOM)
        tk.Button(btn_box, text=self.tr("modal_close"), font=self.font_btn_action, fg=COLOR_TEXT_MAIN, bg=COLOR_BTN_SECONDARY, relief=tk.FLAT, bd=0, cursor="hand2", padx=16, pady=8, command=dialog.destroy).pack(side=tk.LEFT)
        tk.Button(btn_box, text=self.tr("btn_save_and_apply"), font=self.font_btn_action, fg="#ffffff", bg=COLOR_BTN_CONNECT, relief=tk.FLAT, bd=0, cursor="hand2", padx=20, pady=8, command=save_and_apply).pack(side=tk.RIGHT)

        show_tab(initial_tab)

    def open_credentials_dialog(self, host_key, host_info, alert_msg=None, prefill_user=None, attempt=1):
        """Modal credentials prompt:
        Connessione RDP – [Nome PC selezionato]
        - Username: campo di testo
        - Password: campo protetto
        - Salva credenziali: checkbox, inizialmente non selezionata
        - Connetti: pulsante per avviare la sessione
        - Annulla: pulsante per tornare alla schermata precedente
        """
        dialog = tk.Toplevel(self.root)
        host_name = host_info.get("name") or host_key
        dlg_title = f"{'Connessione RDP' if self.lang == 'it' else 'RDP Connection'} – {host_name}"
        dialog.title(dlg_title)
        dialog.geometry("480x380")
        dialog.configure(bg=COLOR_CARD)
        dialog.transient(self.root)
        dialog.grab_set()
        self._center_window(dialog, 480, 380)

        tk.Label(
            dialog,
            text=dlg_title,
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
            prompt_lbl = "Inserisci le credenziali Windows per connetterti" if self.lang == "it" else "Enter Windows credentials to connect"
            tk.Label(
                dialog,
                text=prompt_lbl,
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
            text=self.tr("cred_modal_save"),
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
            text=self.tr("modal_cancel"),
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
            text="Connetti" if self.lang == "it" else "Connect",
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
        title = self.tr("btn_reboot")
        msg = self.tr("confirm_reboot_msg")
        if messagebox.askyesno(title, msg):
            threading.Thread(target=lambda: self._api_post("/api/system/reboot"), daemon=True).start()

    def confirm_poweroff(self):
        title = self.tr("btn_poweroff")
        msg = self.tr("confirm_poweroff_msg")
        if messagebox.askyesno(title, msg):
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
