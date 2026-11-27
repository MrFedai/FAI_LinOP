"""v3.0.0 O1: `latest` names only real runs (1.1), root refusal per sub-command (1.12),
dry runs write no profile (1.3)."""

from __future__ import annotations

import argparse
import io
import os
from pathlib import Path

import pytest
from rich.console import Console

from fai_linop.core.action import Action, Change, clear_registry, register
from fai_linop.core.paths import Paths
from fai_linop.core.runner import FakeRunner
from fai_linop.core.ui import UI
from fai_linop.display.model import Mode, Monitor
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.recovery.journal import Journal, latest_real, list_runs

ARCH = OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux")


def _app(tmp_path, command, answers=(), yes=False, dry=False, run_id=None, what="show", runner=None):
    from fai_linop.cli import App
    args = argparse.Namespace(command=command, profile=None, dry_run=dry, yes=yes, keep_going=False,
                              verbose=False, run_id=run_id, what=what)
    out = io.StringIO()
    feed = iter(answers)
    ui = UI(Console(file=out, width=200), input_fn=lambda _p: next(feed), assume_yes=yes, interactive=True)
    env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_STATE_HOME": str(tmp_path / "st")}
    app = App(args, ui=ui, runner=runner or FakeRunner(dry_run=dry or command == "plan"),
              paths=Paths.from_env(env), os_info=ARCH, repo_root=tmp_path)
    return app, out


@pytest.fixture
def edit_module(tmp_path):
    """One registered action that rewrites `target` (a file with known original content)."""
    from fai_linop import modules
    modules.load()          # import the real modules now, so run_profile's load() registers nothing
    clear_registry()
    target = tmp_path / "home.conf"
    target.write_text("original\n")

    class Edit(Action):
        id, title = "edit", "edit home.conf"

        def plan(self, ctx):
            return [] if target.read_text() == "linop\n" else [Change("file", str(target))]

        def apply(self, ctx):
            ctx.files.write(target, b"linop\n")

        def verify(self, ctx):
            return target.read_text() == "linop\n"

    register("dotfiles", "Dotfiles")(lambda ctx: [Edit()])
    yield target
    clear_registry()


# ---- 1.1 journal `latest` ---------------------------------------------------------------

def test_apply_then_plan_then_rollback_restores_the_real_run(tmp_path, edit_module):
    target = edit_module
    app, _ = _app(tmp_path, "apply", answers=["y"])
    assert app.cmd_apply() == 0 and target.read_text() == "linop\n"
    applied = latest_real(app.paths.runs).run_id
    app, _ = _app(tmp_path, "plan")
    assert app.cmd_plan() == 0
    assert (app.paths.runs / "latest").read_text().strip() == applied      # the dry run did not move it
    app, out = _app(tmp_path, "rollback", answers=["y"])
    assert app.cmd_rollback() == 0 and target.read_text() == "original\n"
    assert applied in out.getvalue()


def test_dry_run_journal_is_marked_and_never_latest(tmp_path):
    runs = tmp_path / "runs"
    Journal.create(runs, run_id="r1", command="apply", dry_run=False)
    dry = Journal.create(runs, run_id="r2", command="apply", dry_run=True)
    assert dry.dry_run and not dry.changes_machine()
    assert (runs / "latest").read_text().strip() == "r1" and Journal.open(runs).run_id == "r1"


def test_stale_latest_pointing_at_a_dry_run_is_ignored(tmp_path):
    runs = tmp_path / "runs"
    Journal.create(runs, run_id="r1", command="apply", dry_run=False)
    Journal.create(runs, run_id="r2", command="display")      # an older FAI_LinOP moved `latest` here
    (runs / "latest").write_text("r2\n")
    assert Journal.open(runs).run_id == "r1"


def test_plan_then_resume_plans_the_actions_again(tmp_path, edit_module):
    target = edit_module
    app, _ = _app(tmp_path, "plan")
    assert app.cmd_plan() == 0 and target.read_text() == "original\n"
    app, out = _app(tmp_path, "resume")
    assert app.cmd_resume() == 2 and "No previous run" in out.getvalue()   # a dry run is nothing to resume
    # an interrupted real run followed by a plan: resume continues the real run, not the plan
    runs = app.paths.runs
    Journal.create(runs, run_id="00-real", command="apply", profile="p", dry_run=False)
    app, _ = _app(tmp_path, "plan")
    assert app.cmd_plan() == 0
    app, out = _app(tmp_path, "resume", answers=["y"])
    assert app.cmd_resume() == 0 and "nothing to do" not in out.getvalue().lower()
    assert "Resuming run 00-real" in out.getvalue() and target.read_text() == "linop\n"


def test_resume_never_takes_done_from_a_dry_journal(tmp_path, edit_module):
    target = edit_module
    app, _ = _app(tmp_path, "plan")
    assert app.cmd_plan() == 0
    dry = [j for j in list_runs(app.paths.runs) if j.dry_run][0]
    assert any(v == "done" for v in dry.action_status().values())       # the dry run "did" the action
    app, _ = _app(tmp_path, "apply", answers=["y"])
    assert app.run_profile(app.load_profile(), resume_from=dry) == 0
    assert target.read_text() == "linop\n"


