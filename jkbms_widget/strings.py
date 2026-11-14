"""All user-visible UI text (Ukrainian) and value formatting.

Keep every string the user sees here, so the UI can be translated later.
Units follow the owner's mockup (Latin: V, A, W, kW).
"""

from __future__ import annotations

from .state import CHARGING, DISCHARGING, IDLE

APP_TITLE = "Jikong BMS Monitor"

STATE_NAMES = {CHARGING: "Заряд", DISCHARGING: "Розряд", IDLE: "Очікування"}

# Connection status codes emitted by data sources -> text.
STATUS_TEXT = {
    "connecting": "Підключення…",
    "connected": "Підключено",
    "lost": "Зв'язок втрачено",
    "stopped": "Відключено",
    "replay": "Відтворення запису",
}

ALARM_NAMES_UK: dict[int, str] = {
    0: "Високий опір балансувальних проводів",
    1: "Перегрів MOSFET",
    2: "Кількість комірок не відповідає налаштуванням",
    3: "Несправність датчика струму",
    4: "Батарея повністю заряджена",
    5: "Перенапруга батареї",
    6: "Перевищення струму заряду",
    7: "Коротке замикання під час заряду",
    8: "Перегрів під час заряду",
    9: "Занизька температура для заряду",
    10: "Помилка зв'язку зі співпроцесором",
    11: "Низька напруга комірки",
    12: "Низька напруга батареї",
    13: "Перевищення струму розряду",
    14: "Коротке замикання під час розряду",
    15: "Перегрів під час розряду",
    16: "Несправність MOSFET заряду",
    17: "Несправність MOSFET розряду",
    18: "GPS-модуль відключено",
    19: "Потрібно змінити пароль",
    20: "Не вдалося увімкнути розряд",
    21: "Перегрів батареї",
    22: "Несправність датчика температури",
    23: "Несправність PL-модуля (паралельне з'єднання)",
    24: "Не вдалося зняти захист від КЗ",
    25: "Перевищення струму розряду (рівень II)",
    26: "Перевищення струму розряду (рівень III)",
    27: "Занизька температура для розряду",
    28: "Віддалене блокування через GPS",
}


def alarm_text(bit: int) -> str:
    return ALARM_NAMES_UK.get(bit, f"Невідома аварія (біт {bit})")


NO_VALUE = "—"


def fmt_voltage(v: float) -> str:
    return f"{v:.2f}"


def fmt_current(i: float) -> str:
    return f"{i:.1f}" if abs(i) >= 10 else f"{i:.2f}"


def fmt_power(w: float) -> tuple[str, str]:
    """(number, unit), e.g. ('-5.6', 'W') or ('-1.57', 'kW')."""
    if abs(w) >= 1000:
        return f"{w / 1000:.2f}", "kW"
    return f"{w:.1f}", "W"


def fmt_hours(hours: float | None) -> str:
    if hours is None:
        return NO_VALUE
    if hours < 1:
        return f"≈ {hours * 60:.0f} хв"
    if hours < 48:
        return f"≈ {hours:.1f} год"
    return f"≈ {hours / 24:.0f} дн"


TIME_LEFT_KIND = {"empty": "до розряду", "full": "до повного заряду", None: "струм ≈ 0"}
TIME_KINDS = ("empty", "full")


def fmt_time_left_short(hours: float | None, kind: str | None) -> str:
    """'≈ 3.8 год' for the taskbar strip; '' if unknown.

    No arrow (owner's request): charge/discharge is shown by the line colour
    and the bolt on the battery icon.
    """
    if hours is None or kind not in TIME_KINDS:
        return ""
    return fmt_hours(hours)


def fmt_time_left_long(hours: float | None, kind: str | None) -> str:
    """'≈ 3.8 год до розряду'; '' if unknown."""
    if hours is None or kind not in TIME_KINDS:
        return ""
    return f"{fmt_hours(hours)} {TIME_LEFT_KIND[kind]}"

# Alarm dialog
ALARMS_TITLE = "Аварії та попередження"
ALARMS_STALE = "Немає свіжих даних від BMS — список може бути застарілим."
NO_ALARMS = "Активних аварій немає"
CLOSE = "Закрити"

# Compact widget / menus
MENU_EXPAND = "Розгорнути"
MENU_COLLAPSE = "Згорнути"
MENU_CONNECT = "Підключитися"
MENU_DISCONNECT = "Відключитися"
MENU_EXIT = "Вихід"
TIP_ALARMS = "Аварії (натисніть для списку)"
TIP_EXPAND = "Розгорнути панель"
TIP_COLLAPSE = "Згорнути до віджета"
TIP_CLOSE = "Закрити програму"

