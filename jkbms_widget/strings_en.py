"""English UI texts. Same names as the Ukrainian originals in strings.py.

Only data here: strings.set_language("en") copies these over the Ukrainian
values. tests/test_strings.py checks that names, types, dict keys and
{placeholders} match.
"""

from __future__ import annotations

from .state import CHARGING, DISCHARGING, IDLE

APP_TITLE = "OpenBMS Monitor"

STATE_NAMES = {CHARGING: "Charging", DISCHARGING: "Discharging", IDLE: "Idle"}

STATUS_TEXT = {
    "connecting": "Connecting…",
    "connected": "Connected",
    "lost": "Connection lost",
    "stopped": "Disconnected",
    "replay": "Playing a recording",
}

ALARM_TEXT: dict[str, str] = {
    "balance_wire_resistance": "Balance wire resistance too high",
    "mosfet_overtemperature": "MOSFET overtemperature",
    "cell_count_mismatch": "Cell count does not match settings",
    "current_sensor_fault": "Current sensor fault",
    "fully_charged": "Battery fully charged",
    "pack_overvoltage": "Battery overvoltage",
    "charge_overcurrent": "Charge overcurrent",
    "charge_short_circuit": "Short circuit while charging",
    "charge_overtemperature": "Overtemperature while charging",
    "charge_undertemperature": "Too cold to charge",
    "coprocessor_error": "Coprocessor communication error",
    "cell_undervoltage": "Cell undervoltage",
    "pack_undervoltage": "Battery undervoltage",
    "discharge_overcurrent": "Discharge overcurrent",
    "discharge_short_circuit": "Short circuit while discharging",
    "discharge_overtemperature": "Overtemperature while discharging",
    "charge_mosfet_fault": "Charge MOSFET fault",
    "discharge_mosfet_fault": "Discharge MOSFET fault",
    "gps_disconnected": "GPS module disconnected",
    "password_change_required": "Password change required",
    "discharge_on_failed": "Failed to switch discharge on",
    "battery_overtemperature": "Battery overtemperature",
    "temperature_sensor_fault": "Temperature sensor fault",
    "parallel_module_fault": "PL module fault (parallel connection)",
    "short_circuit_release_failed": "Failed to release short-circuit protection",
    "discharge_overcurrent_2": "Discharge overcurrent (level II)",
    "discharge_overcurrent_3": "Discharge overcurrent (level III)",
    "discharge_undertemperature": "Too cold to discharge",
    "gps_remote_lock": "Remote lock via GPS",
}
ALARM_UNKNOWN = "Unknown alarm ({code})"

UNIT_MIN, UNIT_HOUR, UNIT_DAY = "min", "h", "d"

TIME_LEFT_KIND = {"empty": "to empty", "full": "to full", None: "current ≈ 0"}

# Alarm dialog
ALARMS_TITLE = "Alarms and warnings"
ALARMS_STALE = "No fresh data from the BMS, the list may be out of date."
NO_ALARMS = "No active alarms"
CLOSE = "Close"

# Compact widget / menus
MENU_EXPAND = "Expand"
MENU_COLLAPSE = "Collapse"
MENU_CONNECT = "Connect"
MENU_DISCONNECT = "Disconnect"
MENU_EXIT = "Exit"
TIP_ALARMS = "Alarms (click for the list)"
TIP_EXPAND = "Open the dashboard"
TIP_COLLAPSE = "Collapse to the widget"
TIP_CLOSE = "Exit the app"

MENU_SHOW_DASHBOARD = "Open dashboard"
MENU_HIDE_DASHBOARD = "Hide dashboard"
MENU_SHOW_WIDGET = "Show widget"
MENU_HIDE_WIDGET = "Hide widget"
MENU_DISPLAY_MODE = "Display mode"
MODE_WIDGET = "Floating widget"
MODE_TASKBAR = "On the taskbar"
MENU_PICK_BMS = "Choose BMS…"
MENU_SCALE = "Scale"
MENU_AUTOSTART = "Start with Windows"
TIP_AUTOSTART_DEV = "Only available in the built app (.exe)"
MENU_SETTINGS_FOLDER = "Open settings folder"
TASKBAR_UNSUPPORTED = (
    "Taskbar mode works only with a horizontal taskbar that is not "
    "auto-hidden. Switching back to the floating widget."
)
ALREADY_RUNNING = "The widget is already running (see the tray icon)."

