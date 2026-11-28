"""Smart Factory Reset (F10, D19): explicit lists, protected packages enforced
for configs too, verified backups first, typed confirmation. User data (browser
profiles, editor settings, chat logins) is never touched — v2.5 deleted
~/.config/google-chrome, ~/.config/Code and ~/.config/discord."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from fai_linop.core.action import Action, Change, Context, Reversible, Risk
from fai_linop.core.common import read_text
from fai_linop.core.paths import current_user
from fai_linop.package import catalog as cat
from fai_linop.package.actions import profile_extra_names
from fai_linop.package.providers import native_for
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.recovery.backup import backup_dir, dconf_user

# v2.5 PROTECTED_PKGS (tests/golden/v25/packages.json) — never removed
# Kept as catalog ids (fai_linop/data/packages.toml) and translated to each distro's own name
# (V300 1.10): Fedora's `vim-enhanced` and Debian's `network-manager-gnome` stay too.
PROTECTED_IDS = {"base-devel", "network-manager-applet", "wget", "curl", "git", "vim", "neovim", "kitty",
                 "alacritty", "terminator", "gnome-terminal", "zsh", "fish"}
# core names that are not in the catalog, in each family's own spelling
PROTECTED_CORE = {
    Family.ARCH: {"base", "linux", "linux-firmware", "sudo", "pacman", "yay", "systemd", "systemd-libs", "glibc",
                  "networkmanager", "wpa_supplicant", "openssh", "nano", "bluez", "bluez-utils", "konsole",
                  "xfce4-terminal", "bash"},
    Family.DEBIAN: {"sudo", "apt", "dpkg", "systemd", "libc6", "network-manager", "wpasupplicant",
                    "openssh-client", "openssh-server", "nano", "bluez", "konsole", "xfce4-terminal", "bash",
                    "linux-image-amd64", "linux-image-generic", "linux-firmware", "build-essential"},
    Family.FEDORA: {"sudo", "dnf", "rpm", "systemd", "systemd-libs", "glibc", "NetworkManager", "wpa_supplicant",
                    "openssh", "openssh-clients", "openssh-server", "nano", "bluez", "konsole", "xfce4-terminal",
                    "bash", "kernel", "kernel-core", "linux-firmware"},
}


def protected_names(os_info: OSInfo) -> set[str]:
    """Native names of every protected package on this distro."""
    catalog = cat.load()
    names = {catalog[i].native(os_info).removeprefix("aur:") for i in PROTECTED_IDS if i in catalog}
    return (names | PROTECTED_CORE.get(os_info.family, set())) - {""}


# Arch view, kept for callers that import the old name
PROTECTED = protected_names(OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux"))
# config paths FAI_LinOP itself writes or that belong to packages it installs (relative to $HOME)
# (configs of PROTECTED packages — kitty, alacritty, terminator, nvim, vim, git — are kept: D19)
CONFIGS = (".config/hypr", ".config/waybar", ".config/wofi", ".config/fastfetch", ".config/btop",
           ".config/gamemode.ini", ".config/starship.toml", ".oh-my-zsh")
GROUPS = ("essentials", "media", "cyber", "remote", "privacy", "power", "hyprland", "gaming", "security")


class ResetConfigs(Action):
    id, title, risk, reversible = "reset.configs", "Remove FAI_LinOP-managed config files (backup first)", Risk.HIGH, Reversible.YES

    def plan(self, ctx):
        self._paths = [ctx.home / p for p in CONFIGS if (ctx.home / p).exists()]
        return [Change("file-remove", str(p), "backed up") for p in self._paths]

    def apply(self, ctx):
        for path in self._paths:
            if ctx.dry_run:
                continue
            if backup_dir(ctx.journal, path) is None:
                continue
            shutil.rmtree(path) if path.is_dir() and not path.is_symlink() else path.unlink()


class ResetPackages(Action):
    id, title, risk, reversible = "reset.packages", "Uninstall packages FAI_LinOP installs (protected list kept)", Risk.HIGH, Reversible.PARTIAL

    def plan(self, ctx):
        names = {e.native(ctx.os).removeprefix("aur:") for g in GROUPS for e in cat.group(g)} - {""}
        names |= set(profile_extra_names(ctx))   # packages.extra + packages.custom_file
        names -= protected_names(ctx.os)
        self._names = sorted(native_for(ctx.os, ctx.runner).installed(names))
        ctx.facts["reset_packages_planned"] = list(self._names)
        return [Change("package-remove", n) for n in self._names]

    def apply(self, ctx):
        ctx.journal.write("packages_removed", names=self._names)
        native_for(ctx.os, ctx.runner).remove(self._names)


class ResetOrphans(Action):
    """Sweep packages left unneeded by ResetPackages — by name, never a blanket autoremove."""
    id, title, risk, reversible = "reset.orphans", "Remove orphaned packages left behind (listed by name)", Risk.HIGH, Reversible.NO

    def plan(self, ctx):
        gone = set(ctx.facts.get("reset_packages_planned", []))   # ResetPackages removes these anyway
        self._names = sorted(native_for(ctx.os, ctx.runner).orphans() - protected_names(ctx.os) - gone)
        return [Change("package-remove", n, "orphan") for n in self._names]

    def apply(self, ctx):
        if not self._names:
            return
        ctx.journal.write("orphans_removed", names=self._names)
        native_for(ctx.os, ctx.runner).remove(self._names)


class ResetShell(Action):
    id, title, risk, reversible = "reset.shell", "Switch the login shell back to bash and remove ~/.zshrc (backed up)", Risk.HIGH, Reversible.PARTIAL

    def plan(self, ctx):
        from fai_linop.terminal.actions import ChangeShell
        changes = []
        self._bash = None
        if os.path.basename(ChangeShell.login_shell(ctx)) != "bash":
            self._bash = ChangeShell.shell_path("bash", read_text(Path("/etc/shells")) or "")
            changes.append(Change("setting", "login shell -> bash", "chsh"))
        self._zshrc = ctx.home / ".zshrc"
        if self._zshrc.exists() or self._zshrc.is_symlink():
            changes.append(Change("file-remove", str(self._zshrc), "backed up"))
        else:
            self._zshrc = None
        return changes

    def apply(self, ctx):
        from fai_linop.terminal.actions import ChangeShell
        current = ChangeShell.login_shell(ctx)
        if os.path.basename(current) != "bash":
            path = self._bash
            if path is None:
                if not ctx.dry_run:
                    raise RuntimeError("bash is not listed in /etc/shells")
                path = "/usr/bin/bash"
            ctx.journal.write("login_shell", user=current_user(), previous=current, new=path)
            ctx.runner.run(["chsh", "-s", path, current_user()], sudo=True)
        if self._zshrc is not None and not ctx.dry_run:
            if backup_dir(ctx.journal, self._zshrc) is not None:
                self._zshrc.unlink()


class ResetGnome(Action):
    id, title, risk, reversible = "reset.gnome", "Reset all GNOME settings (full dconf backup first)", Risk.HIGH, Reversible.YES

    def plan(self, ctx):
        return [Change("setting", "dconf /", "reset to defaults")]

    def apply(self, ctx):
        dump = dconf_user(ctx.runner, "dump", "/", mutating=False).stdout  # user db only
        path = ctx.journal.backup_dir / "dconf-full.ini"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dump)
        ctx.journal.write("dconf_backup", path=str(path))
        ctx.runner.run(["dconf", "reset", "-f", "/"])


def reset_actions(uninstall: bool, gnome: bool, shell: bool = False) -> list[Action]:
    actions: list[Action] = [ResetConfigs()]
    if uninstall:
        actions += [ResetPackages(), ResetOrphans()]
    if gnome:
        actions.append(ResetGnome())
    if shell:
        actions.append(ResetShell())
    return actions
