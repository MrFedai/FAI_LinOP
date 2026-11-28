"""`wallpaper.repo` (D25): optional private wallpaper repository, cloned with the
user's own git credentials into ~/Pictures/wallp. No credentials → skipped with a warning."""

from __future__ import annotations

from pathlib import Path

from fai_linop.core.action import Action, Change, Context, Reversible, Risk

WALLPAPER_DIR = Path("Pictures") / "wallp"  # relative to $HOME
SHOWN_DIR = "~/Pictures/wallp"
GIT_ENV = {"GIT_TERMINAL_PROMPT": "0"}  # no password prompt: missing credentials fail fast


def wallpaper_dir(ctx: Context) -> Path:
    return ctx.home / WALLPAPER_DIR


class WallpaperRepo(Action):
    id, title = "wallpaper.repo", f"Wallpaper repository ({SHOWN_DIR})"
    risk, reversible = Risk.LOW, Reversible.PARTIAL

    def plan(self, ctx):
        repo = ctx.profile.get("wallpaper", "repo")
        if not repo:
            return []
        target = wallpaper_dir(ctx)
        if not target.exists():
            return [Change("command", f"git clone {repo} {SHOWN_DIR}")]
        if (target / ".git").exists():
            return [Change("command", f"git -C {SHOWN_DIR} pull --ff-only")]
        ctx.ui.warn(f"wallpaper repo: {SHOWN_DIR} exists but is not a git checkout — left untouched")
        return []

    def apply(self, ctx):
        repo = ctx.profile.get("wallpaper", "repo")
        target = wallpaper_dir(ctx)
        if (target / ".git").exists():
            argv = ["git", "-C", str(target), "pull", "--ff-only"]
        elif target.exists():
            return
        else:
            if not ctx.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
            argv = ["git", "clone", repo, str(target)]
        result = ctx.runner.run(argv, check=False, env=GIT_ENV, timeout=600)
        if not result.ok:
            lines = result.stderr.strip().splitlines()
            reason = lines[0] if lines else f"exit {result.returncode}"
            ctx.ui.warn("wallpaper repo: clone/pull failed (no git credentials?) — skipped; "
                        "background stays as configured")
            ctx.journal.write("wallpaper_repo_skipped", reason=reason)

    def verify(self, ctx):
        return True  # a skipped clone is not an error
