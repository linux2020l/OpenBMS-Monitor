"""Registry of supported BMS families.

Adding a brand: create drivers/<brand>/ with a BmsDriver subclass (see
base.py), its read-only allowlist, a decoder and tests built from a real
capture, then add its DRIVER to DRIVERS below.
"""

from __future__ import annotations

from .base import BmsDriver, ForbiddenCommandError, Request
from .jk import DRIVER as JK

DRIVERS: tuple[BmsDriver, ...] = (JK,)
DEFAULT_DRIVER = JK

__all__ = ["BmsDriver", "DRIVERS", "DEFAULT_DRIVER", "ForbiddenCommandError", "Request",
           "detect", "get"]


def get(driver_id: str | None) -> BmsDriver:
    """Driver by id; unknown/None -> the default (JK), as in old settings files."""
    return next((d for d in DRIVERS if d.id == driver_id), DEFAULT_DRIVER)


def detect(name: str, service_uuids: list[str]) -> BmsDriver | None:
    """First driver that recognises a scanned device, or None."""
    uuids = [u.lower() for u in service_uuids]
    return next((d for d in DRIVERS if d.matches(name or "", uuids)), None)
