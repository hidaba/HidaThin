# HidaThin — Delivery Report: Boot Optimization, Resilience, and Bug Fixing

Date: October 25, 2026  
Version: `0.2.17`  
Working Branch: `feature/boot-opt-and-bugfix`  
Base Commits: `3f08a27` (Audit base v0.2.16) / `4523da2` (Latest local pre-intervention commit)  

---

## 1. Task Summary and Implementation Status

| Task ID | Summary Description | Status | Verification Notes |
|---|---|---|---|
| **SEC-01** | Default bind `127.0.0.1`, RDP credential isolation, remote auth, and password semantics | **Implemented** | Verified via unit and integration tests (T01, T02, T03). Passwords removed from DOM, HTML, and JSON. |
| **SEC-02** | VNC strictly bound to Tailscale (no LAN/0.0.0.0 listener or empty password) | **Implemented** | Verified via T04 and T05. Rejection of LAN/0.0.0.0 fallback, removal of default `thinclient` password. |
| **FS-01** | Volatile runtime logs compatible with Read-Only root filesystem | **Implemented** | Verified via T06. Redirection to `/run/thinclient` (systemd RuntimeDirectory) with `/dev/null` fallback. |
| **FS-02** | `/data` persistence, dynamic UUID detection, no implicit formatting, and coherent rollback | **Implemented** | Verified via T09 and T10. Abort on invalid block device or mount failure; recent data preserved on `--undo`. |
| **INS-01** | Clean installer, removed orphan `EOF`, staging dir for git clone, config preservation | **Implemented** | Verified via T07 and T08. Validated with `bash -n`, supports both `chromium` and `chromium-browser`. |
| **BOOT-01** | Instant cyberpunk splash, zero artificial delays, immediate checks and cancellability | **Implemented** | Verified via T11, T12, and T13. Splash transition <= 200ms when ready, recovery buttons always interactive. |
| **BOOT-02** | `/healthz` endpoint, background system collector with thread-safe cache & bounded workers | **Implemented** | Verified via T14 and T15. No stalls on slow subprocesses; strict TCP/DNS timeouts. |
| **RDP-01** | Isolated session lifecycle (`RDPSession`), deterministic supervision, targeted Chromium signals | **Implemented** | Verified via T16 and T17. Stale sessions do not clobber new instances; `start_new_session=True`. |
| **NET-01** | Tailscale cache invalidation on restart, strict timeouts, and direct IP fallback | **Implemented** | Verified via T18. Fresh status retrieved immediately following `tailscaled` service restart. |
| **WIFI-01** | `nmcli` parser for `\:`, `\\`, quotes and Unicode; safe DOM buttons; non-destructive connect | **Implemented** | Verified via T19 and T20. Working prior Wi-Fi profiles are not deleted on connection failure. |
| **UPD-01** | OS updater worker with preventive atomic lock, sync, and faithful mount state restoration | **Implemented** | Verified via T21, T22, and T23. Distinction for `completed_ro_failed` and respect of initial state (RW/RO). |
| **BOOT-03** | Configurable direct-to-RDP mode with dedicated coordinator and dashboard fallback | **Implemented** | Verified via T24 (`direct_rdp_coordinator.py`). No infinite bounce loops between browser and FreeRDP. |
| **TEST-01** | Automated regression test suite of 25 tests (T01 - T25) | **Implemented** | All 25 tests pass (`python -m pytest tests/ -v`). |
| **DOC-01** | Aligned documentation (`README.md`, `TODO.md`, `CHANGELOG.md`, settings) | **Implemented** | Documented all new settings, security architecture, and validation procedures. |

---

## 2. Modified Files and Rationale

1. **`app/main.py`**:
   - HTTP default bind set to `127.0.0.1:8080`.
   - Access control middleware rejecting unauthorized remote mutating calls and guarding against DNS rebinding.
   - Exclusion of credentials via `load_hosts_data(include_passwords=False)` for all HTML templates and JSON API responses.
   - High-speed `/healthz` endpoint and thread-safe background system status collector with rate limiting and bounded workers.
   - Password semantics: use saved password, support transient single-session passwords (`save_password=False`), explicit credential clearing (`clear_password`).
