"""JSON-lines journal — ALWAYS written (D6). Drives resume, idempotency,
rollback and the final report.

Layout:  <state>/runs/<run_id>/journal.jsonl
         <state>/runs/<run_id>/backup/<absolute path of each backed-up file>
         <state>/runs/latest -> <run_id>   (text file, not a symlink)

`latest` names the last REAL run that changed the machine (apply or reset).
Dry runs and the other commands never move it, so `linop rollback` and
`linop resume` without a run id always act on what was really applied.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

# action status as recorded in the journal
STARTED, DONE, SKIPPED, FAILED = "started", "done", "skipped", "failed"

# commands whose real (not dry) runs change the machine and can be rolled back
CHANGING_COMMANDS = ("apply", "reset")


def new_run_id() -> str:
    """Sortable and unique even for several runs in the same second."""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ") + "-" + secrets.token_hex(2)


@dataclass
class Journal:
    run_dir: Path

    @classmethod
    def create(cls, runs_dir: Path, run_id: str | None = None, *, latest: bool = True,
               **meta: Any) -> "Journal":
        """Start a run. `latest` is moved only when `latest` is true AND the run
        is real (`dry_run` not set): a dry run never becomes the run that
        rollback / resume act on."""
        run_id = run_id or new_run_id()
        run_dir = runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        journal = cls(run_dir)
        journal.write("run_start", **meta)
        if latest and not meta.get("dry_run", False):
            (runs_dir / "latest").write_text(run_id + "\n")
        return journal

    @classmethod
    def open(cls, runs_dir: Path, run_id: str | None = None) -> "Journal":
        """Open `run_id`, or without it the last real apply / reset run."""
        if run_id is None:
            journal = latest_real(runs_dir)
            if journal is None:
                raise FileNotFoundError("no previous run")
            return journal
        run_dir = runs_dir / run_id
        if not (run_dir / "journal.jsonl").exists():
            raise FileNotFoundError(f"run {run_id} has no journal")
        return cls(run_dir)

    @property
    def run_id(self) -> str:
        return self.run_dir.name

    @property
    def path(self) -> Path:
        return self.run_dir / "journal.jsonl"

    @property
    def backup_dir(self) -> Path:
        return self.run_dir / "backup"

    def write(self, event: str, **data: Any) -> None:
        record = {"ts": time.time(), "event": event, **data}
        line = json.dumps(record, sort_keys=True, default=str)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def events(self) -> Iterator[dict[str, Any]]:
        with self.path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue  # a line cut by a crash is ignored, not fatal

    def action_status(self) -> dict[str, str]:
        """Last recorded status per action id."""
        status: dict[str, str] = {}
        for ev in self.events():
            if ev["event"] == "action":
                status[ev["id"]] = ev["status"]
        return status

    def finished(self) -> bool:
        return any(ev["event"] == "run_end" for ev in self.events())

    def meta(self) -> dict[str, Any]:
        """The `run_start` record (empty when the first line was lost)."""
        for ev in self.events():
            return ev if ev.get("event") == "run_start" else {}
        return {}

    @property
    def dry_run(self) -> bool:
        return bool(self.meta().get("dry_run", False))

    @property
    def command(self) -> str | None:
        meta = self.meta()
        if "command" in meta:
            return meta["command"]
        return "apply" if "profile" in meta else None   # journals written before `command` was recorded

    def changes_machine(self) -> bool:
        """A real apply / reset run: the only kind rollback and resume act on.
        A journal without any command record (bare `Journal.create`) counts too."""
        return not self.dry_run and self.command in (*CHANGING_COMMANDS, None)

    def state(self) -> str:
        end = None
        for ev in self.events():
            if ev["event"] == "run_end":
                end = ev.get("summary") or {}
        if end is None:
            return "interrupted"
        if end.get("cancelled"):
            return "cancelled"
        if end.get("nothing_to_do"):
            return "nothing to do"
        if end.get("preflight") == "failed":
            return "preflight failed"
        return "finished"


def list_runs(runs_dir: Path) -> list[Journal]:
    if not runs_dir.is_dir():
        return []
    return [Journal(d) for d in sorted(runs_dir.iterdir()) if (d / "journal.jsonl").exists()]


def latest_real(runs_dir: Path) -> Journal | None:
    """The last real apply / reset run. Trusts the `latest` pointer only when it
    names such a run (an older FAI_LinOP also pointed it at dry runs)."""
    pointer = runs_dir / "latest"
    if pointer.exists():
        run_dir = runs_dir / pointer.read_text().strip()
        if (run_dir / "journal.jsonl").exists() and Journal(run_dir).changes_machine():
            return Journal(run_dir)
    for journal in reversed(list_runs(runs_dir)):
        if journal.changes_machine():
            return journal
    return None


class NullJournal(Journal):
    """For read-only commands: records nothing and creates no file, so a
    command like `linop display show` leaves no run behind."""

    def __init__(self) -> None:
        super().__init__(Path(os.devnull))

    def write(self, event: str, **data: Any) -> None:
        return None

    def events(self) -> Iterator[dict[str, Any]]:
        return iter(())
