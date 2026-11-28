"""V301 2.2: package resolution follows the apply order (D22: repo → AUR → Flatpak).
A source the plan cannot know without side effects is "deferred: resolved at apply".
FakeRunner only; nothing touches the system."""

from __future__ import annotations

from fai_linop.core import engine
from fai_linop.core.runner import FakeRunner
from fai_linop.package import actions as pkg
from fai_linop.package.actions import (InstallAur, InstallAurHelper, InstallFlatpak, InstallNative, SetupFlathub,
                                       multilib_pending, resolution)
from fai_linop.package.catalog import Entry
from fai_linop.package.resolve import DEFERRED, resolve
from fai_linop.system import actions as system_actions
from test_phase5 import ARCH, UBUNTU, ctx_for

MULTILIB_OFF = "[options]\nArchitecture = auto\n\n#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n"
APT = ("env", "DEBIAN_FRONTEND=noninteractive", "apt-get")


def entry(id, arch="", ubuntu="", flatpak=""):
    return Entry(id, ("test",), arch, "", ubuntu, "", flatpak, id)


def wanted(monkeypatch, *entries):
    monkeypatch.setattr(pkg, "wanted_entries", lambda groups, ids=(): list(entries))


def package_actions():
    return [InstallNative(), InstallAurHelper(), InstallAur(), SetupFlathub(), InstallFlatpak()]


class FakeSystem:
    """Package state behind a FakeRunner: repos, AUR, apt index, installed names, tools."""

    def __init__(self, repo=(), aur=(), yay=False, flatpak=False, index=None, dry_run=False):
        self.repo, self.aur, self.installed, self.flatpaks = list(repo), set(aur), set(), set()
        self.index = list(repo) if index is None else list(index)   # apt: what `apt-cache pkgnames` sees now
        self.tools, self.remote = {"yay": yay, "flatpak": flatpak}, flatpak
        r = self.runner = FakeRunner(dry_run=dry_run)
        r.on("pacman", "-Qq", result=lambda c, i: "\n".join(self.installed))
        r.on("pacman", "-Slq", result=lambda c, i: "\n".join(self.repo))
        r.on("pacman", "-S", result=self._install)
        r.on("sh", "-c", result=lambda c, i: 0 if self.tools.get(c[-1].split()[-1]) else 1)
        r.on("yay", "-Si", result=lambda c, i: "".join(f"Name            : {n}\n" for n in c[3:] if n in self.aur))
        r.on("yay", "-S", result=self._install)
        r.on("makepkg", result=lambda c, i: self.tools.update(yay=True) or 0)
        r.on("dpkg-query", result=lambda c, i: "".join(f"{n}\tinstalled\n" for n in self.installed))
        r.on("apt-cache", "pkgnames", result=lambda c, i: "\n".join(self.index))
        r.on("find", "/var/lib/apt/lists", result=lambda c, i: "x_Packages\n" if self.index else "")
        r.on(*APT, "update", result=lambda c, i: self.index.extend(n for n in self.repo if n not in self.index) or 0)
        r.on(*APT, "install", result=self._install)
        r.on("flatpak", "list", result=lambda c, i: "\n".join(self.flatpaks))
        r.on("flatpak", "remotes", result=lambda c, i: "flathub\n" if self.remote else "")
        r.on("flatpak", "remote-add", result=lambda c, i: setattr(self, "remote", True) or 0)
        r.on("flatpak", "install", result=lambda c, i: self.flatpaks.update(c[5:]) or 0)

    def _install(self, cmd, _input):
        names = [a for a in cmd[2:] if not a.startswith("-") and a not in ("install", "apt-get", "None")]
        self.installed.update(names)
        self.tools["flatpak"] = self.tools["flatpak"] or "flatpak" in names
        return 0

    def planning_had_no_side_effects(self):
        """Planning never syncs a database, builds or runs anything with sudo."""
        for call in self.runner.calls:
            assert call[0] != "sudo", call
            assert not any(a in ("-Sy", "-Syu", "update", "makepkg", "clone") for a in call), call


