"""`linop` command line.

    linop                 wizard → plan → one confirmation → apply  (the v2.5 flow, D14)
    linop plan            show what would change (dry run)
    linop apply           apply the saved profile without the wizard
    linop wizard          only (re)answer the questions and save the profile
    linop resume          continue the last real apply run
    linop rollback [RUN]  restore files changed by a real apply / reset run (default: the last one;
                          packages are never "rolled back" silently)
    linop runs            list previous apply / reset / rollback runs (dry runs are not listed)
    linop profile show|path|validate
    linop doctor          what FAI_LinOP detects on this machine
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from fai_linop import __version__
from fai_linop.core.action import Context
from fai_linop.core.engine import build_plan, collect_actions, execute, report, show_plan
from fai_linop.core.log import setup_file_logging
from fai_linop.core.paths import Paths
from fai_linop.core.profile import Profile, ProfileError
from fai_linop.core.runner import DryRunRunner, Runner, SystemRunner
from fai_linop.core.ui import UI
from fai_linop.core.wizard import run_wizard
from fai_linop.platform.detect import OSInfo, Tier, detect
from fai_linop.recovery import snapshot
from fai_linop.recovery.backup import FileChanger, restore_files
from fai_linop.recovery.journal import DONE, FAILED, Journal, NullJournal, list_runs

REPO_ROOT = Path(__file__).resolve().parents[1]
EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_UNSUPPORTED = 0, 1, 2, 3


EPILOG = """without a command: wizard -> plan -> one confirmation -> apply (the v2.5 flow)

examples:
  linop plan                                   what would change (dry run)
  linop --profile profiles/mrfedai.toml        the owner's setup
  linop display capture                        save the current monitor layout
  linop rollback                               undo the file changes of the last run
