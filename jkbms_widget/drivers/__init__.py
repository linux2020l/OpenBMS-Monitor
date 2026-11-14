"""Registry of supported BMS families.

Adding a brand: create drivers/<brand> with a BmsDriver subclass (see
base.py), its read-only allowlist, a decoder and tests built from a real
capture, then add its DRIVER to DRIVERS below. Brands whose decoder is not
written yet are `capture_only`: they can record diagnostics for the
community, but cannot be the monitored BMS.
"""

from __future__ import annotations

from .ant import DRIVER as ANT
from .base import BmsDriver, ForbiddenCommandError, Request
from .daly import DRIVER as DALY
from .jbd import DRIVER as JBD
from .jk import DRIVER as JK

DRIVERS: tuple[BmsDriver, ...] = (JK, JBD, DALY, ANT)
DEFAULT_DRIVER = JK
# Detection order: ANT uses the same GATT UUIDs as JK, so it is checked by
# name first; JK (matched by its service UUID) comes last.
_DETECT_ORDER: tuple[BmsDriver, ...] = (ANT, JBD, DALY, JK)

__all__ = ["BmsDriver", "DRIVERS", "DEFAULT_DRIVER", "ForbiddenCommandError", "Request",
           "detect", "get", "monitorable"]


def get(driver_id: str | None) -> BmsDriver:
    """Driver by id; unknown/None -> the default (JK), as in old settings files."""
    return next((d for d in DRIVERS if d.id == driver_id), DEFAULT_DRIVER)


def detect(name: str, service_uuids: list[str]) -> BmsDriver | None:
    """First driver that recognises a scanned device, or None."""
    uuids = [u.lower() for u in service_uuids]
    return next((d for d in _DETECT_ORDER if d.matches(name or "", uuids)), None)


def monitorable(driver_id: str | None) -> bool:
    """True if the app can show live data for this brand (not capture-only)."""
    return driver_id is not None and not get(driver_id).capture_only
