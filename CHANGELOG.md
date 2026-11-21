# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to `0.2.x` versioning.

## [0.2.31] - 2026-11-21

### Added
- **Tailscale VPN Management in Settings Menu & Native Launcher (`app/tailscale.py`, `app/launcher.py`, `templates/settings.html`, `app/main.py`, `app/system.py`, `config/settings.yaml`, `install.sh`)**:
  - Added dedicated **Tailscale VPN** configuration and control section accessible from the Settings dialog and Web Admin.
  - Implemented real-time status monitoring with cache TTL (15s monotonic time) avoiding CPU overhead on Raspberry Pi 3: detects `Connected`, `Connecting`, `Disconnected`, `Disabled`, `Authentication Required`, `Not Installed`, and `Error`.
  - Added persistent ON/OFF toggle switch (`tailscale.enabled`) in `config/settings.yaml` and schema validation in `app/system.py`.
  - Implemented official CLI and API-driven connection controls: Connect (`tailscale up --reset=false`), Disconnect (`tailscale down`), Refresh Status (`tailscale status --json`), and Login flow (`tailscale login` with AuthURL extraction).
  - Added dynamic authentication banner with clickable web link when Tailnet approval or re-authentication is required.
  - Added interactive status badge and card in Native Tkinter Launcher (`app/launcher.py`), supporting direct click-to-open navigation into the Tailscale settings tab.
  - Added automatic boot-time state application (`apply_boot_tailscale_state`) in a background daemon thread without blocking Kiosk UI startup.
  - Integrated smart RDP routing in `app/rdp.py`:
    - RDP targets with LAN addresses (`192.168.x.x`, `10.x.x.x`, private hostnames) connect directly even when Tailscale is disabled or disconnected.
    - Tailscale targets (CGNAT `100.64.0.0/10`, IPv6 `fd7a:115c:a1e0::/48`, `.ts.net`, MagicDNS peers) validate VPN connectivity and return friendly descriptive errors if Tailscale is disabled or disconnected.
  - Added comprehensive test suite `tests/test_tailscale_settings.py` covering all 9 mandatory verification scenarios with 100% pass rate.

## [0.2.30] - 2026-11-21

