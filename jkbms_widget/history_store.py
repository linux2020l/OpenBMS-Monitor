"""Long-term chart history in SQLite (stdlib sqlite3), one series per BMS.

File: %APPDATA%\\OpenBmsMonitor\\history.sqlite. Rows are the 10-second
buckets of `state.History`; anything older than RETENTION_S is pruned.
Pure Python, no Qt. All calls happen on the GUI thread.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .state import HistoryPoint

RETENTION_S = 7 * 24 * 3600  # keep one week per BMS


class HistoryStore:
    def __init__(self, path: str | Path) -> None:
        self.conn = sqlite3.connect(str(path))
        self.conn.execute("PRAGMA journal_mode=WAL")  # cheap small writes
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS samples ("
            " bms TEXT NOT NULL, t REAL NOT NULL, soc REAL NOT NULL, current REAL NOT NULL,"
            " voltage REAL,"
            " PRIMARY KEY (bms, t)) WITHOUT ROWID"
        )
        # Databases from the first version have no voltage column: add it.
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(samples)")}
        if "voltage" not in columns:
            self.conn.execute("ALTER TABLE samples ADD COLUMN voltage REAL")
        self.conn.commit()

    @staticmethod
    def _row(bms: str, p: HistoryPoint) -> tuple:
        return (bms.upper(), p.time, p.soc, p.current, p.voltage)

    def add(self, bms: str, point: HistoryPoint) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO samples (bms, t, soc, current, voltage) VALUES (?, ?, ?, ?, ?)",
            self._row(bms, point),
        )
        self.conn.commit()

    def add_many(self, bms: str, points: list[HistoryPoint]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO samples (bms, t, soc, current, voltage) VALUES (?, ?, ?, ?, ?)",
            [self._row(bms, p) for p in points],
        )
        self.conn.commit()

    def load(self, bms: str, since: float) -> list[HistoryPoint]:
        rows = self.conn.execute(
            "SELECT t, soc, current, voltage FROM samples WHERE bms = ? AND t >= ? ORDER BY t",
            (bms.upper(), since),
        ).fetchall()
        return [HistoryPoint(t, soc, i, v) for t, soc, i, v in rows]

    def prune(self, now: float, retention_s: float = RETENTION_S) -> int:
        cur = self.conn.execute("DELETE FROM samples WHERE t < ?", (now - retention_s,))
        self.conn.commit()
        return cur.rowcount

    def close(self) -> None:
        self.conn.close()
