"""Turn wanted packages into an install plan: native repo / AUR / Flatpak /
unavailable. Nothing is installed by guess (fixes v2.5 #15: unknown names were
sent to yay).

D22 order for a name: distro repo → AUR (Arch) → Flatpak → reported unavailable.
When the plan cannot know a name's source without side effects — a repository
this run enables (Arch multilib), an apt index that is empty or old, an AUR
helper that is not built yet — the name is *deferred* and resolved again at
apply time, in the same order (V301 2.2). Planning never syncs a database."""

from __future__ import annotations

from dataclasses import dataclass, field

from fai_linop.core.runner import Runner
from fai_linop.package import catalog as cat
from fai_linop.package.providers import Apt, AurHelper, Flatpak, native_for
from fai_linop.platform.detect import Family, OSInfo

DEFERRED = "deferred: resolved at apply"


@dataclass
class Resolution:
    native: list[str] = field(default_factory=list)       # to install from the distro repos
    aur: list[str] = field(default_factory=list)          # to build from the AUR
    flatpak: list[str] = field(default_factory=list)      # Flathub ids (D22 fallback)
    installed: list[str] = field(default_factory=list)    # already present (idempotency)
    unavailable: list[str] = field(default_factory=list)  # reported, never guessed
    deferred: dict[str, cat.Entry | None] = field(default_factory=dict)  # name → catalog entry (None: user name)
    flatpak_fallback: bool = True

    @property
    def empty(self) -> bool:
        return not (self.native or self.aur or self.flatpak or self.deferred)


def wanted_entries(groups: list[str], ids: list[str] = ()) -> list[cat.Entry]:
    catalog = cat.load()
    seen, out = set(), []
    for g in ["base", *groups]:
        for e in cat.group(g, catalog):
            if e.id not in seen:
                seen.add(e.id)
                out.append(e)
    for pid in ids:
        if pid in catalog and pid not in seen:
            seen.add(pid)
            out.append(catalog[pid])
    return out


def resolve(os: OSInfo, runner: Runner, entries: list[cat.Entry], extra: list[str] = (),
            flatpak_fallback: bool = True, aur_helper: str = "yay", repos_pending: bool = False) -> Resolution:
    """`repos_pending`: the repository set changes before installation (e.g. multilib is
    enabled by this run), so a name missing from the repos now is deferred, not decided."""
    res = Resolution(flatpak_fallback=flatpak_fallback)
    pm = native_for(os, runner)
    wanted: dict[str, cat.Entry | None] = {}
    aur_names: list[str] = []
    for e in entries:
        name = e.native(os)
        if name.startswith("aur:"):
            aur_names.append(name[4:])
        elif name:
            wanted[name] = e
        elif flatpak_fallback and e.flatpak:
            res.flatpak.append(e.flatpak)
        else:
            res.unavailable.append(f"{e.id} (not packaged for {os.id})")
    for name in extra:  # user packages (profile `extra`, custom file): must exist somewhere
        wanted.setdefault(name, None)

    present = pm.installed(list(wanted) + aur_names)
    res.installed += sorted(present)
    res.aur = [n for n in aur_names if n not in present]
    todo = [n for n in wanted if n not in present]
    if isinstance(pm, Apt) and todo and not pm.index_current():
        repos_pending = True  # empty / old index: apt-get update runs first at apply
    in_repo = pm.available(todo)
    res.native = [n for n in todo if n in in_repo]
    missing = {n: wanted[n] for n in todo if n not in in_repo}

    if repos_pending:
        res.deferred = missing
    elif os.family is Family.ARCH:
        helper = AurHelper(runner, aur_helper)
        if helper.present():
            _aur_or_fallback(res, helper, missing)
        else:
            res.deferred = missing  # checked against the AUR once the helper is built
    else:
        _fallback(res, missing)
    _drop_installed_flatpaks(res, runner)
    return res


def settle_repos(os: OSInfo, runner: Runner, res: Resolution) -> list[str]:
    """Apply time, after the repository set changed (multilib synced, apt-get update):
    deferred names found in the repos join `native`. On Arch the rest wait for the AUR
    step (`settle_aur`); elsewhere they fall back to Flatpak / unavailable now."""
    if not res.deferred:
        return []
    pm = native_for(os, runner)
    names = list(res.deferred)
    present = pm.installed(names)
    in_repo = pm.available([n for n in names if n not in present])
    res.installed += sorted(present)
    found = [n for n in names if n in in_repo and n not in present]
    res.native += [n for n in found if n not in res.native]
    rest = {n: e for n, e in res.deferred.items() if n not in present and n not in in_repo}
    if os.family is Family.ARCH:
        res.deferred = rest
    else:
        res.deferred = {}
        _fallback(res, rest)
        _drop_installed_flatpaks(res, runner)
    return found


def settle_aur(runner: Runner, res: Resolution, aur_helper: str = "yay") -> list[str]:
    """Apply time, the AUR helper exists: deferred names it finds go to `aur`, the rest
    to Flatpak / unavailable. Returns the names added to `aur`."""
    rest, res.deferred = res.deferred, {}
    before = len(res.aur)
    if rest:
        _aur_or_fallback(res, AurHelper(runner, aur_helper), rest)
        _drop_installed_flatpaks(res, runner)
    return res.aur[before:]


def _aur_or_fallback(res: Resolution, helper: AurHelper, missing: dict[str, cat.Entry | None]) -> None:
    found = helper.available(list(missing)) if missing else set()
    res.aur += [n for n in missing if n in found and n not in res.aur]
    _fallback(res, {n: e for n, e in missing.items() if n not in found})


def _fallback(res: Resolution, missing: dict[str, cat.Entry | None]) -> None:
    for n, e in missing.items():
        if e is not None and res.flatpak_fallback and e.flatpak:
            res.flatpak.append(e.flatpak)
        else:
            res.unavailable.append(n if e is None else f"{e.id} ({n} not in the repositories)")


def _drop_installed_flatpaks(res: Resolution, runner: Runner) -> None:
    if res.flatpak:
        have = Flatpak(runner).installed(res.flatpak)
        res.installed += sorted(h for h in have if h not in res.installed)
        res.flatpak = [f for f in dict.fromkeys(res.flatpak) if f not in have]
