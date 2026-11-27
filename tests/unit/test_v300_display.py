"""v3.0.0 O6 (V300 1.9): monitors — the layout is kept, twins do not collide, the
GNOME-captured layout reaches Hyprland with the right `desc:`, and rollback puts the
`display_before` layout back through (fake) Mutter. UNIT TESTED only: real screens
are NATIVE (owner)."""

from __future__ import annotations

import io
import json
from dataclasses import replace

from rich.console import Console

from fai_linop.core.action import Context
from fai_linop.core.profile import Profile
from fai_linop.core.runner import FakeRunner, Result
from fai_linop.core.ui import UI
from fai_linop.display import hyprland
from fai_linop.display.actions import GnomeMonitors, hyprland_block
from fai_linop.display.gnome import PERSISTENT, VERIFY, DisplayConfigError, GnomeDisplay
from fai_linop.display.model import Mode, Monitor, placements_from_state, plan_layout
from fai_linop.platform.detect import Family, OSInfo, Tier
from fai_linop.recovery.backup import FileChanger, restore_files
from fai_linop.recovery.journal import Journal

ARCH = OSInfo(Family.ARCH, Tier.SUPPORTED, "arch", "Arch Linux")

HDMI_MODES = (Mode(1920, 1080, 60.0, "a"), Mode(1920, 1080, 180.0, "b"))
EDP_MODES = (Mode(1920, 1200, 60.0, "c"), Mode(2560, 1600, 165.0, "d", True))
TWIN_MODES = (Mode(1920, 1080, 60.0, "t60"), Mode(1920, 1080, 75.0, "t75"))


class FakeMutter:
    """Mutter's DisplayConfig: state as (monitors, logical); a persistent apply
    changes modes and positions; `reject` makes Mutter refuse persistent applies."""

    def __init__(self, monitors, logical, reject=False):
        self.monitors, self.logical, self.reject, self.calls = list(monitors), list(logical), reject, []

    def get_current_state(self):
        raw = []
        for m in self.monitors:
            modes = [(md.id, md.width, md.height, md.refresh, 1.0, [1.0],
                      {"is-current": ("b", md == m.current), "is-preferred": ("b", md.preferred)}) for md in m.modes]
            raw.append(((m.connector, m.vendor, m.product, m.serial), modes, {"is-builtin": ("b", m.builtin)}))
        lraw = [(lm["x"], lm["y"], lm["scale"], lm.get("transform", 0), lm["primary"],
                 [(c, "", "", "") for c in lm["connectors"]], {}) for lm in self.logical]
        return (7, raw, lraw, {})

    def apply_monitors_config(self, serial, method, logical, props):
        self.calls.append((method, logical))
        if method == VERIFY:
            return
        if self.reject:
            raise DisplayConfigError("org.gnome.Mutter.DisplayConfig.Error: Logical monitors not adjacent")
        mode_of = {conn: mid for (*_, mons) in logical for (conn, mid, _) in mons}
        self.monitors = [replace(m, current=next((md for md in m.modes if md.id == mode_of.get(m.connector)), None))
                         for m in self.monitors]
        self.logical = [{"x": x, "y": y, "scale": s, "transform": t, "primary": p, "connectors": [c for c, _, _ in mons]}
                        for (x, y, s, t, p, mons) in logical]


def _ctx(tmp_path, runner=None, profile_text="", display=None):
    (tmp_path / "p.toml").write_text(profile_text)
    j = Journal.create(tmp_path / "runs", run_id="r1")
    runner = runner or FakeRunner()
    ctx = Context(runner, Profile.load(tmp_path / "p.toml"), ARCH, j, FileChanger(j, runner),
                  UI(Console(file=io.StringIO()), interactive=False), tmp_path, tmp_path)
    ctx.facts["gnome_display"] = display
    return ctx


# ---- layout kept ------------------------------------------------------------------------

