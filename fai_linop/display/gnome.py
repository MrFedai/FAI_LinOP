"""GNOME/Mutter backend (D13): read and apply monitor configuration through
org.gnome.Mutter.DisplayConfig — Mutter writes monitors.xml itself when the
method is "persistent". Dry runs use method "verify": Mutter checks the
configuration without applying it.

The D-Bus connection is behind `Bus` so tests can use a fake.
"""

from __future__ import annotations

from typing import Any, Protocol

from fai_linop.display.model import Mode, Monitor, Target, unique_identities

VERIFY, TEMPORARY, PERSISTENT = 0, 1, 2
_PATH = "/org/gnome/Mutter/DisplayConfig"
_NAME = "org.gnome.Mutter.DisplayConfig"


class DisplayConfigError(RuntimeError):
    pass


class Bus(Protocol):
    def get_current_state(self) -> tuple: ...
    def apply_monitors_config(self, serial: int, method: int, logical: list, props: dict) -> None: ...


class JeepneyBus:
    """Real session-bus client (needs a GNOME session: DBUS_SESSION_BUS_ADDRESS)."""

    def __init__(self):
        from jeepney import DBusAddress
        from jeepney.io.blocking import open_dbus_connection
        self._addr = DBusAddress(_PATH, bus_name=_NAME, interface=_NAME)
        try:
            self._conn = open_dbus_connection(bus="SESSION")
        except Exception as exc:  # no session bus: not in a desktop session
            raise DisplayConfigError(f"no D-Bus session bus: {exc}") from exc

    def _call(self, method: str, signature: str | None = None, body: tuple = ()) -> tuple:
        from jeepney import new_method_call
        from jeepney.wrappers import DBusErrorResponse
        msg = new_method_call(self._addr, method, signature, body) if signature else new_method_call(self._addr, method)
        try:
            reply = self._conn.send_and_get_reply(msg, timeout=15)
        except DBusErrorResponse as exc:
            raise DisplayConfigError(str(exc)) from exc
        if reply.header.message_type.name == "error":
            raise DisplayConfigError(str(reply.body))
        return reply.body

    def get_current_state(self) -> tuple:
        return self._call("GetCurrentState")

    def apply_monitors_config(self, serial, method, logical, props):
        self._call("ApplyMonitorsConfig", "uua(iiduba(ssa{sv}))a{sv}", (serial, method, logical, props))


def _prop(props: dict, key: str, default: Any = None) -> Any:
    value = props.get(key, default)
    # jeepney returns variants as (signature, value)
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[1]
    return value


def parse_state(state: tuple) -> tuple[int, list[Monitor], list[dict]]:
    serial, monitors_raw, logical_raw, _props = state
    monitors = []
    for (connector, vendor, product, serial_no), modes_raw, props in monitors_raw:
        modes, current = [], None
        for mode_id, width, height, refresh, _pref_scale, _scales, mprops in modes_raw:
            mode = Mode(int(width), int(height), float(refresh), str(mode_id),
                        bool(_prop(mprops, "is-preferred", False)))
            modes.append(mode)
            if _prop(mprops, "is-current", False):
                current = mode
        monitors.append(Monitor(connector, vendor, product, serial_no, tuple(modes), current,
                                bool(_prop(props, "is-builtin", False)), str(_prop(props, "display-name", ""))))
    monitors = unique_identities(monitors)
    logical = []
    for x, y, scale, transform, primary, mons, _p in logical_raw:
        logical.append({"x": int(x), "y": int(y), "scale": float(scale), "transform": int(transform),
                        "primary": bool(primary), "connectors": [m[0] for m in mons]})
    return int(serial), monitors, logical


def build_config(targets: list[Target], modes: dict[str, Mode] | None = None) -> list:
    """ApplyMonitorsConfig logical-monitor list; `modes` overrides a target's mode (fallback)."""
    logical = []
    for t in targets:
        mode = (modes or {}).get(t.monitor.identity, t.mode)
        p = t.placement
        logical.append((p.x, p.y, float(p.scale), p.transform, p.primary,
                        [(t.monitor.connector, mode.id, {})]))
    return logical


