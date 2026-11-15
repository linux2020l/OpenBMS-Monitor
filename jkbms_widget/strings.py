"""All user-visible UI text and value formatting.

The constants below are the Ukrainian texts (the original language).
`strings_en.py` defines the same names in English; `set_language("en")`
swaps them in. Call it once at startup, BEFORE any window is created
(views read these constants when they build themselves).

Rules for adding text: every UPPER_CASE name here must also exist in
strings_en.py with the same type, dict keys and {placeholders}
(tests/test_strings.py checks this). Units stay Latin (V, A, W, kW).
"""

from __future__ import annotations

import sys

from .state import CHARGING, DISCHARGING, IDLE

LANGUAGES = ("uk", "en")

APP_TITLE = "OpenBMS Monitor"

STATE_NAMES = {CHARGING: "Заряд", DISCHARGING: "Розряд", IDLE: "Очікування"}

# Connection status codes emitted by data sources -> text.
STATUS_TEXT = {
    "connecting": "Підключення…",
    "connected": "Підключено",
    "lost": "Зв'язок втрачено",
    "stopped": "Відключено",
    "replay": "Відтворення запису",
}

ALARM_TEXT: dict[str, str] = {
    "balance_wire_resistance": "Високий опір балансувальних проводів",
    "mosfet_overtemperature": "Перегрів MOSFET",
    "cell_count_mismatch": "Кількість комірок не відповідає налаштуванням",
    "current_sensor_fault": "Несправність датчика струму",
    "fully_charged": "Батарея повністю заряджена",
    "pack_overvoltage": "Перенапруга батареї",
    "charge_overcurrent": "Перевищення струму заряду",
    "charge_short_circuit": "Коротке замикання під час заряду",
    "charge_overtemperature": "Перегрів під час заряду",
    "charge_undertemperature": "Занизька температура для заряду",
    "coprocessor_error": "Помилка зв'язку зі співпроцесором",
    "cell_undervoltage": "Низька напруга комірки",
    "pack_undervoltage": "Низька напруга батареї",
    "discharge_overcurrent": "Перевищення струму розряду",
    "discharge_short_circuit": "Коротке замикання під час розряду",
    "discharge_overtemperature": "Перегрів під час розряду",
    "charge_mosfet_fault": "Несправність MOSFET заряду",
    "discharge_mosfet_fault": "Несправність MOSFET розряду",
    "gps_disconnected": "GPS-модуль відключено",
    "password_change_required": "Потрібно змінити пароль",
    "discharge_on_failed": "Не вдалося увімкнути розряд",
    "battery_overtemperature": "Перегрів батареї",
    "temperature_sensor_fault": "Несправність датчика температури",
    "parallel_module_fault": "Несправність PL-модуля (паралельне з'єднання)",
    "short_circuit_release_failed": "Не вдалося зняти захист від КЗ",
    "discharge_overcurrent_2": "Перевищення струму розряду (рівень II)",
    "discharge_overcurrent_3": "Перевищення струму розряду (рівень III)",
    "discharge_undertemperature": "Занизька температура для розряду",
    "gps_remote_lock": "Віддалене блокування через GPS",
}


ALARM_UNKNOWN = "Невідома аварія ({code})"


def alarm_text(code: str) -> str:
    """UI text for an alarm code (model.ALARM_CODES); unknown codes are shown as is."""
    return ALARM_TEXT.get(code, ALARM_UNKNOWN.format(code=code))


NO_VALUE = "—"
UNIT_MIN, UNIT_HOUR, UNIT_DAY = "хв", "год", "дн"


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
        return f"≈ {hours * 60:.0f} {UNIT_MIN}"
    if hours < 48:
        return f"≈ {hours:.1f} {UNIT_HOUR}"
    return f"≈ {hours / 24:.0f} {UNIT_DAY}"


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
SCALE_NOTE = "Масштаб і мова застосуються, щойно ви закриєте налаштування (програма перезапуститься за секунду)"
LANGUAGE_LABEL = "Мова"
# Language names are shown in their own language; only "auto" is translated.
LANGUAGE_OPTIONS = [("auto", "Як у Windows"), ("uk", "Українська"), ("en", "English")]
SECTION_BATTERY = "СТАН БАТАРЕЇ"
IDLE_LABEL = "Поріг «Очікування»"
IDLE_NOTE = "Якщо |струм| менший за поріг, стан показується як «Очікування»"
SECTION_SYSTEM = "СИСТЕМА"
SETTINGS_DONE = "Готово"
REPLAY_NOTE = "Режим відтворення запису: BMS змінити не можна"

# BMS picker
PICK_TITLE = "Вибір BMS"
PICK_HINT = (
    "Закрийте застосунок BMS на телефоні: BMS, до якого вже підключено "
    "телефон, не видно в пошуку."
)
PICK_SCANNING = "Пошук пристроїв Bluetooth…"
PICK_FOUND = "Знайдено: {n}"
PICK_NONE = "BMS не знайдено. Перевірте, що Bluetooth увімкнено, і повторіть пошук."
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
TEMP_SENSOR = "Датчик {n}: {t:.1f} °C"
TEMP_MOSFET = "MOSFET: {t:.1f} °C"
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
LEGEND_IDLE = "Очікування"
TIP_CURRENT = "Струм"
TIP_VOLTAGE = "Напруга"
TIP_POWER = "Потужність"
TIP_CHARGE = "заряд"
TIP_DISCHARGE = "розряд"