def test_arch_multilib_enabled_this_run_defers_and_builds_no_helper(tmp_path, monkeypatch):
    conf = tmp_path / "pacman.conf"
    conf.write_text(MULTILIB_OFF)
    monkeypatch.setattr(system_actions, "PACMAN_CONF", conf)
    wanted(monkeypatch, entry("git", arch="git"), entry("steam", arch="steam"), entry("lib32-mesa", arch="lib32-mesa"))
    fs = FakeSystem(repo=["git"])                                   # no yay; multilib not synced yet
    ctx = ctx_for(tmp_path, "[modules]\ngaming = true\n", runner=fs.runner)

    assert multilib_pending(ctx)
    res = resolution(ctx)
    assert res.native == ["git"] and list(res.deferred) == ["steam", "lib32-mesa"]
    assert res.aur == [] and res.unavailable == [] and res.flatpak == []   # not guessed as AUR / Flatpak
    plan = engine.build_plan(ctx, package_actions())
    fs.planning_had_no_side_effects()
    native, helper = plan.items[0].changes, plan.items[1].changes
    assert [(c.target, c.detail) for c in native] == [("git", "repo"), ("steam", DEFERRED), ("lib32-mesa", DEFERRED)]
    assert helper and all("only if a deferred package is AUR-only" in c.detail for c in helper)

    fs.repo += ["steam", "lib32-mesa"]  # system.multilib ran `pacman -Syu` after enabling the repository
    engine.execute(ctx, plan)
    assert [p.status for p in plan.items] == ["done"] * 5
    assert res.native == ["git", "steam", "lib32-mesa"] and not res.deferred
    assert ("sudo", "--", "pacman", "-S", "--needed", "--noconfirm", "git", "steam", "lib32-mesa") in fs.runner.calls
    assert not any("makepkg" in c or "clone" in c for c in fs.runner.calls)    # helper not built for nothing
    assert not fs.tools["yay"]


def test_multilib_already_enabled_or_not_enabled_by_this_run_is_not_pending(tmp_path, monkeypatch):
    conf = tmp_path / "pacman.conf"
    conf.write_text(MULTILIB_OFF.replace("#[multilib]\n#Include", "[multilib]\nInclude"))
    monkeypatch.setattr(system_actions, "PACMAN_CONF", conf)
    assert not multilib_pending(ctx_for(tmp_path, "[modules]\ngaming = true\n"))                  # already on
    conf.write_text(MULTILIB_OFF)
    assert not multilib_pending(ctx_for(tmp_path, ""))                                            # gaming off
    assert not multilib_pending(ctx_for(tmp_path, "[modules]\ngaming = true\nsystem = false\n"))  # nobody enables it
    assert not multilib_pending(ctx_for(tmp_path, "[modules]\ngaming = true\n", os_info=UBUNTU))


def test_ubuntu_empty_apt_index_defers_until_apt_get_update(tmp_path, monkeypatch):
    wanted(monkeypatch, entry("neovim", ubuntu="neovim"), entry("obsidian", ubuntu="obsidian", flatpak="md.obsidian.Obsidian"),
           entry("fastfetch", ubuntu="fastfetch"), entry("discord", flatpak="com.discordapp.Discord"))
    fs = FakeSystem(repo=["neovim"], index=[])                       # fresh install: no package lists yet
    ctx = ctx_for(tmp_path, "", os_info=UBUNTU, runner=fs.runner)

    res = resolution(ctx)
    assert list(res.deferred) == ["neovim", "obsidian", "fastfetch"]   # not "missing": unknown
    assert res.flatpak == ["com.discordapp.Discord"] and res.unavailable == []  # no Ubuntu name: Flatpak is certain
    plan = engine.build_plan(ctx, package_actions())
    fs.planning_had_no_side_effects()
    assert [c.detail for c in plan.items[0].changes] == [DEFERRED] * 3

    fs.runner.calls.clear()
    engine.execute(ctx, plan)
    assert [p.status for p in plan.items] == ["done", "skipped", "skipped", "done", "done"]
    calls = fs.runner.calls
    update = calls.index(("sudo", "--", *APT, "update"))
    requery = max(i for i, c in enumerate(calls) if c[:2] == ("apt-cache", "pkgnames"))
    assert update < requery                                              # resolved again after the update
    assert res.native == ["neovim"] and not res.deferred
    assert res.flatpak == ["com.discordapp.Discord", "md.obsidian.Obsidian"]  # D22: repo → Flatpak
    assert res.unavailable == ["fastfetch (fastfetch not in the repositories)"]
    assert ("sudo", "--", *APT, "install", "-y", "neovim") in calls
    assert fs.flatpaks == {"com.discordapp.Discord", "md.obsidian.Obsidian"}


def test_ubuntu_old_index_defers_only_missing_names():
    fs = FakeSystem(index=["neovim"])
    fs.runner.on("find", "/var/lib/apt/lists", result="")             # no package list written in the last day
    res = resolve(UBUNTU, fs.runner, [entry("neovim", ubuntu="neovim"), entry("fastfetch", ubuntu="fastfetch")])
    assert res.native == ["neovim"] and list(res.deferred) == ["fastfetch"] and res.unavailable == []


