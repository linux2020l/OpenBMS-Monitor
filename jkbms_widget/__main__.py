"""Command-line entry point: `python -m jkbms_widget <subcommand>`.

Subcommands: `commands` (M1), `scan`, `dump` (M2), `replay` (M3), `widget` (M4).
"""

import argparse
import asyncio
import sys
from pathlib import Path

from . import __version__, drivers
from .drivers.jk import VARIANTS

# WinRT HRESULT 0x800710DF "The device is not ready for use":
# raised by bleak when the Bluetooth radio is switched off.
ERROR_NOT_READY = -2147020577

DRIVER_IDS = [d.id for d in drivers.DRIVERS]


def _cmd_commands(_args: argparse.Namespace) -> int:
    """Print the only frames this app is allowed to send, for manual checking."""
    for d in drivers.DRIVERS:
        print(f"{d.name} ({d.id}):")
        labels = {r.frame: r.label for r in d.poll_requests + d.connect_requests}
        for frame in sorted(d.allowed_frames):
            print(f"  {labels.get(frame, '?'):28s} {frame.hex(' ').upper()}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    from .ble import scan  # imported lazily so `commands` works without bleak

    print(f"Scanning for {args.timeout:.0f} s...")
    results = asyncio.run(scan(args.timeout))
    for r in results:
        print(f"{r.driver_id or '-':6s} {r.address}  {r.rssi:4d} dBm  {r.name}")
    print(f"{len(results)} device(s); first column = recognised BMS driver")
    return 0


def _driver(args: argparse.Namespace):
    return drivers.get(args.driver) if getattr(args, "driver", None) else None


def _options(args: argparse.Namespace) -> dict:
    return {"variant": args.variant} if getattr(args, "variant", None) else {}


def _cmd_dump(args: argparse.Namespace) -> int:
    from .dump import run_dump

    return asyncio.run(run_dump(args.address, args.seconds, Path(args.log_dir),
                                _driver(args), _options(args)))


def _cmd_widget(args: argparse.Namespace) -> int:
    from .app import run_widget

    # Without --address the saved BMS is used; on first run a picker opens.
    return run_widget(
        address=args.address,
        replay=args.replay,
        speed=args.speed,
        driver_id=args.driver,
        options=_options(args),
        idle_threshold=args.idle_threshold,
        exit_after=args.exit_after,
        autostart_launch=args.autostart,
    )


def _cmd_replay(args: argparse.Namespace) -> int:
    from .replay import run_replay

    from .capture import capture_driver_id

    driver = _driver(args) or drivers.get(capture_driver_id(args.log))
    return run_replay(args.log, args.speed, args.loop, driver, _options(args))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="jkbms_widget", description="Read-only BMS BLE widget (JK, more to come)"
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("commands", help="show the allowlisted request frames")
    p.set_defaults(func=_cmd_commands)

    p = sub.add_parser("scan", help="list nearby BLE devices")
    p.add_argument("--timeout", type=float, default=8.0, help="scan time, s")
    p.set_defaults(func=_cmd_scan)

    p = sub.add_parser("dump", help="connect and log raw notifications as hex")
    p.add_argument("--address", help="BMS MAC address (default: auto-detect)")
    p.add_argument("--seconds", type=float, default=60.0, help="logging time, s")
    p.add_argument("--log-dir", default="logs", help="output folder")
    p.add_argument("--driver", choices=DRIVER_IDS, help="BMS family (default: detect / jk)")
    p.add_argument("--variant", choices=VARIANTS, help="JK only: force protocol variant")
    p.set_defaults(func=_cmd_dump)

    p = sub.add_parser("replay", help="decode a captured log, no BMS needed")
    p.add_argument("log", help="capture file (logs/dump-*.txt or tests/fixtures/*.txt)")
    p.add_argument("--speed", type=float, default=1.0, help="1 = real time, 0 = no delays")
    p.add_argument("--loop", action="store_true", help="repeat forever")
    p.add_argument("--driver", choices=DRIVER_IDS, help="BMS family (default: detect / jk)")
    p.add_argument("--variant", choices=VARIANTS, help="JK only: force protocol variant")
    p.set_defaults(func=_cmd_replay)

    p = sub.add_parser("widget", help="run the desktop widget")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--address", help="BMS MAC address (saved; default: last used)")
    src.add_argument("--replay", help="capture file to play in a loop (no BMS needed)")
    p.add_argument("--speed", type=float, default=1.0, help="replay speed factor")
    p.add_argument("--idle-threshold", type=float, default=None,
                   help="|I| below this (A) counts as Idle (saved)")
    p.add_argument("--driver", choices=DRIVER_IDS, help="BMS family (default: detect / jk)")
    p.add_argument("--variant", choices=VARIANTS, help="JK only: force protocol variant")
    p.add_argument("--exit-after", type=float, default=None, help=argparse.SUPPRESS)
    # Added by the Windows Run entry: start without opening the dashboard.
    p.add_argument("--autostart", action="store_true", help=argparse.SUPPRESS)
    p.set_defaults(func=_cmd_widget)

    # No subcommand = run the widget (this is what the .exe does).
    argv = sys.argv[1:] if argv is None else argv
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv = ["widget", *argv]
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("Stopped by user.")
        return 130
    except Exception as exc:  # friendly message instead of a traceback
        # BLE errors (adapter off, connection lost, ...) end up here.
        print(f"ERROR: {type(exc).__name__}: {exc}")
        if getattr(exc, "winerror", None) == ERROR_NOT_READY:
            print("Hint: Bluetooth seems to be turned off. Turn it on in Windows "
                  "Settings > Bluetooth & devices (or the quick settings panel).")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
