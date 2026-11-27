"""v3.0.0 O2: `dotfiles capture` shows diffs, asks once, writes byte-exact with
backup + journal and honours -n (1.2); the deploy plan shows the diff (1.11)."""

from __future__ import annotations

import argparse
import io
import logging
import shutil

from conftest import REPO
from rich.console import Console

from fai_linop.core.paths import Paths
from fai_linop.core.runner import FakeRunner
from fai_linop.core.ui import UI
from fai_linop.dotfiles import manager
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.recovery.journal import list_runs

ARCH = OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux")
TERMINATOR = manager.DOTFILES[0]
SOURCE = "configs/terminator/config"
TARGET = ".config/terminator/config"


def _setup(tmp_path, live: bytes | None = None, repo: bytes | None = None):
    """tmp_path is both the repo root and $HOME; only the terminator dotfile is enabled."""
    src = tmp_path / SOURCE
    src.parent.mkdir(parents=True)
    src.write_bytes(repo if repo is not None else (REPO / SOURCE).read_bytes())
    if live is not None:
        (tmp_path / TARGET).parent.mkdir(parents=True)
        (tmp_path / TARGET).write_bytes(live)
    profile = tmp_path / "p.toml"
    profile.write_text("[modules]\ndotfiles = true\nhyprland = false\n")
    return src, profile


def _app(tmp_path, profile, what="capture", answers=(), yes=False, dry=False):
    from fai_linop.cli import App
    args = argparse.Namespace(command="dotfiles", profile=profile, dry_run=dry, yes=yes, keep_going=False,
                              verbose=False, run_id=None, what=what)
    out = io.StringIO()
    feed = iter(answers)
    ui = UI(Console(file=out, width=200), input_fn=lambda _p: next(feed), assume_yes=yes, interactive=True)
    env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_STATE_HOME": str(tmp_path / "st")}
    app = App(args, ui=ui, runner=FakeRunner(dry_run=dry), paths=Paths.from_env(env), os_info=ARCH,
              repo_root=tmp_path)
    return app, out


