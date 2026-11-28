"""Package manager interface; the providers (pacman, apt, dnf) are in `providers.py`."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Iterable

from fai_linop.core.runner import Runner


class NotSupported(RuntimeError):
    """This distro has no provider for the requested operation."""


Size = tuple[int | None, int | None]   # (download bytes, installed bytes); None = unknown

_UNITS = {"": 1, "b": 1, "k": 1024, "kib": 1024, "kb": 1000, "m": 1024**2, "mib": 1024**2, "mb": 1000**2,
          "g": 1024**3, "gib": 1024**3, "gb": 1000**3, "t": 1024**4, "tib": 1024**4, "tb": 1000**4}


def parse_size(text: str, default_unit: str = "") -> int | None:
    """'1.50 MiB' → bytes. IEC (KiB/MiB) = 1024, SI (kB/MB) = 1000, bare K/M/G (dnf, apt) = 1024.
    None when the text is not a size."""
    m = re.match(r"^\s*([0-9]+(?:[.,][0-9]+)?)\s*([A-Za-z]*)\s*$", text or "")
    if not m:
        return None
    factor = _UNITS.get((m.group(2) or default_unit).lower())
    return None if factor is None else int(float(m.group(1).replace(",", ".")) * factor)


def parse_blocks(text: str, name_keys: tuple[str, ...]) -> dict[str, dict[str, str]]:
    """Blank-line separated `Key : value` blocks (pacman -Si, apt-cache show, dnf info) →
    {package: {lower-case key: value}}. The first block of a package wins (apt lists every version)."""
    out: dict[str, dict[str, str]] = {}
    for block in re.split(r"\n\s*\n", text):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if ":" in line and not line[:1].isspace():
                k, v = line.split(":", 1)
                fields.setdefault(k.strip().lower(), v.strip())
        name = next((fields[k] for k in name_keys if k in fields), None)
        if name:
            out.setdefault(name, fields)
    return out


class PackageManager(ABC):
    name: str = ""

    def __init__(self, runner: Runner):
        self.runner = runner

    @abstractmethod
    def installed(self, names: Iterable[str]) -> set[str]:
        """Subset of `names` that is installed (read-only)."""

    @abstractmethod
    def available(self, names: Iterable[str]) -> set[str]:
        """Subset of `names` available from the configured repositories (read-only)."""

    @abstractmethod
    def install(self, names: list[str]) -> None:
        """Install in ONE transaction (v2.5 called the manager once per package)."""

    @abstractmethod
    def remove(self, names: list[str]) -> None: ...

    def orphans(self) -> set[str]:
        """Packages nothing needs any more (read-only; a failing query means none)."""
        return set()

    def sizes(self, names: Iterable[str]) -> dict[str, Size]:
        """Download / installed size per name from ONE query (read-only). Unknown = (None, None);
        a failing query never raises — the preview just shows "unknown"."""
        return {n: (None, None) for n in names}
