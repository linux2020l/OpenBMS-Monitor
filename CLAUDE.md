# CLAUDE.md

Context and rules for working on this repository.

## Project

**OpenBMS Monitor** (formerly JK BMS Monitor): read-only Windows desktop widget for a JK BMS over BLE (more brands planned). Proof of concept for
a home backup power system (~4 kWh battery; the PC itself runs from it).
The protocol logic may later be ported to an Android app for end users, so
keep it pure and well covered by test vectors.

Hardware (from the official JK app "About" screen, app V6.4.05):
- BMS: **JK_B1A8S20P**, HW **V11A**, SW **V11.53**
  → protocol variant **JK02_32S** (HW ≥ 11). Cell-info frame has 32 cell
  slots; only the populated ones are non-zero.
- BLE name "LFP 3.8kWh", MAC C8:47:80:1A:F9:9E (several other JK BMS are in
  radio range, so never auto-pick "the first JK device").
- Battery: **4S LiFePO4, 304 Ah** (~3.9 kWh, ~13.6 V), per the device-info
  frame and cell count in real captures.
- Second, newer BMS (owner has several): **JK-B2A8S20P HW 19H SW 19.34**,
  BLE name "LFP-4kWh", MAC C8:47:80:7A:DC:B3, 4S, 314 Ah. Same JK02_32S
  cell-info layout (verified 2026-11-14 at idle, current 0 A — sign/scale
  of current not yet seen under load). On Windows its frames arrive as
  128 + 128 + 44 bytes **without** the BCD prefix, plus stray 4-byte
  `AT\r\n` notifications (dropped). Serial number is 15 chars (HW 11A: 11).
  Fixture: `tests/fixtures/jk02_32s_b2a8s20p_hw19.txt`.
  A third JK ("E-Bike 5.2kWh") is far away in the yard (~−96 dBm): don't
  use it for captures.
- PC: Windows 11 Pro, built-in BLE adapter "RZ608 Bluetooth(R) Adapter"
  (MediaTek Wi-Fi/BT combo).

## Working with the owner

- Owner is experienced in electronics/embedded (STM32, CAN, BMS), beginner in
  application programming.
- Explain in chat in **Ukrainian**. Code, comments, README, commit messages and
  this file are in **English**.
- Prefer simple approaches over "perfect" ones. Comment non-obvious parts.
- Work in milestones; stop after each one and tell the owner exactly how to
  run and verify it.

## Hard requirements

1. **READ-ONLY.** Only documented read requests may ever be written to a
   BMS. For JK: device info (`0x97`) and cell info (`0x96`), defined in
   `jkbms_widget/drivers/jk/commands.py`. Every driver declares its exact
   frames in `allowed_frames` (whole-frame allowlist, no generic frame
   builder). The BLE layer has exactly one write function
   (`ble.send_request`) and it calls `driver.ensure_read_only()` right
   before `write_gatt_char`. Never add a register-write / settings command
   for any brand, not even behind a flag or for testing.
   `tests/test_ble.py` checks every registered driver.
2. Windows desktop, BLE only.
3. Small always-on-top, frameless, draggable widget: SOC %, current (A, signed),
   power (W), state (Charging / Discharging / Idle; idle if |I| < 1.0 A,
   configurable — owner's decision 2026-11-14: inverter standby draw
   counts as Idle), pack voltage, alarm indicator. Clicking the indicator shows
   active alarms in plain language.
4. Auto-reconnect; clear "disconnected" state in UI; manual disconnect (so the
   phone app can connect).
5. Persist window position and selected BMS (MAC address).

## UI target design (milestone 4)

