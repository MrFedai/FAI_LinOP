"""The font a deployed dotfile names is requested as a package (the Terminator config says
"Adwaita Mono 10"; without the font the terminal falls back to a proportional one)."""

from __future__ import annotations

from conftest import REPO

from fai_linop.dotfiles import manager
from fai_linop.package import catalog as cat
from fai_linop.package.actions import ModuleRequests, resolution
from fai_linop.platform.detect import Family, OSInfo, Tier
from test_phase5 import ARCH, UBUNTU, ctx_for
from test_v301_package_resolve import FakeSystem

FEDORA = OSInfo(Family.FEDORA, Tier.SUPPORTED, "fedora", "Fedora Linux")


def test_font_family_is_read_from_the_terminator_config():
    assert manager.font_packages((REPO / "configs/terminator/config").read_text()) == ["font-adwaita-mono"]
    assert manager.font_packages("    font = JetBrainsMono Nerd Font 11\n") == ["font-jetbrains-nerd"]
    assert manager.font_packages("    font = Some Unknown Font 12\n    use_system_font = True\n") == []


def test_catalog_names_per_distro():
    entry = cat.load()["font-adwaita-mono"]
    assert entry.native(ARCH) == "adwaita-fonts" and entry.native(FEDORA) == "adwaita-mono-fonts"
    assert entry.native(UBUNTU) == "" and not entry.flatpak        # not packaged: reported, never guessed


def test_dotfiles_module_requests_the_font(tmp_path):
    ctx = ctx_for(tmp_path)
    actions = manager.build(ctx)
    assert ctx.facts["package_ids"] == ["font-adwaita-mono"] and [a.id for a in actions] == ["dotfiles.terminator"]


def test_staged_dotfiles_stage_installs_the_font_on_arch(tmp_path):
    fs = FakeSystem(repo=["adwaita-fonts"])
    ctx = ctx_for(tmp_path, runner=fs.runner)
    with ModuleRequests(ctx, "dotfiles") as wanted:
        own = manager.build(ctx)
    actions = wanted.with_dependencies(own)
    assert actions[0].id == "packages.native:dotfiles" and resolution(ctx).native == ["adwaita-fonts"]


def test_ubuntu_reports_the_font_as_not_available(tmp_path):
    ctx = ctx_for(tmp_path, os_info=UBUNTU, runner=FakeSystem().runner)
    with ModuleRequests(ctx, "dotfiles") as wanted:
        own = manager.build(ctx)
    wanted.with_dependencies(own)
    assert resolution(ctx).native == [] and resolution(ctx).unavailable == ["font-adwaita-mono (not packaged for ubuntu)"]
