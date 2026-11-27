"""`hyprland` module (F22, D12/D24): optional desktop with FAI_LinOP's own config only.
Third-party theme installers are deferred to v3.1 (D24)."""

from __future__ import annotations

from fai_linop.core.action import Context, register
from fai_linop.dotfiles.manager import DOTFILES, DeployDotfile
from fai_linop.package import catalog as cat
from fai_linop.package.actions import request


@register("hyprland", "Hyprland", order=45)
def build(ctx: Context):
    request(ctx, ids=[e.id for e in cat.group("hyprland")])
    actions = [DeployDotfile(d) for d in DOTFILES if d.module == "hyprland"]
    for a in actions:
        a.requires = ("packages.native",)
    return actions
