"""Entry point for the PyInstaller .exe: runs the widget (or any CLI subcommand)."""

from jkbms_widget.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
