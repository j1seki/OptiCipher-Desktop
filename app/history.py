"""
app.history
===========

A small, honest activity log for the current session.

The log stays in memory by default. The desktop UI can opt in to retaining
the bounded log in the current user's application settings.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
import json
from typing import List, Optional
from uuid import uuid4

#: How many entries the session log keeps. Old entries are dropped, so a
#: long session cannot grow without bound.
MAX_ENTRIES = 200
MAX_JOBS = 100


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

    def log_line(self, timestamps=True) -> str:
        prefix = f"{timestamp_text(self.timestamp)}  " if timestamps else ""
        level = {"ok": "OK", "error": "ERROR", "skip": "SKIP"}.get(self.status, "INFO")
        subject = f" · {self.subject}" if self.subject else ""
        detail = f" · {self.detail}" if self.detail else ""
        return f"{prefix}[{level}] {self.kind}{subject}{detail}"


def timestamp_text(value: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


@dataclass
class JobRecord:
    id: str
    name: str
    started: float = field(default_factory=time.time)
    finished: Optional[float] = None
    reviewed: Optional[float] = None
    summary: str = "Running"
    outcomes: List[HistoryEntry] = field(default_factory=list)


class SessionHistory:
    """
    A bounded activity log with optional local persistence.
    """

    def __init__(self, limit: int = MAX_ENTRIES) -> None:
        self._entries: List[HistoryEntry] = []
        self._jobs: dict[str, JobRecord] = {}
        self._limit = limit
        self.settings = None
        self.persistent = False
        self.on_change = None

    def attach_settings(self, settings) -> None:
        self.settings = settings
        self.persistent = settings.value("activity/keep", False, bool)
        if self.persistent:
            try:
                records = json.loads(settings.value("activity/entries", "[]"))
                self._entries = [HistoryEntry(**item) for item in records[-self._limit:]]
            except (TypeError, ValueError):
                self._entries = []
            try:
                jobs = json.loads(settings.value("activity/jobs", "[]"))
                for item in jobs[-MAX_JOBS:]:
                    outcomes = [HistoryEntry(**entry) for entry in item.pop("outcomes", [])]
                    job = JobRecord(**item, outcomes=outcomes)
                    if job.finished is None:
                        job.finished = time.time()
                        job.summary = "Interrupted before completion"
                    self._jobs[job.id] = job
                self._save_jobs()
            except (TypeError, ValueError, AttributeError):
                self._jobs.clear()

    def set_persistent(self, enabled: bool) -> None:
        if self.settings is None:
            return
        self.persistent = enabled
        self.settings.setValue("activity/keep", enabled)
        if enabled:
            self._save()
            self._save_jobs()
        else:
            self.settings.remove("activity/entries")
            self.settings.remove("activity/jobs")

    def _save_jobs(self) -> None:
        if self.persistent:
            self.settings.setValue("activity/jobs", json.dumps([asdict(job) for job in self._jobs.values()]))

    def _save(self) -> None:
        if self.persistent:
            self.settings.setValue("activity/entries", json.dumps([asdict(entry) for entry in self._entries]))
        if self.on_change:
            self.on_change()

    def begin_job(self, name: str, detail: str = "Started") -> str:
        job = JobRecord(uuid4().hex, name)
        self._jobs[job.id] = job
        self._save_jobs()
        self.record(name, "", "info", detail)
        return job.id

    def finish_job(self, job_id, summary: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.finished is not None:
            return
        job.finished = time.time()
        job.summary = summary
        complete = [item.id for item in self._jobs.values() if item.finished is not None]
        for old in complete[:-MAX_JOBS]:
            del self._jobs[old]
        self._save_jobs()
        self.record(job.name, "", "info", summary)

    def confirm_review(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job and job.finished is not None and job.reviewed is None:
            job.reviewed = time.time()
            self._save_jobs()
            self.record(job.name, "", "info", "Review confirmed")

    @property
    def jobs(self) -> List[JobRecord]:
        return list(reversed(self._jobs.values()))

    # -- writing ------------------------------------------------------------
    def record(
        self,
        kind: str,
        subject: str,
        status: str,
        detail: str = "",
        output: Optional[str] = None,
        job_id: Optional[str] = None,
    ) -> HistoryEntry:
        entry = HistoryEntry(
            kind=kind,
            subject=subject,
            status=status,
            detail=detail,
            output=output,
        )
        self._entries.append(entry)
        if job_id in self._jobs:
            self._jobs[job_id].outcomes.append(entry)
            self._save_jobs()
        if len(self._entries) > self._limit:
            del self._entries[: len(self._entries) - self._limit]
        self._save()
        return entry

    # -- reading ------------------------------------------------------------
    @property
    def entries(self) -> List[HistoryEntry]:
        """The recorded entries, oldest first."""
        return list(self._entries)

    def recent(self, count: int = 20, include_events: bool = True) -> List[HistoryEntry]:
        """The `count` most recent entries, newest first."""
        source = self._entries if include_events else [entry for entry in self._entries if entry.status in ("ok", "error")]
        return list(reversed(source[-count:]))

    def counts(self) -> dict:
        """How many succeeded and how many failed, in this session."""
        ok = sum(1 for e in self._entries if e.status == "ok")
        failed = sum(1 for e in self._entries if e.status == "error")
        return {
            "total": ok + failed,
            "ok": ok,
            "failed": failed,
        }

    def clear(self) -> None:
        self._entries.clear()
        self._save()
