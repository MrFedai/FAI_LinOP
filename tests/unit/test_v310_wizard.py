"""Wizard asks the profile-only settings too (V310 3.10, D14)."""

from __future__ import annotations

import io
import re
from importlib import resources

from rich.console import Console

from fai_linop.core import profile as prof
from fai_linop.core.profile import SCHEMA, Profile
from fai_linop.core.ui import UI
from fai_linop.core.wizard import (
    ASKED_ELSEWHERE, NONE_LABEL, PROFILE_ONLY, QUESTIONS, Question, run_wizard,
)


def _ui(answers=None, assume_yes=False) -> tuple[UI, list[str]]:
    """Fake UI: answers maps a question-text fragment to the typed reply; the rest is empty (default)."""
    asked: list[str] = []
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        for fragment, reply in (answers or {}).items():
            if fragment in prompts_text[-1]:
                return reply
        return ""

    prompts_text: list[str] = []
    ui = UI(Console(file=io.StringIO(), width=200), input_fn=fake_input, assume_yes=assume_yes, interactive=True)
    real_choose, real_text, real_confirm = ui.choose, ui.ask_text, ui.confirm

    def choose(q, choices, default):
        asked.append(q)
        prompts_text.append(q)
        return real_choose(q, choices, default)

    def ask_text(q, default=""):
        asked.append(q)
        prompts_text.append(q)
        return real_text(q, default)

    def confirm(q, default=False, *, wizard=False):
        asked.append(q)
        prompts_text.append(q)
        return real_confirm(q, default, wizard=wizard)

    ui.choose, ui.ask_text, ui.confirm = choose, ask_text, confirm  # type: ignore[method-assign]
    return ui, asked


def _profile(tmp_path, **modules) -> Profile:
    p = Profile.load_or_default(tmp_path / "p.toml")
    for m, on in modules.items():
        p.set("modules", m, on)
    return p


def _q(section: str, key: str) -> Question:
    return next(q for q in QUESTIONS if (q.section, q.key) == (section, key))


# ---- coverage: every schema key is asked or documented profile-only ------------------------------

def test_every_schema_key_asked_or_profile_only():
    schema_keys = {(s, k) for s, keys in SCHEMA.items() for k in keys}
    asked = {(q.section, q.key) for q in QUESTIONS} | ASKED_ELSEWHERE
    assert not (asked & PROFILE_ONLY)
    assert schema_keys == asked | PROFILE_ONLY


def test_profile_only_keys_marked_in_template():
    text = resources.files("fai_linop.data").joinpath("profile.template.toml").read_text()
    section = None
    marked: dict[str, set[str]] = {}
    for line in text.splitlines():
        m = re.match(r"\[(\w+)\]", line)
        if m:
            section = m.group(1)
        if section and "(profile only)" in line:
            if line.startswith("# The layout"):
                marked.setdefault(section, set()).add("monitor")
            else:
                marked.setdefault(section, set()).add(re.match(r"(\w+)", line).group(1))
    for s, k in PROFILE_ONLY:
        assert k in marked.get(s, set()), f"{s}.{k} lacks '(profile only)' in the template"
    # nothing marked that the wizard actually asks
    for s, keys in marked.items():
        for k in keys:
            assert (s, k) in PROFILE_ONLY


# ---- option lists come from one place -----------------------------------------------------------

def test_choices_match_schema():
    pairs = {
        ("terminal", "theme"): prof.TERMINAL_THEMES,
        ("shell", "zsh_theme"): prof.ZSH_THEMES,
        ("shell", "starship_preset"): prof.STARSHIP_PRESETS,
        ("gaming", "gpu"): prof.GPUS,
        ("cleanup", "cache"): prof.CACHE_MODES,
    }
    for (s, k), choices in pairs.items():
        assert SCHEMA[s][k][1].choices == choices
        assert _q(s, k).choices == choices


# ---- new questions: module off -> not asked, module on -> asked ----------------------------------

NEW = [
    # (section, key, module switches that make it asked, profile setup, fragment)
    ("terminal", "theme", {"terminal": True}, [("terminal", "emulator", "kitty")], "colour theme"),
    ("shell", "zsh_theme", {"shell": True}, [("shell", "name", "zsh")], "Oh-My-Zsh theme"),
    ("shell", "starship_preset", {"shell": True}, [("shell", "name", "fish")], "Starship"),
    ("gaming", "gpu", {"gaming": True}, [], "GPU driver set"),
    ("cleanup", "cache", {"cleanup": True}, [], "cache cleanup"),
    ("packages", "custom_file", {"packages": True}, [], "Custom package list"),
    ("wallpaper", "file", {"gnome": True}, [("wallpaper", "mode", "file")], "Wallpaper file"),
]


def _all_off(tmp_path) -> Profile:
    return _profile(tmp_path, **{m: False for m in SCHEMA["modules"]})