def test_arch_without_yay_aur_only_name_deferred_then_resolved_after_build(tmp_path, monkeypatch):
    wanted(monkeypatch, entry("git", arch="git"), entry("planify", arch="planify", flatpak="io.github.alainm23.planify"))
    fs = FakeSystem(repo=["git"], aur=["my-aur-pkg"])
    ctx = ctx_for(tmp_path, '[packages]\nextra = ["my-aur-pkg", "neovm"]\n', runner=fs.runner)

    res = resolution(ctx)
    assert list(res.deferred) == ["planify", "my-aur-pkg", "neovm"]   # no helper to ask: not "unavailable", not AUR
    assert res.aur == [] and res.unavailable == []
    plan = engine.build_plan(ctx, package_actions())
    fs.planning_had_no_side_effects()
    assert [c.target for c in plan.items[1].changes] == ["git base-devel", "yay-bin"]
    assert all(p.deferred for p in plan.items[2:])                     # AUR / Flathub / Flatpak run at apply

    engine.execute(ctx, plan)
    assert [p.status for p in plan.items] == ["done"] * 5
    assert res.aur == ["my-aur-pkg"]                                   # only names the AUR really has
    assert res.flatpak == ["io.github.alainm23.planify"]              # catalog name in neither → Flatpak
    assert res.unavailable == ["neovm"]                               # user typo: reported, never sent to yay
    assert [c for c in fs.runner.calls if c[:2] == ("yay", "-S")] == [
        ("yay", "-S", "--needed", "--noconfirm", "--answerdiff", "None", "--answerclean", "None", "my-aur-pkg")]
    assert fs.flatpaks == {"io.github.alainm23.planify"}


def test_arch_name_in_no_repo_falls_back_to_flatpak_not_aur():
    fs = FakeSystem(repo=["git"], yay=True)                           # the AUR has none of them
    res = resolve(ARCH, fs.runner, [entry("planify", arch="planify", flatpak="io.github.alainm23.planify"),
                                    entry("nothing", arch="nothing")])
    assert res.aur == [] and not res.deferred
    assert res.flatpak == ["io.github.alainm23.planify"]
    assert res.unavailable == ["nothing (nothing not in the repositories)"]
    off = resolve(ARCH, fs.runner, [entry("planify", arch="planify", flatpak="x.y")], flatpak_fallback=False)
    assert off.flatpak == [] and off.unavailable == ["planify (planify not in the repositories)"]


def test_summary_source_column_repo_aur_flatpak_deferred(tmp_path, monkeypatch):
    conf = tmp_path / "pacman.conf"
    conf.write_text(MULTILIB_OFF)
    monkeypatch.setattr(system_actions, "PACMAN_CONF", conf)
    wanted(monkeypatch, entry("git", arch="git"), entry("chrome", arch="aur:google-chrome"),
           entry("discord", flatpak="com.discordapp.Discord"), entry("steam", arch="steam"))
    fs = FakeSystem(repo=["git"], yay=True, flatpak=True)
    ctx = ctx_for(tmp_path, "[modules]\ngaming = true\n", runner=fs.runner)
    plan = engine.build_plan(ctx, package_actions())
    engine.show_plan(ctx, plan)                      # short summary (D30): counts per source, no names
    out = ctx.ui.console.file.getvalue()
    assert "2 package(s) — 1 repo, 1 " + DEFERRED in out and "git" not in out
    ctx.ui.verbose = True                            # -v: the full table with every name
    engine.show_plan(ctx, plan)
    out = ctx.ui.console.file.getvalue()
    assert "package: repo (1): git" in out
    assert "package: AUR (1): google-chrome" in out
    assert "flatpak: Flathub (1): com.discordapp.Discord" in out
    assert f"package: {DEFERRED} (1): steam" in out
    # helper present → skipped; Flathub already set up but more Flatpaks may come → deferred row
    assert [p.status for p in plan.items] == ["pending", "skipped", "pending", "pending", "pending"]
    assert plan.items[3].deferred and engine.DEFERRED_NOTE in out


def test_dry_run_keeps_deferred_names_unresolved(tmp_path, monkeypatch):
    wanted(monkeypatch, entry("neovim", ubuntu="neovim"))
    fs = FakeSystem(repo=["neovim"], index=[], dry_run=True)
    ctx = ctx_for(tmp_path, "", os_info=UBUNTU, runner=fs.runner)
    plan = engine.build_plan(ctx, package_actions())
    engine.execute(ctx, plan)
    res = resolution(ctx)
    assert list(res.deferred) == ["neovim"] and res.unavailable == [] and res.flatpak == []
    assert not fs.installed and not fs.flatpaks