2. **`app/system.py`**:
   - Validation schema for `settings.yaml` with controlled deep-merge to preserve untouched sections.
   - Atomic `write_secure_yaml` function with `0600` file permissions and `0700` directories.
   - OS update worker (`_os_update_worker` / `start_os_update`): atomic setting of `status="running"` under lock before thread creation; initial mount state detection (RO vs RW) with faithful restoration; `completed_ro_failed` status if final RO remount fails.
3. **`app/rdp.py`**:
   - Encapsulation of sessions in `RDPSession` class with unique `session_id`.
   - Stable reference passed to monitor thread, preventing cleanup of stale sessions from disrupting active ones.
   - Replaced `preexec_fn=os.setsid` with `start_new_session=True`.
   - Runtime logging redirected to volatile directory (`/run/thinclient` or `/tmp/thinclient-logs`) with `/dev/null` fallback for read-only filesystem or full disk.
   - Targeted signaling to kiosk browser (`chromium.*--kiosk`) without affecting unrelated processes.
4. **`app/tailscale.py`**:
   - Immediate cache invalidation using monotonic time upon explicit daemon restart.
   - Fallback to direct IP when MagicDNS hostname resolution fails.
5. **`app/vnc.py`**:
   - Safe persistence of VNC settings without overwriting unrelated configuration sections.
   - Removal of default `thinclient` password and strict block against listening when no password is set.
6. **`app/wifi.py`**:
   - Dedicated `parse_nmcli_terse_line` parser handling escaped colons (`\:`), backslashes (`\\`), and UTF-8 characters.
   - Non-destructive connection workflow preserving existing working profiles on authentication failure.
7. **`scripts/x11vnc-start.sh`**:
   - Strict block against listening on `0.0.0.0` or local LAN when `bind_tailscale_only: true` and VPN is not ready.
   - Mandatory check for `0600` password file prior to launching listener.
   - Dynamic port and activation status detection from `settings.yaml`.
8. **`scripts/setup-readonly-fs.sh`**:
   - Dynamic UUID detection for `/data` partition without hardcoding labels.
   - Safety checks preventing accidental selection of `/` or `/boot`.
   - Elimination of implicit formatting on pre-existing ext4 partitions.
   - Safety abort if `/data` mount fails or is not writable.
   - Coherent `--undo` routine synchronizing recent configs on `/data` before restoring `/etc/fstab`.
9. **`scripts/direct_rdp_coordinator.py`**:
   - Supervisor script for direct FreeRDP boot bypassing Chromium.
   - Network readiness waiting with configurable timeout (default 20s) and clean fallback to Kiosk Dashboard.
10. **`scripts/xinitrc`**:
    - Dynamic browser binary resolution (`chromium` or `chromium-browser`).
    - Bounded HTTP 200 check on `/healthz` prior to launching graphical UI.
    - Integration of `direct_rdp` mode.
11. **`scripts/optimize-boot.sh`**:
    - Removed masking of `logrotate.timer` and `e2scrub_all.timer`.
12. **`install.sh`**:
    - Removed orphan `EOF` at script termination.
    - Used temporary staging directory for `git clone` preventing non-empty destination errors.
    - Preserved existing user configurations and enforced `0600`/`0700` permissions.
13. **`systemd/thinclient.service`**:
    - Added `RuntimeDirectory=thinclient` and `RuntimeDirectoryMode=0755`.
14. **`templates/index.html`**:
    - Removed passwords from DOM attributes.
    - Rewrote splash controller for <= 200ms transitions once services are healthy.
    - Recovery buttons ("Configure Wi-Fi", "Open Dashboard") always visible and interactive.
