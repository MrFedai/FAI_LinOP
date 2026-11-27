"""V300 list items 1.5 (planning errors are failures) and 1.6 (dry run never needs the tools)."""

from __future__ import annotations

import argparse
import io
import json

import pytest
from rich.console import Console

from fai_linop.core.action import Action, Change, clear_registry, register
from fai_linop.core.engine import build_plan
from fai_linop.core.paths import Paths
from fai_linop.core.profile import Profile
from fai_linop.core.runner import CommandError, FakeRunner, Result
from fai_linop.core.ui import UI
from fai_linop.platform.detect import Family, OSInfo, Tier

ARCH = OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux")


def _app(tmp_path, command="apply", yes=True, runner=None):
    from fai_linop.cli import App
    args = argparse.Namespace(command=command, profile=None, dry_run=command == "plan", yes=yes,
                              keep_going=False, verbose=False, run_id=None, what="show")
    out = io.StringIO()
    ui = UI(Console(file=out, width=200), input_fn=lambda _p: "", assume_yes=yes, interactive=True)
    env = {"HOME": str(tmp_path), "XDG_CONFIG_HOME": str(tmp_path / "cfg"), "XDG_STATE_HOME": str(tmp_path / "st")}
    app = App(args, ui=ui, runner=runner or FakeRunner(dry_run=command == "plan"),
              paths=Paths.from_env(env), os_info=ARCH, repo_root=tmp_path)
    return app, out


def _boom(exc):
    class Boom(Action):
        id, title = "boom", "exploding action"

        def plan(self, ctx):
            raise exc

        def apply(self, ctx):  # pragma: no cover - never reached
            raise AssertionError("must not apply")

    return Boom


@pytest.fixture
def registry():
    from fai_linop import modules
    modules.load()
    clear_registry()
    yield
    clear_registry()


@pytest.mark.parametrize("exc", [
    OSError("disk on fire"),
    KeyError("missing-key"),
    CommandError(Result(("tool", "x"), 3, "", "bad things")),
])
def test_planning_error_is_a_failure_with_nonzero_exit(tmp_path, registry, exc):
    register("dotfiles", "Dotfiles")(lambda ctx: [_boom(exc)()])
    app, out = _app(tmp_path)
    assert app.run_profile(Profile.load_or_default(app.profile_path)) == 1
    text = out.getvalue()
    assert "boom" in text and type(exc).__name__ in text
    assert "Nothing to do" not in text
    run_dir = next(d for d in app.paths.runs.iterdir() if d.is_dir() and not d.is_symlink())
    events = [json.loads(line) for line in (run_dir / "journal.jsonl").read_text().splitlines()]
    assert any(e.get("status") == "failed" and e.get("id") == "boom" for e in events)
    assert events[-1]["event"] == "run_end"


def test_dry_run_of_security_and_terminal_without_tools_has_no_failed_rows(tmp_path):
    from fai_linop import modules
    modules.load()
    profile = Profile.load_or_default(tmp_path / "none.toml")
    profile.set("security", "usbguard", True)
    profile.set("shell", "name", "bash")
    profile.set("shell", "starship_preset", "tokyo-night")
    profile.set("modules", "blackarch", True)
    profile.set("modules", "security", True)
    profile.set("modules", "shell", True)
    # every tool is "missing": all probes answer 127
    runner = FakeRunner(dry_run=True).on("systemctl", result=Result((), 127, "", "not found")) \
        .on("curl", result=Result((), 127, "", "curl: command not found")) \
        .on("usbguard", result=Result((), 127, "", "usbguard: command not found")) \
        .on("starship", result=Result((), 127, "", "starship: command not found"))
    app, out = _app(tmp_path, "plan", runner=runner)
    ctx = app.read_only_context(profile)
    ctx.facts["usbguard_confirmed"] = True
    ctx.facts["blackarch_confirmed"] = True
    from fai_linop.package.resolve import Resolution
    ctx.facts["packages"] = Resolution(native=["starship"])  # preset is planned only when starship is (to be) installed
    from fai_linop.security.actions import BlackArchRepo, UsbGuard
    from fai_linop.terminal.actions import StarshipPreset
    plan = build_plan(ctx, [UsbGuard(), StarshipPreset(), BlackArchRepo()])
    assert [p for p in plan.items if p.status == "failed"] == []
    ids = {p.action.id for p in plan.items if p.changes}
    assert {"security.usbguard", "shell.starship-preset", "blackarch.repo"} <= ids
    # apply() in dry run records "would run" instead of probing missing tools
    for p in plan.items:
        if p.action.id in ("security.usbguard", "shell.starship-preset", "blackarch.repo"):
            p.action.apply(ctx)
    assert not any(c[:1] == ("curl",) for c in runner.calls)
