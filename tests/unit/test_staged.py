"""The staged run (D30): `linop` asks, shows and applies ONE module at a time."""

from __future__ import annotations

import argparse
import io
import logging

import pytest
from rich.console import Console

from fai_linop.core import preflight
from fai_linop.core.action import Action, Change, Reversible, clear_registry, register
from fai_linop.core.paths import Paths
from fai_linop.core.profile import SCHEMA, Profile
from fai_linop.core.runner import FakeRunner
from fai_linop.core.ui import UI
from fai_linop.core.wizard import QUESTIONS, Wizard
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.recovery.journal import Journal

ARCH = OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux")


class Touch(Action):
    def __init__(self, id, path, fail=False, requires=(), reversible=Reversible.YES):
        self.id, self.title, self.path, self.fail = id, f"touch {path.name}", path, fail
        self.requires, self.reversible = requires, reversible

    def plan(self, ctx):
        return [] if self.path.exists() else [Change("file", str(self.path))]

    def apply(self, ctx):
        if self.fail:
            raise RuntimeError("boom")
        ctx.files.write(self.path, b"x")

    def verify(self, ctx):
        return self.path.exists()


class Session:
    """A fake terminal: scripted answers, every prompt recorded with what existed at that moment."""

    def __init__(self, tmp_path, answers, watch=()):
        self.tmp, self.answers, self.watch = tmp_path, iter(answers), watch
        self.prompts: list[tuple[str, list[str]]] = []
        self.out = io.StringIO()

    def _input(self, prompt):
        self.prompts.append((prompt, [p.name for p in self.watch if p.exists()]))
        return next(self.answers)

    def app(self, command="default", yes=False, dry=False, interactive=True, verbose=False):
        from fai_linop.cli import App
        args = argparse.Namespace(command=command, profile=None, dry_run=dry, yes=yes, keep_going=False,
                                  verbose=verbose, run_id=None, what="show")
        ui = UI(Console(file=self.out, width=200), input_fn=self._input, assume_yes=yes, interactive=interactive,
                verbose=verbose)
        env = {"HOME": str(self.tmp), "XDG_CONFIG_HOME": str(self.tmp / "cfg"), "XDG_STATE_HOME": str(self.tmp / "st")}
        return App(args, ui=ui, runner=FakeRunner(dry_run=dry), paths=Paths.from_env(env), os_info=ARCH,
                   repo_root=self.tmp)

    @property
    def text(self):
        return self.out.getvalue()


@pytest.fixture
def registry(monkeypatch):
    """An empty module registry (the real modules are not loaded) and a preflight that counts its calls."""
    from fai_linop import modules
    calls = []
    monkeypatch.setattr(modules, "load", lambda: None)
    monkeypatch.setattr(preflight, "run", lambda *a, **k: calls.append(1) or True)
    root = logging.getLogger("fai_linop")
    level, handlers = root.level, list(root.handlers)
    clear_registry()
    yield calls
    clear_registry()
    root.setLevel(level)            # a -v run must not leave DEBUG on for the next test
    root.handlers[:] = handlers


def two_modules(tmp_path, **second):
    a, b = tmp_path / "a", tmp_path / "b"
    register("dotfiles", "Dotfiles", order=10)(lambda ctx: [Touch("a", a)])
    register("optimization", "Optimization", order=20)(lambda ctx: [Touch("b", b, **second)])
    return a, b


def test_every_question_belongs_to_a_module_and_starts_with_its_switch():
    seen = []
    for q in QUESTIONS:
        assert q.module in SCHEMA["modules"], q
        if q.module not in seen:
            assert q.section == "modules", f"{q.module}: the yes/no question must come first"
            seen.append(q.module)
    assert set(seen) == set(SCHEMA["modules"])


def test_wizard_asks_one_module_only(tmp_path):
    asked = []
    ui = UI(Console(file=io.StringIO()), input_fn=lambda p: asked.append(p) or "", interactive=True)
    profile = Profile.load_or_default(tmp_path / "p.toml")
    assert Wizard(profile, ui).ask_module("cleanup") is True
    assert len(asked) == 2 and "Clean up" in asked[0]          # the switch + cleanup.cache, nothing else


def test_modules_are_asked_and_applied_one_at_a_time(tmp_path, registry):
    a, b = tmp_path / "a", tmp_path / "b"
    two_modules(tmp_path)
    s = Session(tmp_path, ["y", "", "y", "y"], watch=(a, b))
    app = s.app()
    assert app.cmd_default() == 0 and a.exists() and b.exists()
    prompts = [p for p, _ in s.prompts]
    assert ["Deploy dotfiles" in prompts[0], "Apply Dotfiles?" in prompts[1],
            "optimizations" in prompts[2], "Apply Optimization?" in prompts[3]] == [True] * 4
    # the first module was already applied when the second one was asked about
    assert s.prompts[1][1] == [] and s.prompts[2][1] == ["a"]
    assert registry == [1]                                      # preflight once, not per module
    assert "1/2 Dotfiles" in s.text and "2/2 Optimization" in s.text