The owner's original mockup image stays local only (not published, it is
an example of another app). Current look: [docs/screenshots/](docs/screenshots/)
(rendered from demo data, offscreen; README uses the English UI).
UI text: **Ukrainian (original) + English** (owner's request 2026-11-15).
Every visible string lives in `strings.py` (uk) and `strings_en.py` (en),
same UPPER_CASE names; `tests/test_strings.py` enforces matching names,
types, dict keys and {placeholders}. `strings.set_language()` swaps the
module globals at startup, BEFORE any window exists (views read strings
when built), so a language change applies after restart. Setting
`language`: "auto" (Windows display language: uk → uk, else en) / uk / en.
Never hard-code UI text elsewhere; tests that switch language must switch
back to "uk".
Elements:
- Title bar: app name, BLE connection status (dot + text), minimize, close.
- SOC ring with big percentage; "≈ N h до розряду" (time to empty/full,
  from remaining capacity / |I|).
- Tiles: current (A, signed), power (kW/W, signed), pack voltage, temperature.
- Status panel: overall health ("Акумулятор в нормі" or alarm summary, click
  for the alarm list), mode (Заряд / Розряд / Очікування), time left,
  cell voltage min–max, balancing yes/no, protections/alarms.
- Chart: SOC and current history with 1 h / 6 h / 12 h / 24 h ranges
  (needs a local history buffer).
Decision (owner, 2026-11-14): **compact always-on-top widget that expands
into the full dashboard** (and collapses back). Implemented in milestone 4:
`ui/compact.py` (SOC, V, A, W, state, alarm indicator, expand button,
right-click menu: expand / connect-disconnect / exit) and `ui/dashboard.py`
(mockup layout; title-bar X exits the app, "—" collapses to the widget).
History for the chart is in memory only (lost on restart), 10 s buckets.

## Stack

- Python 3.12, `bleak` (WinRT backend), PySide6, pytest. Later PyInstaller.
- BLE runs on its own asyncio loop in a background thread and sends parsed
  data to the GUI via a Qt signal (thread-safe, queued connection).
  Do not run bleak on the Qt main thread (e.g. via qasync): Qt initializes COM
  as STA there and the WinRT backend misbehaves in STA threads.
- Layering (keep it, it is what makes the Android port feasible):
  - `model.py` (pure): brand-independent `DeviceInfo`, `CellInfo` (fields a
    BMS lacks are None/empty → UI shows "—"), alarm **codes**
    (`ALARM_CODES`, `INFORMATIONAL_ALARMS`), `battery_state`, `describe`.
  - `drivers/` (pure, BMS drivers; added 2026-11-15 to prepare Daly / JBD /
    ANT / 100balance support): `base.py` (`BmsDriver`: id, name, GATT
    UUIDs, `connect_requests`, `poll_requests` + interval, `poll_until_data`,
    `allowed_frames`, `matches()` for scan detection, `new_decoder()`),
    `__init__.py` (registry `DRIVERS`, `get()`, `detect()`; unknown/missing
    id → JK, so old settings keep working).
    `drivers/jk/`: `commands.py` (allowlist), `frames.py` (`FrameAssembler`:
    chunks → CRC-valid 300-byte frames), `parser.py` (`Decoder`, variants,
    JK alarm bit → code map `ALARM_BITS`; unknown bits → `jk_bit_N`).
    Adding a brand: new `drivers/<brand>/` + register it + fixture from a
    real capture + tests; UI texts for any new alarm codes in both
    `strings*.py` (tests enforce it).
    Capture-only drivers (2026-11-15, `capture_only = True`, `RawDecoder`):
    `jbd.py`, `daly.py` (also 100Balance per aiobmsble README), `ant.py`.
    Request frames, UUIDs and matchers come from syssi/esphome-jbd-bms,
    syssi/esphome-ant-bms and patman15/aiobmsble (Apache-2.0; facts only, no
    code copied); `tests/test_drivers.py` checks our builders reproduce the
    frames quoted verbatim in those sources. Only pure reads are used: no
    JBD `DD 5A` writes / `FF AA` auth, no ANT 0x23 password / 0x51 write, no
    Daly device-info reads (X81 one carries the serial). ANT shares JK's
    FFE0/FFE1 UUIDs, so detection order is ANT (by name) → JBD → Daly → JK.
    Capture-only brands can't be picked as the monitored BMS
    (`drivers.monitorable`). Next: real decoders from community captures.
  - `diagnostics.py` (bleak): `record()` = one read-only capture session for
    any driver; `to_text/save()` write a shareable file (no MAC, driver
    `sanitize_events` scrubs private fields — JK: `drivers/jk/privacy.py`).
    UI: `ui/diagnostics_dialog.py` (menu + settings → "Record diagnostics…",
    60 s, saved to `Documents\JK BMS Monitor\`). Community guide:
    `docs/captures.md`, issue template `.github/ISSUE_TEMPLATE/bms-capture.yml`.
    `dump.py` (CLI, raw unsanitized developer log) still has its own loop.
  - Step C (owner's choices 2026-11-15): `notifications.py` (pure
    `Notifier`: low SOC with 5 % re-arm, new fault codes only, lost after
    60 s of reconnecting — not after a manual disconnect, full while
    charging — not when started full; shown as tray balloons via
    `Controller._toast`, never a modal box; settings `notify_enabled`,
    `low_soc_threshold`); `state.energy_kwh/local_midnight` (kWh from
    10 s history buckets, today + 7 days, dashboard status panel, refreshed
    with the chart); `ui/cells.py` (cells **tab** next to the chart in the
    dashboard); `state.history_csv` + menu "Export history (CSV)…"
    (comma, dot decimals, local ISO time).
    Chart range selection (owner 2026-11-15): left-drag on the chart
    shades a range and shows energy in / out, net and SOC change
    (`state.energy_between`, partial buckets by overlap;
    `chart.range_summary`); a click clears it, switching BMS clears it.
  - Step D1, several BMS at once (owner 2026-11-15; D2 = parallel banks
    below): `app.Monitor` = one BMS (source, tracker, notifier,
    history, its own `CompactWindow` + `TaskbarStrip`); `Controller.monitors`
    list, `active` = the one the dashboard shows (title-bar selector,
    clicking a strip/widget selects it). Shortcuts `ctl.source/history/
    compact/strip/...` point at the active monitor (single-BMS paths +
    tests). Settings: the main BMS stays in the old top-level fields
    (old files load unchanged), more BMS in `extra_devices` (`Device`
    dicts); `Settings.devices()/set_devices()`. Strips: `slot` i sits
    i × (width + 6 px) left of the main one, dragging moves the group
    (`taskbar_offset` is the group offset); in the full-screen corner they
    stack upwards. Tray icon = main BMS, red badge if any BMS has a fault.
    Per-BMS `visible` (eye in the settings list, `bms_visible` for the main
    one): hidden BMS stay connected and keep recording history, they just
    get no strip/widget and no slot. With several BMS, strips and widgets
    show the list number. Right-click on a strip/widget: that BMS's items
    first (hide, remove), then the shared menu ("Show on the taskbar"
    submenu brings hidden ones back). Python `write_text` on Windows writes
    CRLF; keep sources LF (git has `text=auto`) or exact-text edits fail.
    Settings dialog is tabbed (BMS list with add/change/remove, banks,
    display, state & alerts, system).
  - Step D2, parallel banks (owner's choices 2026-11-15: several banks, one
    strip per bank, offline member = computed from the rest + warning,
    bank notifies low SOC / full, members notify alarms / lost):
    `bank.py` (pure: `combine_cells` = mean voltage, summed current and
    Ah, SOC = sum remaining / sum nominal (plain mean if a capacity is
    unknown), MOSFET on only if on in every pack, alarm union;
    `bank_label` A, B, …). `settings.banks` = `BankConfig` dicts (id,
    name, member MACs, visible, compact_pos); `clean_banks` drops
    malformed banks, a BMS in two banks, banks under 2 members.
    `app.View` is the base of `Monitor` (one BMS) and `Bank`: own tracker,
    notifier, history (SQLite key `bank:<id>`), widget and strip.
    `Controller.views` = banks first, then BMS; `active` and the dashboard
    selector index into views; `label()` gives letters / numbers. A member's
    `on_cell` feeds its bank. `Snapshot.members/offline/partial` drive the
    amber "1 of 2 BMS offline" in dashboard, widget, strip letter, tray.
    Creating a bank hides its members' strips; ungrouping / removing a
    member (bank under 2) shows them again. Editor: `ui/bank_dialog.py`.
    Later the same day (owner): bank cells per pack (`Snapshot.packs`,
    `CellsView` groups on one common scale, own spread per pack),
    parallel "flow between packs" row (`bank.exchange_current` = min of
    summed charging / discharging currents; energy counters stay external
    = net history), user-picked letter per bank (`BankConfig.letter`,
    unique, banks sorted by letter, `free_letter`), and **series banks**
    (`BankConfig.kind`): voltage sum, mean current, SOC / Ah of the weakest
    pack, cells numbered 1..N across packs + overall spread, no flow row;
    an offline member counts with its last voltage for `SERIES_GRACE_S`
    (60 s), then `Snapshot.missing` → stale + red "no data from a BMS of
    the bank". Status dots removed from dashboard title and widget (owner).
  - Renamed to **OpenBMS Monitor** (owner 2026-11-15, v0.8.0; the app is
    not JK-only any more). Visible names only: title, `OpenBmsMonitor.exe`,
    `installer/OpenBmsMonitor.iss` (same AppId, `UsePreviousAppDir=no`,
    `[InstallDelete]` removes the old `JkBmsWidget` program folder and
    shortcuts, kills the old exe, deletes the old Run value), data folder
    `%APPDATA%\OpenBmsMonitor` (`settings.migrate_legacy_dir` moves the old
    `JkBmsWidget` folder on first start, never overwrites), Run value
    `OpenBmsMonitor` (`autostart.upgrade_entry` takes over the old one),
    `Documents\OpenBMS Monitor`, repo `linux2020l/OpenBMS-Monitor`
    (`updates.REPO`). The Python package stays `jkbms_widget` (internal).
  - Step E (owner 2026-11-15): `updates.py` (pure + one blocking
    `fetch_latest`: GET the public "latest release" API, generic
    User-Agent, no user data; `REPO` is the only place naming the GitHub
    repo; drafts / pre-releases / non-GitHub URLs ignored).
    `app.UpdateChecker` runs it on a daemon thread and signals back.
    Auto check 60 s after start, then daily, only with a settings file and
    not in replay (tests never hit the network). New version → one tray
    balloon per version (`update_notified`), bold menu item "Download
    version X…" opens the release page; settings → System: daily check
    on/off + "Check now". Never downloads or installs anything.
    CI: `.github/workflows/tests.yml` (pytest on windows-latest, push to
    main + PRs) and `release.yml` (tag `vX.Y.Z` = `__version__`, choco
    Inno Setup, `build.ps1` with `BUILD_PYTHON=python`, which throws on CI
    without Inno Setup; softprops/action-gh-release uploads the installer).
    Pushing workflow files needs a GitHub token with the `workflow` scope.
  - Widgets on the desktop (owner 2026-11-15, `widgets_on_desktop`):
    `CompactWindow.set_on_desktop` drops `WindowStaysOnTopHint`,
    `win_taskbar.pin_to_desktop` makes Progman the window's owner (never
    below the desktop, survives Win+D) and sends it to HWND_BOTTOM; owning
    alone failed on the owner's PC (Windows raises a window on every
    show / click), so `CompactWindow.nativeEvent` rewrites every
    WM_WINDOWPOSCHANGING to HWND_BOTTOM (`keep_at_bottom`). Verified on
    the real screen with a z-order script (under another window after
    show, raise and hide/show; still above Progman). No dimming for
    desktop widgets. Never show a modal box from code that tests
    reach without a tray (offscreen): `_notify` falls back to QMessageBox.
  - `capture.py` (log format; `# driver <id>` header), `replay.py` (plays a
    capture back with original timing).
  - `ble.py`: bleak only (scan with driver detection, characteristic
    selection by driver UUIDs + properties, the single write function
    `send_request`). `dump.py`: live logger + decoded console output.
  - Settings: `driver` (default "jk") + driver options (JK: `variant`).
  - `state.py` (pure): `StateTracker` (moving average + hysteresis),
    `time_left`, `History`, `Snapshot` (everything a view needs).
  - `strings.py` (pure): every user-visible string (uk) + formatters +
    language switching; `strings_en.py`: English texts.
  - `sources.py`: `BleSource` (bleak thread, auto-reconnect every 5 s,
    10 s no-data watchdog) and `ReplaySource` (endless loop of a capture);
    both talk to the GUI only through Qt signals.
  - `settings.py` (pure): `Settings` JSON, tolerant of missing/corrupt files.
  - `history_store.py` (pure, sqlite3): 10 s buckets per BMS MAC, 7-day
    retention; `History.on_bucket_closed` writes each bucket immediately.
  - `win_taskbar.py` (ctypes, no Qt): taskbar rect/edge/tray position,
    full-screen detection, light-theme check, `strip_geometry()` (pure, tested).
  - `autostart.py`: HKCU Run key, only when `sys.frozen`.
  - `app.py`: `Controller` (GUI thread; owns source, views, tray, shared
    menu, persistence) + `run_widget()` (settings, logging, single-instance
    lock, QT_SCALE_FACTOR before QApplication).
  - `ui/`: PySide6 only — theme, vector icons, SOC ring, chart, compact
    widget, taskbar strip, dashboard, alarm dialog, BMS picker.
  - `jkbms_widget_app.py` + `build.ps1`: PyInstaller **one-folder**
    windowed build `dist\JkBmsWidget\JkBmsWidget.exe` (faster start, fewer
    antivirus false positives than one-file), then Inno Setup 6
    (`installer/JkBmsWidget.iss`, ISCC in `%LOCALAPPDATA%\Programs\Inno
    Setup 6`) → `dist\JkBmsWidget-Setup-<version>.exe`. Per-user install
    (no admin) to `%LOCALAPPDATA%\Programs\JkBmsWidget`, en/uk wizard,
    optional autostart (same HKCU Run value as `autostart.py`), uninstall
    kills the app and removes the Run value, keeps `%APPDATA%` data.
    Version = `jkbms_widget.__version__`. Windows 10 1709+ x64 only.
    No CLI args = widget. Hidden `--exit-after N` for unattended exe tests
    (run with `QT_QPA_PLATFORM=offscreen`, then read `widget.log`).
    Never run the installer silently from Claude's shell: it changes the
    owner's real system (install dir, Run key) - let the owner run it.

UI rules learned the hard way (owner feedback 2026-11-14):
- Qt style is **Fusion + own dark palette** (`theme.apply_style`). The native
  `windows11` style drew list text black on dark and has laggy hover.
- No `WA_TranslucentBackground` on big windows (layered windows repaint the
  whole surface on every hover); rounded corners come from DWM
  (`win_taskbar.native_rounded_corners`). Only the taskbar strip stays
  translucent.
- Views update through `ui.widgets.Updater` (skip unchanged setText/
  setStyleSheet/setIcon); icons are `lru_cache`d; chart redraw ≥ 5 s apart.
- Checkbox/menu ticks are PNGs rendered at startup (stylesheets need files).
- `QAbstractSpinBox.NoButtons` + stylesheet shrinks the edit to 1 px: hide
  the buttons with `::up-button { width: 0 }` instead.
- Defaults (owner): taskbar mode; autostart (`--autostart`) never opens the
  dashboard; battery icon with a red corner badge for faults; current axis
  in 10 A steps (currents can exceed 100 A).

Taskbar mode: Windows 11 has no API for custom taskbar content (deskbands
removed), so `ui/taskbar_strip.py` is a topmost tool window placed over the
taskbar left of `TrayNotifyWnd`, re-raised every 500 ms (`SetWindowPos
HWND_TOPMOST`, no activation), hidden during full-screen apps
(`SHQueryUserNotificationState`), unsupported for vertical/auto-hide
taskbars. Win32 rects are physical px; divide by the primary screen's
devicePixelRatio for Qt. Owner's PC: taskbar 2560×48 at bottom, tray from x=2340.
  - `tools/make_fixture.py`: raw dump → sanitized fixture in `tests/fixtures/`.

## Commands

```powershell
.\.venv\Scripts\Activate.ps1
python -m pytest                 # unit tests
python -m jkbms_widget commands  # print allowlisted request frames
python -m jkbms_widget scan      # list nearby BLE devices
python -m jkbms_widget dump --address C8:47:80:1A:F9:9E --seconds 60  # live decode + raw log in logs/
python -m jkbms_widget replay tests\fixtures\jk02_32s_b1a8s20p_windows.txt --speed 0
python tools\make_fixture.py logs\dump-X.txt tests\fixtures\NAME.txt --cell-frames 12
python -m jkbms_widget widget --address C8:47:80:1A:F9:9E          # live widget
python -m jkbms_widget widget --replay tests\fixtures\jk02_32s_b1a8s20p_windows.txt  # mock
```
UI screenshots without a display: set `QT_QPA_PLATFORM=offscreen` and
`QT_QPA_FONTDIR=C:\Windows\Fonts` (otherwise text renders as boxes), call
`app.processEvents()` before `widget.grab()`.

## JK BLE protocol notes

Source: syssi/esphome-jk-bms, `components/jk_bms_ble/` (read 2026-11-14).
Status legend: **[esphome]** = matches esphome source, **[real]** = confirmed
on the owner's BMS, **[?]** = unverified.

GATT:
- Service `0xFFE0`, characteristic `0xFFE1`. [esphome]
- Newer BLE modules expose **two** characteristics with UUID `0xFFE1`
  (one write-only, one notify). Older ones expose a single FFE1 with both.
  So select characteristics by *properties*, not by UUID alone (bleak raises
  on ambiguous UUID lookups). [esphome]
- Our device: single FFE1 at handle 0x0011 (write, write-without-response,
  notify) + FFE2 at 0x000F (write-without-response, unused). Also a TI OAD
  service `f000ffc0-…` (firmware update) — never touch it. [real]
- esphome writes **without response**; works on our device. [esphome, real]

Request frame (20 bytes): `AA 55 90 EB | cmd | len | value u32 LE | 9×00 | sum&0xFF`.
Device info `...97 ... 11`, cell info `...96 ... 10`. [esphome; see drivers/jk/commands.py]

Connect sequence in esphome: subscribe to notify → send `0x97` once → send
`0x96`; `0x96` is re-sent every poll (5 s) until a cell-info frame arrives.
After that the BMS streams cell-info frames by itself. [esphome]
On our device: `0x97` → device info (0x03); `0x96` → settings (0x01), device
info (0x03) again, then cell info (0x02) every **~0.55 s**, no re-request
needed. Each request is also answered by a 20-byte ack
`AA 55 90 EB C8 01 01 00 … 44`. [real, capture 2026-11-14]

Response frames:
- Header `55 AA EB 90`; byte 4 = frame type (`0x01` settings, `0x02` cell info,
  `0x03` device info, `0x05` logbook); byte 5 = counter. [esphome]
- Arrive split over several notifications. A notification starting with the
  header starts a new frame. Frame is processed once ≥ 300 bytes buffered;
  CRC = `sum(bytes[0..298]) & 0xFF` compared to `byte[299]`. Buffer max 400.
  Some firmware sends frames longer than 300 bytes; bytes after 299 are not
  covered by the CRC. [esphome]
- **Chunk prefix quirk (Windows, large MTU)** [real, all 228 short chunks]:
  each 300-byte frame arrives as notifications of 128 + 23 + 128 + 23 bytes.
  Every notification shorter than 128 bytes that is not a frame start carries
  **one extra leading byte = remaining length in BCD** (`0x22` before 22 data
  bytes, `0x20` before a 20-byte ack). Strip it, and frames are exactly 300
  bytes with a valid CRC at 299. 128-byte chunks and frame starts have no
  prefix. Likely MTU-dependent (esphome on ESP32 uses MTU 23 and does not see
  it) — expect different chunking on Android; the reassembler must handle
  both, and fixtures must keep the raw chunks.
- The 20-byte acks (`AA 55 90 EB C8 …`) arrive between frames; the
  reassembler must drop data while no frame is in progress, and must not
  append an ack to a finished frame. [real]
- Settings frames (type `0x01`) arrive after `0x96`; parser must ignore
  unknown/unused types gracefully. [real]

Protocol variants: JK04 (old, float32 cells), JK02_24S (HW < 11),
JK02_32S (HW ≥ 11). **esphome does not auto-detect**: it is a required config
option. Plan: guess from the HW version in the device-info frame, allow a manual
override in settings, confirm with real frames. [esphome]

JK02 cell-info offsets (`o` = 0 for 24S, 32 for 32S). All little-endian. [esphome]
JK02_32S offsets confirmed on our device for: cell voltages, pack voltage,
current, SOC, remaining/nominal capacity, cycles, SOH, T1/T2/MOSFET temp,
alarms (0), charge/discharge MOSFET flags. Sample: 4 cells ≈ 3.39 V,
13.566 V, −0.413 A, SOC 100 %, 297.25 / 297.44 Ah, 75 cycles, SOH 98 %,
T1 11.8 °C, T2 12.6 °C, MOS 14.8 °C. [real]
Current resolution on our BMS is ~0.207 A (values 0, 0.413, 0.620, 0.827 A).
In the first captures the inverter was in standby (kept on for fast
automatic transfer) and really draws a fluctuating ~0–11 W, so the reading
jumps around 0.5 A. This is a real load, not noise. Decision: idle threshold
default 1.0 A (`model.DEFAULT_IDLE_THRESHOLD`) so standby shows as Idle;
the UI still adds hysteresis / a short moving average for the *state*
(raw current and power are shown as is). [real]

| Field | Offset | Type / scale |
|---|---|---|
| Cell voltage i | 6 + 2i (not shifted) | u16, mV |
| Cell resistance i | 64 + 2i (24S) / 80 + 2i (32S) | u16, mΩ |
| Pack voltage | 118 + o | u32, mV |
| Current | 126 + o | i32, mA, **positive = charging** |
| Power | computed V × I | (raw field at 122+o is unused by esphome) |
| Temp 1 / 2 | 130 + o / 132 + o | i16, 0.1 °C |
| MOSFET temp | 32S: 112 + o; 24S: 134 | i16, 0.1 °C |
| Alarms | 32S: u32 at 134 + o (=166); 24S: u16 at 136 | bitmask |
| Balance current | 138 + o | i16, mA |
| SOC | 141 + o | u8, % |
| Remaining / nominal capacity | 142 + o / 146 + o | u32, mAh |
| Cycle count | 150 + o | u32 |
| SOH | 158 + o | u8, % |
| Charge / discharge MOSFET on | 166 + o / 167 + o | u8 bool |

Alarm bits (JK02, esphome `DEFAULT_ERRORS_JK02`; 24S uses only bits 0–15):
0 wire resistance, 1 MOSFET overtemperature, 2 cell count ≠ settings,
3 current sensor anomaly (unnamed in recent esphome), 4 battery fully charged,
5 pack overvoltage, 6 charge overcurrent, 7 charge short circuit,
8 charge overtemperature, 9 charge undertemperature, 10 coprocessor comm error,
11 cell undervoltage, 12 pack undervoltage, 13 discharge overcurrent,
14 discharge short circuit, 15 discharge overtemperature, 16 charge MOSFET
abnormal, 17 discharge MOSFET abnormal, 18 GPS disconnected, 19 modify password
in time, 20 discharge on failed, 21 battery overtemperature, 22 temperature
sensor anomaly, 23 PL module anomaly, 24 SCP release failed, 25 discharge OCP II,
26 discharge OCP III, 27 discharge undertemperature, 28 GPS remote lock.
Note: bit 4 "fully charged" is informational, not a fault — UI should not show
it as a red alarm.

Device-info frame (type `0x03`): model 16 B at 6, HW version 8 B at 22,
SW version 8 B at 30, ASCII NUL-padded. [esphome, real: "JK_B1A8S20P",
"11A", "11.53"]. Further ASCII fields (by eye): BLE name at 46, then what look
like the BLE connect passcode and setup passcode, manufacturing date, serial
number, "LiFePo4 304Ah", "21.09.2024".
**Privacy:** before committing a device-info frame as a test fixture, overwrite
the passcode and serial fields and recompute the CRC. Raw dumps in `logs/`
are gitignored and must stay that way.

## Gotchas

- The project lives in a OneDrive folder. OneDrive syncing `.venv/` and `.git/`
  causes slowness and occasional file locks/corruption. Prefer moving the
  project to a non-synced folder (e.g. `C:\dev\jkbms-widget`); recreate `.venv`
  after moving (venvs are not relocatable).
- Do not pair the BMS in Windows settings; Windows may cache a stale GATT table.
- Only one BLE central at a time: phone app and widget exclude each other.
- Exe test runs started by Claude may write to the owner's REAL
  `%APPDATA%\JkBmsWidget` (MSIX redirection to
  `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\` happens only
  sometimes). Assume real data is used; keep test runs short and offscreen.
  `_remember_positions` skips saving when the Qt platform isn't "windows",
  so offscreen runs can't overwrite the owner's window positions. If a
  package copy exists, it hides the owner's real files from Claude.
- `SHQueryUserNotificationState` also returns QUNS_BUSY after "Show desktop"
  (Win+D): the desktop window has focus and covers the monitor. So
  `fullscreen_app_active` trusts QUNS_BUSY only if the foreground window is
  not a shell window and covers its monitor; the strip logs every
  full-screen on/off switch with the foreground window class.
- `OSError [WinError -2147020577] The device is not ready for use` from bleak
  means the Bluetooth radio is switched off in Windows.

## Milestones

1. [x] Skeleton, git, README, CLAUDE.md, read-only command allowlist + tests
2. [x] BLE scan/connect/subscribe; dump raw notifications as hex to `logs/`;
       print the GATT table. First capture: `logs/dump-20261114-203429.txt`
       (60 s, 113 frames, all CRC-valid after prefix stripping).
3. [x] Reassembly + CRC + parser + tests with captured frames in
       `tests/fixtures/`; replay/mock mode. Verified live: 30/30 frames OK.
4. [x] Widget UI + alarm list (compact + dashboard, live-tested offscreen
       with the real BMS: 22 frames / 14 s, clean disconnect).
       Basic auto-reconnect and manual connect/disconnect are already in.
5. [x] Settings (`%APPDATA%\JkBmsWidget\settings.json`), BMS picker on first
       run, tray icon + shared menu, display modes (floating widget /
       taskbar strip — owner's request 2026-11-14), history persistence,
       single instance (QLockFile), log file, UI scale, autostart (HKCU Run,
       exe only), `build.ps1` → `dist\JkBmsWidget.exe` (~48 MB). Exe tested
       live offscreen (connect, device info, clean exit).
       Not verified by Claude: real on-screen taskbar strip behaviour
       (z-order vs taskbar clicks, light theme) — owner to check.