def _snapshot(tmp_path):
    return {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


# ---- 1.2 capture -------------------------------------------------------------------------

def test_capture_dry_run_prints_the_diff_and_changes_no_file(tmp_path):
    src, profile = _setup(tmp_path, live=(REPO / SOURCE).read_bytes() + b"# local tweak\n")
    before = _snapshot(tmp_path)
    app, out = _app(tmp_path, profile, dry=True)
    assert app.cmd_dotfiles() == 0
    assert "+# local tweak" in out.getvalue() and "nothing written" in out.getvalue()
    assert _snapshot(tmp_path) == before                 # no repo write, no journal, no backup
    assert list_runs(app.paths.runs) == []


def test_capture_without_confirmation_writes_nothing(tmp_path):
    src, profile = _setup(tmp_path, live=b"live\n", repo=b"repo\n")
    before = _snapshot(tmp_path)
    app, out = _app(tmp_path, profile, answers=["n"])
    assert app.cmd_dotfiles() == 0
    assert "-repo" in out.getvalue() and "+live" in out.getvalue() and "Cancelled" in out.getvalue()
    assert _snapshot(tmp_path) == before
    assert list_runs(app.paths.runs) == []


def test_capture_writes_with_backup_in_the_journal(tmp_path):
    src, profile = _setup(tmp_path, live=b"live\n", repo=b"repo\n")
    app, out = _app(tmp_path, profile, answers=["y"])
    assert app.cmd_dotfiles() == 0
    assert src.read_bytes() == b"live\n"
    (run,) = list_runs(app.paths.runs)
    assert run.command == "dotfiles capture"
    backups = [ev for ev in run.events() if ev["event"] == "file_backup"]
    assert len(backups) == 1 and backups[0]["path"] == str(src) and backups[0]["existed"]
    assert (run.backup_dir / str(src.resolve()).lstrip("/")).read_bytes() == b"repo\n"


def test_capture_keeps_crlf_byte_for_byte(tmp_path):
    live = b"[global_config]\r\n  title_hide_sizetext = True\r\n# tweak\r\n"
    src, profile = _setup(tmp_path, live=live, repo=b"[global_config]\r\n  title_hide_sizetext = True\r\n")
    app, _ = _app(tmp_path, profile, yes=True)
    assert app.cmd_dotfiles() == 0
    assert src.read_bytes() == live


def test_capture_in_sync_asks_nothing_and_writes_nothing(tmp_path):
    src, profile = _setup(tmp_path, live=b"same\r\n", repo=b"same\r\n")
    app, out = _app(tmp_path, profile)          # no answers: a question would raise StopIteration
    assert app.cmd_dotfiles() == 0
    assert "Nothing to capture" in out.getvalue()
    assert list_runs(app.paths.runs) == []


def test_capture_hyprland_crlf_drops_the_generated_block(tmp_path):
    shutil.copytree(REPO / "configs", tmp_path / "configs")
    d = next(x for x in manager.DOTFILES if x.name == "hyprland")
    repo = (tmp_path / d.source).read_bytes().replace(b"\n", b"\r\n")
    (tmp_path / d.source).write_bytes(repo)
    block = ("# >>> FAI_LinOP monitors (generated) >>>\r\nmonitor=,preferred,auto,1\r\n"
             "# <<< FAI_LinOP monitors <<<\r\n").encode()
    live = block + repo.replace(b"kb_layout = us", b"kb_layout = tr")

    class Ctx:
        home, repo_root = tmp_path / "home", tmp_path
    (Ctx.home / d.target).parent.mkdir(parents=True)
    (Ctx.home / d.target).write_bytes(live)
    new = manager.captured(Ctx, d)
    assert b"FAI_LinOP monitors" not in new and b"kb_layout = tr" in new
    assert b"\n" not in new.replace(b"\r\n", b"")      # every line ending is still CRLF


# ---- 1.11 deploy plan shows the diff --------------------------------------------------------

def _ctx(tmp_path):
    from test_phase5 import ctx_for
    return ctx_for(tmp_path)


def test_deploy_plan_shows_diff_lines_of_a_different_file(tmp_path):
    ctx = _ctx(tmp_path)
    target = ctx.home / TARGET
    target.parent.mkdir(parents=True)
    target.write_text((REPO / SOURCE).read_text() + "# local tweak\n")
    (change,) = manager.DeployDotfile(TERMINATOR).plan(ctx)
    assert change.detail.startswith("update (backup kept)\n")
    assert "-# local tweak" in change.detail


def test_deploy_plan_has_no_diff_lines_when_the_file_is_equal_or_new(tmp_path):
    ctx = _ctx(tmp_path)
    (change,) = manager.DeployDotfile(TERMINATOR).plan(ctx)
    assert change.detail == "create"
    target = ctx.home / TARGET
    target.parent.mkdir(parents=True)
    target.write_bytes((REPO / SOURCE).read_bytes())
    assert manager.DeployDotfile(TERMINATOR).plan(ctx) == []


def test_deploy_plan_diff_is_shortened_and_shown_in_the_summary(tmp_path):
    from fai_linop.core.engine import Plan, PlannedAction, show_plan
    ctx = _ctx(tmp_path)
    target = ctx.home / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("[section]\n" + "".join(f"old line {i}\n" for i in range(40)))
    action = manager.DeployDotfile(TERMINATOR)
    action.module = "dotfiles"
    (change,) = action.plan(ctx)
    lines = change.detail.splitlines()
    assert len(lines) == 1 + manager.SHORT_DIFF_LINES + 1 and "more changed line" in lines[-1]
    show_plan(ctx, Plan([PlannedAction(action, [change])]))
    shown = ctx.ui.console.file.getvalue()
    assert "-[section]" in shown and "-old line 0" in shown       # markup escaped, not swallowed


def test_deploy_plan_full_diff_with_verbose(tmp_path, caplog):
    ctx = _ctx(tmp_path)
    target = ctx.home / TARGET
    target.parent.mkdir(parents=True)
    target.write_text("".join(f"old line {i}\n" for i in range(40)))
    with caplog.at_level(logging.DEBUG, logger="fai_linop"):
        (change,) = manager.DeployDotfile(TERMINATOR).plan(ctx)
    assert "more changed line" not in change.detail and "-old line 39" in change.detail
    assert "+++ repo:configs/terminator/config (rendered)" in caplog.text      # full diff in the log