def test_declined_module_is_skipped_and_the_answer_is_saved(tmp_path, registry):
    a, b = two_modules(tmp_path)
    s = Session(tmp_path, ["n", "y", "y"])
    app = s.app()
    assert app.cmd_default() == 0 and not a.exists() and b.exists()
    saved = Profile.load(app.profile_path)
    assert saved.enabled("dotfiles") is False and saved.enabled("optimization") is True


def test_summary_can_be_declined_and_nothing_is_changed_or_checked(tmp_path, registry):
    a, b = two_modules(tmp_path)
    s = Session(tmp_path, ["y", "n", "n"])
    assert s.app().cmd_default() == 0 and not a.exists() and not b.exists()
    assert registry == [] and "not applied" in s.text           # no preflight / sudo for nothing


def test_risky_module_defaults_to_no(tmp_path, registry):
    a, b = two_modules(tmp_path, reversible=Reversible.ONE_WAY)
    s = Session(tmp_path, ["y", "", "y", ""])                   # Enter on both "Apply?" questions
    assert s.app().cmd_default() == 0 and a.exists() and not b.exists()
    assert "[y/N]" in s.prompts[3][0] and "[Y/n]" in s.prompts[1][0]


def test_failure_in_one_module_blocks_only_what_requires_it(tmp_path, registry):
    a, c = tmp_path / "a", tmp_path / "c"
    register("dotfiles", "Dotfiles", order=10)(lambda ctx: [Touch("a", a, fail=True)])
    register("terminal", "Terminal", order=20)(lambda ctx: [Touch("b", tmp_path / "b", requires=("a",))])
    register("cleanup", "Cleanup", order=30)(lambda ctx: [Touch("c", c)])
    s = Session(tmp_path, ["y", "y", "y", "", "", "y", "y", "", "y"])
    app = s.app()
    assert app.cmd_default() == 1 and c.exists() and not (tmp_path / "b").exists()
    assert "requires failed action(s): a" in s.text and "1 failed" in s.text
    status = Journal.open(app.paths.runs).action_status()
    assert status == {"a": "failed", "b": "skipped", "c": "done"}


def test_yes_uses_the_profile_and_asks_nothing(tmp_path, registry):
    a, b = two_modules(tmp_path)
    s = Session(tmp_path, [])
    app = s.app(yes=True, interactive=False)
    app.profile_path.parent.mkdir(parents=True)
    app.profile_path.write_text("[modules]\noptimization = false\n")
    assert app.cmd_default() == 0 and a.exists() and not b.exists() and s.prompts == []


def test_non_interactive_without_yes_is_refused(tmp_path, registry):
    a, _ = two_modules(tmp_path)
    s = Session(tmp_path, [])
    app = s.app(interactive=False)
    assert app.cmd_default() == 2 and not a.exists() and not app.paths.runs.exists()


def test_dry_run_changes_and_saves_nothing(tmp_path, registry):
    a, b = two_modules(tmp_path)
    s = Session(tmp_path, ["y", "y"])                           # only the module questions, no "Apply?"
    app = s.app(dry=True)
    assert app.cmd_default() == 0 and not a.exists() and not b.exists()
    assert not app.profile_path.exists() and registry == [] and "DRY RUN" in s.text


def test_preflight_failure_stops_before_any_change(tmp_path, registry, monkeypatch):
    monkeypatch.setattr(preflight, "run", lambda *a, **k: False)
    a, b = two_modules(tmp_path)
    s = Session(tmp_path, ["y", "y"])
    app = s.app()
    assert app.cmd_default() == 1 and not a.exists() and len(s.prompts) == 2
    assert Journal.open(app.paths.runs).state() == "preflight failed"


def test_resume_does_not_ask_again_what_was_answered(tmp_path, registry):
    a, b = tmp_path / "a", tmp_path / "b"
    state = {"fail": True}
    register("dotfiles", "Dotfiles", order=10)(lambda ctx: [Touch("a", a)])
    register("optimization", "Optimization", order=20)(lambda ctx: [Touch("b", b, fail=state["fail"])])
    s = Session(tmp_path, ["y", "y", "y", "y"])
    assert s.app().cmd_default() == 1 and a.exists() and not b.exists()
    state["fail"] = False
    s2 = Session(tmp_path, ["y"])                               # only "Apply Optimization?"
    assert s2.app("resume").cmd_resume() == 0 and b.exists()
    assert [p for p, _ in s2.prompts] == ["Apply Optimization? [Y/n] "]
    assert "completed in a previous run" not in s2.text         # short output: no table of finished actions


def test_short_output_by_default_and_table_with_verbose(tmp_path, registry):
    class Packages(Action):
        id, title = "pk", "Install packages"

        def plan(self, ctx):
            return [Change("package", f"pkg{i}", "repo") for i in range(40)] + [Change("package", "yay-bin", "AUR")]

        def apply(self, ctx):
            pass

    register("dotfiles", "Dotfiles", order=10)(lambda ctx: [Packages()])
    s = Session(tmp_path, ["y", "n"])
    assert s.app().cmd_default() == 0
    assert "Install packages: 41 package(s) — 40 repo, 1 AUR" in s.text and "pkg7" not in s.text
    v = Session(tmp_path, ["y", "n"])
    assert v.app(verbose=True).cmd_default() == 0
    assert "pkg7" in v.text and "FAI_LinOP plan" in v.text
