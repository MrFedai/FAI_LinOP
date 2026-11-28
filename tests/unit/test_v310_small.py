"""v3.1.0 O5: services libvirtd / AnyDesk (3.7, F34), terminal themes + kitty.conf (3.9, F24),
slow-connection warning (3.11, F14), nautilus in the Hyprland group (3.11, F22). FakeRunner only → UNIT TESTED."""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from test_phase5 import ARCH, ctx_for

from fai_linop.core import preflight
from fai_linop.core.profile import ProfileError
from fai_linop.core.runner import FakeRunner
from fai_linop.core.ui import UI
from fai_linop.package import catalog
from fai_linop.package.resolve import Resolution
from fai_linop.package.actions import build as packages_build
from fai_linop.package.actions import service_actions
from fai_linop.terminal.actions import ALACRITTY_THEME_URL, AlacrittyTheme, KittyConf, KittyTheme


def ids(actions):
    return [a.id for a in actions]


# ---- 3.7 services --------------------------------------------------------------------

def test_libvirtd_enabled_when_power_group_selected(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = ["power"]\n')
    acts = service_actions(ctx)
    assert "packages.libvirtd" in ids(acts)
    svc = next(a for a in acts if a.id == "packages.libvirtd")
    assert svc.unit == "libvirtd.service" and svc.plan(ctx)


def test_libvirtd_enabled_when_extra_selects_qemu(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = []\nextra = ["virt-manager"]\n')
    assert "packages.libvirtd" in ids(service_actions(ctx))


def test_service_actions_run_after_installs(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = ["power", "remote"]\n')
    order = ids(packages_build(ctx))
    for svc, inst in (("packages.libvirtd", "packages.native"), ("packages.anydesk", "packages.aur")):
        assert order.index(svc) > order.index(inst)
    assert order.index("packages.libvirtd") > order.index("packages.flatpak")


def test_alacritty_theme_url_pinned():
    import re
    assert "master" not in ALACRITTY_THEME_URL
    assert re.search(r"/[0-9a-f]{40}/", ALACRITTY_THEME_URL)


def test_no_service_actions_when_not_selected(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = ["media"]\n')
    assert ids(service_actions(ctx)) == []


def test_anydesk_service_when_native(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = ["remote"]\n')
    ctx.facts["packages"] = Resolution(aur=["anydesk-bin"])
    svc = next(a for a in service_actions(ctx) if a.id == "packages.anydesk")
    assert svc.unit == "anydesk.service" and svc.plan(ctx)


def test_anydesk_no_service_when_flatpak(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = ["remote"]\n')
    ctx.facts["packages"] = Resolution(flatpak=["com.anydesk.Anydesk"])
    svc = next(a for a in service_actions(ctx) if a.id == "packages.anydesk")
    assert svc.plan(ctx) == []


def test_anydesk_absent_when_not_selected(tmp_path):
    ctx = ctx_for(tmp_path, '[packages]\ngroups = ["power"]\n')
    assert "packages.anydesk" not in ids(service_actions(ctx))


# ---- 3.9 terminal themes -------------------------------------------------------------

def term(tmp_path, emulator, theme):
    return ctx_for(tmp_path, f'[terminal]\nemulator = "{emulator}"\ntheme = "{theme}"\n')


def test_profile_accepts_new_themes(tmp_path):
    for theme in ("cyberpunk", "omni"):
        assert term(tmp_path, "kitty", theme).profile.get("terminal", "theme") == theme


def test_profile_rejects_unknown_theme(tmp_path):
    with pytest.raises(ProfileError):
        term(tmp_path, "kitty", "nope")


def test_cyberpunk_kitty_only(tmp_path):
    ctx = term(tmp_path, "kitty", "cyberpunk")
    assert any("Cyberpunk" in c.detail for c in KittyTheme().plan(ctx))
    ctx = term(tmp_path, "alacritty", "cyberpunk")
    changes = AlacrittyTheme().plan(ctx)
    assert [c.detail for c in changes] == ["theme cyberpunk not available for alacritty"]
    AlacrittyTheme().apply(ctx)   # no download, no write
    assert not any(c[0] == "curl" for c in ctx.runner.calls)


def test_omni_alacritty_only(tmp_path):
    ctx = term(tmp_path, "alacritty", "omni")
    assert any("omni.toml" in c.target or "omni.toml" in c.detail for c in AlacrittyTheme().plan(ctx))
    ctx = term(tmp_path, "kitty", "omni")
    assert [c.detail for c in KittyTheme().plan(ctx)] == ["theme omni not available for kitty"]
    KittyTheme().apply(ctx)
    assert ctx.runner.calls == []


def test_kitty_conf_created_when_missing(tmp_path):
    ctx = term(tmp_path, "kitty", "")
    act = KittyConf()
    assert act.plan(ctx)
    ctx.runner.dry_run = False
    act.apply(ctx)
    assert (ctx.home / ".config/kitty/kitty.conf").read_text() == "font_family JetBrainsMono Nerd Font\n"
    assert act.plan(ctx) == []   # idempotent


def test_kitty_conf_existing_untouched(tmp_path):
    ctx = term(tmp_path, "kitty", "")
    conf = ctx.home / ".config/kitty/kitty.conf"
    conf.parent.mkdir(parents=True)
    conf.write_text("font_family Mine\n")
    act = KittyConf()
    assert act.plan(ctx) == []
    ctx.runner.dry_run = False
    act.apply(ctx)
    assert conf.read_text() == "font_family Mine\n"


def test_kitty_conf_not_for_other_emulators(tmp_path):
    assert KittyConf().plan(term(tmp_path, "alacritty", "")) == []


# ---- 3.11 slow connection ------------------------------------------------------------

def test_is_slow():
    assert preflight.is_slow("499 KiB/s")
    assert not preflight.is_slow("500 KiB/s")
    assert not preflight.is_slow("2048 KiB/s")
    assert not preflight.is_slow("unknown (8s, no result)")


def test_preflight_warns_on_slow_speed(tmp_path, monkeypatch):
    monkeypatch.setenv("LINOP_SKIP_SUDO_CHECK", "1")
    out = io.StringIO()
    ui = UI(Console(file=out, width=200), interactive=False)
    runner = FakeRunner().on("curl", result="102400")   # 100 KiB/s
    preflight.run(ARCH, runner, ui, needs_network=False, dry_run=True, root=tmp_path, speedtest=True)
    assert "slow connection" in out.getvalue()
    out.truncate(0)
    out.seek(0)
    runner = FakeRunner().on("curl", result="1048576")  # 1024 KiB/s
    preflight.run(ARCH, runner, ui, needs_network=False, dry_run=True, root=tmp_path, speedtest=True)
    assert "slow connection" not in out.getvalue()


# ---- 3.11 nautilus -------------------------------------------------------------------

def test_nautilus_in_hyprland_group():
    entry = catalog.load()["nautilus"]
    assert "hyprland" in entry.groups
    assert entry.arch == entry.debian == entry.fedora == "nautilus"