# Settings window
MENU_SETTINGS = "Settings…"
TIP_SETTINGS = "Settings"
SETTINGS_TITLE = "Settings"
SECTION_BMS = "BMS"
BMS_NOT_SET = "No BMS selected"
BMS_CHANGE = "Change…"
SECTION_DISPLAY = "DISPLAY"
FULLSCREEN_LABEL = "When a game or video is full-screen"
FULLSCREEN_OPTIONS = [("hide", "Hide the strip"), ("corner", "Show in the bottom-right corner")]
DIM_LABEL = "See-through and click-through when a window is maximized"
DIM_NOTE = ("While the active window is maximized or full-screen, the widget "
            "becomes transparent and clicks pass through it")
SCALE_LABEL = "Interface scale"
SCALE_NOTE = "Scale and language apply when you close the settings (the app restarts in a second)"
LANGUAGE_LABEL = "Language"
LANGUAGE_OPTIONS = [("auto", "Same as Windows"), ("uk", "Українська"), ("en", "English")]
SECTION_BATTERY = "BATTERY STATE"
IDLE_LABEL = "“Idle” threshold"
IDLE_NOTE = "If |current| is below the threshold, the state is shown as “Idle”"
SECTION_SYSTEM = "SYSTEM"
SETTINGS_DONE = "Done"
REPLAY_NOTE = "Playing a recording: the BMS cannot be changed"

# BMS picker
PICK_TITLE = "Choose BMS"
PICK_HINT = (
    "Close the BMS app on your phone: a BMS that is connected to the phone "
    "does not show up in the search."
)
PICK_SCANNING = "Searching for Bluetooth devices…"
PICK_FOUND = "Found: {n}"
PICK_NONE = "No BMS found. Check that Bluetooth is on and search again."
PICK_SAVED_MARK = "(saved)"
PICK_NOT_SEEN = "not visible right now"
PICK_SHOW_ALL = "Show all devices"
PICK_RESCAN = "Search again"
PICK_SELECT = "Select"
PICK_CANCEL = "Cancel"
PICK_ERROR = "Search error: {err}"

# Dashboard
TILE_CURRENT = "Current"
TILE_POWER = "Power"
TILE_VOLTAGE = "Voltage"
TILE_TEMPERATURE = "Temperature"
TEMP_SENSOR = "Sensor {n}: {t:.1f} °C"
TEMP_MOSFET = "MOSFET: {t:.1f} °C"
HEALTH_OK = "Battery OK"
HEALTH_OK_SUB = "All values within limits"
HEALTH_ALARM = "Warning: active alarms ({n})"
HEALTH_NO_DATA = "No data"
HEALTH_NO_DATA_SUB = "Waiting for data from the BMS"
HEALTH_STALE = "No connection to the BMS"
HEALTH_STALE_SUB = "Showing the last received data"
ROW_MODE = "Mode:"
ROW_TIME_LEFT = "Time left:"
ROW_CELLS = "Cell voltage:"
ROW_BALANCING = "Balancing:"
ROW_MOSFETS = "Charge / discharge:"
ROW_ALARMS = "Alarms:"
YES, NO = "Yes", "No"
ON, OFF = "On", "Off"
ALARMS_NONE = "None"
CHART_TITLE = "SOC and current"
CHART_RANGES = [("1h", 3600), ("6h", 6 * 3600), ("24h", 24 * 3600), ("7d", 7 * 24 * 3600)]
CHART_EMPTY = "Collecting data…"
LEGEND_CURRENT = "Current"
LEGEND_CHARGE = "Charge"
LEGEND_DISCHARGE = "Discharge"
LEGEND_IDLE = "Idle"
TIP_CURRENT = "Current"
TIP_VOLTAGE = "Voltage"
TIP_POWER = "Power"
TIP_CHARGE = "charging"
TIP_DISCHARGE = "discharging"