### Added
- **Preferred RDP Client Selection in Settings (`config/settings.yaml`, `app/system.py`, `app/rdp.py`, `app/launcher.py`, `templates/settings.html`)**:
  - Set `hidathin-rdp` as the default system RDP client, delivering maximum performance via native Zero-Copy WTware rendering architecture on Raspberry Pi.
  - Added configuration parameter `rdp_client` (`hidathin-rdp` | `xfreerdp3`) in `DEFAULT_SETTINGS` and in `config/settings.yaml` with strict schema validation (`VALID_RDP_CLIENTS`).
  - Updated `app/rdp.py`: `_find_freerdp_binary(preferred_client)` dynamically selects the preferred program with mutual fallback should one of the binaries be absent.
  - Updated Native Tkinter Launcher settings dialog (`open_settings_dialog` in `app/launcher.py`): added dropdown selector *RDP Client Program* with options `hidathin-rdp` (Recommended) and `xfreerdp3` (Standard FreeRDP 3.x), with instant persistence and application via API.
  - Updated web administration page [templates/settings.html](file:///y:/Progetti/thinclient/templates/settings.html): added RDP client selector menu with detailed description of both operating modes.
  - Updated [install.sh](file:///y:/Progetti/thinclient/install.sh) with new default `rdp_client: "hidathin-rdp"`.
  - Added automated tests for schema validation and binary selection in `tests/test_updater_settings.py` and `tests/test_rdp_lifecycle.py`.

## [0.2.29] - 2026-11-21

### Fixed
- **Resolved BadMatch Crash on X_SetInputFocus in `hidathin-rdp` (`src/hidathin_rdp.c`)**:
  - Identified and fixed the root cause of the native C client crash: the synchronous call to `XSetInputFocus(..., CurrentTime)` was executed immediately after `XMapRaised()`, before the window manager (Openbox) completed processing the `MapRequest` event and rendered the window genuinely `IsViewable`. In the X11 protocol (opcode 42 `X_SetInputFocus`), focusing a window that is not yet viewable raises a `BadMatch` error, triggering an immediate forced process exit from Xlib's default error handler (`_XDefaultError`).
  - Introduced `hida_x_error_handler` (`XSetErrorHandler`) to intercept and silently handle asynchronous non-critical X11 errors (including `BadMatch` on opcode 42, `BadWindow`, and `BadDrawable`).
  - Introduced `hida_set_input_focus_safe()` which queries window attributes with `XGetWindowAttributes()` and applies focus only if the window state is `IsViewable`.
  - Declared ICCCM-compliant hints (`XWMHints` with `hints->input = True` and `NormalState`) and transmitted the EWMH `_NET_ACTIVE_WINDOW` client message to request native window activation from Openbox upon mapping.
  - Added ICCCM protocol `WM_TAKE_FOCUS` to `WM_PROTOCOLS` and handled `MapNotify`, `ButtonPress`, and `ClientMessage (WM_TAKE_FOCUS)` in `process_x11_events` event loop to acquire focus as soon as the window becomes visible or receives a click.
  - Restored automated compilation and installation of `hidathin-rdp` in `install.sh` and `scripts/deploy-thinclient.ps1`, reintroducing priority in `_find_freerdp_binary()` in `app/rdp.py` with guaranteed fallback to `xfreerdp3`.
  - Updated automated test suite in `tests/test_rdp_lifecycle.py`.

## [0.2.28] - 2026-11-21

### Fixed
- **Resolved "Wrong Password" False Positive (`app/rdp.py`)**:
  - Removed unqualified generic keywords (`credentials`, `credential`, `credenziali`, `nla`, `logon`) from `AUTH_ERROR_KEYWORDS`. FreeRDP logs routinely contain strings such as `kerberos_AcquireCredentialsHandleA` (during NTLM fallback for Windows local accounts) and `CONNECTION_STATE_NLA`: previously, any disconnection or warning was mistakenly classified as an authentication failure (`auth_error=True`), prompting the launcher to ask for credentials again even when correct.
  - Replaced with precise diagnostic error strings and status codes (`ERRCONNECT_LOGON_FAILURE`, `ERRCONNECT_AUTHENTICATION_FAILED`, `ERRCONNECT_ACCOUNT_DISABLED`, `ERRCONNECT_PASSWORD_EXPIRED`, `STATUS_LOGON_FAILURE`, `SEC_E_LOGON_DENIED`, `invalid credentials`, `0x00020014`, `154`).

- **RDP Connection Stability and Restored `xfreerdp3` Priority (`app/rdp.py`, `scripts/deploy-thinclient.ps1`, `install.sh`)**:
  - Restored `xfreerdp3` as the primary client in `_find_freerdp_binary()`. The experimental C client `hidathin-rdp` caused a `BadMatch` crash on `X_SetInputFocus` (opcode 42) upon fullscreen X11 attachment when the window was not yet viewable.
  - Removed forced compilation of `hidathin-rdp`, ensuring maximum stability and reliability with upstream FreeRDP 3.15.

- **Eliminated Premature Black Screen on Session Startup (`app/launcher.py`)**:
  - Tkinter launcher no longer hides its window (`self.root.withdraw()`) before RDP connection is established. The overlay displaying connection progress and the *Cancel* button remains visible during handshake and NLA/DNS resolution; the main window is hidden only when the connection transitions to `CONNECTED`. On error or rejection, the launcher restores the card or opens the dialog without jarring black screen transitions.

- **Fixed `pc-officina` Host Configuration (`config/hosts.yaml`)**:
  - Verified and restored the correct local username `hidab` for `pc-officina` (replacing `hidaba@hidaba.it` which triggered Kerberos DNS lookups and NLA failure `ERRCONNECT_LOGON_FAILURE`).

## [0.2.27] - 2026-11-21

### Fixed
- **Fixed Remote PC Selection Auto-Reset Bug (`app/launcher.py`, `templates/index.html`, `tests/test_launcher_ui.py`)**:
  - Fixed root cause of automatic remote PC selection switching: periodic status polling (`_periodic_status_poll` at 8s intervals in `app/launcher.py`) invoked `_apply_data()`, which recalculated the selected index forcing it exclusively to the default host (`selected_index = default_host_index`).
  - Introduced persistent tracking of active user selection (`self.selected_host_key`): background polling and refresh cycles strictly preserve the PC chosen by the operator.
  - Protected input fields during typing: automatic data updates do not overwrite or clear username, password, or checkboxes while editing.
  - Dynamic loading and credential isolation on host change: when the user selects another PC from the dropdown, its saved credentials are loaded (without exposing or inheriting the previous PC's password), preserving unsaved drafts in a temporary registry per host.
  - Implemented the same draft persistence (`hostDrafts`) and deselection protection in the web dashboard (`templates/index.html`).
  - Added regression tests in `tests/test_launcher_ui.py` simulating typing over 30s during concurrent polling.

### Improved
- **RDP Connection Handling Without Preconfigured Credentials (Case A / Case B) (`app/rdp.py`, `app/launcher.py`, `templates/index.html`, `tests/test_rdp_auth_retry.py`)**:
  - Removed preventive block that prevented pressing **Connect** when username/password were absent.
  - **Case A (Saved or entered credentials)**: RDP connection launches normally with credentials associated with the selected PC.
  - **Case B (Username and password not configured)**:
    1. RDP client initiates connection without preconfigured credentials.
    2. If the server supports interactive logon (e.g. Windows native logon screen without strict NLA), the session displays full-screen, allowing direct authentication.
    3. If the client exits or strictly requires credentials (NLA/auth error), a local dialog appears:
       - Title: `RDP Connection – [Selected PC Name]`
       - Text field for Username
       - Masked field for Password
       - `Save credentials` checkbox, **initially unchecked**
       - `Connect` and `Cancel` buttons
    4. If the user checks `Save credentials`, data is persistently and securely stored (YAML file with `0600` permissions on data partition) for that specific remote PC, without changing the default host. If unchecked, credentials apply only to the current session.
    5. On authentication failure, credentials can be corrected and retried (up to 3 attempts) before returning to the main screen.
    6. Pressing `Cancel` or `Esc` closes the window, returning to the main menu without altering saved settings.
  - Updated RDP session manager (`app/rdp.py`) to reliably detect credential prompts even without explicit error codes when FreeRDP exits without a password.

### Added
- **Native Zero-Copy RDP Client `hidathin-rdp` with WTware Architecture (`src/hidathin_rdp.c`, `src/Makefile`, `app/rdp.py`, `install.sh`, `scripts/deploy-thinclient.ps1`)**:
  - Developed and integrated native C client `hidathin-rdp` (`/usr/local/bin/hidathin-rdp`, compiled with `-O3 -mcpu=native -ftree-vectorize`) based on architecture reverse-engineered from WTware 6.2.92 (`/sbin/rdpclient` and `/usr/lib/ui32.so`):
    1. **Zero-Copy Shared Memory Framebuffer (`MIT-SHM` + `gdi_init_ex`)**: allocates a 32-bit `XRGB8888` System V shared memory segment 64-byte aligned for ARM64 NEON and passes it directly to `gdi_init_ex(instance, PIXEL_FORMAT_BGRX32, ...)`, allowing GDI/ClearCodec/Planar/AVC444 decoders to write directly into Xorg shared buffer, eliminating the 3 intermediate copies (`GDI -> XImage -> Pixmap -> Window`) of `xfreerdp3`.
    2. **Dirty-Buffer Coalescing (`dirtybuf.cpp`) + `XShmCompletionEvent` Synchronization**: coalesces all invalidated micro-rectangles per PDU into a single dirty region and presents frames via DMA `XShmPutImage` synchronized with `XShmCompletionEvent`, eliminating X11 socket saturation and tearing.
    3. **Mouse Motion Event Coalescing (`tsclient-input.cpp`)**: compresses queued `MotionNotify` event bursts in X11 server into a single FastPath `PTR_FLAGS_MOVE` packet, eliminating mouse pointer trail/lag at 500 Hz USB polling.
    4. **Hardware DRM Cursor Plane (`Xcursor` ARGB32)** and **Native WinPR XKB Scancode Translation**: local hardware cursor rendering at 500 Hz and direct XKB keycode mapping.
    5. **Direct TCP Socket Tuning (`rdpclient-transport-tcp.cpp`)**: applies `TCP_NODELAY=1`, `SO_RCVBUF=65536` (64 KB anti-bufferbloat), `SO_KEEPALIVE=1` (15s/5s/3), and `TCP_USER_TIMEOUT=30000` directly onto RDP transport file descriptors.
  - Updated `RDPManager._find_freerdp_binary()` in `app/rdp.py` to prioritize `hidathin-rdp` with transparent fallback to `xfreerdp3`.
  - Updated `install.sh` and `scripts/deploy-thinclient.ps1` to compile and install `/usr/local/bin/hidathin-rdp`.

## [0.2.26] - 2026-11-20

### Optimized (RDP & System Tuning Derived from WTware 6.2.92 Reverse-Engineering)
- **RDP Pipeline, Double-Buffered Frame Acknowledging, and WTware Performance Flags (`app/rdp.py`, `tests/test_rdp_lifecycle.py`)**:
  - **Double-Buffered Frame Ack (`/frame-ack:2`)**: Configured `CAPSETTYPE_FRAME_ACKNOWLEDGE` with `maxUnacknowledgedFrameCount = 2` (matching WTware `sbin/rdpclient`), keeping the graphics pipeline full with 1 frame decoding and 1 in-flight, eliminating both `/frame-ack:1` ping-pong stalls and unbounded frame bufferbloat.
  - **WTware Performance Flags (`PFlags = 0x1AF` -> `-window-drag`, `-wallpaper`, `-menu-anims`, `+fonts`, `+aero`)**: Disabled full window redraw during dragging (`-window-drag` / `PERF_DISABLE_FULLWINDOWDRAG = 0x02`) across `balanced` and `quality` profiles, displaying wireframe outlines during moves and eliminating Raspberry Pi CPU spikes while preserving ClearType (`+fonts`) and DWM Desktop Composition (`+aero`).
  - **`RDPEGFX` Flags `small-cache:on,thin-client:off` and Geometry Video Channel (`+video`)**: Updated `quality` profile with `/gfx:AVC444:on,AVC420:off,RFX:off,progressive:off,small-cache:on,thin-client:off` + `+video` to mirror WTware's `RDPGFX_CAPS_FLAG_SMALL_CACHE (0x02)` + `RDPGFX_CAPS_FLAG_AVC_THINCLIENT (0x40)` (capping surface cache to 16 MB in RAM and enabling geometric video streaming redirect).
  - **Dynamic Compressed Audio AAC/ADPCM (`/sound:sys:alsa,format:1,quality:dynamic`)**: Enabled dynamic compressed audio codec negotiation on ALSA to reduce bandwidth consumption and prevent audio micro-stutters.
- **Boot Firmware (`config.txt`) and Low-Latency TCP Stack Optimizations (`install.sh`)**:
  - Added `arm_boost=1` and `avoid_warnings=2` in `/boot/firmware/config.txt` to unlock maximum SoC boost frequency and prevent undervoltage firmware overlays from interrupting KMS/DRM page flipping.
  - Added `/etc/sysctl.d/99-rdp-network.conf` (`net.ipv4.tcp_low_latency=1`, `tcp_keepalive_time=15`, `tcp_keepalive_intvl=5`, `tcp_keepalive_probes=3`, `tcp_fin_timeout=15`) to minimize RDP TCP packet latency.

## [0.2.25] - 2026-11-20

### Fixed & Improved
- **Eliminated Blurry Fonts: Disabled Forced `AVC420` 4:2:0 from `/network:auto` and Restored 1:1 Native `1920x1080` Mapping (`app/rdp.py`, `app/system.py`, `scripts/xinitrc`, `app/launcher.py`, `config/settings.yaml`, `install.sh`)**:
  - **FreeRDP 3.15 (`xfreerdp3`) `/network:auto` Fix**: In FreeRDP 3.x, `/network:auto` forcibly enabled `FreeRDP_SupportGraphicsPipeline = 1`, `FreeRDP_RemoteFxCodec = 1`, and `FreeRDP_GfxH264 = 1` (lossy H.264 `AVC420` video compression with YUV 4:2:0 chroma subsampling), degrading ClearType RGB subpixels. Replaced in `balanced` profile with `/network:lan` + `/compression-level:2` + `/cache:bitmap:on,offscreen:on,glyph:on` + `/scale:100`, ensuring **100% lossless 32-bit** GDI/Planar pipeline (`GfxH264=0`, `RemoteFxCodec=0`, `AllowFontSmoothing=1`).
  - **`quality` Profile Fix (True 4:4:4 without `AVC420` fallback)**: Replaced `/gfx:AVC444,AVC420` (which allowed Windows to negotiate `AVC420` 4:2:0) with `/gfx:AVC444:on,AVC420:off,RFX:off,progressive:off` and removed the `/frame-ack:1` bottleneck.
  - **`performance` Profile Fix (ClearType Preservation)**: Replaced `/network:broadband` (which in FreeRDP 3.x overrode `AllowFontSmoothing=0` disabling ClearType even with `+fonts`) with `/network:wan`.
  - **X11 Scaling and Double Overscan Fix (`1971x1109` / `2022x1138` -> `1920x1080` 1:1)**: Mode `overscan: auto` applied a fractional transform matrix `xrandr --transform 1.052632...` together with hardware DRM margins on Samsung/LG displays, expanding X11 framebuffer to `1971x1109` (`2022x1138`) and causing nearest-neighbor resampling (1 pixel lost every 19) across all fonts. Set `overscan: "none"` (1:1 Pixel-Perfect `1920x1080` with `Broadcast RGB: Full`) as default and zeroed out duplicate DRM margins.
  - **Xft LCD Subpixel Configuration & Video Quality Panel in Launcher (`scripts/xinitrc`, `app/launcher.py`)**: Added `xrdb` merge for `Xft.dpi: 96`, `Xft.antialias: 1`, `Xft.rgba: rgb`, `Xft.lcdfilter: lcddefault` at X11 startup, and integrated direct RDP Graphics Profile, 1:1 Pixel Mapping / Overscan, and 32-bit Color Depth controls into `⚙ Settings` in Native Launcher.

## [0.2.24] - 2026-10-27

### Fixed & Improved
- **RDP Tuning: Crystal-Clear ClearType Text and Blurry Font Resolution (`app/rdp.py`, `app/system.py`, `config/settings.yaml`, `templates/settings.html`, `install.sh`)**:
  - Explicitly enabled TrueType/ClearType font subpixel antialiasing with `+fonts` and desktop composition `+aero` in FreeRDP 3.
  - Increased default color depth from 24 to 32 bits (`color_depth: 32` / `/bpp:32`), an essential requirement for ClearType alpha channels to eliminate font visual artifacts. Automatically promoted pre-existing 24-bit configs to 32-bit in `balanced` profile.
  - Removed `progressive` codec from default `balanced` profile: progressive compression caused text blurring in motion and saturated the Raspberry Pi 3 CPU during software decoding.
  - `balanced` profile now leverages native GDI pipeline with vector glyph rendering and advanced bitmap caching (`/cache:bitmap:on,offscreen:on`), keeping Pi 3 CPU load low (<15%) and fonts 100% pixel-perfect.
  - Updated `quality` profile with `/gfx:AVC444,AVC420` support (YUV 4:4:4 without chroma compression that degraded colored text) and `/frame-ack:1`.
  - Preserved `+fonts` in `performance` profile, disabling heavy window animations and drag effects to save bandwidth without compromising text readability.

### Added
- **Windows Host Optimization Scripts and Registry Module (`scripts/tune-windows-rdp-host.reg`, `scripts/tune-windows-rdp-host.ps1`)**:
  - Created optimization scripts for Windows PCs: unlocked native 30 FPS cap raising DWM framerate to 60 FPS (`DWMFRAMEINTERVAL = 15`), enabled GPU hardware acceleration for Remote Desktop sessions, and prioritized hardware codecs.
  - Added dedicated regression test `test_t30_rdp_cleartype_fonts_and_profile_tuning` in `tests/test_rdp_lifecycle.py`.

## [0.2.23] - 2026-10-27

### Added
- **Native Tkinter Launcher WTware-Style (`app/launcher.py`, `scripts/xinitrc`, `config/settings.yaml`, `install.sh`, `tests/test_launcher_ui.py`)**:
  - Implemented new ultra-lightweight Python/Tkinter Native Launcher replacing Chromium Kiosk UI as default local graphical interface (`ui.mode: native`).
  - Reduced memory footprint from >300 MB to ~25 MB RAM (<10% of Chromium) and reduced load time from 5-7s to <250 ms.
  - Support for remote workstation grid with real-time reachability status, interactive/persistent credential management, Wi-Fi and Tailscale status pills, Wi-Fi configuration modal with network scanning, and confirmation dialogs for poweroff and reboot.
  - Integrated muted cyberpunk background (`cyberpunk_bg.png`) on Tkinter Canvas and feh root window, tuning brightness for high contrast and readability.
  - Built-in Direct-to-RDP countdown with immediate button to cancel local autoconnect.
  - Full coordination with FreeRDP: launcher hides (`root.withdraw()`) during full-screen session and instantly restores (`root.deiconify()`) on exit.
  - Flask server remains active in background on port 8080 for remote administration and diagnostics (LAN / Tailscale).
  - Added automated test suite `tests/test_launcher_ui.py`.

### Fixed & Improved
- **Default PC Setting and Read-Only Filesystem Remount (`app/system.py`, `app/main.py`, `app/vnc.py`, `templates/hosts.html`, `templates/index.html`, `scripts/setup-readonly-fs.sh`)**:
  - Resolved error 500 / EROFS ("Read-only file system") when saving default host at boot: read-only `remount_fs` routine only handled root (`/`), omitting persistent bind-mounts (`/opt/thinclient/config`, `/etc/NetworkManager/system-connections`, `/var/lib/tailscale`) which remained locked read-only.
  - Implemented `get_managed_mountpoints()` in `app/system.py` to dynamically discover, remount in read-write (RW), and restore to read-only (RO) both the root filesystem and all active bind mounts.
  - Fixed exception handling across `try ... finally` blocks in `save_hosts_data()`, `save_settings()`, and `set_vnc_password()`, preventing unhandled Flask crashes and guaranteeing `ro=True` restoration.
  - Added pre-filtering of transient keys (`has_password`) before dumping to `hosts.yaml`.
  - Added quick `Set as default` button directly in main web screen (`templates/index.html`) alongside remote computer dropdown, with dynamic status update.
  - Updated terminal maintenance aliases `rw` and `ro` in `scripts/setup-readonly-fs.sh` (`/etc/profile.d/readonly-helpers.sh`) to include all managed bind-mounts.
  - Added dedicated test suite in `tests/test_default_host.py`.

## [0.2.22] - 2026-10-27

### Fixed & Improved
- **Universal X11 Display Overscan Compensation (`app/system.py`, `templates/settings.html`, `templates/diagnostics.html`)**:
  - Implemented canvas scaling via X11 coordinate transformation matrix (`xrandr --transform`) with bilinear filtering on Hardware Video Scaler (HVS), ensuring margin pullback across all GPUs (including Broadcom VC4 on Pi 3 lacking DRM underscan properties).
  - Introduced smart TV auto-detection vs PC monitors by inspecting EDID descriptor blocks from major manufacturers (Samsung, LG, Sony, Philips, Panasonic, TCL, Hisense) and presence of interlaced video modes (1080i, 576i, 480i).
  - Added new `heavy` option (~7.5% margin reduction: 72px horizontal, 40px vertical) for televisions with aggressive optical overscan.
  - Enabled `Broadcast RGB: Full` on supported outputs to inform TVs of full-range PC color space, disabling broadcast overscan automatically.

## [0.2.21] - 2026-10-27

### Added
- **Interactive Credentials Prompt on Connect and 3-Attempt RDP Retry Loop (`templates/index.html`, `static/css/style.css`, `app/rdp.py`, `app/main.py`)**:
  - On clicking "CONNECT" toward a remote PC without preconfigured credentials (missing username or password), interface automatically displays modal requesting Windows Username and Password.
  - Added password visibility toggle (👁/🙈) for easy typing on touchscreens or compact keyboards.
  - Implemented 3-attempt retry loop on invalid credentials: detects authentication failure (FreeRDP status and exit codes 134, 145, 133, 148, 154, 155) and allows retrying with visual step counter ("Attempt 1 of 3", "Attempt 2 of 3", "Attempt 3 of 3 (Final)").
  - After 3 failed attempts, connection loop halts with user notification and reset to prevent remote account lockouts.
  - Added backend endpoint `/api/rdp/reset-failed-credentials` to clear invalid stored credentials if all attempts fail.
  - Added automated test suite `tests/test_rdp_auth_retry.py` (T29, T30, T31).

## [0.2.20] - 2026-10-27

### Added
- **Automatic TV Edge / Overscan Compensation (`app/system.py`, `app/main.py`, `scripts/xinitrc`, `templates/settings.html`, `templates/diagnostics.html`)**:
  - Implemented native HDMI overscan compensation (clipped borders on TV sets) via hardware DRM underscan properties (`vc4-kms-v3d`).
  - Added new configuration parameter `overscan` in `settings.yaml` with 4 selectable modes:
    - `none`: No compensation (1:1 pixel-perfect mapping for PC monitors).
    - `auto`: Automatic detection based on EDID/CEA display flags.
    - `light`: Subtle compensation (~2.5% hardware margins: 24px horizontal, 16px vertical).
    - `medium`: Standard compensation (~5% hardware margins: 48px horizontal, 32px vertical for traditional TVs).
  - Added startup hook in `scripts/xinitrc` to apply configured underscan across all active display outputs at X11 initialization.
  - Added REST endpoint `/api/system/overscan/apply` with live preview in Settings page: changing modes immediately updates the display without reboot.
  - Updated `templates/diagnostics.html` with active overscan indicator.
  - Updated `install.sh` to include `overscan: "auto"` in default configuration template and disable legacy firmware overscan in `config.txt` (`disable_overscan=1`) in favor of dynamic KMS control.
  - Added automated tests in `tests/test_updater_settings.py` (T26, T27, T28) and access control in `tests/test_sec.py`.

## [0.2.19] - 2026-10-27

### Fixed
- **Software Version Badge Position in Footer (`templates/base.html`)**:
  - Moved version badge (`footer-version`) to the right of network and Tailscale status info (`system-info-text`), placing it after the Tailscale IP separated by a dot divider (`•`), improving overall status bar clarity.
  - Added regression test T28 in `tests/test_boot_status.py` verifying footer element order.
- **Restored Mouse Cursor Visibility (`systemd/thinclient-ui.service`, `scripts/xinitrc`, `install.sh`)**:
  - Removed destructive `-nocursor` flag from Xorg startup command in `thinclient-ui.service`. In Xorg, `-nocursor` globally disables pointer sprite rendering for the entire session (Chromium Kiosk, Openbox, and FreeRDP), rendering the mouse cursor invisible.
  - Configured default cursor in `scripts/xinitrc` via `xsetroot -cursor_name left_ptr`, eliminating obsolete X11 root font "X" cursor and providing a visible standard arrow pointer starting from splash screen.
  - Added `adwaita-icon-theme` to `PACKAGES_CORE` in `install.sh` for modern vector cursor themes out of the box.
  - Updated regression test T27 in `tests/test_boot_status.py` verifying `-nocursor` is not reintroduced.

## [0.2.18] - 2026-10-26

### User Experience & Graphical Boot (Silent Boot & Splash Screen)
- **Silent Xorg Startup and Console Warning Suppression (`systemd/thinclient-ui.service`, `scripts/xinitrc`)**:
  - Redirected `StandardOutput` and `StandardError` to `journal` in `thinclient-ui.service`, preventing `xinit`, `Xorg`, shell scripts, and Chromium from writing loading banners or warnings to `/dev/tty1`.
  - Added `-logverbose 0` flag to Xorg command line to silence console logging.
  - Added `--log-level=3` flag to Chromium Kiosk startup to suppress stderr warnings.
  - Automated configuration in `/boot/firmware/cmdline.txt` (`quiet loglevel=3 logo.nologo consoleblank=0 vt.global_cursor_default=0`) and `/boot/firmware/config.txt` (`disable_splash=1`) via `install.sh` for silent boot from power-on to X11.
- **Immediate Splash Background Display in X11 (`scripts/xinitrc`, `install.sh`)**:
  - Integrated `feh --bg-fill` at Openbox startup to instantly set Cyberpunk background image on root X11 window, eliminating blank screen while Chromium loads.
  - Added `feh` package to core dependencies in `install.sh`.
- **Smooth Connection Phase Progression in Splash (`templates/index.html`, `config/settings.yaml`, `app/system.py`)**:
  - Implemented smooth sequence displaying 4 readiness stages prior to dashboard:
    1. `[01/04] HIDATHIN KIOSK ENGINE` (Flask & X11)
    2. `[02/04] NETWORK CONNECTION` (Wi-Fi with SSID/IP or Ethernet)
    3. `[03/04] TAILSCALE WIREGUARD VPN TUNNEL` (WireGuard status and 100.x IP)
    4. `[04/04] REMOTE RDP HOST CHECK` (Port 3389 reachability)
  - Introduced configurable `startup.splash_min_duration_seconds` (default: 2s) to allow users to visually verify connection checks before fading to dashboard (or set to `0` for instant startup).
  - Recovery controls ("Configure Wi-Fi", "Open Dashboard") always immediately clickable to bypass splash.
- **Automated Tests (`tests/test_boot_status.py`)**:
  - Added regression tests T26 (connection phase validation and dwell time support) and T27 (Silent Boot verification in systemd and xinitrc).

## [0.2.17] - 2026-10-25

### Security (SEC-01 & SEC-02)
- **Local Bind and Remote Access Protection (`app/main.py`, `config/settings.yaml`)**:
  - Default Flask backend bind set to `127.0.0.1:8080`.
  - Added access controls (`web_admin.remote_enabled`, `web_admin.admin_token`) rejecting unauthorized remote mutating calls (403/401) and validating `Host` header against DNS rebinding attacks.
  - Local kiosk and OSD overlay operate smoothly on loopback.
- **Credentials Stripped from Frontend & API Flows (`templates/index.html`, `templates/hosts.html`, `app/main.py`)**:
  - Removed plaintext passwords from all HTML templates, DOM attributes (`data-password`), and JSON API responses.
  - Exposed only boolean flag `has_password`.
  - Enforced strict password semantics: empty field denotes "no replacement" (preserves existing backend password); credential clearing requires explicit action (`clear_password`); single-session temporary passwords supported (`save_password=False`).
  - Strict `0600` permissions and `0700` directories for config files (`hosts.yaml`, `settings.yaml`, `x11vnc.pass`).
- **VNC Strictly Bound to Tailscale (`scripts/x11vnc-start.sh`, `app/vnc.py`)**:
  - With `bind_tailscale_only: true`, eliminated unsafe fallback to `0.0.0.0` or local LAN: if Tailscale is not ready, launcher exits with error code letting systemd retry.
  - Removed default hardcoded `thinclient` password from new installs: explicit password configuration required before VNC starts.

### Filesystem & Installer Reliability (FS-01, FS-02, INS-01)
- **Volatile Runtime Logging and Read-Only Root (`app/rdp.py`, `systemd/thinclient.service`)**:
  - Moved runtime logs to volatile directory (`/run/thinclient`, configured with `RuntimeDirectory=thinclient` in systemd).
  - Resilient error handling: controlled fallback to `/dev/null` on protected filesystem or inode exhaustion.
- **`/data` Persistence, Migration, and Idempotent Rollback (`scripts/setup-readonly-fs.sh`)**:
  - Dynamic detection of actual partition UUID without assuming fixed labels.
  - Safety verification preventing accidental selection of root (`/`) or boot partitions.
  - Eliminated implicit formatting of ext4 partitions containing existing data.
  - Abort RO activation if `/data` mount fails or is unwritable.
  - Coherent rollback (`--undo`) preserving newest configurations on `/data` before restoring `/etc/fstab`.
- **Clean and Conservative Installer (`install.sh`)**:
  - Safe clone via staging directory preventing collisions in non-empty targets.
  - Removed orphan `EOF` at script end.
  - Clean separation between code and user config (no destructive overwrites).
  - Seamless support for both `chromium` and `chromium-browser` packages.

### Startup Performance & State Management (BOOT-01, BOOT-02)
- **Instant Non-Blocking Cyberpunk Splash (`templates/index.html`)**:
  - Eliminated artificial delays (`setTimeout`): when network and VPN are active, splash transitions in <= 200ms.
  - Recovery controls ("Configure Wi-Fi", "Open Dashboard") immediately interactive.
  - Single-request polling with `AbortController` and instant cancellation on splash exit.
- **Local `/healthz` Endpoint and Background State Cache (`app/main.py`)**:
  - High-speed `/healthz` endpoint (zero subprocesses, no network/DNS lookups).
  - Background system status collection with thread-safe cache and monotonic time TTL (`time.monotonic()`), preventing duplicate subprocess spawning under concurrent requests.
  - Strict timeouts and fallback from hostname to direct IP for RDP host checks.
  - Removed indiscriminate masking of `logrotate.timer` from `scripts/optimize-boot.sh`.

### Session Lifecycle, Networking & Updates (RDP-01, NET-01, WIFI-01, UPD-01)
- **FreeRDP Session Isolation and Kiosk Coordination (`app/rdp.py`)**:
  - Created `RDPSession` class with unique `session_id`. Monitoring thread tracks only its own instance without altering subsequent sessions.
  - Replaced `os.setsid` with `start_new_session=True`.
  - Targeted `SIGSTOP`/`SIGCONT` signaling specifically to kiosk browser processes (`chromium.*--kiosk`) without impacting unrelated user processes.
- **Tailscale Cache Invalidation and Robust Wi-Fi Parsing (`app/tailscale.py`, `app/wifi.py`, `templates/wifi.html`)**:
  - Immediate cache invalidation on daemon restart.
  - Robust parser for terse `nmcli` output handling `\:`, `\\`, quotes, and UTF-8 characters.
  - Constructed Wi-Fi action buttons via DOM APIs (`addEventListener`), preventing JavaScript injection vulnerabilities in network names.
  - Non-destructive Wi-Fi connection workflow preserving previous working profiles on incorrect credentials.
- **Atomic Debian OS Updater and Mount State Preservation (`app/system.py`)**:
  - Atomic setting of `running` status under lock before thread creation, preventing concurrent update workers.
  - Tracked initial mount state (RO vs RW) with faithful restoration (no RO enforcement on systems originally mounted RW).
  - Reported `completed_ro_failed` state if APT packages updated but RO remount failed.

### Direct-to-RDP Mode (BOOT-03)
- **Configurable Direct RDP Boot (`scripts/direct_rdp_coordinator.py`, `scripts/xinitrc`, `config/settings.yaml`)**:
  - Introduced `startup.mode: direct_rdp` mode (disabled by default).
  - Dedicated coordinator awaiting network connectivity and launching default host session without initially starting Chromium.
  - Automatic fallback to Kiosk Dashboard on timeout, error, or session disconnect without bounce loops.

### Integrated Test Suite (TEST-01)
- **25 Automated Regression Tests (`tests/`)**:
  - Covered all required test scenarios: T01-T05 (Security), T06-T10 (Filesystem & Installer), T11-T15 (Boot & Healthz), T16-T17-T24 (RDP Lifecycle & Coordinator), T18-T20 (Network & Wi-Fi), T21-T23-T25 (Updater & Settings Schema).

## [0.2.16] - 2026-10-25

### Fixed & Improved (Read-Only Boot & Appliance Mode)
- **Eliminated Boot Swap Errors (`scripts/setup-readonly-fs.sh`, `/etc/rpi/swap.conf`)**:
  - Cleaned up `/var/swap` residual file on SD card prior to RO mount, configuring `Mechanism=zram` for compressed RAM swap allocation.
  - Masked MicroSD swap services (`rpi-resize-swap-file`, `rpi-remove-swap-file@`, `rpi-setup-loop@var-swap`, `dphys-swapfile`), eliminating boot warnings (`0 failed units`).
- **Stabilized Chromium & Xorg Startup on Read-Only Filesystem (`scripts/xinitrc`, `systemd/thinclient-ui.service`)**:
  - Redirected `--user-data-dir` and `--disk-cache-dir` of Chromium to volatile `/tmp` directory (tmpfs), fixing black screen crash loop on boot.
  - Redirected Xorg server log to `/tmp/Xorg.0.log` preventing write locks upon RO remount.

## [0.2.15] - 2026-10-25

### Added
- **Turnkey Automated One-Liner Installer for Raspbian / Debian (`install.sh`, `scripts/install.sh`)**:
  - Quick installation script runnable directly via `curl -sSL https://raw.githubusercontent.com/hidaba/HidaThin/main/install.sh | sudo bash` or locally with `sudo bash install.sh`.
  - Automated installation and setup of system packages (Xorg, Openbox, Chromium kiosk, Python 3, Flask, FreeRDP 3, x11vnc, NetworkManager, wireless-tools).
  - Automated installation and enablement of Tailscale WireGuard Mesh.
  - Synchronized repository into `/opt/thinclient` with appropriate ownership, permissions, and log paths.
  - Applied hardware optimizations: 1:1 linear flat pointer profile, 500 Hz USB polling (`usbhid.mousepoll=2`), 128 MB GPU allocation (`gpu_mem=128`), and SD card wear reduction (`vm.swappiness=10`).
  - Fast-boot script execution to mask unneeded background services.
  - Registered and enabled systemd services (`thinclient.service`, `thinclient-ui.service`, `thinclient-vnc.service`, `cpu-governor.service`).
  - Added wrapper script `scripts/install.sh`.
- **Repository Maintenance Rule**:
  - Established binding maintenance rule ensuring `install.sh` is continuously kept up to date whenever repository files, dependencies, or service configurations are added, removed, or modified.

## [0.2.14] - 2026-10-25

### Resilience & Maintenance
- **Read-Only Root Filesystem with Persistent /data Partition (Solution B)**:
  - **Automated Setup Script (`scripts/setup-readonly-fs.sh`)**: configured root (`/`) and `/boot/firmware` in read-only (`ro`) in `/etc/fstab`, persistent bind-mounts for HidaThin configs, Tailscale state, and NetworkManager profiles, RAM tmpfs partitions (`/tmp`, `/var/tmp`, `/var/log`, `/var/spool`), and volatile journald storage.
  - **Debian OS Update with Guaranteed RW/RO Management (`app/system.py`)**: background worker unlocking filesystem to write (`rw`), running `apt update` & `apt dist-upgrade -y`, cleaning packages with `clean`/`autoremove`, syncing physical buffers, and reliably restoring Read-Only (`ro`) in `finally` block.
  - **Maintenance & Update Web Interface (`templates/settings.html`, `static/css/style.css`)**: dedicated section in Settings with live status badge (`READ-ONLY (Protected SD)` vs `WRITE (RW)`), manual unlock toggle, and Debian OS upgrade button with auto-scrolling terminal modal and progress indicator.
  - **Filesystem Status in Diagnostics (`templates/diagnostics.html`)**: displayed root and `/data` mount status on diagnostic dashboard.
  - **Automatic Config Write Fallback (`app/main.py`, `app/system.py`)**: automatic temporary on-demand RW remount when saving `hosts.yaml` and `settings.yaml` under protected filesystem.

## [0.2.13] - 2026-10-25

### Optimization & Boot Speed
- **Aggressive Systemd Services Pruning & Masking Script (`scripts/optimize-boot.sh`)**:
  - Automated script disabling and masking unneeded background daemons and timers for a dedicated thin client (~2-4s boot speedup, reduced SD I/O bottlenecks).
  - Masked periodic timers: `apt-daily.timer`, `apt-daily-upgrade.timer`, `man-db.timer`, `e2scrub_all.timer`, `logrotate.timer`.
  - Disabled unused services: `cups` (printing), `avahi-daemon` (redundant with Tailscale MagicDNS), `ModemManager`, `triggerhappy`, `plymouth`, `bluetooth`, and `hciuart`.
  - Disabled boot-blocking syncs: `systemd-udev-settle.service` and `systemd-time-wait-sync.service`.
  - Added `--undo` parameter for immediate restoration.
  - Documented in [README.md](file:///y:/Progetti/thinclient/README.md) and tracked in [TODO.md](file:///y:/Progetti/thinclient/TODO.md).

## [0.2.12] - 2026-10-25

### Fixed & Optimized
- **Eliminated Mouse Lag and Input Latency (Local & RDP)**:
  - **Direct Linear Pointer Profile (`flat`)**: configured Xorg (`/etc/X11/xorg.conf.d/50-mouse.conf`) with `Option "AccelProfile" "flat"` and `Option "AccelSpeed" "0.2"`. Default `libinput` `adaptive` profile applied smoothing and deceleration curves, causing noticeable inertia. With `flat`, tracking is 1:1, instant, and curve-free.
  - **Increased Hardware USB Polling Rate (`usbhid.mousepoll=2`)**: forced 500 Hz (2ms) USB polling at runtime and in `/boot/firmware/cmdline.txt`, cutting packet latency from 10ms to 2ms.
  - **Removed `unclutter` Daemon (`scripts/xinitrc`)**: eliminated `unclutter` daemon that hid mouse pointer after 3s via invisible X11 subwindow, resolving cursor freeze upon resumption.
  - **Disabled Legacy X11 Acceleration Thresholds (`xset m 1 1`)**: applied 1:1 linear mapping in X server.
  - **Wireless Dongle 2.4 GHz RF Interference Mitigation**: documented known EMI between HDMI/Wi-Fi and nano-USB receivers on Pi 3, recommending USB extension cables if jitter is observed.

## [0.2.11] - 2026-10-25

### Fixed & Improved
- **Robust Wi-Fi Network Switching & Credential Conflict Resolution**:
  - **Automatic Profile Cleanup (`app/wifi.py`)**: proactive removal of obsolete or broken NetworkManager profiles associated with target SSID before attempting connection. Previously, invalid passwords produced broken `need-auth` profiles causing `no secrets: No agents were available for this request` on subsequent attempts.
  - **Clean Rollback on Error**: on handshake failure or timeout, temporary profiles are purged immediately, preventing fruitless background reconnect loops.
  - **Clear User Feedback**: mapped low-level `nmcli` errors into friendly, accurate diagnostic messages (wrong password, network not found, weak signal timeout).
  - **Instant Network Cache Invalidation**: `invalidate_network_cache()` clears 15s cache on network switch or deletion, letting the UI update immediately.
  - **Wi-Fi Modal UI Enhancements (`templates/wifi.html`)**:
    - Added interactive password visibility toggle ("👁" and checkbox).
    - Added `Enter` key submit support.
    - Added autofocus on password field upon opening modal.

## [0.2.10] - 2026-10-17

### Fixed & Improved
- **Resolved Missing Splash Screen on Boot**:
  - **Ultra-Fast UI Startup (13.8s)**: moved `thinclient.service` dependency from `network.target` to `basic.target`. `network.target` previously waited 31s for Wi-Fi negotiation before starting UI, causing a black screen. With `basic.target`, `thinclient-ui.service` and Chromium launch in just **13.8 seconds** from power-on.
  - **Kernel `boot_id` Tracking on `/api/boot/status`**: integrated unique `boot_id` from `/proc/sys/kernel/random/boot_id` generated on each reboot. Ensures splash screen plays reliably on every startup without Chromium session cache suppression.
  - **Chromium Kiosk Incognito Mode**: added `--incognito` and `--lang=en` in `scripts/xinitrc` preventing session restore popups or stale caches.
  - **Immediate Splash Visibility**: removed initial `display: none` from HTML markup; Cyberpunk overlay renders on the first frame without flicker.
  - **Guaranteed Bootstrap Sequence (3.5 - 4.0s)**: smooth progress allowing users to see all 4 initialization stages (UI, Network, Tailscale, RDP Host) with green checkmarks before fading into dashboard.

## [0.2.9] - 2026-10-16

### Added
- **Native Hot-Corner OSD Overlay (Top-Left during RDP session)**:
  - **Tkinter OSD Microservice (`app/overlay.py`)**:
    - Borderless window for X11 (`DISPLAY=:0`) with `overrideredirect(True)` and `attributes('-topmost', True)`, staying above fullscreen FreeRDP 3 (`/f`).
    - Ultra-low resource footprint (~15-20 MB RAM, 0% CPU in idle).
    - **Hot Corner Trigger (1.0s)**: minimal activation area (16x16 px) in top-left corner (`0, 0`). Expands only when cursor hovers continuously for >= 1s, preventing accidental activation.
    - **Information Panel**: displays local IP (Wi-Fi SSID or Ethernet), Tailscale WireGuard VPN IP, and active remote host.
    - **"Disconnect Session" Button**: terminates RDP session with one click via `/api/rdp/disconnect`, immediately waking Chromium Kiosk and closing the overlay.
    - **Dismiss Timer (2.0s)**: starts 2-second countdown when cursor leaves overlay perimeter; resets if cursor returns, otherwise collapses back into hidden trigger mode.
  - **FreeRDP Lifecycle Integration (`app/rdp.py`)**:
    - Automatically launches overlay on RDP connection and cleanly stops it on disconnection.
  - **Diagnostics & Testing (`app/main.py`, `templates/diagnostics.html`)**:
    - Added `/api/overlay/test` test endpoint and interactive "Test OSD Overlay" button in Diagnostics panel.

## [0.2.8] - 2026-10-16

### Added
- **VNC Remote Supervision & Assistance (Desktop Shadowing on DISPLAY :0)**:
  - **Dedicated Systemd Service (`systemd/thinclient-vnc.service`)**:
    - Bound to `DISPLAY=:0` to mirror physical screen in real time (both Kiosk UI and active FreeRDP 3 session).
    - Non-blocking parallel startup (`After=thinclient-ui.service tailscaled.service`, `PartOf=thinclient-ui.service`).
  - **RPi 3 Optimized Launch Script (`scripts/x11vnc-start.sh`)**:
    - Checks and awaits X11 display availability (`/tmp/.X11-unix/X0` and `xset -q`).
    - Low-CPU parameters (`-wait 50 -defer 40 -noxdamage -repeat`) maintaining CPU usage under 5-10% without VC4/Glamor acceleration conflicts.
    - Intelligent bind mode: strictly bound to Tailscale WireGuard IPv4 (`-listen $TS_IP` or `-interface tailscale0`) preventing unauthorized access from local LAN.
    - Encrypted password file with `0600` permissions (`config/x11vnc.pass`).
  - **Python Backend & REST API (`app/vnc.py`, `app/main.py`)**:
    - Daemon status monitoring and active client connection tracking via socket inspection (`ss`/`netstat`).
    - RESTful APIs `/api/vnc/status`, `/api/vnc/save`, `/api/vnc/restart`.
    - Live password update via `x11vnc -storepasswd`.
  - **Web UI & Kiosk Integration**:
    - **Settings Panel (`/settings`)**: dedicated "Remote Assistance (VNC)" section with toggle switch, Tailscale-only restriction, password management, and MagicDNS/IP endpoints.
    - **Diagnostics Panel (`/diagnostics`)**: card with service state, port 5900, connected clients, and restart button.
    - **Live Header Indicator (`base.html`, `app.js`)**: dynamic badge displaying *"Remote Assistance Active"* when a technician connects to port 5900.

## [0.2.7] - 2026-10-16

### Added & Optimized
- **Critical Boot Speedup (Reduced boot time from 71s to ~16s)**:
  - **Decoupled Kiosk UI Startup**: removed blocking network dependency (`After=network-online.target tailscaled.service`) from `thinclient.service`. Local Flask server and Chromium Kiosk start immediately without waiting for external network or Tailscale.
  - **Eliminated Systemd Bottlenecks**: disabled and masked residual `cloud-init` services (`cloud-init-main`, `cloud-init-local`, `cloud-init-network`, `cloud-config`, `cloud-final`), saving >10s on `sysinit.target`.
  - **Eliminated Network Wait**: disabled and masked `NetworkManager-wait-online.service`, allowing NetworkManager and Tailscale to connect in background while graphics are running.
  - **Disabled Unnecessary Services**: disabled `rpi-eeprom-update.service` (unsupported on Pi 3), `keyboard-setup.service`, and `console-setup.service`.
  - **Firmware & Silent Boot Optimizations (`config.txt` / `cmdline.txt`)**:
    - Enabled `boot_delay=0`, `disable_splash=1`, `initial_turbo=30` (maximum CPU clock for first 30 seconds of boot).
    - Disabled `camera_auto_detect=0` and `display_auto_detect=0` to eliminate futile I2C probe cycles.
    - Configured **Silent Boot** in `cmdline.txt` (`quiet loglevel=3 logo.nologo vt.global_cursor_default=0 consoleblank=0`), suppressing kernel scrolling text.
    - Instant dark X11 root background in `scripts/xinitrc` (`xsetroot -solid "#0f172a"`).
- **New Cyberpunk Theme and "HiDaThin" Rebranding**:
  - Introduced official **HiDaThin** (Remote Thin Client OS via Tailscale) branding across UI and splash screen.
  - Generated and integrated high-definition **Cyberpunk** artwork (`cyberpunk_splash.jpg`), featuring dark carbon mainframe, cyan neon circuits, and HUD effects.
  - Redesigned splash screen card with Cyberpunk HUD style, `#00f0ff` neon borders, retro-futuristic scanlines, electric cyan/magenta progress bar, and high-contrast checklist.
  - Fixed JavaScript syntax typo that inhibited button handlers and bootstrap controller, restoring immediate responsiveness.
  - Added automatic suppression of Chromium translation popups (`translate="no"`, `meta notranslate`).

## [0.2.6] - 2026-10-16

### Optimized
- **FreeRDP GPU Hardware Acceleration (Glamor / X11)**:
  - Enabled `/gdi:hw` flag in FreeRDP 3: 2D rendering and blitting delegated directly to Xorg server with `vc4-kms-v3d` driver and Glamor acceleration on VideoCore IV GPU, eliminating software CPU rasterization.
  - Enabled thin-client specific Microsoft EGFX graphics pipeline: `/gfx:progressive,thin-client:on,small-cache:on` for balanced profile and `/gfx:RFX,thin-client:on,small-cache:on` for performance profile.
  - Replaced `/network:lan` with `/network:broadband` and disabled heavy Windows desktop effects (`-wallpaper`, `-menu-anims`, `-window-drag`), reducing unnecessary pixel transfers. Fixed animation parameter syntax typo (`-menu-anims`).
- **Automatic Chromium Kiosk Suspension**:
  - Upon starting full-screen RDP session, Flask backend sends `SIGSTOP` to Chromium Kiosk, freezing its processes (0% CPU, no MicroSD swapping).
  - Upon session exit, Chromium is resumed immediately via `SIGCONT`.
- **Critical Hardware Diagnostics**:
  - Detected active power supply undervoltage (`throttled=0x50005`), causing hardware firmware to halve CPU clock from 1.2 GHz to 600 MHz.

## [0.2.5] - 2026-10-16

### Fixed & Improved
- **NLA Authentication Handling and FreeRDP Diagnostics**:
  - **FreeRDP Error Code Mapping**: translated numeric exit codes (e.g. 145 for NLA authentication failure, 134 for invalid credentials, 141 for unreachable host) into clear user messages instead of raw `code: 145`.
  - **User Cancellation Handling**: silenced spurious error on clicking "Cancel" (`SIGTERM`).
  - **Default Username per Host Support**: added optional `username` field in `config/hosts.yaml` and in host management UI (`/hosts`), pre-filling username upon host selection.
  - **Smart Credentials UX**: automatic expansion and focus of password field when target host requires Network Level Authentication (NLA), with `Enter` key submission support.

## [0.2.4] - 2026-10-16

### Optimized
- **CPU Performance & Input Latency Reduction**:
  - **System Call Caching**: introduced 15s TTL cache for `get_network_status()` (`nmcli`, `ip`) and `get_tailscale_status()` (`tailscale status`), eliminating load on `NetworkManager` and `dbus-daemon`.
  - **Zero-Overhead Wi-Fi Signal Reading**: direct reads from `/proc/net/wireless` avoiding invasive periodic scans via `nmcli dev wifi`.
  - **Web Interface Polling**: increased polling interval from 4s to 15s in `static/js/app.js`.
  - **Chromium Kiosk Optimization**: disabled ANGLE GPU process (`--no-gl-override`, `--disable-gpu`, `--disable-gpu-rasterization`, `--disable-software-rasterizer`), saving >120 MB RAM and 20% steady-state CPU on Raspberry Pi 3.

## [0.2.3] - 2026-10-16

### Fixed
- **Keyboard & Mouse Detection in Xorg**:
  - Installed missing X11 input driver packages: `xserver-xorg-input-all`, `xserver-xorg-input-libinput`, `libinput10`, and `xinput` utility. Previously Xorg detected USB peripherals via udev but ignored them due to missing drivers.
  - Removed `-nocursor` flag from X server startup command in `systemd/thinclient-ui.service`. Mouse pointer is visible during motion.

## [0.2.2] - 2026-10-07

### Added
- **Tailscale & MagicDNS**:
  - Installed official Tailscale package (v1.102.5).
  - Authenticated node `thin01` (IP `100.68.91.18`).
  - Enabled and started `tailscaled.service`.
  - Verified MagicDNS resolution (`taild1b0f0.ts.net`) and ping connectivity (7-11ms latency to `pc-mimmo`, `pc-officina`, `pc-studio`).
  - Verified TCP port 3389 (RDP) reachability across all remote PCs.
- **FreeRDP 3 Client**:
  - Installed `freerdp3-x11` (v3.15.0) with `/usr/bin/xfreerdp` symlink.
  - Optimized startup parameters for Raspberry Pi 3: `/cache:bitmap:on,offscreen:on`, `+clipboard`, `/network:lan`, `/compression`, `/cert:ignore`.
  - Supported three performance profiles: High Performance (16-bit, compression), Balanced (default, 24-bit, crisp fonts), Quality (32-bit, GFX AVC420).
  - Secure credential passing via RAM stdin (`/from-stdin:force`), with no plaintext storage on disk or in logs.
- **Raspberry Pi 3 System Optimizations**:
  - Disabled unnecessary services (`bluetooth.service`, `avahi-daemon.service`, `avahi-daemon.socket`).
  - Configured CPU scaling governor to permanent `performance` via `cpu-governor.service` to eliminate clock transition latency.
  - Configured `vm.swappiness=10` in `/etc/sysctl.d/99-thinclient.conf` to minimize MicroSD writes.
  - Allocated `gpu_mem=128` in `/boot/firmware/config.txt`.
- **Thin Client Application (`/opt/thinclient`)**:
  - Lightweight Python + Flask backend with RESTful API on port 8080.
  - Fullscreen responsive dark-mode web UI optimized for mouse and keyboard with large touch targets:
    - Main screen: Wi-Fi status, Tailscale status, PC dropdown selector (`pc-mimmo` default), large "CONNECT" button, quick settings menu.
    - Wi-Fi Management: network scanning via `nmcli`, signal strength and encryption display, connection and automatic persistence.
    - RDP Host Management: persistent list (`config/hosts.yaml`), add/edit/delete hosts, default host selection, ping test.
    - Diagnostics: real-time summary of LAN IP, SSID, signal strength, gateway, DNS, Tailscale state, RAM, CPU, temperature, throttling alarms, and port 3389 test.
    - Settings: performance profiles, display resolution, and color depth configuration (`config/settings.yaml`).
- **Autostart and Kiosk Mode**:
  - Systemd service `thinclient.service` with automatic restart on failure (`Restart=always`).
  - Graphical service `thinclient-ui.service` based on Xorg, Openbox, and Chromium kiosk mode (`--kiosk --app=http://127.0.0.1:8080`) with watchdog.
  - Configured logrotate for automatic session log rotation in `/etc/logrotate.d/thinclient`.

## [0.2.1] - 2026-10-07

### Added
- Preliminary hardware and software analysis of Raspberry Pi 3 Model B (Rev 1.2, Debian 13 trixie aarch64).
- Safety backup of original system configuration files in `/root/backup_original_config/`.
- Configured SSH authentication with ed25519 key for secure remote management and automation.
- Verified package availability for `freerdp3-x11`, `xserver-xorg`, `openbox`, `NetworkManager`.