15. **`templates/hosts.html`**:
    - Removed password serialization in HTML (`data-password` and `host|tojson` removed).
    - Edit mode with protected placeholder and explicit credential deletion checkbox.
16. **`templates/wifi.html`**:
    - Dynamic row and button generation via DOM APIs (`addEventListener`), preventing XSS in SSID names.
17. **`tests/`**:
    - Full regression test suite covering 25 test cases (`test_sec.py`, `test_fs_installer.py`, `test_boot_status.py`, `test_rdp_lifecycle.py`, `test_net_wifi.py`, `test_updater_settings.py`).

---

## 3. Test Execution and Results

Run full test suite:
```bash
python -m pytest tests/ -v
```
Result: **25 passed in 9.05s** (100% success rate).

---

## 4. Upgrade Procedure for Existing Systems

1. Connect to the Raspberry Pi via SSH:
   ```bash
   ssh root@<ip-address>
   ```
2. If filesystem is mounted read-only, temporarily remount as read-write:
   ```bash
   rw   # alias for mount -o remount,rw / && mount -o remount,rw /boot/firmware
   ```
3. Pull and apply the updated code without overwriting existing configuration:
   ```bash
   cd /opt/thinclient
   git pull origin main
   bash install.sh
   ```
4. If `config/settings.yaml` does not contain the new sections, secure defaults are automatically applied (`bind: 127.0.0.1`, `remote_enabled: false`, `startup.mode: dashboard`). To enable remote web management over Tailscale:
   ```yaml
   web_admin:
     bind: "0.0.0.0"
     port: 8080
     remote_enabled: true
     admin_token: "YourSecretToken"
   ```
5. Restart services:
   ```bash
   systemctl restart thinclient thinclient-ui thinclient-vnc
   ```
6. Restore read-only protection:
   ```bash
   ro   # alias for sync && mount -o remount,ro / && mount -o remount,ro /boot/firmware
   ```

---

## 5. Conservative Rollback Procedure

To roll back Read-Only mode or restore previous configurations while preserving modified data:
1. Run:
   ```bash
   sudo bash /opt/thinclient/scripts/setup-readonly-fs.sh --undo
   ```
2. The script automatically synchronizes all files from `/data/thinclient-config/`, `/data/tailscale/`, and `/data/NetworkManager/system-connections/` back into `/opt/thinclient/config/`, `/var/lib/tailscale/`, and `/etc/NetworkManager/system-connections/`, ensuring no passwords or network profiles are lost.
3. Reboot via `sudo reboot`.

---

## 6. Enabling and Disabling Direct-to-RDP Mode

### To enable Direct-to-RDP:
1. Edit `/opt/thinclient/config/settings.yaml`:
   ```yaml
   startup:
     mode: "direct_rdp"
     connect_timeout_seconds: 20
     fallback_to_dashboard: true
   ```
2. Ensure `/opt/thinclient/config/hosts.yaml` contains a valid default host (`default_host: ...`).
3. Upon reboot (`sudo reboot`), the Raspberry Pi awaits network and Tailscale readiness, then launches FreeRDP full-screen immediately without loading Chromium Kiosk.

### To disable Direct-to-RDP and return to Dashboard:
- If the FreeRDP session ends, or network fails to initialize within 20s, the system automatically opens the Kiosk Dashboard.
- From the Kiosk Dashboard (or via SSH), restore in `settings.yaml`:
  ```yaml
  startup:
    mode: "dashboard"
  ```

---

## 7. Remaining Hardware Measurements

Because development and unit tests run in simulated environments, the following hardware chronometer measurements should be performed on the physical test Raspberry Pi 3:
1. `systemd-analyze time` and `systemd-analyze critical-chain thinclient-ui.service`.
2. Power-on time to first visible splash screen frame.
3. Power-on time to active FreeRDP session (comparing `dashboard` vs `direct_rdp` mode).
4. Thermal and throttling verification under prolonged full-screen load: `vcgencmd get_throttled`.
