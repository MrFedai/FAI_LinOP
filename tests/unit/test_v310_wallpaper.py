"""v3.1.0 O4a: wallpaper repository (3.1, D25). FakeRunner; nothing touches the system."""

from __future__ import annotations

from conftest import REPO
from test_phase5 import ctx_for

from fai_linop.core.runner import FakeRunner, Result
from fai_linop.desktop.gnome import build, render_gno
from fai_linop.desktop.wallpaper import WallpaperRepo

REPO_URL = "https://github.com/MrFedai/wallp.git"
PROFILE = f'[wallpaper]\nrepo = "{REPO_URL}"\n'


def _out(ctx) -> str:
    return ctx.ui.console.file.getvalue()


def test_empty_repo_plan_is_empty(tmp_path):
    ctx = ctx_for(tmp_path)
    assert WallpaperRepo().plan(ctx) == []


def test_clone_runs_as_user_without_prompt(tmp_path):
    seen = {}

    class Spy(FakeRunner):
        def run(self, argv, **kw):
            seen.update(kw)
            return super().run(argv, **kw)

    ctx = ctx_for(tmp_path, PROFILE, runner=Spy())
    action = WallpaperRepo()
    assert [c.target for c in action.plan(ctx)] == [f"git clone {REPO_URL} ~/Pictures/wallp"]
    action.apply(ctx)
    target = ctx.home / "Pictures" / "wallp"
    assert ctx.runner.calls == [("git", "clone", REPO_URL, str(target))]
    assert seen["env"] == {"GIT_TERMINAL_PROMPT": "0"} and not seen.get("sudo")
    assert target.parent.is_dir() and action.verify(ctx)


def test_existing_checkout_is_pulled(tmp_path):
    ctx = ctx_for(tmp_path, PROFILE)
    target = ctx.home / "Pictures" / "wallp"
    (target / ".git").mkdir(parents=True)
    action = WallpaperRepo()
    assert [c.target for c in action.plan(ctx)] == ["git -C ~/Pictures/wallp pull --ff-only"]
    action.apply(ctx)
    assert ctx.runner.calls == [("git", "-C", str(target), "pull", "--ff-only")]


def test_non_git_dir_is_left_alone_with_warning(tmp_path):
    ctx = ctx_for(tmp_path, PROFILE)
    (ctx.home / "Pictures" / "wallp").mkdir(parents=True)
    assert WallpaperRepo().plan(ctx) == []
    assert "not a git checkout" in _out(ctx)


def test_clone_failure_warns_and_journals_without_raising(tmp_path):
    runner = FakeRunner().on("git", "clone", result=Result((), 128, "", "fatal: could not read Username\nmore"))
    ctx = ctx_for(tmp_path, PROFILE, runner=runner)
    action = WallpaperRepo()
    action.apply(ctx)
    assert "skipped" in _out(ctx)
    log = list(tmp_path.rglob("*.jsonl"))
    text = "".join(p.read_text() for p in log)
    assert "wallpaper_repo_skipped" in text and "could not read Username" in text
    assert action.verify(ctx)


def test_build_puts_repo_first_only_when_set(tmp_path):
    ctx = ctx_for(tmp_path, PROFILE)
    assert build(ctx)[0].id == "wallpaper.repo"
    (tmp_path / "b").mkdir()
    ctx2 = ctx_for(tmp_path / "b")
    assert all(a.id != "wallpaper.repo" for a in build(ctx2))


def test_relative_file_resolves_into_clone(tmp_path):
    text = (REPO / "configs" / "gno.conf").read_text()
    ctx = ctx_for(tmp_path, '[wallpaper]\nmode = "file"\nfile = "x.jpg"\n')
    assert f"picture-uri='file://{ctx.home}/Pictures/wallp/x.jpg'" in render_gno(ctx, text)


def test_absolute_path_unchanged_and_none_is_black(tmp_path):
    text = (REPO / "configs" / "gno.conf").read_text()
    ctx = ctx_for(tmp_path, '[wallpaper]\nmode = "file"\nfile = "/data/w.jpg"\n')
    assert "picture-uri='file:///data/w.jpg'" in render_gno(ctx, text)
    (tmp_path / "b").mkdir()
    black = render_gno(ctx_for(tmp_path / "b"), text)
    assert "picture-options='none'" in black and "picture-uri=''" in black
