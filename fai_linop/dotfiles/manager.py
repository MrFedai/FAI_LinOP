"""Dotfile manager (D10): deploy / diff / capture. Files stay in their native
format; only the D18 substitutions are applied (checked by rules.check)."""

from __future__ import annotations

import difflib
import re
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from fai_linop.core.action import Change, Context, Reversible, Risk, register
from fai_linop.core.common import WriteFile, read_text
from fai_linop.dotfiles import rules

log = logging.getLogger("fai_linop.dotfiles")

# 1.11: the summary shows at most this many changed lines per dotfile; the full
# diff goes to the run's log file (and to the screen with -v).
SHORT_DIFF_LINES = 12
SHORT_DIFF_WIDTH = 120


@dataclass(frozen=True)
class Dotfile:
    name: str
    source: str               # relative to the repo root
    target: str               # relative to $HOME
    kind: str                 # rules.check kind
    module: str               # which profile module deploys it
    render: Callable[[Context, str], str] = lambda ctx, text: text


def _render_hyprland(ctx: Context, text: str) -> str:
    from fai_linop.display.actions import hyprland_block
    from fai_linop.display.hyprland import replace_monitor_lines
    return replace_monitor_lines(text, hyprland_block(ctx))


def _render_hyprlock(ctx: Context, text: str) -> str:
    if (ctx.home / ".config" / "Ax-Shell").exists():
        return text
    return text.replace(rules.AXSHELL_SOURCE, rules.LINOP_SOURCE, 1)


DOTFILES = (
    Dotfile("terminator", "configs/terminator/config", ".config/terminator/config", "verbatim", "dotfiles"),
    Dotfile("hyprland", "configs/hypr/hyprland.conf", ".config/hypr/hyprland.conf", "hyprland", "hyprland",
            _render_hyprland),
    Dotfile("hypridle", "configs/hypr/hypridle.conf", ".config/hypr/hypridle.conf", "verbatim", "hyprland"),
    Dotfile("hyprlock", "configs/hypr/hyprlock.conf", ".config/hypr/hyprlock.conf", "hyprlock", "hyprland",
            _render_hyprlock),
    Dotfile("linop-colors", "configs/hypr/linop-colors.conf", ".config/hypr/linop-colors.conf", "verbatim", "hyprland"),
)


def rendered(ctx: Context, d: Dotfile) -> str:
    return d.render(ctx, (ctx.repo_root / d.source).read_text())


class DeployDotfile(WriteFile):
    reversible = Reversible.YES

    def __init__(self, d: Dotfile):
        self.dotfile = d
        super().__init__(f"dotfiles.{d.name}", f"Deploy {d.target}", Path("~") / d.target,
                         lambda ctx: rendered(ctx, d), risk=Risk.LOW)

    def plan(self, ctx):
        self.path = ctx.home / self.dotfile.target
        source = (ctx.repo_root / self.dotfile.source).read_text()
        problems = rules.check(self.dotfile.kind, source, self.content(ctx), ctx.profile.get("profile", "name"))
        if problems:  # never deploy something that breaks D8/D18
            raise RuntimeError(f"{self.dotfile.name}: rendered file violates D18: {problems[:3]}")
        changes = super().plan(ctx)
        old = read_text(self.path)
        if not changes or old is None:
            return changes
        # 1.11 (D10): an overwritten dotfile shows its diff in the summary.
        full = unified(old, self.content(ctx), f"live:~/{self.dotfile.target}",
                       f"repo:{self.dotfile.source} (rendered)")
        log.info("diff for %s:\n%s", self.path, full)
        return [Change("file", str(self.path), "update (backup kept)" + summary_diff(full))]


def unified(old: str | bytes, new: str | bytes, old_label: str, new_label: str) -> str:
    """Unified diff of two texts. Bytes are shown as UTF-8 (undecodable bytes
    replaced, for display only); line endings stay part of each line."""
    def lines(x: str | bytes) -> list[str]:
        return (x.decode("utf-8", "replace") if isinstance(x, bytes) else x).splitlines(True)
    out = []
    for line in difflib.unified_diff(lines(old), lines(new), old_label, new_label):
        out.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(out)


