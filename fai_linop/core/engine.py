"""Plan → show → confirm → apply → verify, with the journal as the source of
truth for resume and the final report (D6, D14)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, registered_modules
from fai_linop.recovery.journal import DONE, FAILED, SKIPPED, STARTED

log = logging.getLogger("fai_linop.engine")


@dataclass
class PlannedAction:
    action: Action
    changes: list[Change]
    status: str = "pending"  # pending | done | partial | skipped | failed | not-run
    message: str = ""
    deferred: bool = False   # no planned change, but work may appear at apply time (runs anyway)


PARTIAL = "partial"   # journal status: the action ran, some of its packages failed (re-run on resume)


def has_partial(plan: "Plan") -> bool:
    return any(p.status == "partial" for p in plan.items)


def human_size(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return ""


def size_summary(ctx: Context, plan: Plan) -> str | None:
    """Total download / installed size of the repo packages in the plan (v2.5 printed this, D14).
    AUR, Flatpak and deferred names have no size here → counted as unknown. A failing query
    leaves everything "unknown"; it never fails the plan."""
    from fai_linop.package.providers import native_for
    changes = [c for p in plan.items for c in p.changes if c.kind in ("package", "flatpak")]
    deferred = sum(1 for p in plan.items if p.deferred)
    if not changes and not deferred:
        return None
    repo = [c.target for c in changes if c.kind == "package" and c.detail == "repo"]
    sizes = {}
    if repo:
        try:
            sizes = native_for(ctx.os, ctx.runner).sizes(repo)
        except Exception:  # noqa: BLE001
            log.exception("size query failed")
    down = [d for d, _ in sizes.values() if d is not None]
    inst = [i for _, i in sizes.values() if i is not None]
    unknown = len(changes) - sum(1 for n in repo if sizes.get(n, (None, None)) != (None, None))
    unknown = max(unknown, 0)
    parts = []
    if down or inst:
        parts.append(f"download {human_size(sum(down))}, installed {human_size(sum(inst))}")
    if unknown or deferred or not parts:
        parts.append(f"{unknown} package(s) size unknown" + (" (deferred names resolve at apply)" if deferred else ""))
    return "Size: " + "; ".join(parts)


DEFERRED_NOTE ="deferred: runs only if needed, resolved at apply"


@dataclass
class Plan:
    items: list[PlannedAction] = field(default_factory=list)

    @property
    def pending(self) -> list[PlannedAction]:
        return [p for p in self.items if (p.changes or p.deferred) and p.status == "pending"]

    @property
    def one_way(self) -> list[PlannedAction]:
        return [p for p in self.pending if p.action.reversible is Reversible.ONE_WAY]


def collect_actions(ctx: Context) -> list[Action]:
    actions: list[Action] = []
    for module in registered_modules():
        if module.name in _schema_modules() and not ctx.profile.enabled(module.name):
            continue
        for action in module.build(ctx):
            action.module = action.module or module.name
            actions.append(action)
    ids = [a.id for a in actions]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"duplicate action ids: {sorted(dupes)}")
    return actions


def _schema_modules() -> set[str]:
    from fai_linop.core.profile import SCHEMA
    return set(SCHEMA["modules"])


def build_plan(ctx: Context, actions: list[Action], done: set[str] = frozenset()) -> Plan:
    plan = Plan()
    for action in actions:
        if action.id in done:
            plan.items.append(PlannedAction(action, [], "done", "completed in a previous run"))
            continue
        try:
            changes = action.plan(ctx)
            deferred = not changes and action.deferred(ctx)
        except Exception as exc:  # any planning error (CommandError, OSError, KeyError…) is a failed row
            log.exception("planning %s failed", action.id)
            first = str(exc).splitlines()[0] if str(exc) else ""
            detail = f"{type(exc).__name__}: {first}" if first else type(exc).__name__
            plan.items.append(PlannedAction(action, [], "failed", f"planning failed: {detail}"))
            continue
        if deferred:
            plan.items.append(PlannedAction(action, [], "pending", DEFERRED_NOTE, deferred=True))
            continue
        status = "pending" if changes else "skipped"
        plan.items.append(PlannedAction(action, changes, status, "" if changes else "already in the desired state"))
    return plan


def show_plan(ctx: Context, plan: Plan) -> None:
    ui = ctx.ui
    rows, kinds = [], {}
    for p in plan.items:
        if p.deferred and p.status == "pending":
            rows.append((p.action.module, p.action.title, DEFERRED_NOTE, p.action.risk.value, p.action.reversible.value))
            continue
        if not p.changes:
            continue
        for c in p.changes:
            kinds[c.kind] = kinds.get(c.kind, 0) + 1
        groups: dict[str, list[str]] = {}
        for c in p.changes:
            groups.setdefault(f"{c.kind}: {c.detail}" if c.detail and c.kind in ("package", "flatpak") else c.kind, []).append(
                c.target if c.kind in ("package", "flatpak") else f"{c.target} ({c.detail})" if c.detail else c.target)
        what = "\n".join(f"[bold]{k}[/bold] ({len(v)}): {', '.join(v)}" for k, v in groups.items())
        rows.append((p.action.module, p.action.title, what, p.action.risk.value, p.action.reversible.value))
    failed = [p for p in plan.items if p.status == "failed"]
    if not rows:
        if failed:
            for p in failed:
                ui.error(f"{p.action.title} ({p.action.id}): {p.message}")
            ui.error(f"{len(failed)} action(s) could not be planned — fix the error(s) above.")
        else:
            ui.ok("Nothing to do — the system already matches the profile.")
        return
    ui.table("FAI_LinOP plan", ("Module", "Action", "Changes", "Risk", "Reversible"), rows)
    ui.info("Totals: " + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    size_line = size_summary(ctx, plan)
    if size_line:
        ui.info(size_line)
    for p in plan.one_way:
        ui.warn(f"ONE-WAY: {p.action.title} runs third-party code and cannot be rolled back")
    for p in plan.pending:
        if p.action.risk is Risk.HIGH:
            ui.warn(f"HIGH RISK: {p.action.title}")
    for p in failed:
        ui.error(f"PLANNING FAILED: {p.action.title} ({p.action.id}): {p.message}")
    skipped = [p for p in plan.items if p.status in ("skipped", "done")]
    if skipped:
        ui.info(f"{len(skipped)} action(s) already satisfied")


def execute(ctx: Context, plan: Plan, keep_going: bool = False) -> Plan:
    journal = ctx.journal
    failed: set[str] = {p.action.id for p in plan.items if p.status == "failed"}
    for p in plan.items:
        a = p.action
        if p.status in ("done", "skipped"):
            journal.write("action", id=a.id, status=SKIPPED if p.status == "skipped" else DONE,
                          reason=p.message)
            continue
        if p.status == "failed":
            journal.write("action", id=a.id, status=FAILED, error=p.message)
            if not keep_going:
                break
            continue
        blocked = [r for r in a.requires if r in failed]
        if blocked:
            p.status, p.message = "not-run", f"requires failed action(s): {', '.join(blocked)}"
            journal.write("action", id=a.id, status=SKIPPED, reason=p.message)
            continue
        journal.write("action", id=a.id, status=STARTED, title=a.title, dry_run=ctx.dry_run,
                      changes=[c.__dict__ for c in p.changes])
        try:
            a.apply(ctx)
            if not ctx.dry_run and not a.verify(ctx):
                raise RuntimeError("verification failed")
        except Exception as exc:  # an action failure must never abort the journal
            log.exception("action %s failed", a.id)
            p.status, p.message = "failed", str(exc).splitlines()[0] if str(exc) else type(exc).__name__
            failed.add(a.id)
            journal.write("action", id=a.id, status=FAILED, error=str(exc))
            ctx.ui.error(f"{a.title}: {p.message}")
            if not keep_going:
                break
            continue
        lost = [f for f in ctx.facts.get("install_failures", []) if f["action"] == a.id]
        if lost:   # the action ran, but some packages did not install (D14: report, don't hide)
            p.status, p.message = "partial", f"{len(lost)} package(s) failed to install"
            journal.write("action", id=a.id, status=PARTIAL, dry_run=ctx.dry_run, failed=[f["name"] for f in lost])
            ctx.ui.warn(f"{a.title}: {p.message}")
            continue
        p.status = "done"
        journal.write("action", id=a.id, status=DONE, dry_run=ctx.dry_run)
        ctx.ui.ok(a.title + (" (dry run)" if ctx.dry_run else ""))
    for p in plan.items:
        if p.status == "pending":
            p.status = "not-run"
    journal.write("run_end", summary={s: sum(1 for p in plan.items if p.status == s)
                                      for s in ("done", "partial", "skipped", "failed", "not-run")})
    return plan


def report(ctx: Context, plan: Plan) -> int:
    """Final summary built from real statuses (v2.5 printed success unconditionally, F31)."""
    rows = [(p.action.module, p.action.title, p.status, p.message) for p in plan.items]
    if rows:
        ctx.ui.table(f"Run {ctx.journal.run_id}", ("Module", "Action", "Status", "Note"), rows)
    failed = [p for p in plan.items if p.status == "failed"]
    lost = ctx.facts.get("install_failures", [])
    if lost:
        ctx.ui.table("Packages that failed to install", ("Source", "Package", "Reason"),
                     [(f["source"], f["name"], f["reason"]) for f in lost])
        ctx.ui.warn(f"{len(lost)} package(s) failed to install; the others were installed.")
    if any(p.action.reboot and p.status == "done" for p in plan.items):
        ctx.ui.warn("A reboot is required for some changes to take effect.")
    if failed:
        ctx.ui.error(f"{len(failed)} action(s) failed — log: {ctx.journal.run_dir}")
        ctx.ui.info("Continue later with: linop resume")
        return 1
    return 0
