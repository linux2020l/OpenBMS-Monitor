"""Colors, palette and the global Qt stylesheet (dark theme from the mockup).

We use Qt's "Fusion" style with our own dark palette instead of the native
"windows11" style: the native style has its own hover animations and
ignores parts of our colors (it drew list text black on our dark background),
so Fusion gives the same look and predictable behaviour everywhere.
"""

BG = "#10131a"
CARD = "#181c25"
CARD_BORDER = "#262c38"
TRACK = "#2b313d"  # empty part of the SOC ring, grid lines, hover background
HOVER = "#343b49"
TEXT = "#e7e9ee"
MUTED = "#8a93a3"
GREEN = "#34d27b"
BLUE = "#3b82f6"
PURPLE = "#8b5cf6"
RED = "#ef4444"
AMBER = "#f5b70b"
GREY = "#5b6472"

STATUS_COLORS = {
    "connecting": AMBER,
    "connected": GREEN,
    "lost": RED,
    "stopped": GREY,
    "replay": BLUE,
}

FONT_FAMILY = "Segoe UI"

STYLESHEET = f"""
QWidget {{ color: {TEXT}; font-family: '{FONT_FAMILY}'; font-size: 10pt; }}
QDialog {{ background: {BG}; }}
QFrame#root {{ background: {BG}; border: none; }}
QFrame[card="true"] {{
    background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 12px;
}}
QLabel {{ background: transparent; border: none; }}
QLabel[muted="true"] {{ color: {MUTED}; }}
QLabel[section="true"] {{ color: {MUTED}; font-size: 9pt; font-weight: 600; }}
QToolButton, QPushButton {{
    background: transparent; border: none; border-radius: 8px; padding: 4px 8px;
}}
QToolButton:hover, QPushButton:hover {{ background: {HOVER}; }}
QToolButton:pressed, QPushButton:pressed {{ background: {TRACK}; }}
QPushButton:disabled {{ color: {GREY}; }}
QPushButton[primary="true"] {{ background: {BLUE}; color: white; padding: 6px 16px; }}
QPushButton[primary="true"]:hover {{ background: #5592f7; }}
QPushButton[primary="true"]:disabled {{ background: {TRACK}; color: {GREY}; }}
QPushButton[secondary="true"] {{ background: {TRACK}; padding: 6px 14px; }}
QPushButton[secondary="true"]:hover {{ background: {HOVER}; }}
QPushButton[range="true"] {{ color: {MUTED}; padding: 4px 14px; border-radius: 13px; }}
QPushButton[range="true"]:checked {{ background: {BLUE}; color: white; }}
QFrame#line {{ background: {CARD_BORDER}; max-height: 1px; min-height: 1px; border: none; }}
QListWidget {{
    background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 8px;
    padding: 4px; outline: none;
}}
QListWidget::item {{ color: {TEXT}; padding: 8px; border-radius: 6px; }}
QListWidget::item:hover {{ background: {TRACK}; }}
QListWidget::item:selected {{ background: #1f3b63; color: {TEXT}; }}
QCheckBox, QRadioButton {{ spacing: 8px; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px; height: 16px; border: 2px solid {GREY}; background: {CARD};
}}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 10px; }}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {MUTED}; }}
QCheckBox::indicator:checked {{ background: {BLUE}; border-color: {BLUE}; }}
QRadioButton::indicator:checked {{
    border-color: {BLUE};
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
        stop:0 {BLUE}, stop:0.55 {BLUE}, stop:0.65 {CARD}, stop:1 {CARD});
}}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: {TRACK}; }}
QCheckBox:disabled, QRadioButton:disabled {{ color: {GREY}; }}
QComboBox {{
    background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 6px;
    padding: 4px 8px; min-height: 22px;
}}
QDoubleSpinBox, QSpinBox {{
    background: {CARD}; border: 1px solid {CARD_BORDER}; border-radius: 6px;
    min-height: 30px;
}}
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button,
QSpinBox::up-button, QSpinBox::down-button {{ width: 0px; border: none; }}
QComboBox:hover, QDoubleSpinBox:hover, QSpinBox:hover {{ border-color: {GREY}; }}
QComboBox QAbstractItemView {{
    background: {CARD}; border: 1px solid {CARD_BORDER}; selection-background-color: {HOVER};
}}
QMenu {{ background: {CARD}; border: 1px solid {CARD_BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {HOVER}; }}
QMenu::item:disabled {{ color: {GREY}; }}
QMenu::separator {{ height: 1px; background: {CARD_BORDER}; margin: 4px 8px; }}
QToolTip {{ background: {CARD}; color: {TEXT}; border: 1px solid {CARD_BORDER}; }}
"""


def _indicator_images() -> str:
    """Stylesheet rules that draw real tick marks.

    Qt stylesheets can only use image *files* for indicators, so the vector
    tick is rendered once to PNGs in a temp folder.
    """
    import tempfile
    from pathlib import Path

    from . import icons

    folder = Path(tempfile.gettempdir()) / "jkbms_widget_ui"
    folder.mkdir(exist_ok=True)
    white, blue = folder / "tick_white.png", folder / "tick_blue.png"
    icons.pixmap("checkmark", "#ffffff", 16).save(str(white))
    icons.pixmap("checkmark", BLUE, 16).save(str(blue))
    w, b = white.as_posix(), blue.as_posix()
    return f"""
QCheckBox::indicator:checked {{ image: url("{w}"); }}
QMenu::indicator {{ width: 16px; height: 16px; margin-left: 6px; }}
QMenu::indicator:checked {{ image: url("{b}"); }}
QMenu::item {{ padding: 6px 18px 6px 28px; }}
"""


def apply_style(app) -> None:
    """Fusion style + dark palette + stylesheet for the whole application."""
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")
    pal = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT, QPalette.Base: CARD,
        QPalette.AlternateBase: TRACK, QPalette.Text: TEXT, QPalette.Button: CARD,
        QPalette.ButtonText: TEXT, QPalette.BrightText: "#ffffff", QPalette.Highlight: BLUE,
        QPalette.HighlightedText: "#ffffff", QPalette.ToolTipBase: CARD,
        QPalette.ToolTipText: TEXT, QPalette.PlaceholderText: MUTED, QPalette.Link: BLUE,
        QPalette.Mid: CARD_BORDER, QPalette.Dark: BG, QPalette.Light: HOVER,
    }
    for role, color in roles.items():
        pal.setColor(role, QColor(color))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(GREY))
    app.setPalette(pal)
    try:
        extra = _indicator_images()
    except OSError:
        extra = ""  # no temp folder: fall back to colour-only indicators
    app.setStyleSheet(STYLESHEET + extra)


def soc_color(soc: float) -> str:
    if soc < 20:
        return RED
    if soc < 50:
        return AMBER
    return GREEN