# Diagnostics (community captures for new BMS brands)
MENU_DIAGNOSTICS = "Записати діагностику…"
DIAG_TITLE = "Діагностичний запис"
DIAG_INTRO = (
    "Записує 60 секунд обміну з BMS у файл, щоб розробник міг додати "
    "підтримку вашої BMS. Програма лише читає дані й нічого в BMS не змінює. "
    "MAC-адресу, серійний номер і паролі буде вилучено з файлу (назва "
    "пристрою лишається). Закрийте застосунок BMS на телефоні."
)
DIAG_BRAND = "Марка BMS:"
DIAG_START = "Почати запис"
DIAG_STOP = "Зупинити"
DIAG_CONNECTING = "Підключення…"
DIAG_PROGRESS = "Запис… {s} с із {total}, отримано пакетів: {n}"
DIAG_NO_DATA = ("BMS не надіслав даних. Перевірте, чи правильно вибрано марку і чи "
                "відключено телефон.")
DIAG_ERROR = "Запис перервано: {err}"
DIAG_SAVED = ("Збережено: {path}\nПакетів: {n}. Додайте файл до звернення на GitHub "
              "або надішліть розробнику.")
DIAG_OPEN_FOLDER = "Відкрити теку"
BRAND_UNKNOWN = "Невідома марка"
PICK_CAPTURE_ONLY = (
    "{brand}: ця марка поки що підтримується лише для діагностичного запису. "
    "Запишіть діагностику (меню → «Записати діагностику…») і поділіться файлом, "
    "щоб ми додали повну підтримку."
)

# Notifications
NOTIFY_LOW_SOC = "Низький заряд батареї: {soc}%"
NOTIFY_FULL = "Батарею повністю заряджено"
NOTIFY_ALARM = "Аварія BMS: {names}"
NOTIFY_LOST = "Немає зв'язку з BMS понад хвилину"
NOTIFY_LABEL = "Сповіщення Windows"
NOTIFY_NOTE = "Низький заряд, нові аварії, втрата зв'язку на хвилину, повний заряд"
LOW_SOC_LABEL = "Поріг низького заряду"

# Energy counters (dashboard)
ROW_ENERGY_TODAY = "Енергія сьогодні:"
ROW_ENERGY_WEEK = "Енергія за 7 днів:"
ENERGY_TIP = ("Заряд / розряд, кВт·год. Рахується з історії, тож час, коли програма "
              "не працювала, не враховано.")

# Cells tab (dashboard)
TAB_CHART = "Графік"
TAB_CELLS = "Комірки"
CELLS_SUMMARY = "Δ {delta:.0f} mV · середня {avg:.3f} V · мін №{imin} · макс №{imax}"
CELLS_NO_DATA = "Немає даних від BMS"
CELLS_BALANCING = "Балансування"

# CSV export
MENU_EXPORT_CSV = "Експорт історії (CSV)…"
EXPORT_TITLE = "Експорт історії"
EXPORT_DONE = "Історію збережено: {path} ({n} записів)"
EXPORT_EMPTY = "Історія порожня, нема чого експортувати."

SECTION_DATA = "ДАНІ"
LOW_SOC_TIP = "Від 5 до 100 %. Сповіщення приходить, коли заряд падає до цього значення або нижче."

# Several BMS (settings tabs, BMS list, dashboard selector)
SETTINGS_TAB_BMS = "BMS"
SETTINGS_TAB_DISPLAY = "Відображення"
SETTINGS_TAB_ALERTS = "Стан і сповіщення"
SETTINGS_TAB_SYSTEM = "Система"
BMS_ADD = "Додати…"
BMS_REMOVE = "Прибрати"
BMS_MAIN_MARK = "(головна)"
BMS_LIST_NOTE = ("Кожна BMS має свою смужку на панелі завдань або свій віджет. Головна BMS "
                 "показується в значку в треї. Історію прибраної BMS не видаляємо.")
BMS_ALREADY = "Ця BMS уже є в списку."
MENU_ADD_BMS = "Додати BMS…"
DASH_SELECT_TIP = "Яку BMS показувати"

MENU_HIDE_BMS = "Сховати з панелі"
MENU_REMOVE_BMS = "Прибрати цю BMS"
MENU_SHOWN_BMS = "Показувати на панелі"
TIP_EYE = "Показувати смужку / віджет цієї BMS. Дані й графік записуються завжди."

LOW_SOC_STATE = "Низький заряд (поріг {t}%)"
BALANCING_ACTIVE = "Активне"

