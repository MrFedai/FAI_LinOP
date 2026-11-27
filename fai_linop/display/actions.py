"""`display` module (D13): best mode per monitor, the owner's layout kept.

The layout comes from `[[display.monitor]]` in the profile; when the profile
has none, the CURRENT layout is kept (only modes change). `linop display capture`
writes the current layout into the profile."""

from __future__ import annotations

import os
from dataclasses import replace

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, register
from fai_linop.display import hyprland
from fai_linop.display.gnome import DisplayConfigError, GnomeDisplay, JeepneyBus, snapshot
from fai_linop.display.model import (Mode, Monitor, Target, placements_from_profile, placements_from_state,
                                 plan_layout)


def gnome_session(env=os.environ) -> bool:
    return "GNOME" in env.get("XDG_CURRENT_DESKTOP", "").upper() and bool(env.get("DBUS_SESSION_BUS_ADDRESS"))


def session_backend(warn=None) -> GnomeDisplay | None:
    """Mutter's DisplayConfig on the session bus, or None outside a GNOME session."""
    if not gnome_session():
        return None
    try:
        return GnomeDisplay(JeepneyBus())
    except DisplayConfigError as exc:
        if warn:
            warn(f"display: {exc}")
        return None


def gnome_backend(ctx: Context) -> GnomeDisplay | None:
    if "gnome_display" not in ctx.facts:
        ctx.facts["gnome_display"] = session_backend(ctx.ui.warn)
    return ctx.facts["gnome_display"]


def restore_layout(event: dict, backend: GnomeDisplay | None = None) -> str:
    """Rollback of `GnomeMonitors`: apply the `display_before` layout again through
    Mutter. Returns one report line; a failure starts with "FAILED"."""
    backend = backend or session_backend()
    if backend is None:
        return ("FAILED monitor layout not restored: no GNOME session "
                "(run `linop rollback` again from your desktop session)")
    try:
        backend.restore(event)
    except Exception as exc:        # D-Bus / Mutter errors: reported, the rest of the rollback goes on
        return f"FAILED monitor layout not restored: {exc}"
    return "restored monitor layout (modes and positions from before the run)"


def targets_for(ctx: Context, monitors: list[Monitor], logical: list[dict]) -> list[Target]:
    entries = ctx.profile.get("display", "monitor")
    placements = placements_from_profile(entries) if entries else placements_from_state(monitors, logical)
    return plan_layout(monitors, placements, ctx.profile.get("display", "prefer"),
                       keep_positions=bool(entries))


def _changes(targets: list[Target], monitors: list[Monitor], logical: list[dict]) -> list[Change]:
    changes = []
    current_pos = {}
    by_conn = {m.connector: m for m in monitors}
    for lm in logical:
        for c in lm["connectors"]:
            if c in by_conn:
                current_pos[by_conn[c].identity] = (lm["x"], lm["y"], lm["scale"], lm["primary"])
    for t in targets:
        cur = t.monitor.current
        if cur is None or (cur.width, cur.height, round(cur.refresh, 1)) != (t.mode.width, t.mode.height, round(t.mode.refresh, 1)):
            changes.append(Change("setting", t.monitor.identity,
                                  f"mode {cur.label() if cur else 'off'} -> {t.mode.label()}"))
        p = t.placement
        if current_pos.get(t.monitor.identity) != (p.x, p.y, p.scale, p.primary):
            changes.append(Change("setting", t.monitor.identity,
                                  f"position {p.x},{p.y} scale {p.scale:g}{' primary' if p.primary else ''}"))
    return changes


class GnomeMonitors(Action):
    id, title = "display.gnome", "Monitors: best mode, keep layout (GNOME)"
    risk, reversible = Risk.MEDIUM, Reversible.YES

    def plan(self, ctx):
        backend = gnome_backend(ctx)
        if backend is None:
            return []
        _, monitors, logical = backend.read()
        self._targets = targets_for(ctx, monitors, logical)
        return _changes(self._targets, monitors, logical)

    def apply(self, ctx):
        backend = gnome_backend(ctx)
        _, monitors_before, logical_before = backend.read()
        # read back by `linop rollback` (restore_layout)
        ctx.journal.write("display_before", **snapshot(monitors_before, logical_before))
        applied = backend.apply(self._targets, dry_run=ctx.dry_run)
        for t in self._targets:
            if applied[t.monitor.identity] != t.mode:
                ctx.ui.warn(f"{t.monitor.identity}: {t.mode.label()} did not work, using {applied[t.monitor.identity].label()}")
        ctx.journal.write("display_applied", modes={k: v.label() for k, v in applied.items()})


def hyprland_block(ctx: Context) -> str:
    """Monitor block for hyprland.conf (D18). Uses live Hyprland data when running,
    otherwise connector names + Hyprland's own best-mode keyword."""
    prefer = ctx.profile.get("display", "prefer")
    monitors = hyprland.read(ctx.runner)
    if monitors:
        entries = ctx.profile.get("display", "monitor")
        placements = placements_from_profile(entries) if entries else []
        targets = plan_layout(monitors, placements, prefer, keep_positions=bool(entries))
        return hyprland.render_block(hyprland.monitor_lines(targets, prefer))
    backend = gnome_backend(ctx)
    lines = []
    if backend is not None:
        _, gmons, logical = backend.read()
        entries = ctx.profile.get("display", "monitor")
        placements = placements_from_profile(entries) if entries else placements_from_state(gmons, logical)
        # laid out with the real modes (a new monitor goes right of the others), written
        # with Hyprland's keyword; Mutter's display-name is not Hyprland's `desc:`
        targets = plan_layout(gmons, placements, prefer, keep_positions=True)
        auto = [replace(t, monitor=replace(t.monitor, display_name=""), candidates=[Mode(0, 0, 0.0, "auto")])
                for t in targets]
        lines = hyprland.monitor_lines(auto, prefer)
    else:
        lines = ["# monitors could not be detected; Hyprland picks the preferred mode",
                 "monitor=,preferred,auto,1"]
    return hyprland.render_block(lines)


@register("display", "Monitors", order=30)
def build(ctx: Context) -> list[Action]:
    if gnome_backend(ctx) is None:
        ctx.ui.info("display: no GNOME session detected — monitor modes are left unchanged")
        return []
    return [GnomeMonitors()]
