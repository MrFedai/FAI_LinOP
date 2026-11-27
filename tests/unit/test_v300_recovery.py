"""v3.0.0 O5: first backup survives a second write and unreadable root files are read
through sudo (1.7); rollback is resilient and honest (1.8); the protected packages are
translated per distro (1.10)."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest
from rich.console import Console

from fai_linop.core.action import Context
from fai_linop.core.profile import Profile
from fai_linop.core.runner import CommandError, FakeRunner, Result
from fai_linop.core.ui import UI
from fai_linop.package import catalog as cat
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.recovery.backup import FileChanger, restore_files
from fai_linop.recovery.journal import Journal
from fai_linop.recovery.reset import PROTECTED_IDS, ResetPackages, protected_names

REPO = Path(__file__).resolve().parents[2]
ARCH = OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux")
DEBIAN = OSInfo(Family.DEBIAN, Tier.SUPPORTED, "debian", "Debian")
FEDORA = OSInfo(Family.FEDORA, Tier.SUPPORTED, "fedora", "Fedora")


# ---- 1.7 -------------------------------------------------------------------------------------

def test_two_writes_then_rollback_gives_original(tmp_path):
    j = Journal.create(tmp_path / "runs", run_id="r1")
    fc = FileChanger(j, FakeRunner())
    f = tmp_path / "home" / "a.conf"
    f.parent.mkdir()
    f.write_text("original\n")
    assert fc.write(f, b"first\n") and fc.write(f, b"second\n")
    assert f.read_text() == "second\n"
    assert sum(ev["event"] == "file_backup" for ev in j.events()) == 1
    restore_files(j, FakeRunner())
    assert f.read_text() == "original\n"


def test_backup_only_then_write_keeps_the_first_backup(tmp_path):
    j = Journal.create(tmp_path / "runs", run_id="r1")
    fc = FileChanger(j, FakeRunner())
    f = tmp_path / "a.conf"
    f.write_text("original\n")
    fc.backup_only(f)
    f.write_text("changed by another program\n")
    fc.write(f, b"ours\n")
    restore_files(j, FakeRunner())
    assert f.read_text() == "original\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_root_file_is_backed_up_through_sudo(tmp_path):
    secret = tmp_path / "rules.conf"
    secret.write_text("allow all\n")
    secret.chmod(0)
    runner = FakeRunner().on("cat", result="allow all\n")
    j = Journal.create(tmp_path / "runs", run_id="r1")
    try:
        assert FileChanger(j, runner).write(secret, b"block all\n", root=True)
    finally:
        secret.chmod(0o600)
    ev = [e for e in j.events() if e["event"] == "file_backup"][0]
    assert ev["existed"] is True and Path(ev["backup"]).read_text() == "allow all\n"
    assert ("sudo", "--", "cat", str(secret)) in runner.calls
    assert ("sudo", "--", "tee", str(secret)) in runner.calls


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read everything")
def test_unreadable_target_is_not_written_without_backup(tmp_path):
    secret = tmp_path / "rules.conf"
    secret.write_text("allow all\n")
    secret.chmod(0)
    runner = FakeRunner().on("cat", result=Result((), 1, "", "denied"))
    j = Journal.create(tmp_path / "runs", run_id="r1")
    try:
        with pytest.raises(OSError):
            FileChanger(j, runner).write(secret, b"block all\n", root=True)
    finally:
        secret.chmod(0o600)
    assert not any(c[2:3] == ("tee",) for c in runner.calls)
    assert not any(e["event"] == "file_backup" for e in j.events())


# ---- 1.8 -------------------------------------------------------------------------------------

def _dconf_journal(tmp_path, dump_text):
    j = Journal.create(tmp_path / "runs", run_id="r1")
    dump = tmp_path / "dconf-full.ini"
    dump.write_text(dump_text)
    j.write("dconf_backup", path=str(dump))
    return j


def test_broken_dconf_dump_leaves_database_alone(tmp_path):
    j = _dconf_journal(tmp_path, "this is [not a keyfile\n")
    runner = FakeRunner()
    report = restore_files(j, runner)
    assert report[0].startswith("FAILED")
    assert not any("reset" in c for c in runner.calls)
    assert [e for e in j.events() if e["event"] == "rollback"][0]["ok"] is False


def test_failing_dconf_load_puts_previous_state_back(tmp_path):
    j = _dconf_journal(tmp_path, "[org/x]\nk='1'\n")
    loads = []

    def load(cmd, input):
        loads.append(input)
        return Result((), 1, "", "boom") if len(loads) == 1 else 0

    runner = FakeRunner().on("dconf", "dump", result="[org/x]\nk='0'\n").on("dconf", "load", result=load)
    report = restore_files(j, runner)
    assert report[0].startswith("FAILED") and "put back" in report[0]
    assert loads == ["[org/x]\nk='1'\n", "[org/x]\nk='0'\n"]


def test_one_failing_item_does_not_stop_the_others(tmp_path):
    j = Journal.create(tmp_path / "runs", run_id="r1")
    fc = FileChanger(j, FakeRunner())
    a, b = tmp_path / "a.conf", tmp_path / "b.conf"
    a.write_text("a0")
    b.write_text("b0")
    fc.write(a, b"a1")
    fc.write(b, b"b1")
    # b is restored first (newest first); its root restore raises, a must still be restored
    for e in list(j.events()):
        if e["event"] == "file_backup" and e["path"] == str(b):
            j.write("file_backup", path=str(b), existed=True, backup=e["backup"], root=True)
    runner = FakeRunner().on("cp", result=1)
    report = restore_files(j, runner)
    assert report[0].startswith("FAILED") and f"restored {a}" in report
    assert a.read_text() == "a0"
    ev = [e for e in j.events() if e["event"] == "rollback"][0]
    assert ev["failed"] >= 1 and ev["ok"] is False


def test_reset_message_says_packages_are_not_reinstalled():
    from fai_linop import cli
    src = Path(cli.__file__).read_text()
    assert "NOT reinstalled by rollback" in src


# ---- 1.10 ------------------------------------------------------------------------------------

@pytest.mark.parametrize("os_info", [ARCH, DEBIAN, FEDORA])
def test_protected_packages_are_not_in_the_removal_plan(tmp_path, os_info):
    catalog = cat.load()
    assert PROTECTED_IDS <= set(catalog)
    protected = {catalog[i].native(os_info).removeprefix("aur:") for i in PROTECTED_IDS} - {""}
    assert protected and protected <= protected_names(os_info)
    runner = FakeRunner()
    listing = "\n".join(sorted(protected | {"steam"}))
    runner.on("pacman", "-Qq", result=listing)
    runner.on("dpkg-query", result="".join(f"{n}\tinstalled\n" for n in sorted(protected | {"steam"})))
    runner.on("rpm", result=listing)
    runner.on("dnf", result=listing)
    (tmp_path / "p.toml").write_text("")
    j = Journal.create(tmp_path / "runs")
    ui = UI(Console(file=io.StringIO(), width=200), input_fn=lambda _p: "", interactive=False)
    ctx = Context(runner, Profile.load(tmp_path / "p.toml"), os_info, j, FileChanger(j, runner), ui, REPO, tmp_path)
    planned = {c.target for c in ResetPackages().plan(ctx)}
    assert not planned & protected_names(os_info)


def test_fedora_and_debian_native_names_are_protected():
    assert "vim-enhanced" in protected_names(FEDORA)
    assert "network-manager-gnome" in protected_names(DEBIAN) or \
        cat.load()["network-manager-applet"].native(DEBIAN) in protected_names(DEBIAN)
