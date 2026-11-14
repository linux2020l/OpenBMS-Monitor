"""Generate the application icon (assets/icon.ico) from the vector battery icon.

Usage: python tools/make_icon.py assets/icon.ico
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QGuiApplication  # noqa: E402

from jkbms_widget.ui import icons, theme  # noqa: E402

app = QGuiApplication([])
out = Path(sys.argv[1] if len(sys.argv) > 1 else "assets/icon.ico")
out.parent.mkdir(parents=True, exist_ok=True)
image = icons.battery_level_icon(80, theme.GREEN).pixmap(256, 256).toImage()
if not image.save(str(out)):
    raise SystemExit(f"could not write {out}")
print(f"wrote {out}")
