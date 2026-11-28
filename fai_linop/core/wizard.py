"""The questions. `linop` asks them one module at a time, right before that module
is applied (D30); `linop wizard` asks all of them and only saves the profile.
Answers are written to the profile and are the defaults of the next run."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from fai_linop.core.profile import (
    CACHE_MODES, GPUS, GROUPS, STARSHIP_PRESETS, TERMINAL_THEMES, ZSH_THEMES, Profile,
)
from fai_linop.core.ui import UI


@dataclass(frozen=True)
class Question:
    section: str
    key: str
    text: str
    choices: tuple[str, ...] = ()               # empty = yes/no (or free text when free=True)
    free: bool = False                          # free-text answer (empty input keeps the current value)
    when: Callable[[Profile], bool] = lambda p: True

    @property
    def module(self) -> str:
        """The module (stage) this question belongs to."""
        return self.key if self.section == "modules" else SECTION_MODULE.get(self.section, self.section)


# profile sections that are asked with another module
SECTION_MODULE = {"wallpaper": "gnome"}


NONE_LABEL = "(none)"   # how the empty profile value "" is shown in a choice list


def _shell_is(*names: str) -> Callable[[Profile], bool]:
    return lambda p: p.enabled("shell") and p.get("shell", "name") in names


def _mod(name: str) -> Callable[[Profile], bool]:
    return lambda p: p.enabled(name)


QUESTIONS: tuple[Question, ...] = (
    Question("modules", "system", "Update the system first (full upgrade)?"),
    Question("system", "mirrors", "Arch: benchmark and pick the fastest mirrors (reflector)?", when=_mod("system")),
    Question("modules", "packages", "Install packages?"),
    Question("packages", "custom_file", "Custom package list file (path, empty = none)", free=True,
             when=_mod("packages")),
    Question("modules", "gnome", "Apply GNOME settings (dark theme, keybindings, app folders)?"),
    Question("gnome", "debloat", "Remove GNOME bloatware (Tour, Weather, Maps, Contacts, Music, Web)?", when=_mod("gnome")),
    Question("wallpaper", "mode", "Wallpaper", ("none", "file"), when=_mod("gnome")),
    Question("wallpaper", "file", "Wallpaper file (path)", free=True,
             when=lambda p: p.enabled("gnome") and p.get("wallpaper", "mode") == "file"),
    Question("modules", "display", "Detect monitors and use their best mode?"),
    Question("display", "prefer", "If max resolution and max refresh rate cannot coexist, prefer",
             ("resolution", "refresh"), when=_mod("display")),
    Question("modules", "hyprland", "Install Hyprland with FAI_LinOP's config (optional desktop)?"),
    Question("modules", "dotfiles", "Deploy dotfiles (Terminator config, …)?"),
    Question("modules", "terminal", "Configure a terminal emulator?"),
    Question("terminal", "emulator", "Terminal emulator", ("terminator", "kitty", "alacritty", "gnome-terminal"),
             when=_mod("terminal")),
    Question("terminal", "theme", "Terminal colour theme (kitty / alacritty)", TERMINAL_THEMES,
             when=lambda p: p.enabled("terminal") and p.get("terminal", "emulator") in ("kitty", "alacritty")),
    Question("modules", "shell", "Configure the shell?"),
    Question("shell", "name", "Shell", ("zsh", "fish", "bash", "none"), when=_mod("shell")),
    Question("shell", "zsh_theme", "Oh-My-Zsh theme", ZSH_THEMES, when=_shell_is("zsh")),
    Question("shell", "starship_preset", "Starship prompt preset (fish / bash)", STARSHIP_PRESETS,
             when=_shell_is("fish", "bash")),
    Question("modules", "gaming", "Gaming mode (Steam, GameMode, GPU drivers)?"),
    Question("gaming", "gpu", "GPU driver set for gaming", GPUS, when=_mod("gaming")),
    Question("modules", "blackarch", "BlackArch repository (Arch only)?"),
    Question("blackarch", "install", "BlackArch", ("core", "full", "remove"), when=_mod("blackarch")),
    Question("modules", "security", "Security tools and hardening?"),
    Question("security", "tools", "Install security tools (arch-audit/debsecan, ClamAV, rkhunter, Lynis, Firejail, nethogs)?", when=_mod("security")),
    Question("security", "firewall", "Enable firewall (deny incoming, SSH kept reachable if running)?", when=_mod("security")),
    Question("security", "sysctl", "Apply kernel/network sysctl hardening?", when=_mod("security")),
    Question("security", "ssh_root_login", "Disable SSH root login?", when=_mod("security")),
    Question("security", "ssh_disable_password", "Disable SSH password login (key-only)?", when=_mod("security")),
    Question("security", "scans", "Run security scans at the end (slow)?", when=_mod("security")),
    Question("security", "opensnitch", "Install OpenSnitch application firewall?", when=_mod("security")),
    Question("security", "usbguard", "Enable USBGuard (blocks new USB devices)?", when=_mod("security")),
    Question("modules", "optimization", "Apply recommended optimizations (TRIM, ZRAM, …)?"),
    Question("modules", "cleanup", "Clean up afterwards (orphans, old package cache)?"),
    Question("cleanup", "cache", "Package cache cleanup: trim (keep 2 versions) / none / purge", CACHE_MODES,
             when=_mod("cleanup")),
)

# Keys the wizard asks outside QUESTIONS (package groups are one yes/no per group).
ASKED_ELSEWHERE = {("packages", "groups")}

# Profile keys the wizard deliberately does not ask (V310 3.10): rarely changed, risky or structured.
# Each one carries "(profile only)" in profile.template.toml.
PROFILE_ONLY = {
    ("profile", "name"),
    ("packages", "extra"), ("packages", "aur_helper"), ("packages", "flatpak_fallback"),
    ("system", "upgrade"), ("system", "keyring_reset"), ("system", "speedtest"),
    ("wallpaper", "repo"),
    ("display", "monitor"),
    ("optimization", "items"),
    ("cleanup", "orphans"),
}


class Wizard:
    """Asks questions and writes the answers into the profile."""

    def __init__(self, profile: Profile, ui: UI):
        self.profile = profile
        self.ui = ui

    def ask_module(self, module: str) -> bool:
        """One module: its yes/no question, then (when yes) its own questions."""
        self._ask(q for q in QUESTIONS if q.module == module)
        return self.profile.enabled(module)

    def ask_all(self) -> Profile:
        self._ask(QUESTIONS)
        return self.profile

    def _ask(self, questions) -> None:
        profile, ui = self.profile, self.ui
        for q in questions:
            if not q.when(profile):
                continue
            current = profile.get(q.section, q.key)
            if q.choices:
                profile.set(q.section, q.key, _choose(ui, q, current))
            elif q.free:
                profile.set(q.section, q.key, ui.ask_text(q.text, str(current or "")))
            else:
                profile.set(q.section, q.key, ui.confirm(q.text, bool(current), wizard=True))
            if (q.section, q.key) == ("modules", "packages") and profile.enabled("packages"):
                _ask_groups(profile, ui)


def run_wizard(profile: Profile, ui: UI) -> Profile:
    """`linop wizard`: every question in one go, nothing applied."""
    ui.heading("FAI_LinOP setup wizard")
    if profile.path and profile.path.exists():
        if ui.confirm(f"Reuse previous answers from {profile.path}?", default=True):
            return profile
    return Wizard(profile, ui).ask_all()


def _choose(ui: UI, q: Question, current: str) -> str:
    """Empty profile values ("") are shown as NONE_LABEL; the profile still stores ""."""
    shown = tuple(c or NONE_LABEL for c in q.choices)
    answer = ui.choose(q.text, shown, current or NONE_LABEL)
    return "" if answer == NONE_LABEL else answer


def _ask_groups(profile: Profile, ui: UI) -> None:
    current = set(profile.get("packages", "groups"))
    chosen = [g for g in GROUPS if ui.confirm(f"  package group '{g}'?", g in current, wizard=True)]
    profile.set("packages", "groups", chosen)