def test_vertical_layout_is_kept_when_modes_change():
    mons = [Monitor("HDMI-A-1", "SAM", "Odyssey", "H1", HDMI_MODES, HDMI_MODES[0]),
            Monitor("eDP-1", "BOE", "0x0bca", "", EDP_MODES, EDP_MODES[0], builtin=True)]
    logical = [{"x": 0, "y": 0, "scale": 1.0, "primary": False, "connectors": ["HDMI-A-1"]},
               {"x": 0, "y": 1080, "scale": 1.0, "primary": True, "connectors": ["eDP-1"]}]   # laptop below
    targets = plan_layout(mons, placements_from_state(mons, logical), "resolution")
    assert {(t.monitor.connector, t.placement.x, t.placement.y) for t in targets} == {
        ("HDMI-A-1", 0, 0), ("eDP-1", 0, 1080)}


def test_mirrored_layout_is_kept():
    mons = [Monitor("HDMI-A-1", "SAM", "Odyssey", "H1", HDMI_MODES, HDMI_MODES[0]),
            Monitor("DP-1", "DEL", "P2419H", "X", HDMI_MODES, HDMI_MODES[0])]
    logical = [{"x": 0, "y": 0, "scale": 1.0, "primary": True, "connectors": ["HDMI-A-1", "DP-1"]}]
    targets = plan_layout(mons, placements_from_state(mons, logical), "resolution")
    assert [(t.placement.x, t.placement.y) for t in targets] == [(0, 0), (0, 0)]


def test_only_monitors_right_of_a_wider_one_move():
    # row: eDP (1920 -> 2560 wide) | HDMI ; a third monitor above the eDP stays put
    top = Monitor("DP-1", "DEL", "P2419H", "X", HDMI_MODES, HDMI_MODES[0])
    mons = [Monitor("eDP-1", "BOE", "0x0bca", "", EDP_MODES, EDP_MODES[0], builtin=True),
            Monitor("HDMI-A-1", "SAM", "Odyssey", "H1", HDMI_MODES, HDMI_MODES[0]), top]
    logical = [{"x": 0, "y": 1080, "scale": 1.0, "primary": True, "connectors": ["eDP-1"]},
               {"x": 1920, "y": 1080, "scale": 1.0, "primary": False, "connectors": ["HDMI-A-1"]},
               {"x": 0, "y": 0, "scale": 1.0, "primary": False, "connectors": ["DP-1"]}]
    targets = {t.monitor.connector: t.placement for t in plan_layout(mons, placements_from_state(mons, logical),
                                                                         "resolution")}
    assert (targets["eDP-1"].x, targets["HDMI-A-1"].x, targets["DP-1"].x) == (0, 2560, 0)


def test_unknown_monitor_goes_right_of_the_others_not_to_a_million():
    mons = [Monitor("HDMI-A-1", "SAM", "Odyssey", "H1", HDMI_MODES, HDMI_MODES[0]),
            Monitor("DP-9", "NEW", "Thing", "1", HDMI_MODES, HDMI_MODES[0])]
    logical = [{"x": 0, "y": 0, "scale": 1.0, "primary": True, "connectors": ["HDMI-A-1"]}]
    for keep in (False, True):
        targets = plan_layout(mons, placements_from_state(mons, logical), "resolution", keep_positions=keep)
        assert [(t.monitor.connector, t.placement.x) for t in targets] == [("HDMI-A-1", 0), ("DP-9", 1920)]


# ---- twins ---------------------------------------------------------------------------------

def _twins():
    return [Monitor("DP-1", "DEL", "U2419H", "", TWIN_MODES, TWIN_MODES[0]),
            Monitor("DP-2", "DEL", "U2419H", "", TWIN_MODES, TWIN_MODES[0])]


def test_twin_monitors_are_two_targets_in_gnome():
    logical = [{"x": 0, "y": 0, "scale": 1.0, "primary": True, "connectors": ["DP-1"]},
               {"x": 1920, "y": 0, "scale": 1.0, "primary": False, "connectors": ["DP-2"]}]
    bus = FakeMutter(_twins(), logical)
    display = GnomeDisplay(bus)
    _, mons, logical = display.read()
    assert [m.identity for m in mons] == ["DEL U2419H [DP-1]", "DEL U2419H [DP-2]"]
    targets = plan_layout(mons, placements_from_state(mons, logical), "resolution")
    assert [(t.monitor.connector, t.placement.x, t.mode.id) for t in targets] == [("DP-1", 0, "t75"),
                                                                                    ("DP-2", 1920, "t75")]
    applied = display.apply(targets, dry_run=False)
    assert len(applied) == 2 and all(m.current.id == "t75" for m in bus.monitors)


