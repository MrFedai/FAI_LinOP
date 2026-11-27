"""Per-file backup and restore (D6 fallback when no filesystem snapshot exists).

Every file FAI_LinOP changes goes through `FileChanger.write()`:
  1. a verified copy of the old file (or the fact that it did not exist) is
     recorded in the journal,
  2. the new content is written atomically,
  3. rollback restores exactly what was recorded.
Root-owned files are handled through the CommandRunner with sudo.
"""

from __future__ import annotations

import configparser
import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fai_linop.core.runner import Runner
from fai_linop.recovery.journal import Journal


# `dconf dump /` shows the MERGED view: the user's database plus system databases
# (e.g. Fedora's authselect keys under /org/gnome/login-screen, which are also
# locked). Backups and restores work on the user's own database only, so a
# restore never tries to write system defaults or locked keys (CI run
# 36056633594: rollback failed on Fedora with "non-writable keys").
USER_ONLY_DCONF_PROFILE = "user-db:user\n"


def dconf_user(runner: Runner, *args: str, input: str | None = None, mutating: bool = True,
               check: bool = True):
    """Run `dconf <args>` against the user database only (DCONF_PROFILE)."""
    with tempfile.TemporaryDirectory(prefix="linop-dconf-") as tmp:
        profile = Path(tmp) / "profile"
        profile.write_text(USER_ONLY_DCONF_PROFILE)
        env = dict(os.environ, DCONF_PROFILE=str(profile))
        return runner.run(["dconf", *args], input=input, env=env, mutating=mutating, check=check)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _backup_path(journal: Journal, target: Path) -> Path:
    return journal.backup_dir / str(target.resolve()).lstrip(os.sep)


def _read_current(runner: Runner, target: Path) -> bytes | None:
    """Current content of `target`, or None when it does not exist.

    Root-owned files the user cannot read (e.g. /etc/usbguard/rules.conf) are
    probed and read through the runner with sudo; `exists()` alone would say
    "missing" and the file would be overwritten without a backup (V300 1.7).
    Raises OSError when the state cannot be determined: never guess."""
    try:
        return target.read_bytes()
    except FileNotFoundError:
        ancestor = target.parent
        while not ancestor.exists() and ancestor != ancestor.parent:
            ancestor = ancestor.parent
        if os.access(ancestor, os.R_OK | os.X_OK):
            return None          # the directories above are visible to us: really absent
    except PermissionError:
        pass
    except IsADirectoryError as exc:
        raise OSError(f"{target} is a directory") from exc
    if runner.run(["test", "-e", str(target)], sudo=True, mutating=False, check=False).returncode != 0:
        return None
    res = runner.run(["cat", str(target)], sudo=True, mutating=False, check=False)
    if not res.ok:
        raise OSError(f"cannot read {target} to back it up: {res.stderr.strip() or res.returncode}")
    return res.stdout.encode()


@dataclass
class FileChanger:
    journal: Journal
    runner: Runner

    def _already_backed_up(self, target: Path) -> bool:
        """The first backup of a file in a run is the original; later changes keep it."""
        return any(ev["event"] == "file_backup" and ev.get("path") == str(target)
                   for ev in self.journal.events())

    def _save(self, target: Path, old: bytes) -> Path:
        backup = _backup_path(self.journal, target)
        backup.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(target, backup)
        except OSError:          # not readable by the user: use the bytes read through sudo
            backup.write_bytes(old)
        if sha256_file(backup) != sha256_bytes(old):
            raise OSError(f"backup verification failed for {target}")
        return backup

    def backup_only(self, target: Path, root: bool = False) -> None:
        """Record a verified backup of a file another program is about to change."""
        target = Path(target)
        old = _read_current(self.runner, target)
        if self.runner.dry_run:
            self.journal.write("file_planned", path=str(target), existed=old is not None)
            return
        if self._already_backed_up(target):
            return
        backup = self._save(target, old) if old is not None else None
        self.journal.write("file_backup", path=str(target), existed=old is not None,
                           backup=str(backup) if backup else None, root=root)

    def write(self, target: Path, content: bytes, *, root: bool = False, mode: int | None = None) -> bool:
        """Write `content` to `target`. Returns False when the file already has
        exactly this content (idempotent, nothing recorded)."""
        target = Path(target)
        old = _read_current(self.runner, target)
        existed = old is not None
        if existed and old == content:
            return False
        if self.runner.dry_run:
            self.journal.write("file_planned", path=str(target), existed=existed,
                               new_sha256=sha256_bytes(content))
            return True
        if self._already_backed_up(target):
            # second change in this run: the journal already holds the original
            backup = _backup_path(self.journal, target) if existed else None
        else:
            backup = self._save(target, old) if existed else None
            self.journal.write("file_backup", path=str(target), existed=existed,
                               backup=str(backup) if backup else None,
                               old_sha256=sha256_bytes(old) if existed else None,
                               new_sha256=sha256_bytes(content), root=root)
        if root:
            self.runner.run(["mkdir", "-p", str(target.parent)], sudo=True)
            self.runner.run(["tee", str(target)], sudo=True, input=content.decode())
            if mode is not None:
                self.runner.run(["chmod", f"{mode:o}", str(target)], sudo=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.linop-")
            with os.fdopen(fd, "wb") as fh:
                fh.write(content)
            if mode is not None:
                os.chmod(tmp, mode)
            elif backup is not None and backup.exists():
                shutil.copymode(backup, tmp)
            os.replace(tmp, target)
        self.journal.write("file_written", path=str(target), sha256=sha256_bytes(content))
        return True


def backup_dir(journal: Journal, source: Path) -> Path | None:
    """Copy a whole directory into the run's backup area (factory reset)."""
    if not source.exists():
        return None
    dest = _backup_path(journal, source)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, dest, symlinks=True, dirs_exist_ok=True)
    else:
        shutil.copy2(source, dest)
    journal.write("dir_backup", path=str(source), backup=str(dest))
    return dest