def test_new_questions_not_asked_when_module_off(tmp_path):
    for s, k, _mods, setup, fragment in NEW:
        p = _all_off(tmp_path)
        for ss, kk, v in setup:
            p.set(ss, kk, v)
        ui, asked = _ui()
        run_wizard(p, ui)
        assert not any(fragment in a for a in asked), (s, k)


def test_new_questions_asked_when_module_on(tmp_path):
    for s, k, mods, setup, fragment in NEW:
        p = _all_off(tmp_path)
        for m, on in mods.items():
            p.set("modules", m, on)
        for ss, kk, v in setup:
            p.set(ss, kk, v)
        ui, asked = _ui()
        run_wizard(p, ui)
        assert any(fragment in a for a in asked), (s, k)


def test_shell_conditions_follow_shell_name(tmp_path):
    p = _all_off(tmp_path)
    p.set("modules", "shell", True)
    p.set("shell", "name", "zsh")
    ui, asked = _ui()
    run_wizard(p, ui)
    assert any("Oh-My-Zsh" in a for a in asked) and not any("Starship" in a for a in asked)
    p.set("shell", "name", "bash")
    ui, asked = _ui()
    run_wizard(p, ui)
    assert any("Starship" in a for a in asked) and not any("Oh-My-Zsh" in a for a in asked)


def test_terminal_theme_not_asked_for_other_emulators(tmp_path):
    p = _all_off(tmp_path)
    p.set("modules", "terminal", True)
    p.set("terminal", "emulator", "terminator")
    ui, asked = _ui()
    run_wizard(p, ui)
    assert not any("colour theme" in a for a in asked)


# ---- answers ------------------------------------------------------------------------------------

def test_answers_are_stored(tmp_path):
    p = _all_off(tmp_path)
    p.set("modules", "terminal", True)
    p.set("terminal", "emulator", "kitty")
    p.set("modules", "cleanup", True)
    p.set("modules", "packages", True)
    ui, _ = _ui({"colour theme": "nord", "cache cleanup": "purge", "Custom package list": " my/list.txt "})
    run_wizard(p, ui)
    assert p.get("terminal", "theme") == "nord"
    assert p.get("cleanup", "cache") == "purge"
    assert p.get("packages", "custom_file") == "my/list.txt"


def test_empty_value_shown_as_none_and_stored_empty(tmp_path):
    p = _all_off(tmp_path)
    p.set("modules", "terminal", True)
    p.set("terminal", "emulator", "kitty")
    p.set("terminal", "theme", "nord")
    index = prof.TERMINAL_THEMES.index("") + 1
    ui, _ = _ui({"colour theme": str(index)})
    run_wizard(p, ui)
    assert p.get("terminal", "theme") == ""
    out = io.StringIO()
    ui2 = UI(Console(file=out, width=200), input_fn=lambda _p: "", interactive=True)
    p.set("terminal", "theme", "")
    run_wizard(p, ui2)
    assert NONE_LABEL in out.getvalue()
    assert p.get("terminal", "theme") == ""


def test_choose_default_is_current_value(tmp_path):
    p = _all_off(tmp_path)
    p.set("modules", "gaming", True)
    p.set("gaming", "gpu", "nvidia")
    ui, _ = _ui()
    run_wizard(p, ui)
    assert p.get("gaming", "gpu") == "nvidia"


# ---- -y keeps profile values -------------------------------------------------------------------

def test_yes_keeps_profile_values(tmp_path):
    p = _profile(tmp_path, terminal=True, shell=True, gaming=True, cleanup=True, packages=True, gnome=True)
    for s, k, v in [("terminal", "emulator", "alacritty"), ("terminal", "theme", "omni"),
                    ("shell", "name", "zsh"), ("shell", "zsh_theme", "bira"),
                    ("gaming", "gpu", "amd"), ("cleanup", "cache", "purge"),
                    ("packages", "custom_file", "x.txt"), ("wallpaper", "mode", "file"),
                    ("wallpaper", "file", "w.png")]:
        p.set(s, k, v)
    before = p.as_dict()
    ui, _ = _ui(assume_yes=True)
    run_wizard(p, ui)
    assert p.as_dict() == before


# ---- ask_text -----------------------------------------------------------------------------------

def test_ask_text_empty_input_returns_default():
    ui = UI(Console(file=io.StringIO()), input_fn=lambda _p: "   ", interactive=True)
    assert ui.ask_text("path?", "keep") == "keep"


def test_ask_text_returns_typed_value():
    ui = UI(Console(file=io.StringIO()), input_fn=lambda _p: " new ", interactive=True)
    assert ui.ask_text("path?", "keep") == "new"


def test_ask_text_assume_yes_and_non_interactive_use_default():
    ui = UI(Console(file=io.StringIO()), input_fn=lambda _p: "typed", assume_yes=True, interactive=True)
    assert ui.ask_text("path?", "keep") == "keep"
    ui = UI(Console(file=io.StringIO()), input_fn=lambda _p: "typed", interactive=False)
    assert ui.ask_text("path?", "keep") == "keep"
