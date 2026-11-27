"""Explicit list of feature modules (no import magic): importing a module
registers its action factory with `fai_linop.core.action.register`."""

import importlib

MODULES = (
    "fai_linop.system.actions",
    "fai_linop.package.actions",
    "fai_linop.display.actions",
    "fai_linop.desktop.gnome",
    "fai_linop.desktop.hyprland",
    "fai_linop.gaming.actions",
    "fai_linop.dotfiles.manager",
    "fai_linop.terminal.actions",
    "fai_linop.security.actions",
    "fai_linop.optimization.actions",
)


def load() -> None:
    for name in MODULES:
        importlib.import_module(name)