def test_twin_monitors_in_hyprland_use_connectors():
    out = json.dumps([{"name": n, "description": f"Dell Inc. DELL U2419H ({n})", "make": "Dell Inc.",
                       "model": "DELL U2419H", "serial": "", "width": 1920, "height": 1080, "refreshRate": 60.0,
                       "availableModes": ["1920x1080@60.00Hz", "1920x1080@75.00Hz"]} for n in ("DP-1", "DP-2")])
    mons = hyprland.read(FakeRunner().on("hyprctl", result=out))
    assert len({m.identity for m in mons}) == 2
    lines = hyprland.monitor_lines(plan_layout(mons, [], "resolution"), "resolution")
    assert lines[:2] == ["monitor=DP-1,1920x1080@75.00,0x0,1", "monitor=DP-2,1920x1080@75.00,1920x0,1"]


# ---- GNOME-captured layout -> Hyprland -----------------------------------------------------

GNOME_PROFILE = """[display]
monitor = [
  { id = "SAM Odyssey G5 H1", position = "0,0", scale = 1.0, primary = false },
  { id = "BOE 0x0bca", position = "1920,-260", scale = 1.0, primary = true },
]
"""

HYPRCTL = json.dumps([
    {"name": "HDMI-A-1", "description": "Samsung Electric Company Odyssey G5 H1 (HDMI-A-1)",
     "make": "Samsung Electric Company", "model": "Odyssey G5", "serial": "H1", "width": 1920, "height": 1080,
     "refreshRate": 60.0, "availableModes": ["1920x1080@180.00Hz", "1920x1080@60.00Hz"]},
    {"name": "eDP-2", "description": "BOE 0x0BCA (eDP-2)", "make": "BOE", "model": "0x0BCA", "serial": "",
     "width": 2560, "height": 1600, "refreshRate": 60.0, "availableModes": ["2560x1600@165.00Hz", "2560x1600@60.00Hz"]},
])


def test_gnome_captured_layout_reaches_hyprland_with_desc(tmp_path):
    ctx = _ctx(tmp_path, FakeRunner().on("hyprctl", result=HYPRCTL), GNOME_PROFILE)
    block = hyprland_block(ctx)
    assert "monitor=desc:Samsung Electric Company Odyssey G5 H1,1920x1080@180.00,0x0,1\n" in block
    assert "monitor=desc:BOE 0x0BCA,2560x1600@165.00,1920x-260,1\n" in block
    assert "(HDMI-A-1)" not in block and "(eDP-2)" not in block and "1000000" not in block


def test_hyprland_block_from_gnome_session_places_new_monitor_beside(tmp_path):
    mons = [Monitor("HDMI-A-1", "SAM", "Odyssey G5", "H1", HDMI_MODES, HDMI_MODES[0]),
            Monitor("DP-3", "NEW", "Thing", "9", HDMI_MODES, HDMI_MODES[0])]
    bus = FakeMutter(mons, [{"x": 0, "y": 0, "scale": 1.0, "primary": True, "connectors": ["HDMI-A-1"]}])
    ctx = _ctx(tmp_path, FakeRunner().on("hyprctl", result=Result((), 1)), GNOME_PROFILE, GnomeDisplay(bus))
    block = hyprland_block(ctx)
    assert "monitor=HDMI-A-1,highres,0x0,1\n" in block and "monitor=DP-3,highres,1920x0,1\n" in block
    assert "1000000" not in block


# ---- rollback ------------------------------------------------------------------------------