# Chart: energy of a range picked with the mouse
SEL_HINT = "Drag with the mouse to measure energy"
SEL_CHARGED = "In"
SEL_DISCHARGED = "Out"
SEL_NET = "Net"
SEL_CLEAR = "Click to clear"

# Diagnostics (community captures for new BMS brands)
MENU_DIAGNOSTICS = "Record diagnostics…"
DIAG_TITLE = "Diagnostic recording"
DIAG_INTRO = (
    "Records 60 seconds of BMS communication to a file, so the developer can "
    "add support for your BMS. The app only reads data and changes nothing in "
    "the BMS. The MAC address, serial number and passwords are removed from "
    "the file (the device name stays). Close the BMS app on your phone."
)
DIAG_BRAND = "BMS brand:"
DIAG_START = "Start recording"
DIAG_STOP = "Stop"
DIAG_CONNECTING = "Connecting…"
DIAG_PROGRESS = "Recording… {s} s of {total}, packets received: {n}"
DIAG_NO_DATA = ("The BMS sent no data. Check that the right brand is selected and "
                "that the phone is disconnected.")
DIAG_ERROR = "Recording stopped: {err}"
DIAG_SAVED = ("Saved: {path}\nPackets: {n}. Attach the file to a GitHub issue "
              "or send it to the developer.")
DIAG_OPEN_FOLDER = "Open folder"
BRAND_UNKNOWN = "Unknown brand"
PICK_CAPTURE_ONLY = (
    "{brand}: this brand is only supported for diagnostic recording so far. "
    "Record diagnostics (menu → “Record diagnostics…”) and share the file so "
    "we can add full support."
)

# Notifications
NOTIFY_LOW_SOC = "Low battery: {soc}%"
NOTIFY_FULL = "Battery fully charged"
NOTIFY_ALARM = "BMS alarm: {names}"
NOTIFY_LOST = "No connection to the BMS for over a minute"
NOTIFY_LABEL = "Windows notifications"
NOTIFY_NOTE = "Low charge, new alarms, connection lost for a minute, fully charged"
LOW_SOC_LABEL = "Low charge threshold"

# Energy counters (dashboard)
ROW_ENERGY_TODAY = "Energy today:"
ROW_ENERGY_WEEK = "Energy, 7 days:"
ENERGY_TIP = ("Charged / discharged, kWh. Calculated from the history, so time when "
              "the app was not running is not counted.")

# Cells tab (dashboard)
TAB_CHART = "Chart"
TAB_CELLS = "Cells"
CELLS_SUMMARY = "Δ {delta:.0f} mV · average {avg:.3f} V · min #{imin} · max #{imax}"
CELLS_NO_DATA = "No data from the BMS"
CELLS_BALANCING = "Balancing"

# CSV export
MENU_EXPORT_CSV = "Export history (CSV)…"
EXPORT_TITLE = "Export history"
EXPORT_DONE = "History saved: {path} ({n} rows)"
EXPORT_EMPTY = "The history is empty, nothing to export."

SECTION_DATA = "DATA"
LOW_SOC_TIP = "5 to 100 %. The notification comes when the charge drops to this value or below."

# Several BMS (settings tabs, BMS list, dashboard selector)
SETTINGS_TAB_BMS = "BMS"
SETTINGS_TAB_DISPLAY = "Display"
SETTINGS_TAB_ALERTS = "State & alerts"
SETTINGS_TAB_SYSTEM = "System"
BMS_ADD = "Add…"
BMS_REMOVE = "Remove"
BMS_MAIN_MARK = "(main)"
BMS_LIST_NOTE = ("Each BMS gets its own strip on the taskbar or its own widget. The main BMS "
                 "is shown in the tray icon. A removed BMS keeps its history.")