class GnomeDisplay:
    name = "gnome"

    def __init__(self, bus: Bus):
        self.bus = bus

    def read(self) -> tuple[int, list[Monitor], list[dict]]:
        return parse_state(self.bus.get_current_state())

    def apply(self, targets: list[Target], dry_run: bool) -> dict[str, Mode]:
        """Apply best modes; on a mode that does not become active, fall back to
        the next candidate for that monitor. Returns the modes in effect."""
        serial, _, _ = self.read()
        chosen = {t.monitor.identity: t.mode for t in targets}
        self.bus.apply_monitors_config(serial, VERIFY if dry_run else PERSISTENT, build_config(targets, chosen), {})
        if dry_run:
            return chosen
        for _attempt in range(max((len(t.candidates) for t in targets), default=1)):
            _, monitors, _ = self.read()
            current = {m.identity: m.current for m in monitors}
            wrong = [t for t in targets if not _same(current.get(t.monitor.identity), chosen[t.monitor.identity])]
            if not wrong:
                return chosen
            for t in wrong:
                idx = t.candidates.index(chosen[t.monitor.identity])
                if idx + 1 >= len(t.candidates):
                    raise DisplayConfigError(f"{t.monitor.identity}: no working mode found")
                chosen[t.monitor.identity] = t.candidates[idx + 1]
            serial, _, _ = self.read()
            self.bus.apply_monitors_config(serial, PERSISTENT, build_config(targets, chosen), {})
        raise DisplayConfigError("monitor configuration did not settle")

    def restore(self, before: dict) -> None:
        """Rollback (D6): apply a layout recorded by `snapshot` again — positions,
        scale, transform, primary and the mode of every monitor — persistently, and
        check that Mutter kept it. Raises DisplayConfigError with the reason; nothing
        is applied when the recorded layout no longer fits the connected monitors."""
        logical_before, monitors_before = before.get("logical") or [], before.get("monitors")
        if not logical_before or monitors_before is None:
            raise DisplayConfigError("this run did not record the monitor modes; restore them in Settings → Displays")
        serial, monitors, _ = self.read()
        by_id = {m.identity: m for m in monitors}
        recorded = {b["connector"]: b for b in monitors_before}
        if new := sorted(set(by_id) - {b["identity"] for b in monitors_before}):
            raise DisplayConfigError(f"{', '.join(new)} was connected after the run; restore by hand")
        chosen: dict[str, tuple[Monitor, Mode]] = {}
        for conn in (c for lm in logical_before for c in lm["connectors"]):
            b = recorded.get(conn)
            if b is None or not b.get("mode"):
                raise DisplayConfigError(f"{conn}: mode before the run was not recorded")
            mon = by_id.get(b["identity"])
            if mon is None:
                raise DisplayConfigError(f"{b['identity']} is not connected any more")
            want = b["mode"]
            mode = next((md for md in mon.modes if md.id == want["id"]), None) or next(
                (md for md in mon.modes if _same(md, Mode(want["width"], want["height"], want["refresh"]))), None)
            if mode is None:
                raise DisplayConfigError(f"{mon.identity}: mode {want['width']}x{want['height']}@{want['refresh']:.2f} "
                                         "is not offered any more")
            chosen[conn] = (mon, mode)
        config = [(int(lm["x"]), int(lm["y"]), float(lm["scale"]), int(lm.get("transform", 0)), bool(lm["primary"]),
                   [(chosen[c][0].connector, chosen[c][1].id, {}) for c in lm["connectors"]])
                  for lm in logical_before]
        self.bus.apply_monitors_config(serial, PERSISTENT, config, {})
        _, monitors, logical = self.read()
        current = {m.identity: m.current for m in monitors}
        where = {c: (lm["x"], lm["y"], lm["scale"], lm["primary"]) for lm in logical for c in lm["connectors"]}
        wrong = []
        for lm in logical_before:
            for c in lm["connectors"]:
                mon, mode = chosen[c]
                if not _same(current.get(mon.identity), mode) or \
                        where.get(mon.connector) != (int(lm["x"]), int(lm["y"]), float(lm["scale"]), bool(lm["primary"])):
                    wrong.append(mon.identity)
        if wrong:
            raise DisplayConfigError(f"Mutter did not keep the restored layout for {', '.join(wrong)}")


def _mode_record(mode: Mode | None) -> dict | None:
    if mode is None:
        return None
    return {"id": mode.id, "width": mode.width, "height": mode.height, "refresh": mode.refresh}


def snapshot(monitors: list[Monitor], logical: list[dict]) -> dict:
    """Journal record of the current layout, enough for `GnomeDisplay.restore`."""
    return {"logical": logical,
            "monitors": [{"connector": m.connector, "identity": m.identity, "mode": _mode_record(m.current)}
                         for m in monitors]}


def _same(a: Mode | None, b: Mode) -> bool:
    return a is not None and (a.width, a.height, round(a.refresh, 1)) == (b.width, b.height, round(b.refresh, 1))