def _owner_bus(**kw):
    mons = [Monitor("HDMI-A-1", "SAM", "Odyssey", "H1", HDMI_MODES, HDMI_MODES[0]),
            Monitor("eDP-1", "BOE", "0x0bca", "", EDP_MODES, EDP_MODES[0], builtin=True)]
    logical = [{"x": 0, "y": 0, "scale": 1.0, "transform": 0, "primary": False, "connectors": ["HDMI-A-1"]},
               {"x": 1920, "y": -260, "scale": 1.0, "transform": 0, "primary": True, "connectors": ["eDP-1"]}]
    return FakeMutter(mons, logical, **kw)


def _apply_display(tmp_path, bus):
    ctx = _ctx(tmp_path, display=GnomeDisplay(bus))
    action = GnomeMonitors()
    assert action.plan(ctx)
    action.apply(ctx)
    return ctx


def test_rollback_puts_display_before_back_into_mutter(tmp_path):
    bus = _owner_bus()
    before = (bus.monitors, bus.logical)
    ctx = _apply_display(tmp_path, bus)
    assert [m.current.id for m in bus.monitors] == ["b", "d"]       # best modes applied
    report = restore_files(ctx.journal, FakeRunner(), display=GnomeDisplay(bus))
    assert report == ["restored monitor layout (modes and positions from before the run)"]
    assert [m.current.id for m in bus.monitors] == [m.current.id for m in before[0]] == ["a", "c"]
    assert [(lm["x"], lm["y"], lm["primary"], lm["connectors"]) for lm in bus.logical] == \
        [(lm["x"], lm["y"], lm["primary"], lm["connectors"]) for lm in before[1]]
    assert bus.calls[-1][0] == PERSISTENT
    rb = [ev for ev in ctx.journal.events() if ev["event"] == "rollback"][-1]
    assert rb["ok"] and rb["failed"] == 0


def test_rollback_reports_failed_line_when_mutter_refuses(tmp_path):
    bus = _owner_bus()
    ctx = _apply_display(tmp_path, bus)
    f = tmp_path / "a.conf"
    f.write_text("old\n")
    ctx.files.write(f, b"new\n")                                   # a file change after the display change
    bus.reject = True
    report = restore_files(ctx.journal, FakeRunner(), display=GnomeDisplay(bus))
    assert report[0] == f"restored {f}" and f.read_text() == "old\n"   # the rest still runs
    assert report[1].startswith("FAILED monitor layout not restored: ") and "not adjacent" in report[1]
    rb = [ev for ev in ctx.journal.events() if ev["event"] == "rollback"][-1]
    assert not rb["ok"] and rb["failed"] == 1


def test_rollback_without_gnome_session_is_failed_not_silent(tmp_path, monkeypatch):
    ctx = _apply_display(tmp_path, _owner_bus())
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    report = restore_files(ctx.journal, FakeRunner())
    assert len(report) == 1 and report[0].startswith("FAILED monitor layout not restored: no GNOME session")


def test_rollback_refuses_when_a_monitor_is_gone(tmp_path):
    bus = _owner_bus()
    ctx = _apply_display(tmp_path, bus)
    bus.monitors = bus.monitors[:1]                                  # laptop lid closed / unplugged
    bus.logical = [{"x": 0, "y": 0, "scale": 1.0, "primary": True, "connectors": ["HDMI-A-1"]}]
    calls = len(bus.calls)
    report = restore_files(ctx.journal, FakeRunner(), display=GnomeDisplay(bus))
    assert report[0].startswith("FAILED") and "BOE 0x0bca is not connected" in report[0]
    assert len(bus.calls) == calls                                   # nothing half-applied


def test_old_journal_without_modes_is_failed(tmp_path):
    j = Journal.create(tmp_path / "runs", run_id="old")
    j.write("display_before", logical=[{"x": 0, "y": 0, "scale": 1.0, "transform": 0, "primary": True,
                                        "connectors": ["HDMI-A-1"]}])
    report = restore_files(j, FakeRunner(), display=GnomeDisplay(_owner_bus()))
    assert report[0].startswith("FAILED") and "did not record the monitor modes" in report[0]
