"""V301 2.5: honest cache purge, named orphan removal, debloat that does not drag packages along."""

from __future__ import annotations

import pytest
from test_phase5 import ARCH, DEBIAN, UBUNTU, ctx_for

from fai_linop.core.runner import FakeRunner
from fai_linop.desktop.gnome import Debloat
from fai_linop.optimization import actions as opt
from fai_linop.optimization.actions import Cache, Orphans
from fai_linop.platform.detect import Family, OSInfo, Tier

FEDORA = OSInfo(Family.FEDORA, Tier.SUPPORTED, "fedora", "Fedora")

APT_SIM = "Remv libfoo1 [1.0]\nRemv foo-data [1.0] [bar:amd64]\nInst x [1]\n"
DNF_SIM = """Dependencies resolved.
================================================
 Package        Arch     Version      Repository  Size
================================================
Removing:
 gnome-tour     x86_64   45.0-1.fc40  @fedora     1.2 M
Removing unused dependencies:
 libfoo         x86_64   1.0-1.fc40   @fedora     200 k

Transaction Summary
================================================
Remove  2 Packages
Operation aborted.
"""


def test_purge_answers_both_pacman_questions(tmp_path):
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, '[cleanup]\ncache = "purge"\n', runner=runner)
    Cache().apply(ctx)
    assert runner.calls == [("sudo", "--", "pacman", "-Scc")]
    assert runner.inputs == ["y\ny\n"]


def test_cache_verify_false_while_packages_remain(tmp_path, monkeypatch):
    cache = tmp_path / "pkg"
    cache.mkdir()
    (cache / "foo-1-1-x86_64.pkg.tar.zst").write_text("x")
    monkeypatch.setattr(opt, "PACMAN_CACHE", cache)
    ctx = ctx_for(tmp_path, '[cleanup]\ncache = "purge"\n')
    assert Cache().verify(ctx) is False
    (cache / "foo-1-1-x86_64.pkg.tar.zst").unlink()
    assert Cache().verify(ctx) is True


def test_cache_verify_debian_looks_at_deb_files(tmp_path, monkeypatch):
    cache = tmp_path / "archives"
    cache.mkdir()
    (cache / "a.deb").write_text("x")
    monkeypatch.setattr(opt, "APT_CACHE", cache)
    ctx = ctx_for(tmp_path, '[cleanup]\ncache = "purge"\n', os_info=UBUNTU)
    assert Cache().verify(ctx) is False


def test_apt_orphans_plan_from_simulation_and_named_removal(tmp_path):
    runner = FakeRunner().on("apt-get", "--simulate", "autoremove", result=APT_SIM)
    ctx = ctx_for(tmp_path, "[cleanup]\norphans = true\n", os_info=DEBIAN, runner=runner)
    a = Orphans()
    assert [c.target for c in a.plan(ctx)] == ["foo-data", "libfoo1"]
    a.apply(ctx)
    assert runner.calls[-1][-4:] == ("remove", "-y", "foo-data", "libfoo1")
    assert "autoremove" not in runner.calls[-1]


def test_dnf_orphans_plan_from_assumeno(tmp_path):
    runner = FakeRunner().on("dnf", "autoremove", result=DNF_SIM)
    ctx = ctx_for(tmp_path, "[cleanup]\norphans = true\n", os_info=FEDORA, runner=runner)
    a = Orphans()
    assert [c.target for c in a.plan(ctx)] == ["gnome-tour", "libfoo"]
    a.apply(ctx)
    assert runner.calls[-1] == ("sudo", "--", "dnf", "remove", "-y", "gnome-tour", "libfoo")


def test_orphans_empty_simulation_means_empty_plan_and_no_command(tmp_path):
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, "[cleanup]\norphans = true\n", os_info=DEBIAN, runner=runner)
    a = Orphans()
    assert a.plan(ctx) == []
    a.apply(ctx)
    assert all(c[0] != "sudo" for c in runner.calls)


def _debloat_ctx(tmp_path, sim, os_info=UBUNTU):
    runner = (FakeRunner()
              .on("dpkg-query", result="gnome-tour\tinstalled\n")
              .on("apt-get", "--simulate", "remove", result=sim))
    return ctx_for(tmp_path, "[gnome]\ndebloat = true\n", os_info=os_info, runner=runner), runner


def test_debloat_stops_when_simulation_takes_metapackage(tmp_path):
    ctx, runner = _debloat_ctx(tmp_path, "Remv gnome-tour [1]\nRemv ubuntu-desktop [1]\n")
    d = Debloat()
    plan = d.plan(ctx)
    assert any(c.target == "ubuntu-desktop" for c in plan)  # warning line
    with pytest.raises(RuntimeError, match="ubuntu-desktop"):
        d.apply(ctx)
    assert not any("remove" in c and "-y" in c for c in runner.calls)


def test_debloat_proceeds_when_simulation_matches(tmp_path):
    ctx, runner = _debloat_ctx(tmp_path, "Remv gnome-tour [1]\n")
    d = Debloat()
    d.plan(ctx)
    d.apply(ctx)
    assert any(c[-3:] == ("remove", "-y", "gnome-tour") for c in runner.calls)