def test_runs_lists_only_apply_reset_and_rollback_runs(tmp_path, edit_module):
    app, _ = _app(tmp_path, "apply", answers=["y"])
    assert app.cmd_apply() == 0
    app, _ = _app(tmp_path, "plan")
    assert app.cmd_plan() == 0
    Journal.create(app.paths.runs, latest=False, command="dotfiles capture")
    Journal.create(app.paths.runs, command="reset", dry_run=True)
    app, _ = _app(tmp_path, "rollback", answers=["y"])
    assert app.cmd_rollback() == 0
    app, out = _app(tmp_path, "runs")
    assert app.cmd_runs() == 0
    text = out.getvalue()
    assert "apply" in text and "rollback of" in text and "finished" in text
    assert "dotfiles" not in text and "reset" not in text and text.count("finished") == 2


def test_rollback_refuses_a_dry_journal_even_by_id(tmp_path, edit_module):
    app, _ = _app(tmp_path, "plan")
    assert app.cmd_plan() == 0
    dry = list_runs(app.paths.runs)[0]
    app, out = _app(tmp_path, "rollback", answers=["y"], run_id=dry.run_id)
    assert app.cmd_rollback() == 2 and "dry run" in out.getvalue()
    app, out = _app(tmp_path, "rollback", answers=["y"])               # no real run at all
    assert app.cmd_rollback() == 2


def test_rollback_does_not_run_dconf_reset_from_a_dry_reset(tmp_path):
    runs = Paths.from_env({"HOME": str(tmp_path), "XDG_STATE_HOME": str(tmp_path / "st")}).runs
    dry = Journal.create(runs, command="reset", dry_run=True)
    dump = dry.backup_dir / "dconf-full.ini"
    dump.parent.mkdir(parents=True)
    dump.write_text("[org]\n")
    dry.write("dconf_backup", path=str(dump))
    runner = FakeRunner()
    app, _ = _app(tmp_path, "rollback", answers=["y"], run_id=dry.run_id, runner=runner)
    assert app.cmd_rollback() == 2 and runner.calls == []


# ---- 1.12 root refusal per sub-command ------------------------------------------------

@pytest.mark.parametrize("argv", [["profile", "init"], ["display", "capture"], ["plan"], ["dotfiles", "capture"]])
def test_root_is_refused_for_commands_that_write(monkeypatch, capsys, argv):
    import fai_linop.cli as cli
    monkeypatch.setattr(cli, "_is_root", lambda: True)
    monkeypatch.delenv("LINOP_ALLOW_ROOT", raising=False)
    monkeypatch.setattr(cli, "App", lambda *_a, **_k: pytest.fail("must not start"))
    assert cli.main(argv) == 2
    assert "normal user" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["doctor"], ["runs"], ["profile", "show"], ["profile", "path"],
                                  ["display", "show"], ["dotfiles", "diff"]])
def test_root_may_run_read_only_commands(argv):
    from fai_linop.cli import _is_read_only, _parser
    assert _is_read_only(_parser().parse_args(argv))


def test_doctor_creates_no_file(tmp_path):
    app, _ = _app(tmp_path, "doctor")
    before = sorted(tmp_path.rglob("*"))
    assert app.cmd_doctor() == 0
    assert sorted(tmp_path.rglob("*")) == before


class _Backend:
    def read(self):
        mode = Mode(1920, 1080, 60.0, "a")
        return 1, [Monitor("HDMI-A-1", "SAM", "Odyssey", "H1", (mode,), mode)], \
            [{"x": 0, "y": 0, "scale": 1.0, "primary": True, "connectors": ["HDMI-A-1"]}]


def test_display_show_opens_no_journal(tmp_path, monkeypatch):
    import fai_linop.display.actions as actions
    monkeypatch.setattr(actions, "gnome_backend", lambda ctx: _Backend())
    app, out = _app(tmp_path, "display", what="show")
    assert app.cmd_display() == 0 and "SAM Odyssey H1" in out.getvalue()
    assert not app.paths.state.exists()


# ---- 1.3 dry runs write no profile ------------------------------------------------------

def _profile_with_mtime(app):
    path = app.profile_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('[wallpaper]\nmode = "none"\n')
    os.utime(path, (1_000_000_000, 1_000_000_000))
    return path, path.read_bytes(), path.stat().st_mtime_ns


def test_wizard_dry_run_does_not_save_the_profile(tmp_path, monkeypatch):
    import fai_linop.cli as cli

    def answer(profile, ui):
        profile.set("display", "prefer", "refresh")
        return profile

    monkeypatch.setattr(cli, "run_wizard", answer)
    app, out = _app(tmp_path, "wizard", dry=True)
    path, content, mtime = _profile_with_mtime(app)
    assert app.cmd_wizard() == 0
    assert path.read_bytes() == content and path.stat().st_mtime_ns == mtime
    assert "would save" in out.getvalue()
    app, _ = _app(tmp_path, "wizard")                                   # a real run still saves
    assert app.cmd_wizard() == 0 and 'prefer = "refresh"' in path.read_text()


def test_display_capture_dry_run_does_not_save_the_profile(tmp_path, monkeypatch):
    import fai_linop.display.actions as actions
    monkeypatch.setattr(actions, "gnome_backend", lambda ctx: _Backend())
    app, out = _app(tmp_path, "display", what="capture", dry=True)
    path, content, mtime = _profile_with_mtime(app)
    assert app.cmd_display() == 0
    assert path.read_bytes() == content and path.stat().st_mtime_ns == mtime
    assert "would save" in out.getvalue() and not app.paths.state.exists()


def test_profile_init_dry_run_creates_nothing(tmp_path):
    app, out = _app(tmp_path, "profile", what="init", dry=True)
    assert app.cmd_profile() == 0 and not app.profile_path.exists() and "would create" in out.getvalue()
