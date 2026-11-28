"""`system` module (F12, F13, F16, multilib for F19): keyring, mirrors, full
upgrade. Runs first so later installs never produce a partial upgrade."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, register
from fai_linop.core.common import EnableService, WriteFile, read_text
from fai_linop.package.base import NotSupported
from fai_linop.platform.detect import Family

PACMAN_CONF = Path("/etc/pacman.conf")
MIRRORLIST = Path("/etc/pacman.d/mirrorlist")


BLACKARCH_KEY = "4345771566D76030457303332944B067D796237B"   # v2.5 setup.sh 1044, 342-377


def disable_blackarch(conf: str) -> str:
    """Comment out the active [blackarch] section (its header and its own lines only)."""
    out, in_section = [], False
    for line in conf.splitlines(keepends=True):
        stripped = line.strip()
        if re.match(r"^\[blackarch\]$", stripped):
            in_section = True
        elif stripped.startswith("["):
            in_section = False
        out.append("#" + line if in_section and stripped and not stripped.startswith("#") else line)
    return "".join(out)


class KeyringReset(Action):
    id, title = "system.keyring-reset", "Arch: reset the pacman keyring (v2.5 behaviour, opt-in)"
    risk, reversible = Risk.HIGH, Reversible.NO

    def plan(self, ctx):
        if ctx.os.family is not Family.ARCH or not ctx.profile.get("system", "keyring_reset"):
            return []
        return [Change("command", "/etc/pacman.d/gnupg", "delete and re-initialise the keyring")]

    def apply(self, ctx):
        # v2.5 (342-346, 371-377): a [blackarch] section that cannot be verified blocks the
        # keyring rebuild, so it is switched off for the rebuild and switched on afterwards,
        # also when the rebuild fails. pacman.conf goes through FileChanger (backup + journal).
        original = read_text(PACMAN_CONF) or ""
        disabled = disable_blackarch(original)
        toggled = disabled != original
        if toggled:
            ctx.files.write(PACMAN_CONF, disabled.encode(), root=True, mode=0o644)
        try:
            ctx.runner.run(["rm", "-rf", "/etc/pacman.d/gnupg"], sudo=True)
            ctx.runner.run(["pacman-key", "--init"], sudo=True)
            ctx.runner.run(["pacman-key", "--populate", "archlinux"], sudo=True)
        finally:
            if toggled:
                ctx.files.write(PACMAN_CONF, original.encode(), root=True, mode=0o644)
        if toggled:
            # the rebuilt keyring lost the BlackArch key: trust it again (best effort, as v2.5)
            ctx.runner.run(["pacman-key", "--lsign-key", BLACKARCH_KEY], sudo=True, check=False)


def enable_multilib(conf: str) -> str:
    """Uncomment the [multilib] section header and its Include line only."""
    lines, out, in_section = conf.splitlines(keepends=True), [], False
    for line in lines:
        if re.match(r"^#\s*\[multilib\]\s*$", line):
            out.append("[multilib]\n")
            in_section = True
            continue
        if in_section and re.match(r"^#\s*Include\s*=", line):
            out.append(line.lstrip("#").lstrip())
            in_section = False
            continue
        if line.strip().startswith("[") and not line.startswith("#"):
            in_section = False
        out.append(line)
    return "".join(out)


def multilib_needed(ctx: Context) -> bool:
    if ctx.os.family is not Family.ARCH:
        return False
    # BlackArch tools need 32-bit libraries too (v2.5 999-1005): any non-removal mode
    blackarch = ctx.profile.enabled("blackarch") and ctx.profile.get("blackarch", "install") != "remove"
    return ctx.profile.enabled("gaming") or blackarch


class Multilib(WriteFile):
    reversible = Reversible.YES

    def __init__(self):
        super().__init__("system.multilib", "Arch: enable the multilib repository (32-bit libraries for Steam)",
                         PACMAN_CONF, lambda ctx: enable_multilib(read_text(PACMAN_CONF) or ""), root=True,
                         mode=0o644, risk=Risk.MEDIUM, after=self._sync,
                         verify_fn=lambda ctx: re.search(r"^\[multilib\]", read_text(PACMAN_CONF) or "", re.M) is not None)

    @staticmethod
    def _sync(ctx: Context) -> None:
        # a new repository needs a database sync; -Syu (never -Sy alone) avoids a partial upgrade
        ctx.runner.run(["pacman", "-Syu", "--noconfirm"], sudo=True, interactive=True)

    def plan(self, ctx):
        if not multilib_needed(ctx) or re.search(r"^\[multilib\]", read_text(PACMAN_CONF) or "", re.M):
            return []
        changes = super().plan(ctx)
        return [Change("repo", "multilib", "uncomment [multilib] in /etc/pacman.conf (backup kept)")] if changes else []


class Mirrors(Action):
    id, title = "system.mirrors", "Arch: rank mirrors with reflector (mirrorlist backed up)"
    risk, reversible = Risk.LOW, Reversible.YES

    def plan(self, ctx):
        if ctx.os.family is not Family.ARCH or not ctx.profile.get("system", "mirrors"):
            return []
        return [Change("file", str(MIRRORLIST), "20 latest HTTPS mirrors sorted by rate")]

    def apply(self, ctx):
        if not ctx.runner.run(["sh", "-c", "command -v reflector"], mutating=False, check=False).ok:
            ctx.runner.run(["pacman", "-S", "--needed", "--noconfirm", "reflector"], sudo=True, interactive=True)
        with tempfile.TemporaryDirectory(prefix="linop-mirrors-") as tmp:
            out = Path(tmp) / "mirrorlist"
            ctx.runner.run(["reflector", "--protocol", "https", "--latest", "20", "--sort", "rate",
                            "--download-timeout", "5", "--save", str(out)], timeout=600)
            if not ctx.dry_run:
                text = out.read_text()
                if "Server" not in text:
                    raise RuntimeError("reflector produced no servers — mirrorlist left unchanged")
                ctx.files.write(MIRRORLIST, text.encode(), root=True, mode=0o644)


# One transaction per family. Arch: `-Syu` is the full upgrade and the keyring rides in
# the same transaction (a separate `-Sy keyring` + `-Su` would be a partial upgrade).
UPGRADE_COMMANDS = {
    Family.ARCH: "pacman -Syu --needed --noconfirm archlinux-keyring",
    Family.DEBIAN: "apt-get update && apt-get full-upgrade",
    Family.FEDORA: "dnf upgrade --refresh",
}


class Upgrade(Action):
    id, title = "system.upgrade", "Full system upgrade"
    risk, reversible = Risk.MEDIUM, Reversible.NO
    requires = ("system.multilib",)

    def plan(self, ctx):
        if not ctx.profile.get("system", "upgrade"):
            return []
        command = UPGRADE_COMMANDS.get(ctx.os.family)
        if command is None:  # unknown family: report it, no KeyError traceback
            return [Change("command", f"not supported on {ctx.os.family.value}", "no upgrade path for this family")]
        return [Change("command", command)]

    def apply(self, ctx):
        r = ctx.runner
        if ctx.os.family is Family.ARCH:
            r.run(["pacman", "-Syu", "--needed", "--noconfirm", "archlinux-keyring"], sudo=True, interactive=True)
        elif ctx.os.family is Family.DEBIAN:
            env = ["env", "DEBIAN_FRONTEND=noninteractive"]
            r.run([*env, "apt-get", "update"], sudo=True, interactive=True)
            r.run([*env, "apt-get", "full-upgrade", "-y"], sudo=True, interactive=True)
        elif ctx.os.family is Family.FEDORA:
            r.run(["dnf", "upgrade", "--refresh", "-y"], sudo=True, interactive=True)
        else:
            raise NotSupported(f"system upgrade on {ctx.os.family.value} is not supported")


LIBVIRT_PACKAGES = {"qemu", "virt-manager"}


def selected_ids(ctx: Context) -> set[str]:
    """Catalog ids this profile asks for (groups + extra + custom file)."""
    from fai_linop.package.actions import profile_extra_names  # local: package.actions imports this module
    from fai_linop.package.resolve import wanted_entries
    ids = {e.id for e in wanted_entries(ctx.profile.get("packages", "groups"))}
    return ids | set(profile_extra_names(ctx))


def anydesk_native(ctx: Context) -> bool:
    """AnyDesk from the distro / AUR ships `anydesk.service`; the Flatpak has no unit."""
    from fai_linop.package.actions import resolution
    res = resolution(ctx)
    return any(n in group for group in (res.installed, res.native, res.aur, res.deferred)
               for n in ("anydesk", "anydesk-bin"))


def service_actions(ctx: Context) -> list[Action]:
    """F34: enable libvirtd / AnyDesk only when the profile selects the package; nothing otherwise."""
    selected = selected_ids(ctx)
    actions: list[Action] = []
    if selected & LIBVIRT_PACKAGES:
        svc = EnableService("system.libvirtd", "libvirtd.service", "libvirtd (virtual machines)")
        svc.requires = ("packages.native",)
        actions.append(svc)
    if "anydesk" in selected:
        svc = EnableService("system.anydesk", "anydesk.service", "AnyDesk service", when=anydesk_native)
        svc.requires = ("packages.native",)
        actions.append(svc)
    return actions


@register("system", "System", order=10)
def build(ctx: Context):
    return [KeyringReset(), Mirrors(), Multilib(), Upgrade(), *service_actions(ctx)]