def summary_diff(full: str) -> str:
    """The changed lines of `full` for the plan table, shortened unless -v.
    Escaped, because the plan table renders rich markup ("[section]" lines)."""
    from rich.markup import escape
    changed = [line.rstrip("\r\n") for line in full.splitlines(True)
               if line[:1] in ("+", "-") and not line.startswith(("+++ ", "--- "))]
    if not changed:
        return ""
    if log.isEnabledFor(logging.DEBUG):     # -v: the whole diff
        shown, rest = changed, 0
    else:
        shown, rest = changed[:SHORT_DIFF_LINES], len(changed) - SHORT_DIFF_LINES
        shown = [s if len(s) <= SHORT_DIFF_WIDTH else s[:SHORT_DIFF_WIDTH] + "…" for s in shown]
    text = "".join(f"\n{escape(s)}" for s in shown)
    if rest > 0:
        text += f"\n… {rest} more changed line(s) — full diff with -v and in the run's log file"
    return text


def diff(ctx: Context, d: Dotfile) -> str:
    live = read_text(ctx.home / d.target)
    if live is None:
        return f"{d.target}: not deployed\n"
    want = rendered(ctx, d)
    return "".join(difflib.unified_diff(want.splitlines(True), live.splitlines(True),
                                        f"repo:{d.source} (rendered)", f"live:~/{d.target}"))


def captured(ctx: Context, d: Dotfile) -> bytes | None:
    """The bytes `capture` would write into the repo, or None when the live file
    is missing or already equal to the repo file (1.2: byte level, CRLF kept).
    Generated parts are not captured: hyprland's monitor block is replaced by the
    repo's own monitor lines, hyprlock keeps the Ax-Shell source line."""
    try:
        live = (ctx.home / d.target).read_bytes()
    except OSError:
        return None
    source = (ctx.repo_root / d.source).read_bytes()
    if d.kind in ("hyprland", "hyprlock"):
        text = live.decode("utf-8", "surrogateescape")
        if d.kind == "hyprland":
            src = source.decode("utf-8", "surrogateescape")
            original = "".join(line for line in src.splitlines(True) if rules._MONITOR_LINE.match(line))
            block = _block_of(text)
            text = text.replace(block, original) if block else text
        else:
            text = text.replace(rules.LINOP_SOURCE, rules.AXSHELL_SOURCE, 1)
        live = text.encode("utf-8", "surrogateescape")
    return None if live == source else live


def capture_diff(ctx: Context, d: Dotfile, new: bytes) -> str:
    return unified((ctx.repo_root / d.source).read_bytes(), new, f"repo:{d.source}", f"captured:~/{d.target}")


def capture(ctx: Context, d: Dotfile) -> bool:
    """Copy the live file back into the repo (D11: the owner refreshes the source)
    through FileChanger: the old repo file is backed up and journalled (D10)."""
    new = captured(ctx, d)
    if new is None:
        return False
    return ctx.files.write(ctx.repo_root / d.source, new)


def _block_of(text: str) -> str:
    """The generated monitor block including its line ending (LF or CRLF)."""
    start = text.find(rules.MONITOR_BEGIN)
    end = text.find(rules.MONITOR_END)
    if start == -1 or end == -1:
        return ""
    end += len(rules.MONITOR_END)
    if text.startswith("\r\n", end):
        end += 2
    elif text.startswith("\n", end):
        end += 1
    return text[start:end]


# font family named in a dotfile -> catalog id of the package that ships it
FONT_PACKAGES = {"Adwaita Mono": "font-adwaita-mono", "JetBrainsMono Nerd Font": "font-jetbrains-nerd"}
_TERMINATOR_FONT = re.compile(r"^\s*font\s*=\s*(.+?)\s+\d+(?:\.\d+)?\s*$", re.MULTILINE)


def font_packages(terminator_config: str) -> list[str]:
    """Catalog ids of the fonts a Terminator config asks for (`font = Adwaita Mono 10`).
    A config is useless without its font: the terminal falls back to a proportional one.
    The file itself is never changed (D8) — only the package is requested."""
    families = {m.group(1) for m in _TERMINATOR_FONT.finditer(terminator_config)}
    return sorted(FONT_PACKAGES[f] for f in families if f in FONT_PACKAGES)


@register("dotfiles", "Dotfiles", order=60)
def build(ctx: Context):
    from fai_linop.package.actions import request
    wanted = [d for d in DOTFILES if d.module == "dotfiles"]
    for d in wanted:
        source = ctx.repo_root / d.source
        if d.name == "terminator" and source.exists():
            request(ctx, ids=font_packages(source.read_text(errors="replace")))
    return [DeployDotfile(d) for d in wanted]
