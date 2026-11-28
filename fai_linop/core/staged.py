"""The staged run (D30): one module at a time — ask, show, confirm, apply — then the
next one. Nothing is asked for a module before the previous one has finished, so the
user never approves everything up front and then waits (the v2.5 ArCoN flow).

    StagedRun   walks the registered modules in execution order
    Stage       one module: its questions, its plan, its confirmation, its apply
"""

from __future__ import annotations

from typing import Callable

from fai_linop.core.action import Context, Module, Reversible, Risk, registered_modules
from fai_linop.core.engine import (
    Plan, apply_plan, build_plan, check_unique, end_run, module_actions, optional, show_plan,
)
from fai_linop.core.wizard import Wizard


class Aborted(Exception):
    """The run cannot go on (preflight failed); nothing more is asked or applied."""


class Stage:
    """One module of a staged run."""

    def __init__(self, run: "StagedRun", module: Module, number: int, total: int):
        self.run = run
        self.module = module
        self.number = number
        self.total = total

    def execute(self) -> None:
        ctx, run, name = self.run.ctx, self.run, self.module.name
        ctx.ui.heading(f"{self.number}/{self.total} {self.module.title}")
        if not self._wanted():
            ctx.journal.write("stage", module=name, enabled=False)
            ctx.ui.info("  skipped")
            return
        ctx.journal.write("stage", module=name, enabled=True)
        plan = build_plan(ctx, module_actions(ctx, self.module), run.done)
        run.add(plan)
        show_plan(ctx, plan, nothing="Already set up — nothing to change.")
        if plan.pending and not ctx.dry_run:
            if not self._confirmed(plan):
                for p in plan.pending:
                    p.status, p.message = "not-run", "declined"
                ctx.ui.info("  not applied")
            else:
                run.prepare_once()
        apply_plan(ctx, plan, run.keep_going, run.failed)

    def _wanted(self) -> bool:
        """Ask the module's questions (unless a resumed run already has the answers)."""
        ctx, run, name = self.run.ctx, self.run, self.module.name
        if not optional(self.module):
            return True
        if name in run.answered:
            return ctx.profile.enabled(name)
        enabled = Wizard(ctx.profile, ctx.ui).ask_module(name)
        run.save(ctx.profile)
        return enabled

    def _confirmed(self, plan: Plan) -> bool:
        """Enter applies — except when something risky or one-way is in the plan."""
        careful = any(p.action.risk is Risk.HIGH or p.action.reversible is Reversible.ONE_WAY for p in plan.pending)
        return self.run.ctx.ui.confirm(f"Apply {self.module.title}?", default=not careful)


class StagedRun:
    def __init__(self, ctx: Context, *, save: Callable, prepare: Callable[[], bool],
                 keep_going: bool = False, done: frozenset[str] | set[str] = frozenset(),
                 answered: frozenset[str] | set[str] = frozenset()):
        self.ctx = ctx
        self.save = save                  # save(profile): called after every module's answers
        self._prepare = prepare           # preflight + snapshot; False = stop the run
        self.keep_going = keep_going
        self.done = set(done)             # action ids finished by the run being resumed
        self.answered = set(answered)     # modules already asked in the run being resumed
        self.failed: set[str] = set()     # failed action ids, shared by all stages (`requires`)
        self.plan = Plan()                # every stage's plan, for the final report
        self._prepared = False
        self.aborted = False              # preflight failed: nothing was changed

    def add(self, plan: Plan) -> None:
        self.plan.items.extend(plan.items)
        check_unique([p.action for p in self.plan.items])

    def prepare_once(self) -> None:
        """Preflight and snapshot run once, right before the first real change."""
        if self._prepared:
            return
        if not self._prepare():
            raise Aborted
        self._prepared = True

    def run(self) -> Plan:
        modules = registered_modules()
        try:
            for number, module in enumerate(modules, start=1):
                Stage(self, module, number, len(modules)).execute()
        except Aborted:
            self.aborted = True
            self.ctx.journal.write("run_end", summary={"preflight": "failed"})
            return self.plan
        end_run(self.ctx, self.plan)
        return self.plan