"""


def _common(defaults: bool) -> argparse.ArgumentParser:
    """Global options, accepted before or after the command."""
    d = (lambda v: v) if defaults else (lambda v: argparse.SUPPRESS)
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--profile", type=Path, default=d(None),
                   help="profile TOML (default: ~/.config/linop/profile.toml)")
    p.add_argument("-n", "--dry-run", action="store_true", default=d(False),
                   help="show and journal changes without making them (writes no profile)")
    p.add_argument("-y", "--yes", action="store_true", default=d(False),
                   help="answer yes to normal confirmations (never to typed ones)")
    p.add_argument("--keep-going", action="store_true", default=d(False),
                   help="continue with other actions after a failure")
    p.add_argument("-v", "--verbose", action="store_true", default=d(False))
    return p


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="linop", description="FAI_LinOP — system setup and configuration toolkit",
                                epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter,
                                parents=[_common(True)])
    p.add_argument("--version", action="version", version=f"linop {__version__}")
    sub = p.add_subparsers(dest="command", metavar="command")
    common = [_common(False)]
    sub.add_parser("plan", parents=common, help="dry run: show what would change")
    sub.add_parser("apply", parents=common, help="apply the saved profile")
    sub.add_parser("wizard", parents=common, help="answer the questions and save the profile")
    sub.add_parser("resume", parents=common, help="continue the latest unfinished run")
    rb = sub.add_parser("rollback", parents=common, help="restore files changed by a run")
    rb.add_argument("run_id", nargs="?")
    sub.add_parser("runs", parents=common, help="list previous runs")
    pr = sub.add_parser("profile", parents=common, help="show / validate / create the profile")
    pr.add_argument("what", choices=("show", "path", "validate", "init"))
    sub.add_parser("doctor", parents=common, help="show detected platform, hardware and recovery options")
    dp = sub.add_parser("display", parents=common, help="show monitors / save the current layout to the profile")
    dp.add_argument("what", choices=("show", "capture"))
    df = sub.add_parser("dotfiles", parents=common, help="diff deployed dotfiles / capture them back into the repo")
    df.add_argument("what", choices=("diff", "capture"))
    rs = sub.add_parser("reset", parents=common, help="Smart Factory Reset (backup first, typed confirmation)")
    rs.add_argument("--uninstall", action="store_true", help="also uninstall packages FAI_LinOP installs")
    rs.add_argument("--gnome", action="store_true", help="also reset all GNOME settings")
    return p


class App:
    def __init__(self, args: argparse.Namespace, ui: UI | None = None, runner: Runner | None = None,
                 paths: Paths | None = None, os_info: OSInfo | None = None, repo_root: Path = REPO_ROOT):
        self.args = args
        self.ui = ui or UI(assume_yes=args.yes)
        self.paths = paths or Paths.from_env()
        self.os = os_info or detect()
        self.repo_root = repo_root
        dry = args.dry_run or args.command == "plan"
        self.runner: Runner = runner or (DryRunRunner() if dry else SystemRunner())
        self.profile_path = args.profile or self.paths.profile

    # ---- helpers ----------------------------------------------------------------
    def load_profile(self) -> Profile:
        return Profile.load_or_default(self.profile_path)

    def context(self, profile: Profile, journal: Journal) -> Context:
        return Context(runner=self.runner, profile=profile, os=self.os, journal=journal,
                       files=FileChanger(journal, self.runner), ui=self.ui,
                       repo_root=self.repo_root, home=self.paths.home)

    def read_only_context(self, profile: Profile) -> Context:
        """Context for commands that change nothing: no journal file is created
        and any file write an action might attempt is only planned."""
        journal = NullJournal()
        return Context(runner=self.runner, profile=profile, os=self.os, journal=journal,
                       files=FileChanger(journal, DryRunRunner(probe=self.runner)), ui=self.ui,
                       repo_root=self.repo_root, home=self.paths.home)

    def save_profile(self, profile: Profile, what: str = "Profile") -> None:
        """Save the profile — except in a dry run, which writes no file (1.3)."""
        if self.runner.dry_run:
            self.ui.info(f"would save {what.lower()} to {self.profile_path} (dry run, nothing written)")
            return
        path = profile.save(self.profile_path)
        self.ui.ok(f"{what} saved: {path}")

    def guard_platform(self) -> int | None:
        if self.os.tier is Tier.STUB:
            self.ui.error(f"{self.os.name}: FAI_LinOP v3.0 ships interfaces only for this platform — nothing is applied.")
            return EXIT_UNSUPPORTED
        if self.os.tier is Tier.UNSUPPORTED:
            self.ui.error(f"{self.os.name} ({self.os.id or 'unknown'}) is not supported. Supported: Arch, Debian, Ubuntu, Fedora.")
            return EXIT_UNSUPPORTED
        if self.os.tier is Tier.EXPERIMENTAL:
            self.ui.warn(f"{self.os.name} is treated as {self.os.family.value} (experimental, not tested).")
        return None

    # ---- the run ----------------------------------------------------------------
    def run_profile(self, profile: Profile, resume_from: Journal | None = None) -> int:
        blocked = self.guard_platform()
        if blocked is not None:
            return blocked
        done: set[str] = set()
        if resume_from is not None and not resume_from.dry_run:   # a dry run marked nothing as really done
            done = {k for k, v in resume_from.action_status().items() if v == DONE}
        journal = Journal.create(self.paths.runs, command="apply", profile=str(profile.path),
                                 dry_run=self.runner.dry_run, os=self.os.id,
                                 resumed_from=resume_from.run_id if resume_from else None)
        setup_file_logging(journal.run_dir / "linop.log", self.args.verbose)
        ctx = self.context(profile, journal)
        from fai_linop import modules
        modules.load()
        plan = build_plan(ctx, collect_actions(ctx), done)
        show_plan(ctx, plan)
        planning_failed = [p for p in plan.items if p.status == "failed"]
        if not plan.pending:
            if planning_failed:
                for p in planning_failed:
                    journal.write("action", id=p.action.id, status=FAILED, error=p.message)
                journal.write("run_end", summary={"failed": len(planning_failed), "planning_failed": True})
                return EXIT_FAILED
            journal.write("run_end", summary={"nothing_to_do": True})
            return EXIT_OK
        if not self.runner.dry_run:
            if not self.ui.interactive and not self.args.yes:
                self.ui.error("non-interactive run: pass --yes to apply the plan above")
                journal.write("run_end", summary={"cancelled": "non-interactive without --yes"})
                return EXIT_USAGE
            if not self.ui.confirm("Apply these changes?", default=False):
                self.ui.info("Cancelled — nothing was changed.")
                journal.write("run_end", summary={"cancelled": True})
                return EXIT_OK
            from fai_linop.core import preflight
            if not preflight.run(self.os, self.runner, self.ui, needs_network=True, dry_run=False,
                                 speedtest=profile.get("system", "speedtest")):
                self.ui.error("Preflight checks failed — nothing was changed.")
                journal.write("run_end", summary={"preflight": "failed"})
                return EXIT_FAILED
            provider = snapshot.detect(self.runner)
            if provider:
                ok = provider.create(self.runner, f"linop {journal.run_id}")
                journal.write("snapshot", provider=provider.name, ok=ok)
                (self.ui.ok if ok else self.ui.warn)(f"{provider.name} snapshot {'created' if ok else 'FAILED'}")
            else:
                journal.write("snapshot", provider=None)
                self.ui.info("No filesystem snapshot tool configured — changed files are backed up individually.")
        execute(ctx, plan, keep_going=self.args.keep_going)
        code = report(ctx, plan)
        if not self.runner.dry_run and any(p.action.reboot and p.status == "done" for p in plan.items) \
                and self.ui.interactive and not self.args.yes and self.ui.confirm("Reboot now?", default=False):
            self.runner.run(["systemctl", "reboot"], sudo=True)
        return code

    # ---- commands ---------------------------------------------------------------
    def cmd_default(self) -> int:
        profile = run_wizard(self.load_profile(), self.ui)
        self.save_profile(profile)
        return self.run_profile(profile)

    def cmd_plan(self) -> int:
        return self.run_profile(self.load_profile())

    cmd_apply = cmd_plan

    def cmd_wizard(self) -> int:
        profile = run_wizard(self.load_profile(), self.ui)
        self.save_profile(profile)
        return EXIT_OK

    def cmd_resume(self) -> int:
        try:
            previous = Journal.open(self.paths.runs)
        except FileNotFoundError:
            self.ui.error("No previous run to resume.")
            return EXIT_USAGE
        if previous.command not in ("apply", None):
            self.ui.error(f"The last run {previous.run_id} was a {previous.command}; resume continues apply runs only.")
            return EXIT_USAGE
        self.ui.info(f"Resuming run {previous.run_id}")
        return self.run_profile(self.load_profile(), resume_from=previous)

    def cmd_rollback(self) -> int:
        try:
            journal = Journal.open(self.paths.runs, self.args.run_id)
        except FileNotFoundError as exc:
            self.ui.error(str(exc))
            return EXIT_USAGE
        if not journal.changes_machine():
            kind = "a dry run" if journal.dry_run else f"a {journal.command or 'unknown'} run"
            self.ui.error(f"Run {journal.run_id} is {kind} — it changed nothing, so there is nothing to roll back. "
                          "Only real apply / reset runs can be rolled back (see `linop runs`).")
            return EXIT_USAGE
        if not self.ui.confirm(f"Restore all files changed by run {journal.run_id}?", default=False):
            return EXIT_OK
        if self.runner.dry_run:
            for ev in journal.events():
                if ev["event"] == "file_backup":
                    self.ui.info(f"would restore {ev['path']}" if ev["existed"] else f"would remove {ev['path']}")
                elif ev["event"] in ("dconf_backup", "dir_backup"):
                    self.ui.info(f"would restore {ev['path']}")
            return EXIT_OK
        # the rollback is a run of its own (listed by `linop runs`) but never becomes `latest`
        record = Journal.create(self.paths.runs, latest=False, command="rollback", target=journal.run_id)
        lines = restore_files(journal, self.runner)
        failed = 0
        for line in lines:
            bad = line.startswith(("FAILED", "MISSING"))
            failed += bad
            (self.ui.error if bad else self.ui.info)(line)
            record.write("restored", line=line, ok=not bad)
        record.write("run_end", summary={"restored": len(lines) - failed, "failed": failed, "target": journal.run_id})
        if failed:
            self.ui.error(f"{failed} item(s) could NOT be restored; the rest were. Details: {record.path}")
        self.ui.warn("Installed packages and started services are NOT reverted automatically; "
                      f"see {journal.path} for the list.")
        return EXIT_FAILED if failed else EXIT_OK

    def cmd_runs(self) -> int:
        rows = []
        for j in list_runs(self.paths.runs):
            command = j.command
            if j.dry_run or command not in ("apply", "reset", "rollback"):
                continue   # dry runs and read-only commands are not runs of the machine
            status = j.action_status()
            what = f"rollback of {j.meta().get('target', '?')}" if command == "rollback" else command
            rows.append((j.run_id, what, j.state(),
                         sum(v == DONE for v in status.values()), sum(v == "failed" for v in status.values())))
        if not rows:
            self.ui.info("No runs yet.")
        else:
            self.ui.table("Runs", ("Run", "Command", "State", "Done", "Failed"), rows)
        return EXIT_OK

    def cmd_profile(self) -> int:
        if self.args.what == "path":
            self.ui.console.print(str(self.profile_path), highlight=False, markup=False)
            return EXIT_OK
        if self.args.what == "init":
            if self.profile_path.exists():
                self.ui.error(f"{self.profile_path} already exists — not overwritten")
                return EXIT_USAGE
            if self.runner.dry_run:
                self.ui.info(f"would create {self.profile_path} (dry run, nothing written)")
                return EXIT_OK
            template = Path(__file__).resolve().parent / "data" / "profile.template.toml"
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            self.profile_path.write_text(template.read_text())
            self.ui.ok(f"Profile created: {self.profile_path} (every key documented; edit, then `linop plan`)")
            return EXIT_OK
        profile = self.load_profile()
        if self.args.what == "validate":
            self.ui.ok(f"{self.profile_path}: valid")
            return EXIT_OK
        import tomlkit
        self.ui.console.print(tomlkit.dumps(profile.as_dict()), highlight=False, markup=False)
        return EXIT_OK

    def cmd_dotfiles(self) -> int:
        from fai_linop.dotfiles.manager import DOTFILES, capture_diff, captured, diff
        profile = self.load_profile()
        ctx = self.read_only_context(profile)      # computing diffs writes nothing
        wanted = [d for d in DOTFILES if profile.enabled(d.module)]
        if self.args.what == "diff":
            for d in wanted:
                text = diff(ctx, d)
                self.ui.console.print(text or f"{d.target}: in sync", markup=False, highlight=False)
            return EXIT_OK
        # capture (1.2, D10): every file's diff first, one confirmation, then
        # byte-exact writes through FileChanger (backup + journal); -n stops after the diffs.
        changes = []
        for d in wanted:
            new = captured(ctx, d)
            if new is None:
                live = "in sync with " + d.source if (ctx.home / d.target).exists() else "not deployed"
                self.ui.info(f"~/{d.target}: {live} — nothing to capture")
                continue
            self.ui.console.print(capture_diff(ctx, d, new), markup=False, highlight=False)
            changes.append((d, new))
        if not changes:
            self.ui.ok("Nothing to capture — the repo already matches the live files.")
            return EXIT_OK
        if self.runner.dry_run:
            self.ui.info(f"dry run: {len(changes)} file(s) would be captured into the repo — nothing written.")
            return EXIT_OK
        if not self.ui.confirm(f"Write these {len(changes)} file(s) into the repo (old versions backed up)?"):
            self.ui.info("Cancelled — nothing was changed.")
            return EXIT_OK
        journal = Journal.create(self.paths.runs, latest=False, command="dotfiles capture")
        ctx = self.context(profile, journal)
        for d, new in changes:
            ctx.files.write(self.repo_root / d.source, new)
            self.ui.ok(f"captured ~/{d.target} -> {d.source}")
        journal.write("run_end", summary={"captured": [d.source for d, _ in changes]})
        self.ui.info(f"Old repo files backed up under {journal.backup_dir} (journal: {journal.path}).")
        self.ui.info("GNOME settings are captured with `dconf dump` by hand for now; review with git diff.")
        self.ui.warn("tests/golden/sources.sha256 will fail until you approve the new files (by design, D8).")
        return EXIT_OK

    def cmd_reset(self) -> int:
        from fai_linop.recovery.reset import reset_actions
        blocked = self.guard_platform()
        if blocked is not None:
            return blocked
        journal = Journal.create(self.paths.runs, command="reset", dry_run=self.runner.dry_run)  # real: latest
        setup_file_logging(journal.run_dir / "linop.log", self.args.verbose)
        ctx = self.context(self.load_profile(), journal)
        plan = build_plan(ctx, reset_actions(self.args.uninstall, self.args.gnome))
        show_plan(ctx, plan)
        if not plan.pending:
            return EXIT_OK
        if not self.runner.dry_run and not self.ui.typed_confirm(
                "SMART FACTORY RESET — files and GNOME settings are backed up first; `linop rollback` restores them."
                + (" Packages removed by --uninstall are NOT reinstalled by rollback." if self.args.uninstall else ""),
                "CLEAN"):
            self.ui.info("Cancelled — nothing was changed.")
            journal.write("run_end", summary={"cancelled": True})
            return EXIT_OK
        execute(ctx, plan, keep_going=True)
        return report(ctx, plan)

    def cmd_display(self) -> int:
        from fai_linop.display.actions import gnome_backend, targets_for
        from fai_linop.display.model import placement_to_profile
        ctx = self.read_only_context(self.load_profile())   # reads Mutter's state; only the profile is written
        backend = gnome_backend(ctx)
        if backend is None:
            self.ui.error("No GNOME session (run this from your desktop session, not over SSH/TTY).")
            return EXIT_USAGE
        _, monitors, logical = backend.read()
        targets = targets_for(ctx, monitors, logical)
        self.ui.table("Monitors", ("Identity", "Connector", "Current", "Best", "Position", "Scale", "Primary"), [
            (t.monitor.identity, t.monitor.connector, t.monitor.current.label() if t.monitor.current else "off",
             t.mode.label(), f"{t.placement.x},{t.placement.y}", f"{t.placement.scale:g}",
             "yes" if t.placement.primary else "") for t in targets])
        if self.args.what == "capture":
            from fai_linop.display.model import placements_from_state
            profile = self.load_profile()
            profile.set("display", "monitor", [placement_to_profile(p) for p in placements_from_state(monitors, logical)])
            self.save_profile(profile, "Current monitor layout")
        return EXIT_OK

    def cmd_doctor(self) -> int:
        provider = snapshot.detect(self.runner) if self.os.is_linux else None
        hw_rows = []
        if self.os.is_linux:
            from fai_linop.hardware.linux import detect as detect_hw
            hw = detect_hw(self.runner)
            gpus = ", ".join(f"{g.vendor}:{g.device_id:04x}{' (open modules ok)' if g.nvidia_open_capable else ''}"
                             for g in hw.gpus) or "none"
            hw_rows = [("GPU", gpus), ("CPU", hw.cpu_vendor), ("RAM", f"{hw.ram_mb} MiB"),
                       ("Root disk", {True: "HDD", False: "SSD/NVMe", None: "unknown"}[hw.root_rotational]),
                       ("Kernels", ", ".join(hw.kernels) or "unknown"), ("Virtualization", hw.virtualization)]
        self.ui.table("FAI_LinOP doctor", ("Item", "Value"), [
            ("FAI_LinOP", __version__),
            ("OS", f"{self.os.name} (id={self.os.id or '-'}, family={self.os.family.value})"),
            ("Support tier", self.os.tier.value),
            *hw_rows,
            ("Profile", str(self.profile_path)),
            ("State dir", str(self.paths.state)),
            ("Snapshot tool", provider.name if provider else "none (per-file backups)"),
        ])
        return EXIT_OK


# Commands (or command + sub-command) that write no file at all — journal,
# log or profile — and may therefore run as root. Everything else that
# writes (`profile init`, `display capture`, `plan`'s dry journal, ...)
# would leave root-owned files in the user's home (D15).
READ_ONLY_COMMANDS = {("doctor", None), ("runs", None), ("profile", "show"), ("profile", "path"),
                      ("profile", "validate"), ("display", "show"), ("dotfiles", "diff")}


def _is_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _is_read_only(args: argparse.Namespace) -> bool:
    return (args.command, getattr(args, "what", None)) in READ_ONLY_COMMANDS


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if _is_root() and os.environ.get("LINOP_ALLOW_ROOT") != "1" and not _is_read_only(args):
        print("linop: do not run FAI_LinOP as root — run it as your normal user; it asks for sudo "
              "only for the commands that need it (D15).", file=sys.stderr)
        return EXIT_USAGE
    app = App(args)
    try:
        handler = getattr(app, f"cmd_{args.command or 'default'}")
        return handler()
    except ProfileError as exc:
        app.ui.error(str(exc))
        return EXIT_USAGE
    except KeyboardInterrupt:
        app.ui.warn("Interrupted — continue later with: linop resume")
        return 130
