"""v3.1.0 O3: reset parity (3.8, D19) — extra/custom packages, orphan sweep, --shell.
FakeRunner + tmp_path only → UNIT TESTED (native NOT TESTED)."""

from __future__ import annotations

from fai_linop.cli import _parser
from fai_linop.core.runner import FakeRunner
from fai_linop.package.actions import profile_extra_names
from fai_linop.package.providers import AurHelper, Apt, Dnf, Pacman
from fai_linop.recovery.reset import ResetOrphans, ResetPackages, ResetShell, reset_actions
from test_phase5 import ctx_for


def targets(changes):
    return [c.target for c in changes]


# ---- 1. extra + custom_file ----------------------------------------------------------

def test_extra_and_custom_file_in_reset_plan(tmp_path):
    (tmp_path / "pacs.txt").write_text("htop  # tool\nzsh git\nnotinstalled\n")
    profile = f'[packages]\nextra = ["ripgrep", "git"]\ncustom_file = "{tmp_path / "pacs.txt"}"\n'
    runner = FakeRunner().on("pacman", "-Qq", result="ripgrep\nhtop\nzsh\ngit\nsteam\n")
    ctx = ctx_for(tmp_path, profile, runner=runner)
    assert profile_extra_names(ctx) == ["ripgrep", "git", "htop", "zsh", "git", "notinstalled"]
    planned = targets(ResetPackages().plan(ctx))
    assert {"ripgrep", "htop", "steam"} <= set(planned)
    assert not {"zsh", "git", "notinstalled"} & set(planned)   # protected / not installed


def test_missing_custom_file_warns_once_per_call(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ncustom_file = "nope.txt"\n')
    assert profile_extra_names(ctx) == []


# ---- 2. orphans per family ----------------------------------------------------------

def test_pacman_orphans_and_none():
    r = FakeRunner().on("pacman", "-Qtdq", result="libfoo\nlibbar\n")
    assert Pacman(r).orphans() == {"libfoo", "libbar"}
    assert r.calls == [("pacman", "-Qtdq")]
    assert Pacman(FakeRunner().on("pacman", "-Qtdq", result=1)).orphans() == set()   # rc 1 = none
    assert AurHelper(r).orphans() == {"libfoo", "libbar"}


def test_apt_orphans_parse_remv_lines():
    out = "Reading package lists...\nRemv libold [1.0]\nRemv libgone [2.1] [x]\nInst other (1 repo)\n"
    r = FakeRunner().on("apt-get", "-s", "autoremove", result=out)
    assert Apt(r).orphans() == {"libold", "libgone"}


def test_dnf_orphans():
    r = FakeRunner().on("dnf", "-q", "repoquery", "--unneeded", result="liba\nlibb\n")
    assert Dnf(r).orphans() == {"liba", "libb"}
    assert r.calls[0][:4] == ("dnf", "-q", "repoquery", "--unneeded")


# ---- ResetOrphans --------------------------------------------------------------------

def test_reset_orphans_plan_and_apply(tmp_path):
    runner = (FakeRunner().on("pacman", "-Qq", result="steam\n")
              .on("pacman", "-Qtdq", result="libfoo\ngit\nsteam\nlibbar\n"))
    ctx = ctx_for(tmp_path, runner=runner)
    ResetPackages().plan(ctx)
    action = ResetOrphans()
    changes = action.plan(ctx)
    assert targets(changes) == ["libbar", "libfoo"]            # protected git + steam (already removed) out
    assert all(c.kind == "package-remove" and c.detail == "orphan" for c in changes)
    action.apply(ctx)
    removals = [c for c in runner.calls if "-Rs" in c]
    assert len(removals) == 1 and removals[0][-2:] == ("libbar", "libfoo")   # only the planned names
    assert not any("autoremove" in " ".join(c) for c in runner.calls)


def test_reset_orphans_empty_changes_nothing(tmp_path):
    runner = FakeRunner().on("pacman", "-Qtdq", result=1)
    ctx = ctx_for(tmp_path, runner=runner)
    action = ResetOrphans()
    assert action.plan(ctx) == []
    action.apply(ctx)
    assert not any("-Rs" in c for c in runner.calls)


# ---- ResetShell ----------------------------------------------------------------------

def test_reset_shell_plan_and_apply(tmp_path, monkeypatch):
    monkeypatch.setenv("USER", "tester")
    runner = FakeRunner().on("getent", "passwd", result="tester:x:1000:1000::/home/tester:/usr/bin/zsh\n")
    ctx = ctx_for(tmp_path, runner=runner)
    zshrc = ctx.home / ".zshrc"
    zshrc.write_text("# mine\n")
    action = ResetShell()
    changes = action.plan(ctx)
    assert [(c.kind, c.target) for c in changes] == [("setting", "login shell -> bash"), ("file-remove", str(zshrc))]
    action.apply(ctx)
    assert not zshrc.exists()
    backups = [p for p in ctx.journal.backup_dir.rglob(".zshrc")]
    assert backups and backups[0].read_text() == "# mine\n"
    chsh = [c for c in runner.calls if "chsh" in c]
    assert len(chsh) == 1 and chsh[0][-1] == "tester" and "-s" in chsh[0]


def test_reset_shell_bash_already_login(tmp_path, monkeypatch):
    monkeypatch.setenv("USER", "tester")
    runner = FakeRunner().on("getent", "passwd", result="tester:x:1000:1000::/home/tester:/usr/bin/bash\n")
    ctx = ctx_for(tmp_path, runner=runner)
    action = ResetShell()
    assert action.plan(ctx) == []                  # no .zshrc, bash already
    action.apply(ctx)
    assert not any("chsh" in c for c in runner.calls)


# ---- wiring --------------------------------------------------------------------------

def test_shell_flag_and_action_order():
    assert _parser().parse_args(["reset", "--shell"]).shell is True
    assert _parser().parse_args(["reset"]).shell is False
    ids = [a.id for a in reset_actions(True, True, True)]
    assert ids == ["reset.configs", "reset.packages", "reset.orphans", "reset.gnome", "reset.shell"]
    assert [a.id for a in reset_actions(False, False, True)] == ["reset.configs", "reset.shell"]
