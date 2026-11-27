"""V301 2.1 (zsh plugins order, partial clone) + 2.3 (Alacritty valid TOML)."""

from __future__ import annotations

import tomllib
from pathlib import Path

from test_phase5 import ctx_for

from fai_linop.core.runner import FakeRunner
from fai_linop.terminal import actions
from fai_linop.terminal.actions import OhMyZsh, Zshrc, _alacritty_import

THEME = "/h/.config/alacritty/themes/nord.toml"
ZSH = '[shell]\nname = "zsh"\n'


def test_zshrc_plugins_before_source_on_empty_home(tmp_path):
    out = Zshrc._render(ctx_for(tmp_path, ZSH))
    assert out.index("plugins=(") < out.index("oh-my-zsh.sh")


def test_zshrc_plugins_before_source_in_user_file(tmp_path):
    ctx = ctx_for(tmp_path, ZSH)
    (ctx.home / ".zshrc").write_text("export ZSH=x\nsource $ZSH/oh-my-zsh.sh\nalias a=b\n")
    out = Zshrc._render(ctx)
    assert out.index("plugins=(") < out.index("source $ZSH/oh-my-zsh.sh") < out.index("alias")


def test_partial_clone_counts_as_missing(tmp_path):
    ctx = ctx_for(tmp_path, ZSH)
    omz = ctx.home / ".oh-my-zsh"
    (omz / ".git").mkdir(parents=True)
    act = OhMyZsh()
    assert any(c.detail == str(omz) for c in act.plan(ctx))
    assert not act.verify(ctx)


def test_clone_into_tmp_then_rename(tmp_path):
    runner = FakeRunner()
    runner.dry_run = False
    ctx = ctx_for(tmp_path, ZSH, runner=runner)
    omz = ctx.home / ".oh-my-zsh"
    (omz / ".git").mkdir(parents=True)          # leftover of a failed run
    orig = runner.run

    def run(cmd, **kw):
        if cmd[:2] == ["git", "init"]:
            Path(cmd[-1]).mkdir(parents=True)
            (Path(cmd[-1]) / "oh-my-zsh.sh").write_text("")
        return orig(cmd, **kw)

    runner.run = run
    actions.pinned_clone(ctx, "ohmyzsh", omz)
    assert (omz / "oh-my-zsh.sh").is_file()
    assert not (ctx.home / ".oh-my-zsh.linop-tmp").exists()


def test_alacritty_existing_import_list():
    src = '# top\n[general]\nimport = ["a.toml"]\nlive_config_reload = true\n\n[font]\nsize = 12\n'
    out = _alacritty_import(src, THEME)
    d = tomllib.loads(out)
    assert d["general"]["import"] == ["a.toml", THEME] and d["general"]["live_config_reload"] is True
    assert d["font"]["size"] == 12 and out.startswith("# top")
    assert _alacritty_import(out, THEME) == out


def test_alacritty_without_general_keeps_top_level_keys():
    d = tomllib.loads(_alacritty_import("live_config_reload = true\n[font]\nsize = 12\n", THEME))
    assert d["live_config_reload"] is True and d["font"]["size"] == 12 and d["general"]["import"] == [THEME]


def test_alacritty_empty_file():
    assert tomllib.loads(_alacritty_import("", THEME))["general"]["import"] == [THEME]


# ---- 2.4 starship conditional, preset keeps user edits; 2.6 chsh prerequisite ---------

BASH = '[shell]\nname = "bash"\nstarship_preset = "nerd-font-symbols"\n'


def _starship_ctx(tmp_path, **res):
    from fai_linop.package.resolve import Resolution
    ctx = ctx_for(tmp_path, BASH)
    ctx.facts["packages"] = Resolution(**res)
    return ctx


def _preset_handler(cmd, _input):
    Path(cmd[cmd.index("-o") + 1]).write_bytes(b"[x]\n")
    return 0


def test_starship_unavailable_leaves_shell_file_alone(tmp_path):
    from fai_linop.terminal.actions import ShellInitLine
    ctx = _starship_ctx(tmp_path, unavailable=["starship"])
    rc = ctx.home / ".bashrc"
    rc.write_text("alias a=b\n")
    act = ShellInitLine("bash")
    changes = act.plan(ctx)
    assert [c.kind for c in changes] == ["warning"] and "unavailable" in changes[0].detail
    act.apply(ctx)
    assert rc.read_text() == "alias a=b\n"


def test_starship_to_be_installed_plans_init_line(tmp_path):
    from fai_linop.terminal.actions import ShellInitLine
    ctx = _starship_ctx(tmp_path, native=["starship"])
    assert [c.kind for c in ShellInitLine("bash").plan(ctx)] == ["file"]


def test_starship_command_missing_at_apply_skips_line(tmp_path):
    from fai_linop.terminal.actions import ShellInitLine
    ctx = _starship_ctx(tmp_path, installed=["starship"])
    ctx.runner.on("sh", "-c", result=1)
    ShellInitLine("bash").apply(ctx)
    assert not (ctx.home / ".bashrc").exists()


def test_preset_written_when_missing_then_user_edit_kept(tmp_path):
    from fai_linop.terminal.actions import StarshipPreset
    ctx = _starship_ctx(tmp_path, installed=["starship"])
    ctx.runner.on("starship", "preset", result=_preset_handler)
    act = StarshipPreset()
    assert len(act.plan(ctx)) == 1
    act.apply(ctx)
    target = ctx.home / ".config" / "starship.toml"
    assert target.read_bytes() == b"[x]\n"
    target.write_text("# mine\n")
    assert act.plan(ctx) == []
    act.apply(ctx)
    assert target.read_text() == "# mine\n"


def test_preset_kept_when_file_exists_without_state(tmp_path):
    from fai_linop.terminal.actions import StarshipPreset
    ctx = _starship_ctx(tmp_path, installed=["starship"])
    target = ctx.home / ".config" / "starship.toml"
    target.parent.mkdir(parents=True)
    target.write_text("# mine\n")
    assert StarshipPreset().plan(ctx) == []


def test_fedora_chsh_requests_util_linux_user(tmp_path):
    from fai_linop.platform.detect import Family, OSInfo, Tier
    fedora = OSInfo(Family.FEDORA, Tier.SUPPORTED, "fedora", "Fedora")
    runner = FakeRunner().on("getent", result="u:x:1:1::/h:/bin/bash")
    ctx = ctx_for(tmp_path, ZSH, fedora, runner=runner)
    actions.build_shell(ctx)
    assert "util-linux-user" in ctx.facts["package_ids"]