# Parallel banks (step D2) + widgets on the desktop
BANK_DEFAULT_NAME = "Банк {label}"
SETTINGS_TAB_BANKS = "Банки"
BANK_CREATE = "Створити банк…"
BANK_REMOVE = "Розформувати"
BANKS_NOTE = ("Банк — кілька BMS, з'єднаних паралельно. Програма показує їх як одну батарею: "
              "сумарний струм і потужність, SOC з урахуванням ємності, спільний графік і "
              "одна смужка на панелі. Кожну BMS банку можна відкрити окремо в головному вікні.")
BANKS_EMPTY = "Банків ще немає"
BANK_EDITOR_TITLE = "Банк"
BANK_NAME_LABEL = "Назва"
BANK_MEMBERS_LABEL = "BMS у банку (щонайменше дві)"
BANK_EDITOR_NOTE = ("BMS з іншого банку тут не показано. Смужки BMS банку ховаються; "
                    "їх можна повернути оком у списку BMS.")
BANK_SAVE = "Зберегти"
BANK_NEED_TWO = "Для банку потрібні щонайменше дві BMS, що ще не входять в інший банк."
BANK_MEMBERS_DETAIL = "{n} BMS: {names}"
BANK_MEMBER_OF = "у банку {label}"
MENU_REMOVE_BANK = "Розформувати банк"
BANK_PARTIAL = "{n} з {total} BMS без зв'язку"
BANK_PARTIAL_SHORT = "{n} з {total} без зв'язку"  # compact widget
BANK_PARTIAL_SUB = "Не враховано: {names}"
TIP_EYE_BANK = "Показувати смужку / віджет цього банку. Дані й графік записуються завжди."
DESKTOP_LABEL = "Віджети на робочому столі (не поверх інших вікон)"
DESKTOP_NOTE = ("Віджети лишаються під іншими програмами й видимі, коли згорнути все (Win+D). "
                "Смужка на панелі завдань не змінюється.")
ROW_EXCHANGE = "Перетік між акумами:"
EXCHANGE_TIP = ("Струм, що йде з одного акума банку в інший. У сумі банку він взаємно "
                "знищується: сума — це те, що йде в інвертор або від зарядки.")
BANK_KIND_NAMES = {"parallel": "Паралельно", "series": "Послідовно"}
BANK_KIND_LABEL = "З'єднання"
BANK_KIND_TIPS = {
    "parallel": "Однакова напруга, струми й ємності сумуються, SOC з урахуванням ємності.",
    "series": "Напруги сумуються, струм спільний, SOC і час до розряду — за найслабшим акумом.",
}
BANK_LETTER_LABEL = "Буква"
BANK_SERIES_PARTIAL_SUB = "Остання відома напруга: {names}"
BANK_NO_DATA = "Немає даних від BMS банку"
BANK_NO_DATA_SHORT = "Немає даних"
BANK_NO_DATA_SUB = "Без зв'язку понад хвилину: {names}"
CELLS_ALL = "Усі комірки:"
SECTION_UPDATES = "ОНОВЛЕННЯ"
UPDATE_CHECK_LABEL = "Перевіряти оновлення раз на день"
UPDATE_CHECK_NOW = "Перевірити зараз"
UPDATE_CHECK_NOTE = ("Програма лише дізнається номер останньої версії на GitHub. Вона нічого "
                     "не завантажує й не встановлює сама: оновлення ставите ви.")
UPDATE_AVAILABLE = "Доступна нова версія {version}. Натисніть, щоб відкрити сторінку завантаження."
UPDATE_NONE = "У вас найновіша версія (остання на GitHub: {version})."
UPDATE_FAILED = "Не вдалося перевірити оновлення. Перевірте з'єднання з інтернетом."
MENU_UPDATE = "Завантажити версію {version}…"

def partial_note(snap) -> str:
    """Which members of a bank are not live (parallel: left out of the sums;
    series: counted with their last known voltage)."""
    names = ", ".join(snap.offline)
    return (BANK_SERIES_PARTIAL_SUB if snap.series else BANK_PARTIAL_SUB).format(names=names)

# ----- language switching ---------------------------------------------------------
def _text_names() -> list[str]:
    return [n for n in globals() if n.isupper() and not n.startswith("_") and n != "LANGUAGES"]


_UK = {name: globals()[name] for name in _text_names()}  # originals, to switch back
language = "uk"


def set_language(lang: str) -> None:
    """Swap all UPPER_CASE texts to `lang` ("uk" or "en"). Unknown -> "en"."""
    global language
    if lang not in LANGUAGES:
        lang = "en"
    values = dict(_UK)
    if lang == "en":
        from . import strings_en

        values.update({n: getattr(strings_en, n) for n in _UK if hasattr(strings_en, n)})
    globals().update(values)
    language = lang


def resolve_language(setting: str, system_lang: str | None) -> str:
    """Setting "auto" follows Windows: Ukrainian Windows -> "uk", else "en"."""
    if setting in LANGUAGES:
        return setting
    return "uk" if system_lang == "uk" else "en"


def system_language() -> str | None:
    """Two-letter code of the Windows display language, e.g. "uk"/"en"."""
    if sys.platform != "win32":
        return None
    import ctypes
    import locale

    langid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    name = locale.windows_locale.get(langid, "")  # e.g. "uk_UA"
    return name.split("_")[0] or None
