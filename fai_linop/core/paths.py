"""Where FAI_LinOP keeps its own files (XDG base directories)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Paths:
    home: Path
    config: Path  # profile.toml
    state: Path   # runs/, logs/

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Paths":
        env = dict(os.environ if env is None else env)
        home = Path(env.get("HOME") or Path.home())
        config = Path(env.get("XDG_CONFIG_HOME") or home / ".config") / "linop"
        state = Path(env.get("XDG_STATE_HOME") or home / ".local" / "state") / "linop"
        return cls(home=home, config=config, state=state)

    @property
    def profile(self) -> Path:
        return self.config / "profile.toml"

    @property
    def runs(self) -> Path:
        return self.state / "runs"


def current_user() -> str:
    """Login name of the user running FAI_LinOP ($USER may be unset in some shells)."""
    import getpass
    return os.environ.get("USER") or getpass.getuser()
