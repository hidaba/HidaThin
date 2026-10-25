#!/usr/bin/env python3
"""
Thin Client RDP Hot-Corner Overlay (OSD)
Small top-left corner widget that expands upon 1 second hover,
displays local and Tailscale IP addresses, and provides a 1-click
RDP disconnect button. Collapses after mouse leaves for 2 seconds.

Uses continuous global pointer polling via XQueryPointer so it is
completely immune to FreeRDP fullscreen pointer grabs.
"""

import sys
import os
import json
import time
import argparse
import threading
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import font as tkfont

TRIGGER_SIZE = 16
PANEL_WIDTH = 320
PANEL_HEIGHT = 175
CORNER_THRESHOLD = 35  # pixels from top-left (0,0)

COLOR_BG = "#0f172a"          # Slate 900
COLOR_CARD = "#1e293b"        # Slate 800
COLOR_BORDER = "#334155"      # Slate 700
COLOR_TEXT_MAIN = "#f8fafc"   # Slate 50
COLOR_TEXT_MUTED = "#94a3b8"  # Slate 400
COLOR_ACCENT = "#38bdf8"      # Sky 400
COLOR_SUCCESS = "#4ade80"     # Green 400
COLOR_BTN_DANGER = "#dc2626"  # Red 600
COLOR_BTN_ACTIVE = "#b91c1c"  # Red 700

