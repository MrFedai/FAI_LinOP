"""`packages` module: base + selected groups + extra names, one transaction per
source (native repo, AUR, Flatpak). Everything missing is reported up front; a
name whose source the plan cannot know is shown as deferred and resolved at
apply time in D22 order (repo → AUR → Flatpak)."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, register
from fai_linop.core.runner import CommandError
from fai_linop.package.base import PackageManager
from fai_linop.package.providers import Apt, AurHelper, Flatpak, Pacman, native_for
from fai_linop.package.resolve import DEFERRED, Resolution, resolve, settle_aur, settle_repos, wanted_entries
from fai_linop.platform.detect import Family
from fai_linop.system.actions import Multilib


log = logging.getLogger("fai_linop.packages")


def read_custom_file(path: Path) -> list[str]:
    """pacs.txt format: one or more names per line, `#` starts a comment."""
    names = []
    for line in path.read_text().splitlines():
        names += line.split("#", 1)[0].split()
    return names


def multilib_pending(ctx: Context) -> bool:
    """Arch: this run enables multilib (system module), so its packages (steam, lib32-*)
    are not in the package database at plan time."""
    return ctx.os.family is Family.ARCH and ctx.profile.enabled("system") and bool(Multilib().plan(ctx))


def resolution(ctx: Context) -> Resolution:
    if "packages" not in ctx.facts:
        p = ctx.profile
        extra = list(p.get("packages", "extra"))
        custom = p.get("packages", "custom_file")
        if custom:
            path = Path(custom) if Path(custom).is_absolute() else ctx.repo_root / custom
            if path.exists():
                extra += read_custom_file(path)
            else:
                ctx.ui.warn(f"custom package file not found: {path}")
        extra += ctx.facts.get("package_names", [])  # raw names requested by other modules (e.g. kernel headers)
        ids = ctx.facts.get("package_ids", [])       # catalog ids requested by other modules
        ctx.facts["packages"] = resolve(ctx.os, ctx.runner, wanted_entries(p.get("packages", "groups"), ids),
                                        extra, p.get("packages", "flatpak_fallback"), p.get("packages", "aur_helper"),
                                        repos_pending=multilib_pending(ctx))
    return ctx.facts["packages"]


def _settle(ctx: Context, step) -> list[str]:
    """Resolve the deferred names now (D22 order) and report where they went. A dry run
    changed no repository, so they stay deferred (a query would repeat the plan's answer)."""
    res = resolution(ctx)
    if not res.deferred:
        return []
    if ctx.dry_run:
        ctx.ui.info(f"dry run: {len(res.deferred)} deferred package(s) stay unresolved: {', '.join(res.deferred)}")
        return []
    unavailable_before, flatpak_before = len(res.unavailable), list(res.flatpak)
    added = step(res)
    for item in res.unavailable[unavailable_before:]:
        ctx.ui.warn(f"not available, skipped: {item}")
    moved = [f for f in res.flatpak if f not in flatpak_before]
    if moved:
        ctx.ui.info(f"Flatpak fallback (D22): {', '.join(moved)}")
    return added


def _reason(exc: CommandError) -> str:
    """One line for the report: the manager's own error line, else its last output line."""
    lines = [l.strip() for l in (exc.result.stderr or exc.result.stdout or "").splitlines() if l.strip()]
    line = next((l for l in lines if "error" in l.lower() or "not found" in l.lower() or "unable" in l.lower()),
                lines[-1] if lines else f"exit code {exc.result.returncode}")
    return line[:200]


def install_each(ctx: Context, action_id: str, pm: PackageManager, names: list[str]) -> list[str]:
    """ONE transaction first; when it fails, the rest is tried name by name so one bad package
    does not take the others down. Journal: `packages_installed` (those that went in) and
    `packages_failed` (name + reason); failures also go to ctx.facts for the engine's report.
    A dry run installs nothing, so it never falls back. Returns the installed names."""
    try:
        pm.install(names)
    except CommandError as exc:
        if ctx.dry_run:
            raise
        ctx.ui.warn(f"{pm.name}: one transaction failed — trying the {len(names)} package(s) one by one")
        log.warning("batch install by %s failed: %s", pm.name, exc)
        installed, failed = [], []
        for n in names:
            try:
                pm.install([n])
                installed.append(n)
            except CommandError as one:
                failed.append({"name": n, "reason": _reason(one)})
        ctx.journal.write("packages_installed", source=pm.name, names=installed)
        if failed:
            ctx.journal.write("packages_failed", source=pm.name, failed=failed)
            ctx.facts.setdefault("install_failures", []).extend(
                {"action": action_id, "source": pm.name, **f} for f in failed)
        return installed
    ctx.journal.write("packages_installed", source=pm.name, names=names)
    return list(names)


def failed_names(ctx: Context, action_id: str) -> set[str]:
    return {f["name"] for f in ctx.facts.get("install_failures", []) if f["action"] == action_id}


class InstallNative(Action):
    id, title, risk, reversible = "packages.native", "Install packages from the distro repositories", Risk.LOW, Reversible.PARTIAL

    def plan(self, ctx):
        res = resolution(ctx)
        for item in res.unavailable:
            ctx.ui.warn(f"not available, skipped: {item}")
        return [Change("package", n, "repo") for n in res.native] + [Change("package", n, DEFERRED) for n in res.deferred]

    def apply(self, ctx):
        pm = native_for(ctx.os, ctx.runner)
        if isinstance(pm, Apt) and not pm.refresh():
            ctx.ui.warn("apt-get update reported errors (a repository failed) — continuing with the indexes that updated")
        found = _settle(ctx, lambda res: settle_repos(ctx.os, ctx.runner, res))
        if found:
            ctx.ui.info(f"Resolved from the repositories: {', '.join(found)}")
        names = resolution(ctx).native
        install_each(ctx, self.id, pm, names)

    def verify(self, ctx):
        wanted = set(resolution(ctx).native) - failed_names(ctx, self.id)   # failures are reported, not re-raised
        return native_for(ctx.os, ctx.runner).installed(wanted) == wanted


def _aur_work(ctx: Context) -> bool:
    res = resolution(ctx)
    return ctx.os.family is Family.ARCH and bool(res.aur or res.deferred)


class InstallAurHelper(Action):
    id, title, risk, reversible = "packages.aur-helper", "Build the AUR helper", Risk.MEDIUM, Reversible.YES
    requires = ()

    def _helper(self, ctx):
        return AurHelper(ctx.runner, ctx.profile.get("packages", "aur_helper"))

    def plan(self, ctx):
        if not _aur_work(ctx) or self._helper(ctx).present():
            return []
        name = self._helper(ctx).name + "-bin"
        when = "" if resolution(ctx).aur else " — only if a deferred package is AUR-only"
        return [Change("package", "git base-devel", "repo (needed to build from the AUR)" + when),
                Change("package", name, "AUR, built with makepkg" + when)]

    def apply(self, ctx):
        if not _aur_work(ctx):  # every deferred name came from the repos (e.g. multilib): no helper
            ctx.ui.info("AUR helper not needed — the deferred packages were found in the repositories")
            return
        helper = self._helper(ctx).name
        Pacman(ctx.runner).install(["git", "base-devel"])
        with tempfile.TemporaryDirectory(prefix="linop-aur-") as tmp:
            ctx.runner.run(["git", "clone", "--depth", "1", f"https://aur.archlinux.org/{helper}-bin.git", tmp + "/src"])
            ctx.runner.run(["makepkg", "-si", "--noconfirm"], cwd=tmp + "/src", interactive=True)
        ctx.journal.write("packages_installed", source="aur", names=[f"{helper}-bin"])

    def verify(self, ctx):
        return not _aur_work(ctx) or self._helper(ctx).present()


class InstallAur(Action):
    id, title, risk, reversible = "packages.aur", "Build and install AUR packages", Risk.MEDIUM, Reversible.PARTIAL
    requires = ("packages.aur-helper",)

    def plan(self, ctx):
        return [Change("package", n, "AUR") for n in resolution(ctx).aur] if ctx.os.family is Family.ARCH else []

    def deferred(self, ctx):
        return ctx.os.family is Family.ARCH and bool(resolution(ctx).deferred)

    def apply(self, ctx):
        helper = ctx.profile.get("packages", "aur_helper")
        _settle(ctx, lambda res: settle_aur(ctx.runner, res, helper))
        names = resolution(ctx).aur
        if not names:
            return
        install_each(ctx, self.id, AurHelper(ctx.runner, helper), names)

    def verify(self, ctx):
        wanted = set(resolution(ctx).aur) - failed_names(ctx, self.id)
        return Pacman(ctx.runner).installed(wanted) == wanted


def _flatpak_deferred(ctx: Context) -> bool:
    res = resolution(ctx)
    return bool(res.deferred) and res.flatpak_fallback


class SetupFlathub(Action):
    id, title, risk, reversible = "packages.flathub", "Enable Flathub (Flatpak fallback, D22)", Risk.LOW, Reversible.YES

    def plan(self, ctx):
        if not resolution(ctx).flatpak:
            return []
        flat = Flatpak(ctx.runner)
        changes = []
        if not flat.present():
            changes.append(Change("package", "flatpak", "repo"))
        if not flat.has_remote():
            changes.append(Change("repo", "flathub", flat.remote_url))
        return changes

    def deferred(self, ctx):
        return _flatpak_deferred(ctx)

    def apply(self, ctx):
        if not resolution(ctx).flatpak:  # run for deferred names that all resolved elsewhere
            return
        flat = Flatpak(ctx.runner)
        if not flat.present():
            native_for(ctx.os, ctx.runner).install(["flatpak"])
        flat.add_remote()

    def verify(self, ctx):
        return not resolution(ctx).flatpak or Flatpak(ctx.runner).has_remote()


class InstallFlatpak(Action):
    id, title, risk, reversible = "packages.flatpak", "Install Flatpak applications", Risk.LOW, Reversible.YES
    requires = ("packages.flathub",)

    def plan(self, ctx):
        return [Change("flatpak", f, "Flathub") for f in resolution(ctx).flatpak]

    def deferred(self, ctx):
        return _flatpak_deferred(ctx)

    def apply(self, ctx):
        names = resolution(ctx).flatpak
        if not names:
            return
        install_each(ctx, self.id, Flatpak(ctx.runner), names)

    def verify(self, ctx):
        wanted = set(resolution(ctx).flatpak) - failed_names(ctx, self.id)
        return Flatpak(ctx.runner).installed(wanted) == wanted


def request(ctx: Context, ids: list[str] = (), names: list[str] = ()) -> None:
    """Other modules ask for packages; they are installed by the packages module
    in the same transactions (call from a module's build(), before planning)."""
    ctx.facts.setdefault("package_ids", []).extend(i for i in ids if i not in ctx.facts["package_ids"])
    ctx.facts.setdefault("package_names", []).extend(n for n in names if n not in ctx.facts["package_names"])


@register("packages", "Packages", order=20)
def build(ctx: Context) -> list[Action]:
    return [InstallNative(), InstallAurHelper(), InstallAur(), SetupFlathub(), InstallFlatpak()]
