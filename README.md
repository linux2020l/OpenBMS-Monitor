# JK BMS Monitor for Windows

A small, **read-only** Windows desktop monitor for **JK (Jikong) BMS** over
Bluetooth Low Energy. It shows state of charge, current, power, pack voltage,
time to full/empty and active alarms right on the Windows taskbar, in a
floating widget, or in a full dashboard with a 7-day history chart.

Built for a home backup battery (4S LiFePO4), where the PC itself runs from
the battery and you want to see what it is doing at a glance.

![Dashboard](docs/screenshots/dashboard.png)

| Taskbar strip | Floating widget |
|---|---|
| ![Taskbar strip: discharging, charging, fault](docs/screenshots/taskbar.png) | ![Floating widget](docs/screenshots/widget.png) |

*Screenshots use demo data. The user interface is in Ukrainian; all texts
live in one module (`jkbms_widget/strings.py`) and can be translated.*

## Features

- **Taskbar strip** (default): battery icon (fill = SOC, lightning bolt while
  charging, red badge on faults), SOC, voltage, current, power and time to
  full/empty, placed next to the system tray. Drag it along the taskbar.
  During full-screen apps it hides or moves to the screen corner.
- **Floating widget**: small always-on-top frameless window, drag anywhere.
- **Dashboard**: SOC ring, current, power, voltage, temperature, cell
  voltage range, balancing, MOSFET state, health summary.
- **History chart**: SOC and current for 1 h / 6 h / 24 h / 7 days, stored
  per BMS in SQLite, survives restarts. Hover to see time, SOC, current,
  voltage and power. Colours show charge (green) / discharge (amber).
- **Alarms in plain language**: click the indicator for the list of active
  protections (e.g. cell undervoltage, charge overtemperature).
- **Charging / Discharging / Idle** with a configurable idle threshold, so an
  inverter's standby draw does not flicker the state.
- **Robust connection**: automatic reconnect, clear "disconnected" state,
  manual disconnect to free the BMS for the phone app.
- Remembers the selected BMS and window positions; tray icon; start with
  Windows; single instance; UI scaling; widgets fade and become
  click-through while another window is maximized.

## Read-only by design

The app can send **exactly two** request frames to the BMS: device info
(`0x97`) and cell info (`0x96`). Every outgoing write passes through one
function that checks the **whole frame** against an allowlist in
[`jkbms_widget/commands.py`](jkbms_widget/commands.py); anything else raises
`ForbiddenCommandError` and is never sent. There is no code that changes BMS
settings, and there never will be: use the official JK app for that.

## Supported hardware

| BMS | Hardware / software | Status |
|---|---|---|
| JK_B1A8S20P | HW 11A, SW 11.53 | tested daily |
| JK-B2A8S20P | HW 19H, SW 19.34 | tested (decoding verified at idle) |
| Other JK-B "JK02_32S" models (HW ≥ 11) | — | expected to work, untested |
| Older JK-B (HW < 11, JK02_24S) | — | parser exists, untested |
| JK04, JK-PB (inverter BMS), other brands | — | not supported yet |

Reports from other models are very welcome. A short capture
(`python -m jkbms_widget dump`, see below) is enough to add a model to the
tests.

Requirements: Windows 10/11 with Bluetooth LE (built-in or USB dongle).

## Getting started

### Run the app

1. Close the JK phone app (or disconnect it). The BMS accepts only one
   Bluetooth connection at a time.
