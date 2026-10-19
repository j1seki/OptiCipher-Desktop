"""
app.history
===========

A small, honest activity log for the current session.

OptiCipher does not keep a permanent history: nothing about the files a
user encrypts should be written to disk by a tool whose whole purpose is
not to leave traces. The History screen therefore shows what happened *in
this session only*, and says so.

The log is plain data (a list of records) with no Qt dependency, so it can
be unit-tested without a QApplication.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

#: How many entries the session log keeps. Old entries are dropped, so a
#: long session cannot grow without bound.
MAX_ENTRIES = 200


@dataclass
class HistoryEntry:
    """One recorded operation."""

    kind: str                 # "encrypt" | "decrypt" | "verify"
    subject: str              # file name
    status: str               # "ok" | "error"
    detail: str = ""          # output path or reason
    timestamp: float = field(default_factory=time.time)
    output: Optional[str] = None

    @property
    def time_text(self) -> str:
        return time.strftime("%H:%M:%S", time.localtime(self.timestamp))


class SessionHistory:
    """
    An in-memory, session-scoped activity log.

    Nothing here is ever persisted: closing the application discards it.
    """

    def __init__(self, limit: int = MAX_ENTRIES) -> None:
        self._entries: List[HistoryEntry] = []
        self._limit = limit

    # -- writing ------------------------------------------------------------
    def record(
        self,
        kind: str,
        subject: str,
        status: str,
        detail: str = "",
        output: Optional[str] = None,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            kind=kind,
            subject=subject,
            status=status,
            detail=detail,
            output=output,
        )
        self._entries.append(entry)
        if len(self._entries) > self._limit:
            del self._entries[: len(self._entries) - self._limit]
        return entry

    # -- reading ------------------------------------------------------------
    @property
    def entries(self) -> List[HistoryEntry]:
        """The recorded entries, oldest first."""
        return list(self._entries)

    def recent(self, count: int = 20) -> List[HistoryEntry]:
        """The `count` most recent entries, newest first."""
        return list(reversed(self._entries[-count:]))

    def counts(self) -> dict:
        """How many succeeded and how many failed, in this session."""
        ok = sum(1 for e in self._entries if e.status == "ok")
        return {
            "total": len(self._entries),
            "ok": ok,
            "failed": len(self._entries) - ok,
        }

    def clear(self) -> None:
        self._entries.clear()
