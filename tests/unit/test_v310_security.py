"""v3.1.0 O2: BlackArch complements (3.5) and first-install security steps + doctor summary (3.6).
FakeRunner only: command order is checked, nothing touches a real system (UNIT TESTED;
real Arch + BlackArch NOT TESTED)."""

from __future__ import annotations

import pytest

from fai_linop.core.runner import FakeRunner
from fai_linop.platform.detect import Family
from fai_linop.security import actions as sec
from fai_linop.system import actions as system
from fai_linop.system.actions import BLACKARCH_KEY, KeyringReset, Multilib, disable_blackarch, multilib_needed
from test_phase5 import ARCH, DEBIAN, ctx_for

CONF = """[options]
HoldPkg = pacman glibc

#[multilib]
#Include = /etc/pacman.d/mirrorlist

[blackarch]
Server = https://example.invalid/$repo/os/$arch
"""

CONF_BA_INCLUDE = "[core]\nInclude = /etc/pacman.d/mirrorlist\n\n[blackarch]\nInclude = /etc/pacman.d/blackarch-mirrorlist\n[extra]\nInclude = /etc/pacman.d/mirrorlist\n"


@pytest.fixture
def conf(tmp_path, monkeypatch):
    path = tmp_path / "pacman.conf"
    monkeypatch.setattr(system, "PACMAN_CONF", path)
    monkeypatch.setattr(sec, "blackarch_enabled", lambda: "[blackarch]" in path.read_text())
    return path


def conf_runner(path, **fail):
    """FakeRunner whose `tee` really writes the file, so the second write sees the first."""
    def tee(cmd, text):
        path.write_text(text)
        return 0

    runner = FakeRunner().on("tee", result=tee)
    if fail:
        runner.on("pacman-key", "--init", result=lambda cmd, _i: (_ for _ in ()).throw(RuntimeError("boom")))
    return runner


def sub(tmp_path, name):
    path = tmp_path / name
    path.mkdir()
    return path


def tails(runner, *prefix):
    return [list(c[c.index(prefix[0]):]) for c in runner.calls if prefix[0] in c]


# ---- 3.5 ---------------------------------------------------------------------------

def test_disable_blackarch_comments_only_its_section():
    out = disable_blackarch(CONF_BA_INCLUDE)
    assert "#[blackarch]\n#Include = /etc/pacman.d/blackarch-mirrorlist\n[extra]\nInclude" in out
    assert out.startswith("[core]\nInclude = /etc/pacman.d/mirrorlist\n")   # other sections untouched
    assert disable_blackarch("[core]\nInclude = x\n") == "[core]\nInclude = x\n"


def test_keyring_reset_switches_blackarch_off_then_on(tmp_path, conf):
    conf.write_text(CONF)
    runner = conf_runner(conf)
    ctx = ctx_for(tmp_path, "[system]\nkeyring_reset = true\n", ARCH, runner=runner)
    KeyringReset().apply(ctx)
    tee = [(i, c) for i, c in enumerate(runner.calls) if "tee" in c]
    assert len(tee) == 2
    assert "#[blackarch]" in runner.inputs[tee[0][0]] and "#Server" in runner.inputs[tee[0][0]]
    assert runner.inputs[tee[1][0]] == CONF          # switched back on, original bytes
    rm = next(i for i, c in enumerate(runner.calls) if "rm" in c)
    assert tee[0][0] < rm < tee[1][0]
    assert tails(runner, "pacman-key")[-1] == ["pacman-key", "--lsign-key", BLACKARCH_KEY]


def test_keyring_reset_restores_blackarch_when_rebuild_fails(tmp_path, conf):
    conf.write_text(CONF)
    runner = conf_runner(conf, fail=True)
    ctx = ctx_for(tmp_path, "[system]\nkeyring_reset = true\n", ARCH, runner=runner)
    with pytest.raises(RuntimeError):
        KeyringReset().apply(ctx)
    tee = [i for i, c in enumerate(runner.calls) if "tee" in c]
    assert len(tee) == 2 and runner.inputs[tee[1]] == CONF


def test_keyring_reset_without_blackarch_writes_no_conf(tmp_path, conf):
    conf.write_text("[core]\nInclude = x\n")
    runner = FakeRunner()
    KeyringReset().apply(ctx_for(tmp_path, "[system]\nkeyring_reset = true\n", ARCH, runner=runner))
    assert not [c for c in runner.calls if "tee" in c]
    assert tails(runner, "pacman-key") == [["pacman-key", "--init"], ["pacman-key", "--populate", "archlinux"]]


def test_blackarch_remove_deletes_key_after_conf(tmp_path, conf):
    conf.write_text(CONF)
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, '[blackarch]\ninstall = "remove"\n', ARCH, runner=runner)
    action = sec.BlackArchRemove()
    action.apply(ctx)
    cmds = [c for c in runner.calls if "tee" in c or "pacman-key" in c or "pacman" in c]
    kinds = ["tee" if "tee" in c else "key" if "pacman-key" in c else "sync" for c in cmds]
    assert kinds == ["tee", "key", "sync"]
    assert tails(runner, "pacman-key") == [["pacman-key", "--delete", BLACKARCH_KEY]]


def test_blackarch_full_requests_prerequisites(tmp_path):
    ctx = ctx_for(tmp_path, '[modules]\nblackarch = true\n[blackarch]\ninstall = "full"\n', ARCH)
    sec.build_blackarch(ctx)
    assert ctx.facts["package_ids"] == ["jdk17-openjdk", "jdk11-openjdk", "rust", "opencl-mesa"]
    core = ctx_for(sub(tmp_path, "c"),'[modules]\nblackarch = true\n[blackarch]\ninstall = "core"\n', ARCH)
    sec.build_blackarch(core)
    assert "package_ids" not in core.facts