2. Start `JkBmsWidget.exe` (see [Build](#build-the-exe)) or, from source,
   `pythonw -m jkbms_widget`.
3. On the first start a dialog lists JK devices nearby: pick yours. The app
   connects to it from now on.

Do **not** pair the BMS in Windows Bluetooth settings; the app connects
without pairing.

### Everyday use

- Left click on the strip/widget opens the dashboard; the ⚙ button opens
  settings; right click (or the tray icon) opens the menu: connect /
  disconnect, choose BMS, display mode, settings, exit.
- Settings: BMS, display mode (taskbar / floating widget), behaviour during
  full-screen apps, scale, fading over maximized windows, idle threshold,
  start with Windows (exe only).
- Settings, chart history and a log are stored in `%APPDATA%\JkBmsWidget\`
  (`settings.json`, `history.sqlite`, `widget.log`). Delete the folder to
  reset everything.

## Development

Python 3.12, [bleak](https://github.com/hbldh/bleak) (BLE),
[PySide6](https://doc.qt.io/qtforpython-6/) (UI), pytest.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser
RemoteSigned` once, or call `.\.venv\Scripts\python.exe` directly.

Useful commands:

```powershell
python -m jkbms_widget                     # the app (same as "widget")
python -m jkbms_widget widget --replay tests\fixtures\jk02_32s_b1a8s20p_windows.txt  # demo data, no BMS
python -m jkbms_widget commands            # print the only frames the app may send
python -m jkbms_widget scan                # list nearby BLE devices, JK first
python -m jkbms_widget dump --address AA:BB:CC:DD:EE:FF --seconds 60
python -m jkbms_widget replay logs\dump-XXXX.txt --speed 0
```

`dump` prints the GATT table and decoded values and writes every raw
notification with a timestamp to `logs\dump-*.txt`. **Raw dumps contain the
BMS serial number and Bluetooth passcodes** (`logs/` is git-ignored). To
share a capture or add it as a test fixture, sanitize it first:

```powershell
python tools\make_fixture.py logs\dump-XXXX.txt tests\fixtures\NAME.txt --note "MODEL HW x SW y"
```

A test checks that every fixture has these fields blanked.

### Build the exe

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

Runs the tests, generates the icon and builds `dist\JkBmsWidget.exe` with
PyInstaller (single file, ~50 MB, no console). The first start takes a few
seconds while it unpacks.

### Project layout

```
jkbms_widget/
  commands.py        read-only request frames + allowlist (safety gate)
  frames.py          notification chunks -> CRC-checked 300-byte frames
  parser.py          device-info / cell-info decoding, alarm names
  capture.py         raw capture log format;  replay.py: play a capture back
  ble.py             bleak: scan, characteristic selection, the only write path
  dump.py            live logger with decoded console output
  state.py           state with hysteresis, time left, history buffer
  history_store.py   7-day per-BMS history (SQLite)
  settings.py        settings.json
  strings.py         all user-visible text (Ukrainian) and formatting
  sources.py         BLE / replay data sources (background thread -> Qt signals)
  win_taskbar.py     taskbar geometry, full-screen detection (Win32 via ctypes)
  autostart.py       start with Windows (HKCU Run key, exe only)
  app.py             controller: sources, views, tray, menu, persistence
  ui/                PySide6 views: taskbar strip, widget, dashboard, chart,
                     settings, alarm list, BMS picker, theme, icons
tests/               pytest; fixtures/ holds sanitized real captures
tools/               make_fixture.py (sanitize dumps), make_icon.py
build.ps1            test + build the exe
CLAUDE.md            design notes, protocol notes and conventions
```

The protocol logic (`commands`, `frames`, `parser`, `state`) is pure Python
without BLE or UI imports, so it can be ported (e.g. to Android) together
with its test vectors. Protocol details, verified offsets and quirks (such
as the length-prefix byte on Windows notifications) are documented in
[CLAUDE.md](CLAUDE.md#jk-ble-protocol-notes).

## Limitations

- Windows only; Bluetooth LE only (no RS485/CAN).
- The taskbar strip is a topmost window placed over the taskbar (Windows 11
  has no API for taskbar widgets); vertical or auto-hiding taskbars are not
  supported.
- One BMS at a time.

## Credits

Protocol details cross-checked against
[syssi/esphome-jk-bms](https://github.com/syssi/esphome-jk-bms)
(`jk_bms_ble` component).

## License

[MIT](LICENSE)

## Disclaimer

Not affiliated with or endorsed by Jikong / JK BMS. "JK" and "Jikong" are
used only to name compatible hardware. Use at your own risk; the displayed
values come from the BMS and are for information only.