BMS_ALREADY = "This BMS is already in the list."
MENU_ADD_BMS = "Add BMS…"
DASH_SELECT_TIP = "Which BMS to show"

MENU_HIDE_BMS = "Hide from the taskbar"
MENU_REMOVE_BMS = "Remove this BMS"
MENU_SHOWN_BMS = "Show on the taskbar"
TIP_EYE = "Show this BMS's strip / widget. Data and the chart are always recorded."

LOW_SOC_STATE = "Low charge (threshold {t}%)"
BALANCING_ACTIVE = "Active"

# Parallel banks (step D2) + widgets on the desktop
BANK_DEFAULT_NAME = "Bank {label}"
SETTINGS_TAB_BANKS = "Banks"
BANK_CREATE = "Create bank…"
BANK_REMOVE = "Ungroup"
BANKS_NOTE = ("A bank is several BMS wired in parallel. The app shows them as one battery: "
              "total current and power, capacity-weighted SOC, one chart and one taskbar "
              "strip. Each BMS of the bank can still be opened in the main window.")
BANKS_EMPTY = "No banks yet"
BANK_EDITOR_TITLE = "Bank"
BANK_NAME_LABEL = "Name"
BANK_MEMBERS_LABEL = "BMS in this bank (at least two)"
BANK_EDITOR_NOTE = ("BMS that belong to another bank are not listed. The strips of the bank's "
                    "BMS are hidden; bring them back with the eye in the BMS list.")
BANK_SAVE = "Save"
BANK_NEED_TWO = "A bank needs at least two BMS that are not in another bank yet."
BANK_MEMBERS_DETAIL = "{n} BMS: {names}"
BANK_MEMBER_OF = "in bank {label}"
MENU_REMOVE_BANK = "Ungroup this bank"
BANK_PARTIAL = "{n} of {total} BMS offline"
BANK_PARTIAL_SHORT = "{n} of {total} offline"  # compact widget
BANK_PARTIAL_SUB = "Not counted: {names}"
TIP_EYE_BANK = "Show this bank's strip / widget. Data and chart are always recorded."
DESKTOP_LABEL = "Widgets on the desktop (not on top of other windows)"
DESKTOP_NOTE = ("Widgets stay under other programs and remain visible after Show desktop "
                "(Win+D). The taskbar strip does not change.")
ROW_EXCHANGE = "Flow between packs:"
EXCHANGE_TIP = ("Current flowing from one pack of the bank into another. It cancels out in "
                "the bank's total, which is what goes to the inverter or comes from the charger.")
BANK_KIND_NAMES = {"parallel": "Parallel", "series": "Series"}
BANK_KIND_LABEL = "Connection"
BANK_KIND_TIPS = {
    "parallel": "Same voltage; currents and capacities add up; capacity-weighted SOC.",
    "series": "Voltages add up, the current is common; SOC and time left follow the weakest pack.",
}
BANK_LETTER_LABEL = "Letter"
BANK_SERIES_PARTIAL_SUB = "Last known voltage: {names}"
BANK_NO_DATA = "No data from a BMS of the bank"
BANK_NO_DATA_SHORT = "No data"
BANK_NO_DATA_SUB = "Offline for over a minute: {names}"
CELLS_ALL = "All cells:"
SECTION_UPDATES = "UPDATES"
UPDATE_CHECK_LABEL = "Check for updates once a day"
UPDATE_CHECK_NOW = "Check now"
UPDATE_CHECK_NOTE = ("The app only reads the latest version number from GitHub. It never "
                     "downloads or installs anything by itself: you install updates.")
UPDATE_AVAILABLE = "Version {version} is available. Click to open the download page."
UPDATE_NONE = "You have the latest version (newest on GitHub: {version})."
UPDATE_FAILED = "Couldn't check for updates. Check your internet connection."
MENU_UPDATE = "Download version {version}…"
