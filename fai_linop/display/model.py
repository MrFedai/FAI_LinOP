"""Monitor model and the D13 rules: best mode per monitor, owner's layout kept.

Identity = vendor + product + serial (never the connector name, which changes
with the driver: eDP-1 vs eDP-2). Only when two connected monitors share that
identity (twins with an empty serial) is the connector added as a distinguishing
tag: "DEL U2419H [DP-1]".
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace

_TAG = re.compile(r"\s*\[[^\]]*\]$")


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: float
    id: str = ""              # backend-specific mode id (Mutter), or "" for Hyprland
    preferred: bool = False

    @property
    def pixels(self) -> int:
        return self.width * self.height

    def label(self) -> str:
        return f"{self.width}x{self.height}@{self.refresh:.2f}"


@dataclass(frozen=True)
class Monitor:
    connector: str
    vendor: str
    product: str
    serial: str
    modes: tuple[Mode, ...]
    current: Mode | None = None
    builtin: bool = False
    display_name: str = ""
    tag: str = ""             # set only for twins (see unique_identities)

    @property
    def base_identity(self) -> str:
        return " ".join(p for p in (self.vendor, self.product, self.serial) if p) or self.connector

    @property
    def identity(self) -> str:
        return f"{self.base_identity} [{self.tag}]" if self.tag else self.base_identity


def unique_identities(monitors: list[Monitor]) -> list[Monitor]:
    """Twins (same vendor/product/serial) get their connector as tag, so every
    monitor stays a separate target and dict keys never collide."""
    counts = Counter(m.base_identity for m in monitors)
    return [replace(m, tag=m.connector) if counts[m.base_identity] > 1 else m for m in monitors]


@dataclass
class Placement:
    """Where a monitor goes: from the profile, or captured from the current state."""
    identity: str
    x: int = 0
    y: int = 0
    scale: float = 1.0
    primary: bool = False
    transform: int = 0
    enabled: bool = True


@dataclass
class Target:
    monitor: Monitor
    candidates: list[Mode]          # best first; later entries are fallbacks (D13)
    placement: Placement

    @property
    def mode(self) -> Mode:
        return self.candidates[0]


def rank_modes(modes: tuple[Mode, ...] | list[Mode], prefer: str = "resolution") -> list[Mode]:
    """Best mode first. prefer=resolution: most pixels, then highest refresh;
    prefer=refresh: highest refresh, then most pixels. Duplicates removed."""
    if prefer == "refresh":
        key = lambda m: (round(m.refresh, 1), m.pixels, m.preferred)
    else:
        key = lambda m: (m.pixels, round(m.refresh, 1), m.preferred)
    seen, ranked = set(), []
    for m in sorted(modes, key=key, reverse=True):
        k = (m.width, m.height, round(m.refresh, 2))
        if k not in seen:
            seen.add(k)
            ranked.append(m)
    return ranked


def plan_layout(monitors: list[Monitor], placements: list[Placement], prefer: str,
                keep_positions: bool = False) -> list[Target]:
    """Combine detected monitors with the wanted placement.

    Positions are kept (stacked, mirrored and offset layouts survive). Unless
    `keep_positions`, a monitor whose width changes with the new mode pushes the
    monitors to its right by the difference, so neighbours keep touching (GNOME
    rejects gaps/overlaps). A monitor without a placement goes right of all others."""
    matched = match_placements(monitors, placements)
    targets, unplaced = [], []
    for i, mon in enumerate(monitors):
        place = matched.get(i)
        if place is not None and not place.enabled:
            continue
        ranked = rank_modes(mon.modes, prefer)
        if not ranked:
            continue
        if place is None:
            unplaced.append(Target(mon, ranked, Placement(mon.identity)))
        else:
            targets.append(Target(mon, ranked, replace(place, identity=mon.identity)))
    if not keep_positions:
        _shift_for_width_changes(targets)
    x = max((t.placement.x + logical_width(t) for t in targets), default=0)
    for t in unplaced:                 # new or unknown monitor: right of everything, not primary
        t.placement.x = x
        x += logical_width(t)
    targets = sorted(targets + unplaced, key=lambda t: (t.placement.x, t.placement.y))
    if targets and not any(t.placement.primary for t in targets):
        builtin = [t for t in targets if t.monitor.builtin]
        (builtin[0] if builtin else targets[0]).placement.primary = True
    return targets


def logical_width(t: Target, mode: Mode | None = None) -> int:
    mode = mode or t.mode
    w = mode.height if t.placement.transform in (1, 3, 5, 7) else mode.width
    return int(round(w / (t.placement.scale or 1.0)))


def _shift_for_width_changes(targets: list[Target]) -> None:
    """Every monitor that starts at or right of another's old right edge moves by
    that monitor's width change. Computed from the old positions, so shifts add up
    along a row; monitors above / below or mirrored stay where they are."""
    old = [(t.placement.x, logical_width(t, t.monitor.current)) for t in targets]
    shift = [0] * len(targets)
    for i, t in enumerate(targets):
        if t.monitor.current is None:          # off: no old width to compare with
            continue
        x0, old_w = old[i]
        delta = logical_width(t) - old_w
        if delta:
            for j in range(len(targets)):
                if j != i and old[j][0] >= x0 + old_w:
                    shift[j] += delta
    for t, dx in zip(targets, shift):
        t.placement.x += dx


def _loose_match(placement_id: str, mon: Monitor) -> bool:
    """Same monitor seen by another compositor: GNOME reports the PNP vendor code
    ("SAM"), Hyprland the full name ("Samsung Electric Company"); product and
    serial agree (case aside). A twin tag is ignored here."""
    pid = _TAG.sub("", placement_id).strip().lower()
    if pid == mon.base_identity.lower():
        return True
    tail = " ".join(p for p in (mon.product, mon.serial) if p).lower()
    return bool(mon.product) and (pid == tail or pid.endswith(" " + tail))


def match_placements(monitors: list[Monitor], placements: list[Placement]) -> dict[int, Placement]:
    """Monitor index → its placement. Each placement is used once; passes in
    order: exact identity, connector (old profiles / no EDID), loose identity."""
    found: dict[int, Placement] = {}
    used: set[int] = set()
    tests = (lambda p, m: p.identity == m.identity,
             lambda p, m: p.identity == m.connector,
             lambda p, m: _loose_match(p.identity, m))
    for test in tests:
        for i, mon in enumerate(monitors):
            if i in found:
                continue
            for j, place in enumerate(placements):
                if j not in used and test(place, mon):
                    found[i] = place
                    used.add(j)
                    break
    return found


def placements_from_state(monitors: list[Monitor], logical: list[dict]) -> list[Placement]:
    """Current layout → placements (used by `linop display capture`)."""
    out = []
    by_connector = {m.connector: m for m in monitors}
    for lm in logical:
        for conn in lm["connectors"]:
            mon = by_connector.get(conn)
            if mon:
                out.append(Placement(mon.identity, lm["x"], lm["y"], lm["scale"], lm["primary"], lm.get("transform", 0)))
    return out


def placements_from_profile(entries: list[dict]) -> list[Placement]:
    out = []
    for e in entries:
        x, y = 0, 0
        pos = str(e.get("position", "0,0")).replace("x", ",")
        if "," in pos:
            x, y = (int(v) for v in pos.split(",", 1))
        out.append(Placement(e["id"], x, y, float(e.get("scale", 1.0)), bool(e.get("primary", False)),
                             int(e.get("transform", 0)), bool(e.get("enabled", True))))
    return out


def placement_to_profile(p: Placement) -> dict:
    entry = {"id": p.identity, "position": f"{p.x},{p.y}", "scale": p.scale, "primary": p.primary}
    if p.transform:
        entry["transform"] = p.transform
    return entry
