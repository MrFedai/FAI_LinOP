"""`optimization` (F27) and `cleanup` (F32) modules — hardware-aware (TRIM only
on SSD, Bluetooth only with an adapter, ZRAM only when none is active)."""

from __future__ import annotations

import re
from pathlib import Path

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, register
from fai_linop.core.common import EnableService, WriteFile, read_text
from fai_linop.gaming.actions import hardware
from fai_linop.package.actions import request
from fai_linop.platform.detect import Family

ZRAM_CONF = "[zram0]\nzram-size = min(ram, 8192)\ncompression-algorithm = zstd\n"
BT_CONF = Path("/etc/bluetooth/main.conf")


def _items(ctx: Context) -> list[str]:
    return ctx.profile.get("optimization", "items")


def _bluetooth(text: str) -> str:
    if re.search(r"^AutoEnable\s*=\s*true", text, re.M):
        return text
    if re.search(r"^#?\s*AutoEnable\s*=.*$", text, re.M):
        return re.sub(r"^#?\s*AutoEnable\s*=.*$", "AutoEnable=true", text, count=1, flags=re.M)
    return text.replace("[Policy]\n", "[Policy]\nAutoEnable=true\n", 1) if "[Policy]" in text else text + "\n[Policy]\nAutoEnable=true\n"


def _zram_active(ctx: Context) -> bool:
    return "zram" in ctx.runner.run(["swapon", "--show", "--noheadings"], mutating=False, check=False).stdout


class Zram(WriteFile):
    requires = ("packages.native",)

    def __init__(self):
        super().__init__("optimization.zram", "ZRAM swap (zstd, min(RAM, 8 GiB))", Path("/etc/systemd/zram-generator.conf"),
                         lambda c: ZRAM_CONF, root=True, mode=0o644, risk=Risk.MEDIUM, reboot=True)

    def plan(self, ctx):
        # an existing zram setup (or config) is the user's: never overwritten
        if _zram_active(ctx) or self.path.exists():
            return []
        return super().plan(ctx)


@register("optimization", "Optimization", order=90)
def build(ctx: Context):
    items, hw, actions = _items(ctx), hardware(ctx), []
    if "fstrim" in items:
        actions.append(EnableService("optimization.fstrim", "fstrim.timer", "Weekly SSD TRIM (fstrim.timer)",
                                     when=lambda c: hardware(c).root_is_ssd))
    if "bluetooth" in items and Path("/sys/class/bluetooth").exists() and BT_CONF.exists():
        actions.append(WriteFile("optimization.bluetooth-conf", "Bluetooth: power on at boot",
                                 BT_CONF, lambda c: _bluetooth(read_text(BT_CONF) or ""), root=True, mode=0o644))
        actions.append(EnableService("optimization.bluetooth", "bluetooth.service", "Enable Bluetooth"))
    if "zram" in items:
        request(ctx, ids=["zram-generator"])
        actions.append(Zram())
    if "ananicy" in items and ctx.os.family is Family.ARCH:
        request(ctx, ids=["ananicy-cpp"])
        svc = EnableService("optimization.ananicy", "ananicy-cpp", "ananicy-cpp (automatic process priorities)")
        svc.requires = ("packages.native",)
        actions.append(svc)
    return actions


PACMAN_CACHE = Path("/var/cache/pacman/pkg")
APT_CACHE = Path("/var/cache/apt/archives")


def simulate_removal(ctx: Context, names: list[str] | None = None) -> list[str]:
    """Packages a removal WOULD take (apt/dnf), from a read-only simulation. `names=None`
    simulates `autoremove`. Arch is not simulated here (callers use `pacman -Qdtq`)."""
    r = ctx.runner
    if ctx.os.family is Family.DEBIAN:
        argv = ["apt-get", "--simulate", *(["remove", *names] if names is not None else ["autoremove"])]
        out = r.run(argv, mutating=False, check=False).stdout
        found = [m.group(1) for m in re.finditer(r"^Remv\s+(\S+)", out, re.M)]
    elif ctx.os.family is Family.FEDORA:
        argv = ["dnf", *(["remove", *names] if names is not None else ["autoremove"]), "--assumeno"]
        out = r.run(argv, mutating=False, check=False).stdout  # --assumeno exits non-zero by design
        found, section = [], False
        for line in out.splitlines():
            if line.startswith("Transaction Summary"):
                break
            if line.startswith("Removing"):
                section = True
            elif section and line.startswith(" ") and len(line.split()) >= 4:
                found.append(line.split()[0])
    else:
        return []
    return sorted(dict.fromkeys(found))


