"""V301 2.7 (Arch upgrade: one transaction, unknown family reported) and 2.8 (NVIDIA
reboot notice tied to the driver packages). FakeRunner only; nothing touches the system."""

from __future__ import annotations

import pytest

from fai_linop.core.runner import FakeRunner
from fai_linop.gaming import actions as gaming
from fai_linop.gaming.actions import GAMEMODE_INI, NvidiaRebootNotice, UbuntuNvidia
from fai_linop.package.base import NotSupported
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.system.actions import Upgrade
from test_phase5 import ARCH, DEBIAN, ctx_for

UNKNOWN = OSInfo(Family.UNKNOWN, Tier.SUPPORTED, "unknown", "Unknown")
UPGRADE_ON = "[system]\nupgrade = true\n"


def pacman_calls(runner):
    return [list(c[c.index("pacman"):]) for c in runner.calls if "pacman" in c]


# ---- 2.7 system upgrade --------------------------------------------------------------

def test_arch_upgrade_is_one_full_transaction(tmp_path):
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, UPGRADE_ON, ARCH, runner=runner)
    Upgrade().apply(ctx)
    # keyring rides in the full -Syu; no separate -Sy (stale db) and no partial -Su
    assert pacman_calls(runner) == [["pacman", "-Syu", "--needed", "--noconfirm", "archlinux-keyring"]]


def test_arch_upgrade_plan_matches_apply_command(tmp_path):
    ctx = ctx_for(tmp_path, UPGRADE_ON, ARCH)
    (change,) = Upgrade().plan(ctx)
    assert change.target == "pacman -Syu --needed --noconfirm archlinux-keyring"


def test_debian_and_fedora_upgrade_commands_unchanged(tmp_path):
    runner = FakeRunner()
    Upgrade().apply(ctx_for(tmp_path, UPGRADE_ON, DEBIAN, runner=runner))
    assert [list(c[c.index("apt-get"):]) for c in runner.calls if "apt-get" in c] == [
        ["apt-get", "update"], ["apt-get", "full-upgrade", "-y"]]

    fedora = OSInfo(Family.FEDORA, Tier.SUPPORTED, "fedora", "Fedora")
    (change,) = Upgrade().plan(ctx_for(tmp_path, UPGRADE_ON, fedora))
    assert change.target == "dnf upgrade --refresh"


def test_unknown_family_plan_reports_not_supported_without_traceback(tmp_path):
    ctx = ctx_for(tmp_path, UPGRADE_ON, UNKNOWN)
    (change,) = Upgrade().plan(ctx)  # must not raise KeyError
    assert change.target == "not supported on unknown"


def test_unknown_family_apply_is_not_silent(tmp_path):
    runner = FakeRunner()
    ctx = ctx_for(tmp_path, UPGRADE_ON, UNKNOWN, runner=runner)
    with pytest.raises(NotSupported):
        Upgrade().apply(ctx)
    assert runner.calls == []


# ---- 2.8 NVIDIA reboot notice --------------------------------------------------------

NVIDIA_IDS = ["nvidia-open", "nvidia-utils", "lib32-nvidia-utils", "nvidia-settings"]


def gaming_actions(monkeypatch, ctx, ids):
    monkeypatch.setattr(gaming, "hardware", lambda _ctx: None)
    monkeypatch.setattr(gaming, "gpu_packages", lambda _ctx, _hw: (list(ids), [], []))
    return gaming.build(ctx)


def test_gamemode_ini_current_nvidia_missing_plans_reboot(tmp_path, monkeypatch):
    runner = FakeRunner()  # pacman -Qq: nothing installed
    ctx = ctx_for(tmp_path, "", ARCH, runner=runner)
    ini_path = ctx.home / ".config" / "gamemode.ini"
    ini_path.parent.mkdir(parents=True)
    ini_path.write_text(GAMEMODE_INI)

    actions = gaming_actions(monkeypatch, ctx, NVIDIA_IDS)
    ini = actions[0]
    assert ini.plan(ctx) == []  # file already current: the old carrier action is skipped

    notice = next(a for a in actions if isinstance(a, NvidiaRebootNotice))
    assert notice.reboot is True
    assert not any(a.reboot for a in actions if not isinstance(a, (NvidiaRebootNotice, UbuntuNvidia)))
    changes = notice.plan(ctx)
    assert len(changes) == 1 and "nvidia-open" in changes[0].detail
    notice.apply(ctx)  # no-op, must not touch the system
    assert all(c[:2] != ("sudo", "pacman") for c in runner.calls)


def test_reboot_notice_not_planned_when_driver_installed(tmp_path, monkeypatch):
    runner = FakeRunner().on("pacman", "-Qq", result="\n".join(NVIDIA_IDS) + "\n")
    ctx = ctx_for(tmp_path, "", ARCH, runner=runner)
    actions = gaming_actions(monkeypatch, ctx, NVIDIA_IDS)
    notice = next(a for a in actions if isinstance(a, NvidiaRebootNotice))
    assert notice.plan(ctx) == []


def test_no_notice_without_nvidia(tmp_path, monkeypatch):
    ctx = ctx_for(tmp_path, "", ARCH)
    actions = gaming_actions(monkeypatch, ctx, ["mesa", "vulkan-radeon"])
    assert not any(isinstance(a, NvidiaRebootNotice) for a in actions)
    assert not any(a.reboot for a in actions if not isinstance(a, UbuntuNvidia))