class HotCornerOverlay:
    def __init__(self, host_name=None, server_url="http://127.0.0.1:8080", hover_delay=1000, leave_delay=2000, corner_threshold=CORNER_THRESHOLD):
        self.host_name = host_name or "PC Remoto"
        self.server_url = server_url.rstrip("/")
        self.hover_delay_sec = hover_delay / 1000.0  # default 1.0s
        self.leave_delay_sec = leave_delay / 1000.0  # default 2.0s
        self.corner_threshold = corner_threshold

        self.is_expanded = False
        self.corner_start_time = None
        self.leave_start_time = None

        # Cached status
        self.cached_lan_ip = "--"
        self.cached_ts_ip = "--"
        self.cached_lan_label = "LAN"

        # Create root window
        self.root = tk.Tk()
        self.root.title("ThinClient-OSD")
        self.root.config(bg=COLOR_BG)

        # X11 flags: always on top and bypass window manager to stay above fullscreen FreeRDP
        self.root.overrideredirect(True)
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass

        # Fonts
        self.font_title = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")
        self.font_badge = tkfont.Font(family="DejaVu Sans", size=8, weight="bold")
        self.font_label = tkfont.Font(family="DejaVu Sans", size=8)
        self.font_val = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")
        self.font_btn = tkfont.Font(family="DejaVu Sans", size=9, weight="bold")

        # Initial collapsed state
        self.root.geometry(f"{TRIGGER_SIZE}x{TRIGGER_SIZE}+0+0")

        # Build UI containers
        self._build_trigger_ui()
        self._build_panel_ui()

        # Initial fetch of IP status in background thread
        threading.Thread(target=self._fetch_status_worker, daemon=True).start()

        # Start collapsed
        self.collapse(immediate=True)

        # Continuous global pointer polling (every 80ms)
        self._poll_pointer()

    def _build_trigger_ui(self):
        """Minimal discreet widget visible in collapsed corner."""
        self.trigger_frame = tk.Frame(self.root, bg=COLOR_BG, width=TRIGGER_SIZE, height=TRIGGER_SIZE)
        self.trigger_canvas = tk.Canvas(
            self.trigger_frame,
            width=TRIGGER_SIZE,
            height=TRIGGER_SIZE,
            bg=COLOR_BG,
            highlightthickness=0
        )
        self.trigger_canvas.create_rectangle(0, 0, 3, 3, fill=COLOR_ACCENT, outline="")
        self.trigger_canvas.pack(fill=tk.BOTH, expand=True)

    def _build_panel_ui(self):
        """Full information card with IP details and disconnect button."""
        self.panel_frame = tk.Frame(
            self.root,
            bg=COLOR_BG,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1,
            padx=10,
            pady=8
        )

        # Header Row: Title + Status Badge
        header = tk.Frame(self.panel_frame, bg=COLOR_BG)
        header.pack(fill=tk.X, pady=(0, 6))

        lbl_title = tk.Label(
            header,
            text="🖥️ THIN CLIENT RDP",
            font=self.font_title,
            fg=COLOR_TEXT_MAIN,
            bg=COLOR_BG
        )
        lbl_title.pack(side=tk.LEFT)

        self.lbl_badge = tk.Label(
            header,
            text="● CONNESSO",
            font=self.font_badge,
            fg=COLOR_SUCCESS,
            bg=COLOR_BG
        )
        self.lbl_badge.pack(side=tk.RIGHT)

        # Divider line
        divider = tk.Frame(self.panel_frame, height=1, bg=COLOR_BORDER)
        divider.pack(fill=tk.X, pady=(0, 6))

        # Info rows container
        info_frame = tk.Frame(self.panel_frame, bg=COLOR_CARD, padx=8, pady=6)
        info_frame.pack(fill=tk.X, pady=(0, 8))

        # Row 1: LAN IP
        r1 = tk.Frame(info_frame, bg=COLOR_CARD)
        r1.pack(fill=tk.X, pady=1)
        self.lbl_lan_name = tk.Label(r1, text="IP Locale:", font=self.font_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, width=12, anchor="w")
        self.lbl_lan_name.pack(side=tk.LEFT)
        self.lbl_lan_val = tk.Label(r1, text="--", font=self.font_val, fg=COLOR_TEXT_MAIN, bg=COLOR_CARD, anchor="w")
        self.lbl_lan_val.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Row 2: Tailscale IP
        r2 = tk.Frame(info_frame, bg=COLOR_CARD)
        r2.pack(fill=tk.X, pady=1)
        lbl_ts_name = tk.Label(r2, text="IP Tailscale:", font=self.font_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, width=12, anchor="w")
        lbl_ts_name.pack(side=tk.LEFT)
        self.lbl_ts_val = tk.Label(r2, text="--", font=self.font_val, fg=COLOR_SUCCESS, bg=COLOR_CARD, anchor="w")
        self.lbl_ts_val.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Row 3: Remote Host
        r3 = tk.Frame(info_frame, bg=COLOR_CARD)
        r3.pack(fill=tk.X, pady=1)
        lbl_host_name = tk.Label(r3, text="Host Remoto:", font=self.font_label, fg=COLOR_TEXT_MUTED, bg=COLOR_CARD, width=12, anchor="w")
        lbl_host_name.pack(side=tk.LEFT)
        self.lbl_host_val = tk.Label(r3, text=self.host_name, font=self.font_val, fg=COLOR_ACCENT, bg=COLOR_CARD, anchor="w")
        self.lbl_host_val.pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Disconnect Button
        self.btn_disconnect = tk.Button(
            self.panel_frame,
            text="✖  DISCONNETTI SESSIONE",
            font=self.font_btn,
            fg="#ffffff",
            bg=COLOR_BTN_DANGER,
            activeforeground="#ffffff",
            activebackground=COLOR_BTN_ACTIVE,
            relief=tk.FLAT,
            bd=0,
            cursor="hand2",
            padx=10,
            pady=5,
            command=self.on_disconnect_clicked
        )
        self.btn_disconnect.pack(fill=tk.X)

    def _fetch_status_worker(self):
        """Queries local Flask API for fresh network and Tailscale status."""
        try:
            req = urllib.request.Request(
                f"{self.server_url}/api/status",
                headers={"User-Agent": "ThinClient-OSD"}
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                data = json.loads(resp.read().decode())
                net = data.get("network", {})
                ts = data.get("tailscale", {})

                wf = net.get("wifi", {})
                eth = net.get("ethernet", {})

                if wf.get("connected") and wf.get("ip"):
                    self.cached_lan_ip = f"{wf.get('ip')} ({wf.get('ssid') or 'Wi-Fi'})"
                    self.cached_lan_label = "Wi-Fi:"
                elif eth.get("connected") and eth.get("ip"):
                    self.cached_lan_ip = f"{eth.get('ip')} (Ethernet)"
                    self.cached_lan_label = "Ethernet:"
                elif net.get("primary_ip"):
                    self.cached_lan_ip = net.get("primary_ip")
                    self.cached_lan_label = "IP Locale:"
                else:
                    self.cached_lan_ip = "Disconnesso"
                    self.cached_lan_label = "IP Locale:"

                if ts.get("connected") and ts.get("ip"):
                    self.cached_ts_ip = ts.get("ip")
                else:
                    self.cached_ts_ip = "Non attivo"

                # Update labels in GUI thread
                self.root.after(0, self._update_labels_ui)
        except Exception:
            pass

    def _update_labels_ui(self):
        self.lbl_lan_name.config(text=self.cached_lan_label)
        self.lbl_lan_val.config(text=self.cached_lan_ip)
        self.lbl_ts_val.config(text=self.cached_ts_ip)
        self.lbl_host_val.config(text=self.host_name)

    def _poll_pointer(self):
        """
        Continuously polls the pointer position via XQueryPointer.
        Independent of X11 event delivery and works even when FreeRDP grabs the pointer.
        """
        try:
            px = self.root.winfo_pointerx()
            py = self.root.winfo_pointery()
        except Exception:
            self.root.after(80, self._poll_pointer)
            return

        now = time.time()

        if not self.is_expanded:
            # Check if pointer is in top-left corner (x <= threshold, y <= threshold)
            in_corner = (0 <= px <= self.corner_threshold and 0 <= py <= self.corner_threshold)
            if in_corner:
                if self.corner_start_time is None:
                    self.corner_start_time = now
                elif (now - self.corner_start_time) >= self.hover_delay_sec:
                    # Stayed in corner for at least 1.0 second!
                    self.corner_start_time = None
                    self.expand()
            else:
                self.corner_start_time = None
        else:
            # When expanded, panel occupies (0, 0) to (PANEL_WIDTH, PANEL_HEIGHT)
            inside_panel = (0 <= px <= PANEL_WIDTH and 0 <= py <= PANEL_HEIGHT)
            if inside_panel:
                self.leave_start_time = None
                # Re-raise window periodically to stay on top
                try:
                    self.root.lift()
                except Exception:
                    pass
            else:
                # Pointer is outside panel
                if self.leave_start_time is None:
                    self.leave_start_time = now
                elif (now - self.leave_start_time) >= self.leave_delay_sec:
                    # Pointer has been outside for 2.0 seconds!
                    self.leave_start_time = None
                    self.collapse()

        self.root.after(80, self._poll_pointer)

    def expand(self):
        """Expands overlay to full card size and updates metrics."""
        self.is_expanded = True
        self.corner_start_time = None
        self.leave_start_time = None

        # Refresh status on expand
        threading.Thread(target=self._fetch_status_worker, daemon=True).start()

        # Switch views
        self.trigger_frame.pack_forget()
        self.panel_frame.pack(fill=tk.BOTH, expand=True)

        # Resize and ensure topmost
        self.root.geometry(f"{PANEL_WIDTH}x{PANEL_HEIGHT}+0+0")
        self.root.deiconify()
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass

    def collapse(self, immediate=False):
        """Collapses overlay back to the discreet top-left trigger zone."""
        self.is_expanded = False
        self.corner_start_time = None
        self.leave_start_time = None

        self.panel_frame.pack_forget()
        self.trigger_frame.pack(fill=tk.BOTH, expand=True)
        self.root.geometry(f"{TRIGGER_SIZE}x{TRIGGER_SIZE}+0+0")
        self.root.lift()
        try:
            self.root.attributes("-topmost", True)
        except Exception:
            pass

    # --- Actions ---

    def on_disconnect_clicked(self):
        """Triggers RDP disconnection via Flask API and exits."""
        self.btn_disconnect.config(state=tk.DISABLED, text="Disconnessione in corso...")
        self.lbl_badge.config(text="● CHIUSURA...", fg=COLOR_BTN_DANGER)

        def do_disconnect():
            try:
                data = json.dumps({}).encode("utf-8")
                req = urllib.request.Request(
                    f"{self.server_url}/api/rdp/disconnect",
                    data=data,
                    headers={"Content-Type": "application/json", "User-Agent": "ThinClient-OSD"},
                    method="POST"
                )
                urllib.request.urlopen(req, timeout=2.0)
            except Exception:
                pass
            finally:
                self.root.after(300, self.root.destroy)

        threading.Thread(target=do_disconnect, daemon=True).start()

    def run(self):
        self.root.mainloop()

def main():
    parser = argparse.ArgumentParser(description="Thin Client RDP Hot-Corner Overlay (OSD)")
    parser.add_argument("--host", default="PC Remoto", help="Name or IP of connected host")
    parser.add_argument("--server", default="http://127.0.0.1:8080", help="Thinclient Flask API base URL")
    parser.add_argument("--hover-delay", type=int, default=1000, help="Hover delay before expanding (ms)")
    parser.add_argument("--leave-delay", type=int, default=2000, help="Leave delay before collapsing (ms)")
    parser.add_argument("--corner-threshold", type=int, default=CORNER_THRESHOLD, help="Corner detection threshold (px)")
    args = parser.parse_args()

    app = HotCornerOverlay(
        host_name=args.host,
        server_url=args.server,
        hover_delay=args.hover_delay,
        leave_delay=args.leave_delay,
        corner_threshold=args.corner_threshold
    )
    app.run()

if __name__ == "__main__":
    main()
