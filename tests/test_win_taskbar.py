from jkbms_widget.win_taskbar import (
    ABE_BOTTOM,
    ABE_LEFT,
    FALLBACK_OFFSET,
    TaskbarInfo,
    strip_geometry,
)

# Values measured on the owner's PC: 2560x1440, taskbar 48 px at the bottom,
# tray (TrayNotifyWnd) starting at x=2340, 100 % scaling.
OWNER = TaskbarInfo(0, 1392, 2560, 1440, ABE_BOTTOM, 2340, False)


def test_strip_sits_left_of_tray_at_100_percent():
    x, y, w, h = strip_geometry(OWNER, 1.0, 236, None)
    assert x + w == 2340 - 8  # 8 px gap before the tray
    assert (y, h) == (1395, 42)


def test_strip_scales_with_dpi():
    info = TaskbarInfo(0, 2088, 3840, 2160, ABE_BOTTOM, 3510, False)  # 150 %
    x, y, w, h = strip_geometry(info, 1.5, 236, None)
    assert x + w == round(3510 / 1.5) - 8
    assert y == 2088 / 1.5 + 3 and h == 48 - 6


def test_user_offset_is_clamped_inside_taskbar():
    x, _, w, _ = strip_geometry(OWNER, 1.0, 236, 10_000)
    assert x == 0
    x, _, w, _ = strip_geometry(OWNER, 1.0, 236, -50)
    assert x + w == 2560


def test_fallback_when_tray_not_found():
    info = TaskbarInfo(0, 1392, 2560, 1440, ABE_BOTTOM, None, False)
    x, _, w, _ = strip_geometry(info, 1.0, 236, None)
    assert x + w == 2560 - FALLBACK_OFFSET


def test_vertical_or_autohide_taskbar_not_supported():
    assert strip_geometry(TaskbarInfo(0, 0, 48, 1440, ABE_LEFT, None, False), 1.0, 236, None) is None
    assert strip_geometry(TaskbarInfo(0, 1392, 2560, 1440, ABE_BOTTOM, 2340, True), 1.0, 236, None) is None