def _valid_dconf_dump(text: str) -> bool:
    """A dconf keyfile dump: parseable sections (an empty dump is a valid empty database)."""
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    try:
        parser.read_string(text)
    except configparser.Error:
        return False
    return True


def _restore_dconf(runner: Runner, dump: Path) -> str:
    text = dump.read_text()
    if not _valid_dconf_dump(text):
        return f"FAILED dconf backup {dump} is not a valid dump; GNOME settings left untouched"
    before = dconf_user(runner, "dump", "/", mutating=False, check=False)
    dconf_user(runner, "reset", "-f", "/")
    try:
        dconf_user(runner, "load", "/", input=text)
    except Exception as exc:
        if before.ok:
            try:
                dconf_user(runner, "load", "/", input=before.stdout)
                return f"FAILED dconf load failed ({exc}); the settings from before the restore were put back"
            except Exception as exc2:
                return f"FAILED dconf load and its undo both failed ({exc2}); backup dump: {dump}"
        return f"FAILED dconf load failed ({exc}); the user database is empty, load {dump} by hand"
    return "restored GNOME settings (dconf) from the full backup"


def _restore_one(ev: dict, runner: Runner, display=None) -> str:
    if ev["event"] == "display_before":
        from fai_linop.display.actions import restore_layout   # the logic lives in display/
        return restore_layout(ev, display)
    if ev["event"] == "dir_backup":
        src, target = Path(ev["backup"]), Path(ev["path"])
        if src.is_dir():
            shutil.copytree(src, target, symlinks=True, dirs_exist_ok=True)
        elif src.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        return f"restored {target}" if src.exists() else f"MISSING BACKUP {target}"
    if ev["event"] == "dconf_backup":
        dump = Path(ev["path"])
        return _restore_dconf(runner, dump) if dump.exists() else f"MISSING BACKUP {dump}"
    target = Path(ev["path"])
    root = ev.get("root", False)
    if ev["existed"]:
        src = Path(ev["backup"])
        if not src.exists():
            return f"MISSING BACKUP {target}"
        if root:
            runner.run(["cp", "-a", str(src), str(target)], sudo=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
        return f"restored {target}"
    if root:
        runner.run(["rm", "-f", str(target)], sudo=True)
    elif target.exists():
        target.unlink()
    return f"removed {target} (did not exist before)"


RESTORABLE = ("file_backup", "dconf_backup", "dir_backup", "display_before")


def restore_files(journal: Journal, runner: Runner, display=None) -> list[str]:
    """Undo every file, dconf and monitor-layout change of a run, newest first.
    Every item is reported on its own and one failure never stops the rest. Failed
    items start with "FAILED" / "MISSING". The result is written to the journal.
    `display`: the GNOME display backend (default: the session's Mutter)."""
    report = []
    events = [ev for ev in journal.events() if ev["event"] in RESTORABLE]
    for ev in reversed(events):
        try:
            report.append(_restore_one(ev, runner, display))
        except Exception as exc:
            report.append(f"FAILED {ev.get('path', '?')}: {exc}")
    failed = sum(line.startswith(("FAILED", "MISSING")) for line in report)
    journal.write("rollback", items=len(events), failed=failed, ok=failed == 0)
    return report