class Orphans(Action):
    id, title, risk, reversible = "cleanup.orphans", "Remove orphaned packages (list shown)", Risk.MEDIUM, Reversible.PARTIAL

    def _list(self, ctx) -> list[str]:
        if ctx.os.family is Family.ARCH:
            return ctx.runner.run(["pacman", "-Qdtq"], mutating=False, check=False).stdout.split()
        return simulate_removal(ctx)

    def plan(self, ctx):
        if not ctx.profile.get("cleanup", "orphans"):
            return []
        self._names = self._list(ctx)
        return [Change("package-remove", n, "orphan") for n in self._names]

    def apply(self, ctx):
        names = getattr(self, "_names", None)
        if names is None:
            names = self._names = self._list(ctx)
        if not names:
            return
        ctx.journal.write("packages_removed", names=names)
        if ctx.os.family is Family.ARCH:
            ctx.runner.run(["pacman", "-Rns", "--noconfirm", *names], sudo=True, interactive=True)
        elif ctx.os.family is Family.DEBIAN:
            ctx.runner.run(["env", "DEBIAN_FRONTEND=noninteractive", "apt-get", "remove", "-y", *names], sudo=True, interactive=True)
        else:
            ctx.runner.run(["dnf", "remove", "-y", *names], sudo=True, interactive=True)


class Cache(Action):
    id, risk, reversible = "cleanup.cache", Risk.LOW, Reversible.NO
    title = "Package cache"

    def plan(self, ctx):
        mode = ctx.profile.get("cleanup", "cache")
        if mode == "none":
            return []
        if ctx.os.family is Family.ARCH:
            detail = "paccache -rk2 (keep 2 versions, downgrade stays possible)" if mode == "trim" else \
                "pacman -Scc (ENTIRE cache, no downgrade — v2.5 behaviour)"
        else:
            detail = "autoclean" if mode == "trim" else "clean all"
        return [Change("command", "package cache", detail)]

    def apply(self, ctx):
        mode, r = ctx.profile.get("cleanup", "cache"), ctx.runner
        if ctx.os.family is Family.ARCH:
            if mode == "trim":
                r.run(["paccache", "-rk2"], sudo=True)
            else:
                # -Scc asks twice (packages, then sync databases); --noconfirm answers the
                # default "N", so nothing is deleted while the command still exits 0.
                r.run(["pacman", "-Scc"], sudo=True, input="y\ny\n")
        elif ctx.os.family is Family.DEBIAN:
            r.run(["apt-get", "autoclean" if mode == "trim" else "clean"], sudo=True)
        else:
            r.run(["dnf", "clean", "packages" if mode == "trim" else "all"], sudo=True)

    def verify(self, ctx):
        if ctx.profile.get("cleanup", "cache") != "purge" or ctx.runner.dry_run:
            # trim keeps versions on purpose: there is no fixed "empty" state to look at.
            return True
        if ctx.os.family is Family.ARCH:
            return not any(PACMAN_CACHE.glob("*.pkg.tar.*"))
        if ctx.os.family is Family.DEBIAN:
            return not any(APT_CACHE.glob("*.deb"))
        # dnf cache path differs by version (/var/cache/dnf vs libdnf5); `dnf clean all`
        # failing already raised in run(), so there is nothing reliable left to inspect.
        return True


@register("cleanup", "Cleanup", order=95)
def build_cleanup(ctx: Context):
    if ctx.os.family is Family.ARCH and ctx.profile.get("cleanup", "cache") == "trim":
        request(ctx, ids=["pacman-contrib"])
    return [Orphans(), Cache()]
