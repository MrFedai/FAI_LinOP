"""v3.1.0 O1: package size preview (3.2) and per-package install result (3.3).
Fixtures in tests/fixtures/pkgsize are sample outputs written from the documented format of
`pacman -Si`, `apt-cache show`, `dnf info` (dnf4 and dnf5), not captures of a live system.
FakeRunner only → UNIT TESTED."""

from __future__ import annotations

from pathlib import Path

from fai_linop.core import engine
from fai_linop.core.runner import FakeRunner, Result
from fai_linop.package.actions import InstallNative
from fai_linop.package.base import parse_size
from fai_linop.package.providers import Apt, Dnf, Pacman
from fai_linop.package.resolve import Resolution
from test_phase5 import ctx_for

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "pkgsize"
KiB, MiB = 1024, 1024**2


def fixture(name):
    return (FIX / name).read_text()


# ---- 3.2 unit conversion + parsers --------------------------------------------------

def test_parse_size_units():
    assert parse_size("1 KiB") == 1024
    assert parse_size("1.5 MiB") == int(1.5 * MiB)
    assert parse_size("2 kB") == 2000
    assert parse_size("3 MB") == 3_000_000
    assert parse_size("52 k") == 52 * 1024
    assert parse_size("1.2 M") == int(1.2 * MiB)
    assert parse_size("10", "k") == 10 * 1024
    assert parse_size("7") == 7
    assert parse_size("garbage") is None and parse_size("") is None


def test_pacman_sizes_single_query():
    r = FakeRunner().on("pacman", "-Si", result=fixture("pacman-Si.txt"))
    out = Pacman(r).sizes(["git", "htop", "nosuch"])
    assert out["git"] == (int(4.86 * MiB), int(38.92 * MiB))
    assert out["htop"] == (int(174.2 * KiB), 428 * KiB)
    assert out["nosuch"] == (None, None)
    assert r.calls == [("pacman", "-Si", "git", "htop", "nosuch")]   # one process for all names


def test_apt_sizes_first_version_wins_and_units():
    r = FakeRunner().on("apt-cache", "show", result=fixture("apt-cache-show.txt"))
    out = Apt(r).sizes(["git", "htop"])
    assert out["git"] == (3_680_000, 21457 * KiB)   # Size = bytes, Installed-Size = KiB
    assert out["htop"] == (171_000, 431 * KiB)
    assert len(r.calls) == 1


def test_dnf4_sizes_use_size_as_download():
    r = FakeRunner().on("dnf", "-q", "info", result=fixture("dnf4-info.txt"))
    out = Dnf(r).sizes(["git", "htop"])
    assert out["git"] == (52 * KiB, None)
    assert out["htop"] == (int(1.2 * MiB), None)
    assert len(r.calls) == 1


def test_dnf5_sizes_download_and_installed():
    r = FakeRunner().on("dnf", "-q", "info", result=fixture("dnf5-info.txt"))
    out = Dnf(r).sizes(["git", "htop"])
    assert out["htop"] == (int(1.2 * MiB), 428 * KiB)


def test_failing_query_gives_unknown_not_an_error():
    r = FakeRunner().on("pacman", "-Si", result=Result(("pacman",), 1, "", "error: boom"))
    assert Pacman(r).sizes(["git"]) == {"git": (None, None)}

    def boom(cmd, _in):
        raise OSError("no pacman")
    assert Pacman(FakeRunner().on("pacman", "-Si", result=boom)).sizes(["git"]) == {"git": (None, None)}


# ---- 3.2 summary line -------------------------------------------------------------------

def plan_for(ctx, names):
    ctx.facts["packages"] = Resolution(native=list(names), aur=["yay-thing"], flatpak=[], unavailable=[], deferred=[])
    return engine.build_plan(ctx, [InstallNative()])


def test_show_plan_has_size_totals_and_unknown_count(tmp_path):
    r = FakeRunner().on("pacman", "-Si", result=fixture("pacman-Si.txt"))
    ctx = ctx_for(tmp_path, runner=r)
    plan = plan_for(ctx, ["git", "htop"])
    engine.show_plan(ctx, plan)
    text = ctx.ui.console.file.getvalue()
    assert "download 5.0 MiB, installed 39.3 MiB" in text, text


def test_size_line_counts_unknown_and_survives_query_failure(tmp_path):
    ctx = ctx_for(tmp_path, runner=FakeRunner().on("pacman", "-Si", result=Result(("pacman",), 1, "", "x")))
    plan = plan_for(ctx, ["git", "htop"])
    assert engine.size_summary(ctx, plan) == "Size: 2 package(s) size unknown"


# ---- 3.3 per-package install --------------------------------------------------------------

class Bad(FakeRunner):
    """pacman -S fails when the bad package is among the names."""

    def __init__(self, bad, dry_run=False):
        super().__init__(dry_run=dry_run)
        self.bad, self.installed = bad, set()
        self.on("pacman", "-Qq", result=lambda c, i: "\n".join(self.installed))
        self.on("pacman", "-Slq", result=lambda c, i: "git\nbadpkg\nhtop")
        self.on("pacman", "-S", result=self._s)

    def _s(self, cmd, _in):
        names = [a for a in cmd[2:] if not a.startswith("-")]
        if self.bad in names:
            return Result(tuple(cmd), 1, "", f"error: target not found: {self.bad}\n")
        self.installed.update(names)
        return 0


def run_install(tmp_path, runner):
    ctx = ctx_for(tmp_path, runner=runner)
    ctx.facts["packages"] = Resolution(native=["git", "badpkg", "htop"], aur=[], flatpak=[], unavailable=[], deferred=[])
    plan = engine.build_plan(ctx, [InstallNative()])
    engine.execute(ctx, plan)
    return ctx, plan


def test_one_bad_package_others_install_and_report_names_reason(tmp_path):
    r = Bad("badpkg")
    ctx, plan = run_install(tmp_path, r)
    assert r.installed == {"git", "htop"}
    assert plan.items[0].status == "partial"
    assert engine.has_partial(plan)
    assert any(c[-1] == "badpkg" and "git" not in c for c in r.calls if "-S" in c)   # tried alone
    events = {e["event"]: e for e in ctx.journal.events() if e["event"].startswith("packages_")}
    assert sorted(events["packages_installed"]["names"]) == ["git", "htop"]
    assert events["packages_failed"]["failed"] == [{"name": "badpkg", "reason": "error: target not found: badpkg"}]
    code = engine.report(ctx, plan)
    text = ctx.ui.console.file.getvalue()
    assert "badpkg" in text and "target not found" in text and "Packages that failed to install" in text
    assert code == 0   # report stays 0; the CLI maps a partial run to EXIT_PARTIAL


def test_cli_exit_code_constant_for_partial():
    from fai_linop import cli
    assert cli.EXIT_PARTIAL not in (cli.EXIT_OK, cli.EXIT_FAILED, cli.EXIT_USAGE, cli.EXIT_UNSUPPORTED)


def test_dry_run_never_retries_one_by_one(tmp_path):
    r = Bad("badpkg", dry_run=True)
    ctx, plan = run_install(tmp_path, r)
    installs = [c for c in r.calls if "-S" in c]
    assert len(installs) == 1 and plan.items[0].status == "done"
    assert not any(e["event"] == "packages_failed" for e in ctx.journal.events())


def test_all_good_is_plain_done(tmp_path):
    ctx, plan = run_install(tmp_path, Bad("zzz"))
    assert plan.items[0].status == "done" and not ctx.facts.get("install_failures")
