"""`terminal` (F24) and `shell` (F25) modules.

No `curl | sh` (S-03, D24): Oh-My-Zsh and plugins are cloned from pinned commits,
Starship comes from the distro package, Kitty themes via kitty's own `themes`
kitten, Alacritty themes are imported (alacritty.toml is never overwritten)."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path

import tomlkit

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, register
from fai_linop.core.common import WriteFile, read_text
from fai_linop.core.paths import current_user
from fai_linop.package.actions import request, resolution

# pinned 2026-09-24 (git ls-remote HEAD); update deliberately
PINS = {
    "ohmyzsh": ("https://github.com/ohmyzsh/ohmyzsh.git", "74965c96098134b192f00084f966b4b02438a739"),
    "zsh-autosuggestions": ("https://github.com/zsh-users/zsh-autosuggestions.git", "85919cd1ffa7d2d5412f6d3fe437ebdbeeec4fc5"),
    "zsh-syntax-highlighting": ("https://github.com/zsh-users/zsh-syntax-highlighting.git", "0bfcb582e71d3abe604ce67bc0fe5a21f377507e"),
    "powerlevel10k": ("https://github.com/romkatv/powerlevel10k.git", "d05a1b00f9a61f9578bf9dc19b8451942dde8734"),
}
ALACRITTY_THEME_URL = "https://raw.githubusercontent.com/alacritty/alacritty-theme/master/themes/{}.toml"
KITTY_THEMES = {"dracula": "Dracula", "nord": "Nord", "gruvbox_dark": "Gruvbox Dark", "tokyo_night": "Tokyo Night"}


def _clear_incomplete(dest: Path) -> None:
    """Remove leftovers of an earlier failed clone; anything with user files is moved aside, not deleted."""
    if not dest.exists():
        return
    if all(e.name == ".git" for e in dest.iterdir()):
        shutil.rmtree(dest)
    else:
        dest.rename(dest.with_name(dest.name + ".incomplete"))


def _clone_complete(name: str, path: Path) -> bool:
    if name == "ohmyzsh":
        return (path / "oh-my-zsh.sh").is_file()
    return path.is_dir() and any(e.name != ".git" for e in path.iterdir())


def pinned_clone(ctx: Context, name: str, dest: Path) -> None:
    url, commit = PINS[name]
    r = ctx.runner
    # clone into a temp dir next to dest and rename when done: a failed fetch never leaves `dest` half-made
    tmp = dest.parent / f".{dest.name}.linop-tmp"
    if not ctx.dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(tmp, ignore_errors=True)
    try:
        r.run(["git", "init", "-q", str(tmp)])
        r.run(["git", "-C", str(tmp), "fetch", "-q", "--depth", "1", url, commit], timeout=300)
        r.run(["git", "-C", str(tmp), "checkout", "-q", "FETCH_HEAD"])
        if not ctx.dry_run and tmp.exists():
            _clear_incomplete(dest)
            tmp.rename(dest)
    except BaseException:
        if not ctx.dry_run:
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    ctx.journal.write("git_clone", repo=url, commit=commit, path=str(dest))


# ---- terminal -----------------------------------------------------------------------

class KittyTheme(Action):
    id, title, risk, reversible = "terminal.kitty-theme", "Kitty theme (kitty +kitten themes)", Risk.LOW, Reversible.YES
    requires = ("packages.native",)

    def plan(self, ctx):
        theme = ctx.profile.get("terminal", "theme")
        if ctx.profile.get("terminal", "emulator") != "kitty" or not theme:
            return []
        current = read_text(ctx.home / ".config" / "kitty" / "current-theme.conf") or ""
        if KITTY_THEMES[theme] in current:
            return []
        return [Change("file", "~/.config/kitty/current-theme.conf", KITTY_THEMES[theme])]

    def apply(self, ctx):
        base = ctx.home / ".config" / "kitty"
        for f in ("kitty.conf", "current-theme.conf"):   # the kitten edits these: back them up first
            ctx.files.backup_only(base / f)
        ctx.runner.run(["kitty", "+kitten", "themes", "--reload-in=none", KITTY_THEMES[ctx.profile.get("terminal", "theme")]])


class AlacrittyTheme(Action):
    id, title, risk, reversible = "terminal.alacritty-theme", "Alacritty theme (imported, config kept)", Risk.LOW, Reversible.YES

    def _paths(self, ctx):
        base = ctx.home / ".config" / "alacritty"
        return base / "alacritty.toml", base / "themes" / f"{ctx.profile.get('terminal', 'theme')}.toml"

    def plan(self, ctx):
        theme = ctx.profile.get("terminal", "theme")
        if ctx.profile.get("terminal", "emulator") != "alacritty" or not theme:
            return []
        conf, theme_file = self._paths(ctx)
        changes = []
        if not theme_file.exists():
            changes.append(Change("file", str(theme_file), ALACRITTY_THEME_URL.format(theme)))
        if str(theme_file) not in (read_text(conf) or "") and f"themes/{theme}.toml" not in (read_text(conf) or ""):
            changes.append(Change("file", str(conf), "add general.import (backup kept)"))
        return changes

    def apply(self, ctx):
        conf, theme_file = self._paths(ctx)
        url = ALACRITTY_THEME_URL.format(ctx.profile.get("terminal", "theme"))
        body = ctx.runner.run(["curl", "-fsSL", "--max-time", "30", url], mutating=False).stdout  # -f: no 404 page as config
        ctx.files.write(theme_file, body.encode())
        ctx.files.write(conf, _alacritty_import(read_text(conf) or "", str(theme_file)).encode())


def _alacritty_import(text: str, theme_path: str) -> str:
    """Add theme_path to general.import with tomlkit (comments and order kept; no duplicate key)."""
    doc = tomlkit.parse(text)
    general = doc.get("general")
    if general is None:
        general = tomlkit.table()
        doc["general"] = general
    imports = general.get("import")
    if imports is None:
        imports = tomlkit.array()
        general["import"] = imports
    if theme_path not in [str(i) for i in imports]:
        imports.append(theme_path)
    return tomlkit.dumps(doc)


# ---- shell ----------------------------------------------------------------------------

def _insert_before_source(text: str, line: str) -> str:
    """Put `line` before the `source …oh-my-zsh.sh` line (plugins load only if set before it)."""
    m = re.search(r"^[ \t]*(?:source|\.)[ \t]+\S*oh-my-zsh\.sh.*$", text, re.M)
    if m:
        return text[:m.start()] + line + "\n" + text[m.start():]
    return text + ("" if text.endswith("\n") or not text else "\n") + line + "\n"


def _zshrc_edit(text: str, theme: str) -> str:
    theme_line = f'ZSH_THEME="{theme}"'
    plugins_line = "plugins=(git zsh-autosuggestions zsh-syntax-highlighting)"
    text = re.sub(r"^ZSH_THEME=.*$", theme_line, text, flags=re.M) if re.search(r"^ZSH_THEME=", text, re.M) \
        else theme_line + "\n" + text
    text = re.sub(r"^plugins=\(.*?\)$", plugins_line, text, flags=re.M | re.S) if re.search(r"^plugins=\(", text, re.M) \
        else _insert_before_source(text, plugins_line)
    return text


class OhMyZsh(Action):
    id, title, risk, reversible = "shell.ohmyzsh", "Oh-My-Zsh + plugins (pinned git commits)", Risk.LOW, Reversible.YES
    requires = ("packages.native",)

    def _targets(self, ctx):
        omz = ctx.home / ".oh-my-zsh"
        custom = omz / "custom"
        t = {"ohmyzsh": omz, "zsh-autosuggestions": custom / "plugins" / "zsh-autosuggestions",
             "zsh-syntax-highlighting": custom / "plugins" / "zsh-syntax-highlighting"}
        if ctx.profile.get("shell", "zsh_theme") == "powerlevel10k":
            t["powerlevel10k"] = custom / "themes" / "powerlevel10k"
        return t

    def plan(self, ctx):
        return [Change("command", f"git clone {PINS[n][0]}@{PINS[n][1][:10]}", str(p))
                for n, p in self._targets(ctx).items() if not _clone_complete(n, p)]

    def apply(self, ctx):
        for name, path in self._targets(ctx).items():
            if not _clone_complete(name, path):
                pinned_clone(ctx, name, path)

    def verify(self, ctx):
        return all(_clone_complete(n, p) for n, p in self._targets(ctx).items())


class Zshrc(WriteFile):
    reversible = Reversible.YES

    def __init__(self):
        super().__init__("shell.zshrc", "~/.zshrc: theme + plugins (only these two lines are edited)",
                         Path("~/.zshrc"), self._render)

    @staticmethod
    def _render(ctx):
        theme = ctx.profile.get("shell", "zsh_theme")
        theme = "powerlevel10k/powerlevel10k" if theme == "powerlevel10k" else theme
        current = read_text(ctx.home / ".zshrc")
        if current is None:
            template = read_text(ctx.home / ".oh-my-zsh" / "templates" / "zshrc.zsh-template")
            current = template or 'export ZSH="$HOME/.oh-my-zsh"\nsource $ZSH/oh-my-zsh.sh\n'
        return _zshrc_edit(current, theme)

    def plan(self, ctx):
        self.path = ctx.home / ".zshrc"
        return super().plan(ctx)


def starship_planned(ctx) -> bool:
    """Starship is installed or will be installed in this run (V301 2.4)."""
    res = resolution(ctx)
    return any("starship" in group for group in (res.installed, res.native, res.aur, res.deferred))


def starship_present(ctx) -> bool:
    """Apply-time check; a dry run installs nothing, so it trusts the plan."""
    if ctx.dry_run:
        return True
    return ctx.runner.run(["sh", "-c", "command -v starship"], mutating=False, check=False).ok


class ShellInitLine(WriteFile):
    """Append `starship init` to ~/.bashrc or fish config (idempotent)."""

    def __init__(self, shell: str):
        rel = ".config/fish/config.fish" if shell == "fish" else ".bashrc"
        line = "starship init fish | source" if shell == "fish" else 'eval "$(starship init bash)"'
        self.rel, self.line = rel, line
        super().__init__(f"shell.{shell}-starship", f"Starship prompt in ~/{rel}", Path("~") / rel, self._render)

    def _render(self, ctx):
        text = read_text(ctx.home / self.rel) or ""
        if self.line in text:
            return text
        return text + ("" if text.endswith("\n") or not text else "\n") + self.line + "\n"

    def plan(self, ctx):
        self.path = ctx.home / self.rel
        if not starship_planned(ctx):
            return [Change("warning", "starship", "starship unavailable — prompt line not written")]
        return super().plan(ctx)

    def apply(self, ctx):
        self.path = ctx.home / self.rel
        if not starship_planned(ctx):
            return
        if not starship_present(ctx):
            ctx.ui.warn("starship command not found — prompt line not written")
            return
        super().apply(ctx)

    def verify(self, ctx):
        if not starship_planned(ctx) or not starship_present(ctx):
            return True  # deliberately skipped
        return super().verify(ctx)


class StarshipPreset(Action):
    id, title, risk, reversible = "shell.starship-preset", "Starship preset (~/.config/starship.toml)", Risk.LOW, Reversible.YES
    requires = ("packages.native",)

    @staticmethod
    def _state(ctx) -> Path:
        return ctx.home / ".local" / "state" / "linop" / "starship-preset.sha256"

    def _user_edited(self, ctx) -> bool:
        """True when starship.toml exists and differs from what FAI_LinOP last wrote."""
        target = ctx.home / ".config" / "starship.toml"
        if not target.exists():
            return False
        last = read_text(self._state(ctx))
        return last is None or last.strip() != hashlib.sha256(target.read_bytes()).hexdigest()

    def plan(self, ctx):
        preset = ctx.profile.get("shell", "starship_preset")
        if not preset or ctx.profile.get("shell", "name") not in ("fish", "bash"):
            return []
        if not starship_planned(ctx):
            return []  # the init-line action already warns
        if self._user_edited(ctx):
            ctx.ui.info("kept user's starship.toml")
            return []
        return [Change("file", "~/.config/starship.toml", f"preset {preset} (backup kept)")]

    def apply(self, ctx):
        preset = ctx.profile.get("shell", "starship_preset")
        if not starship_planned(ctx) or self._user_edited(ctx):
            return
        if ctx.dry_run:  # starship may not be installed yet: record "would run" only
            ctx.runner.run(["starship", "preset", preset, "-o", "~/.config/starship.toml"])
            return
        if not starship_present(ctx):
            ctx.ui.warn("starship command not found — preset not written")
            return
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "starship.toml"
            ctx.runner.run(["starship", "preset", preset, "-o", str(out)], mutating=False)
            data = out.read_bytes()
            ctx.files.write(ctx.home / ".config" / "starship.toml", data)
        state = self._state(ctx)
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(hashlib.sha256(data).hexdigest() + "\n")


class ChangeShell(Action):
    id, risk, reversible = "shell.chsh", Risk.LOW, Reversible.PARTIAL   # previous shell journaled; `chsh` to revert
    requires = ("packages.native",)

    @property
    def title(self):
        return "Make it the login shell (chsh)"

    @staticmethod
    def login_shell(ctx) -> str:
        entry = ctx.runner.run(["getent", "passwd", current_user()], mutating=False, check=False).stdout.strip()
        return entry.split(":")[-1] if entry else os.environ.get("SHELL", "")

    def plan(self, ctx):
        name = ctx.profile.get("shell", "name")
        if name == "none" or os.path.basename(self.login_shell(ctx)) == name:
            return []
        return [Change("setting", f"login shell -> {name}", "chsh")]

    @staticmethod
    def shell_path(name: str, shells_text: str) -> str | None:
        """The /etc/shells entry for `name` — chsh accepts only listed paths.

        With /usr/sbin merged into /usr/bin (Arch, Fedora 42+) `which` can answer
        /usr/sbin/zsh, which is the same file as the listed /usr/bin/zsh but not
        listed itself; match entries by the file they point to."""
        listed = [line.strip() for line in shells_text.splitlines() if line.strip().startswith("/")]
        found = shutil.which(name)
        if found in listed:
            return found
        target = os.path.realpath(found) if found else None
        for entry in listed:
            if os.path.basename(entry) == name and (target is None or os.path.realpath(entry) == target):
                return entry
        return None

    def apply(self, ctx):
        name = ctx.profile.get("shell", "name")
        path = self.shell_path(name, read_text(Path("/etc/shells")) or "")
        if path is None:
            if not ctx.dry_run:
                raise RuntimeError(f"{name} is not listed in /etc/shells")
            path = f"/usr/bin/{name}"
        ctx.journal.write("login_shell", user=current_user(), previous=self.login_shell(ctx), new=path)
        ctx.runner.run(["chsh", "-s", path, current_user()], sudo=True)


@register("terminal", "Terminal", order=70)
def build_terminal(ctx: Context):
    emulator = ctx.profile.get("terminal", "emulator")
    if emulator != "none":
        request(ctx, ids=[emulator])
    return [KittyTheme(), AlacrittyTheme()]


@register("shell", "Shell", order=75)
def build_shell(ctx: Context):
    name = ctx.profile.get("shell", "name")
    if name == "none":
        return []
    chsh_ids = ["util-linux-user"] if os.path.basename(ChangeShell.login_shell(ctx)) != name else []  # Fedora: chsh
    request(ctx, ids=["font-jetbrains-nerd", name, *chsh_ids] + (["starship"] if name in ("fish", "bash") else []))
    if name == "zsh":
        return [OhMyZsh(), Zshrc(), ChangeShell()]
    return [ShellInitLine(name), StarshipPreset(), ChangeShell()]