MENU_SHOW_DASHBOARD = "Відкрити панель"
MENU_HIDE_DASHBOARD = "Згорнути панель"
MENU_SHOW_WIDGET = "Показати віджет"
MENU_HIDE_WIDGET = "Сховати віджет"
MENU_DISPLAY_MODE = "Режим відображення"
MODE_WIDGET = "Плаваючий віджет"
MODE_TASKBAR = "На панелі завдань"
MENU_PICK_BMS = "Вибрати BMS…"
MENU_SCALE = "Масштаб"
MENU_AUTOSTART = "Запускати разом з Windows"
TIP_AUTOSTART_DEV = "Доступно лише у зібраній версії (.exe)"
MENU_SETTINGS_FOLDER = "Відкрити теку налаштувань"
SCALE_RESTART = "Масштаб {pct}% застосується після перезапуску програми."
TASKBAR_UNSUPPORTED = (
    "Режим «на панелі завдань» працює лише з горизонтальною панеллю завдань "
    "без автоприховування. Повертаю плаваючий віджет."
)
ALREADY_RUNNING = "Віджет уже запущено (див. значок у треї)."

# Settings window
MENU_SETTINGS = "Налаштування…"
TIP_SETTINGS = "Налаштування"
SETTINGS_TITLE = "Налаштування"
SECTION_BMS = "BMS"
BMS_NOT_SET = "BMS не вибрано"
BMS_CHANGE = "Змінити…"
SECTION_DISPLAY = "ВІДОБРАЖЕННЯ"
FULLSCREEN_LABEL = "Коли гра чи відео на весь екран"
FULLSCREEN_OPTIONS = [("hide", "Ховати смужку"), ("corner", "Показувати в правому нижньому куті")]
DIM_LABEL = "Напівпрозорі й не заважають, коли вікно розгорнуте"
DIM_NOTE = ("Поки активне вікно розгорнуте чи на весь екран, віджет і смужка "
            "стають прозорими, а кліки проходять крізь них")
SCALE_LABEL = "Масштаб інтерфейсу"
SCALE_NOTE = "Застосується після перезапуску програми"
SECTION_BATTERY = "СТАН БАТАРЕЇ"
IDLE_LABEL = "Поріг «Очікування»"
IDLE_NOTE = "Якщо |струм| менший за поріг, стан показується як «Очікування»"
SECTION_SYSTEM = "СИСТЕМА"
SETTINGS_DONE = "Готово"
REPLAY_NOTE = "Режим відтворення запису: BMS змінити не можна"

# BMS picker
PICK_TITLE = "Вибір BMS"
PICK_HINT = (
    "Закрийте застосунок JK на телефоні: BMS, до якого вже підключено "
    "телефон, не видно в пошуку."
)
PICK_SCANNING = "Пошук пристроїв Bluetooth…"
PICK_FOUND = "Знайдено: {n}"
PICK_NONE = "JK BMS не знайдено. Перевірте, що Bluetooth увімкнено, і повторіть пошук."
PICK_SAVED_MARK = "(збережений)"
PICK_NOT_SEEN = "зараз не видно в ефірі"
PICK_SHOW_ALL = "Показати всі пристрої"
PICK_RESCAN = "Шукати знову"
PICK_SELECT = "Вибрати"
PICK_CANCEL = "Скасувати"
PICK_ERROR = "Помилка пошуку: {err}"

# Dashboard
TILE_CURRENT = "Струм"
TILE_POWER = "Потужність"
TILE_VOLTAGE = "Напруга"
TILE_TEMPERATURE = "Температура"
TEMP_TOOLTIP = "Датчик 1: {t1:.1f} °C\nДатчик 2: {t2:.1f} °C\nMOSFET: {mos:.1f} °C"
HEALTH_OK = "Акумулятор в нормі"
HEALTH_OK_SUB = "Усі параметри в межах норми"
HEALTH_ALARM = "Увага: активні аварії ({n})"
HEALTH_NO_DATA = "Немає даних"
HEALTH_NO_DATA_SUB = "Очікування даних від BMS"
HEALTH_STALE = "Немає зв'язку з BMS"
HEALTH_STALE_SUB = "Показано останні отримані дані"
ROW_MODE = "Режим роботи:"
ROW_TIME_LEFT = "Залишилось часу:"
ROW_CELLS = "Напруга комірок:"
ROW_BALANCING = "Балансування:"
ROW_MOSFETS = "Заряд / розряд:"
ROW_ALARMS = "Аварії:"
YES, NO = "Так", "Ні"
ON, OFF = "Увімк.", "Вимк."
ALARMS_NONE = "Немає"
CHART_TITLE = "SOC та струм"
CHART_RANGES = [("1г", 3600), ("6г", 6 * 3600), ("24г", 24 * 3600), ("7д", 7 * 24 * 3600)]
CHART_EMPTY = "Збираю дані…"
LEGEND_CURRENT = "Струм"
LEGEND_CHARGE = "Заряд"
LEGEND_DISCHARGE = "Розряд"
LEGEND_IDLE = STATE_NAMES[IDLE]
TIP_CURRENT = "Струм"
TIP_VOLTAGE = "Напруга"
TIP_POWER = "Потужність"
TIP_CHARGE = "заряд"
TIP_DISCHARGE = "розряд"