def test_prerequisites_are_in_the_catalog_for_arch():
    from fai_linop.package import catalog
    cat = catalog.load()
    for pid in sec.BLACKARCH_PREREQ:
        assert cat[pid].arch == pid and cat[pid].debian == "" and cat[pid].fedora == ""


def test_multilib_for_blackarch_not_for_remove_or_other_families(tmp_path, conf):
    on = ctx_for(sub(tmp_path, "a"), '[modules]\nblackarch = true\n[blackarch]\ninstall = "core"\n', ARCH)
    assert multilib_needed(on)
    removing = ctx_for(sub(tmp_path, "b"), '[modules]\nblackarch = true\n[blackarch]\ninstall = "remove"\n', ARCH)
    assert not multilib_needed(removing)
    assert not multilib_needed(ctx_for(sub(tmp_path, "c"), "[modules]\nblackarch = true\n", DEBIAN))
    assert not multilib_needed(ctx_for(sub(tmp_path, "d"),"[modules]\nblackarch = false\ngaming = false\n", ARCH))
    conf.write_text("#[multilib]\n#Include = /etc/pacman.d/mirrorlist\n")
    assert Multilib().plan(on)


# ---- 3.6 ---------------------------------------------------------------------------

TOOLS = "[security]\ntools = true\n"


def test_freshclam_runs_before_service_and_only_without_database(tmp_path, monkeypatch):
    db = tmp_path / "clamav"
    db.mkdir()
    monkeypatch.setattr(sec, "CLAMAV_DB_DIR", db)
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, TOOLS, ARCH, runner=runner)
    action = sec.ClamavFirstUpdate()
    assert action.plan(ctx)
    action.apply(ctx)
    assert tails(runner, "systemctl") == [["systemctl", "stop", "clamav-freshclam"]]
    assert tails(runner, "freshclam") == [["freshclam"]]
    (db / "daily.cvd").write_text("x")
    assert action.plan(ctx) == []                      # second run: nothing to do
    built = sec.build(ctx_for(sub(tmp_path, "b"), TOOLS, ARCH))
    ids = [a.id for a in built]
    assert ids.index("security.clamav-db") < ids.index("security.freshclam")
    freshclam = next(a for a in built if a.id == "security.freshclam")
    assert freshclam.requires == ("security.clamav-db",)


def test_freshclam_failure_warns_not_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "CLAMAV_DB_DIR", tmp_path / "none")
    runner = FakeRunner().on("freshclam", result=1)
    sec.ClamavFirstUpdate().apply(ctx_for(tmp_path, TOOLS, ARCH, runner=runner))


def test_rkhunter_propupd_only_without_baseline(tmp_path, monkeypatch):
    baseline = tmp_path / "rkhunter.dat"
    monkeypatch.setattr(sec, "RKHUNTER_DB", baseline)
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, TOOLS, ARCH, runner=runner)
    action = sec.RkhunterBaseline()
    assert action.plan(ctx)
    action.apply(ctx)
    assert tails(runner, "rkhunter") == [["rkhunter", "--propupd"]]
    baseline.write_text("x")
    assert action.plan(ctx) == []


def test_opensnitch_autostart_copy_is_idempotent_and_backed_up(tmp_path, monkeypatch):
    src = tmp_path / "opensnitch_ui.desktop"
    src.write_text("[Desktop Entry]\nName=OpenSnitch\n")
    monkeypatch.setattr(sec, "AUTOSTART_SRC", src)
    ctx = ctx_for(tmp_path, "[security]\nopensnitch = true\n", ARCH)
    action = sec.OpensnitchAutostart()
    dest = ctx.home / ".config" / "autostart" / "opensnitch_ui.desktop"
    assert action.plan(ctx)
    action.apply(ctx)
    assert dest.read_text() == src.read_text()
    assert action.plan(ctx) == []
    dest.write_text("edited\n")                        # a changed file is planned, with backup
    (change,) = action.plan(ctx)
    assert "backup" in change.detail


def test_opensnitch_autostart_missing_source_is_planned_but_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(sec, "AUTOSTART_SRC", tmp_path / "absent.desktop")
    ctx = ctx_for(tmp_path, "[security]\nopensnitch = true\n", ARCH)
    action = sec.OpensnitchAutostart()
    assert action.plan(ctx)                            # packages arrive later in the same run
    action.apply(ctx)
    assert not (ctx.home / ".config" / "autostart").exists()
    assert sec.OpensnitchAutostart().plan(ctx_for(sub(tmp_path, "off"), "", ARCH)) == []


def test_security_rows_are_read_only(tmp_path):
    runner = FakeRunner().on("systemctl", "is-active", "ufw", result="active\n").on(
        "systemctl", "is-active", "usbguard", result=("inactive\n"))
    sysctl = tmp_path / "99.conf"
    sysctl.write_text("x")
    rows = dict(sec.security_rows(runner, Family.ARCH, sysctl=sysctl, sshd=tmp_path / "10-linop.conf"))
    assert rows["Firewall"] == "ufw: active"
    assert rows["Sysctl hardening"] == "present" and rows["SSH drop-in"] == "absent"
    assert rows["USBGuard"] == "usbguard: inactive"
    assert rows["OpenSnitch"] == "opensnitchd: unknown"      # no output -> unknown
    assert runner.calls and all(c[0] == "systemctl" for c in runner.calls)   # no sudo, no writes
    fedora = dict(sec.security_rows(FakeRunner(), Family.FEDORA))
    assert fedora["Firewall"].startswith("firewalld:")


def test_doctor_stays_read_only_and_security_rows_use_non_mutating_calls():
    from fai_linop import cli
    assert ("doctor", None) in cli.READ_ONLY_COMMANDS
