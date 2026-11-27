"""-y in the wizard uses defaults / profile values instead of answering yes (V300 O3)."""

from __future__ import annotations

import io

from rich.console import Console

from fai_linop.core.profile import Profile
from fai_linop.core.ui import UI
from fai_linop.core.wizard import run_wizard

RISKY = ("gaming", "blackarch", "security", "hyprland")


def _yes_ui() -> UI:
    return UI(Console(file=io.StringIO(), width=200), input_fn=lambda _p: "", assume_yes=True, interactive=True)


def test_yes_with_empty_profile_keeps_defaults(tmp_path):
    profile = Profile.load_or_default(tmp_path / "p.toml")
    before = {m: profile.enabled(m) for m in (*RISKY, "system", "packages", "gnome", "optimization")}
    groups = profile.get("packages", "groups")
    debloat = profile.get("gnome", "debloat")
    run_wizard(profile, _yes_ui())
    for m in RISKY:
        assert profile.enabled(m) is False
    assert {m: profile.enabled(m) for m in before} == before
    assert profile.get("packages", "groups") == groups
    assert profile.get("gnome", "debloat") == debloat


def test_yes_keeps_explicit_profile_values(tmp_path):
    profile = Profile.load_or_default(tmp_path / "p.toml")
    profile.set("modules", "gaming", True)
    run_wizard(profile, _yes_ui())
    assert profile.enabled("gaming") is True
    assert profile.enabled("blackarch") is False


def test_yes_still_confirms_by_default_outside_wizard():
    assert _yes_ui().confirm("Proceed?", default=False) is True
