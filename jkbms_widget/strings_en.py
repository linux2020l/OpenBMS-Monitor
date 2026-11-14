"""English UI texts. Same names as the Ukrainian originals in strings.py.

Only data here: strings.set_language("en") copies these over the Ukrainian
values. tests/test_strings.py checks that names, types, dict keys and
{placeholders} match.
"""

from __future__ import annotations

from .state import CHARGING, DISCHARGING, IDLE

APP_TITLE = "Jikong BMS Monitor"

STATE_NAMES = {CHARGING: "Charging", DISCHARGING: "Discharging", IDLE: "Idle"}

STATUS_TEXT = {
    "connecting": "Connecting…",
    "connected": "Connected",
    "lost": "Connection lost",
    "stopped": "Disconnected",
    "replay": "Playing a recording",
}

ALARM_TEXT: dict[int, str] = {
    0: "Balance wire resistance too high",
    1: "MOSFET overtemperature",
    2: "Cell count does not match settings",
    3: "Current sensor fault",
    4: "Battery fully charged",
    5: "Battery overvoltage",
    6: "Charge overcurrent",
    7: "Short circuit while charging",
    8: "Overtemperature while charging",
    9: "Too cold to charge",
    10: "Coprocessor communication error",
    11: "Cell undervoltage",
    12: "Battery undervoltage",
    13: "Discharge overcurrent",
    14: "Short circuit while discharging",
    15: "Overtemperature while discharging",
    16: "Charge MOSFET fault",
    17: "Discharge MOSFET fault",
    18: "GPS module disconnected",
    19: "Password change required",
    20: "Failed to switch discharge on",
    21: "Battery overtemperature",
    22: "Temperature sensor fault",
    23: "PL module fault (parallel connection)",
    24: "Failed to release short-circuit protection",
    25: "Discharge overcurrent (level II)",
    26: "Discharge overcurrent (level III)",
    27: "Too cold to discharge",
    28: "Remote lock via GPS",
}
ALARM_UNKNOWN = "Unknown alarm (bit {bit})"

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
SCALE_RESTART = "Scale {pct}% will apply after restarting the app."
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
SCALE_NOTE = "Scale and language apply after restarting the app"
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
    "Close the JK app on your phone: a BMS that is connected to the phone "
    "does not show up in the search."
)
PICK_SCANNING = "Searching for Bluetooth devices…"
PICK_FOUND = "Found: {n}"
PICK_NONE = "No JK BMS found. Check that Bluetooth is on and search again."
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
TEMP_TOOLTIP = "Sensor 1: {t1:.1f} °C\nSensor 2: {t2:.1f} °C\nMOSFET: {mos:.1f} °C"
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
