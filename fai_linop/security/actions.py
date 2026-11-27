"""`security` module (F26, F28–F30) and `blackarch` module (F21). Everything is
opt-in (D23). SSH changes go into a drop-in validated with `sshd -t`; USBGuard
and SSH password-login disable need a typed confirmation."""

from __future__ import annotations

import hashlib
import re
import tempfile
from pathlib import Path

from fai_linop.core.action import Action, Change, Context, Reversible, Risk, register
from fai_linop.core.common import EnableService, WriteFile, read_text
from fai_linop.package.actions import request
from fai_linop.platform.detect import Family
from fai_linop.system.actions import BLACKARCH_KEY

SYSCTL = """# FAI_LinOP security hardening (v2.5 set, CLAUDE.md D23)
kernel.dmesg_restrict = 1
kernel.kptr_restrict = 2
kernel.sysrq = 0
kernel.unprivileged_bpf_disabled = 1
fs.protected_fifos = 2
fs.protected_regular = 2
net.ipv4.conf.all.log_martians = 1
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.default.accept_redirects = 0
net.ipv4.conf.default.accept_source_route = 0
net.ipv6.conf.all.accept_redirects = 0
"""
SYSCTL_PATH = Path("/etc/sysctl.d/99-linop-security.conf")
SSHD_DIR = Path("/etc/ssh/sshd_config.d")
SSHD_DROPIN = SSHD_DIR / "10-linop.conf"


def _on(ctx: Context, key: str) -> bool:
    return bool(ctx.profile.get("security", key))


class Firewall(Action):
    id, title, risk, reversible = "security.firewall", "Firewall: deny incoming, allow outgoing", Risk.MEDIUM, Reversible.YES
    requires = ("packages.native",)

    def plan(self, ctx):
        if not _on(ctx, "firewall"):
            return []
        if ctx.os.family is Family.FEDORA:
            state = ctx.runner.run(["firewall-cmd", "--state"], sudo=True, mutating=False, check=False)
            return [] if state.ok else [Change("service", "firewalld", "enable --now (Fedora default firewall)")]
        status = ctx.runner.run(["ufw", "status"], sudo=True, mutating=False, check=False).stdout
        # v3.0 lesson: "inactive" contains "active" — match the whole word
        if re.search(r"^Status:\s+active\b", status, re.M):
            return []
        return [Change("service", "ufw", "default deny incoming / allow outgoing; SSH kept if sshd runs")]

    def apply(self, ctx):
        r = ctx.runner
        if ctx.os.family is Family.FEDORA:
            r.run(["systemctl", "enable", "--now", "firewalld"], sudo=True)
            return
        r.run(["ufw", "default", "deny", "incoming"], sudo=True)
        r.run(["ufw", "default", "allow", "outgoing"], sudo=True)
        sshd = r.run(["systemctl", "is-active", "sshd"], mutating=False, check=False).stdout.strip() == "active" or \
            r.run(["systemctl", "is-active", "ssh"], mutating=False, check=False).stdout.strip() == "active"
        if sshd:  # v2.5 enabled ufw without allowing SSH first: remote lock-out (S-06)
            if not r.run(["ufw", "allow", "OpenSSH"], sudo=True, check=False).ok:
                r.run(["ufw", "allow", "22/tcp"], sudo=True)
        r.run(["ufw", "--force", "enable"], sudo=True)
        r.run(["systemctl", "enable", "ufw"], sudo=True)


class SshDropIn(Action):
    id, title, risk, reversible = "security.ssh", "SSH hardening (drop-in, validated with sshd -t)", Risk.HIGH, Reversible.YES

    def content(self, ctx) -> str:
        lines = ["# FAI_LinOP SSH hardening (CLAUDE.md D23)"]
        if _on(ctx, "ssh_root_login"):
            lines.append("PermitRootLogin no")
        if _on(ctx, "ssh_disable_password") and ctx.facts.get("ssh_password_confirmed"):
            lines.append("PasswordAuthentication no")
            lines.append("KbdInteractiveAuthentication no")
        return "\n".join(lines) + "\n"

    def plan(self, ctx):
        if not (_on(ctx, "ssh_root_login") or _on(ctx, "ssh_disable_password")):
            return []
        if not Path("/etc/ssh/sshd_config").exists():
            ctx.ui.warn("security: OpenSSH server not installed — SSH hardening skipped")
            return []
        main = read_text(Path("/etc/ssh/sshd_config")) or ""
        if not re.search(r"^\s*Include\s+/etc/ssh/sshd_config\.d/\*\.conf", main, re.M):
            ctx.ui.warn("security: sshd_config has no `Include /etc/ssh/sshd_config.d/*.conf` — "
                        "FAI_LinOP does not edit sshd_config itself; SSH hardening skipped")
            return []
        if _on(ctx, "ssh_disable_password") and "ssh_password_confirmed" not in ctx.facts:
            ctx.facts["ssh_password_confirmed"] = ctx.ui.typed_confirm(
                "Disable SSH password login? Make sure your public key is in ~/.ssh/authorized_keys on this machine.",
                "KEYONLY")
        if read_text(SSHD_DROPIN) == self.content(ctx):
            return []
        return [Change("file", str(SSHD_DROPIN), self.content(ctx).strip().replace("\n", "; "))]

    def apply(self, ctx):
        ctx.files.write(SSHD_DROPIN, self.content(ctx).encode(), root=True, mode=0o644)
        if ctx.dry_run:
            return
        test = ctx.runner.run(["sshd", "-t"], sudo=True, check=False)
        if not test.ok:  # invalid config: take the drop-in out again before anything reloads sshd
            ctx.runner.run(["rm", "-f", str(SSHD_DROPIN)], sudo=True)
            raise RuntimeError(f"sshd -t rejected the configuration: {test.stderr.strip()}")
        for unit in ("sshd", "ssh"):
            if ctx.runner.run(["systemctl", "is-active", unit], mutating=False, check=False).stdout.strip() == "active":
                ctx.runner.run(["systemctl", "reload", unit], sudo=True)


class UsbGuard(Action):
    id, title, risk, reversible = "security.usbguard", "USBGuard: allow current devices, block new ones", Risk.HIGH, Reversible.YES
    requires = ("packages.native",)

    def plan(self, ctx):
        if not _on(ctx, "usbguard"):
            return []
        active = ctx.runner.run(["systemctl", "is-active", "usbguard"], mutating=False, check=False).stdout.strip()
        if active == "active":
            return []
        if "usbguard_confirmed" not in ctx.facts:
            ctx.facts["usbguard_confirmed"] = ctx.ui.typed_confirm(
                "USBGuard blocks every USB device plugged in later (keyboards too) until you allow it.", "USBGUARD")
        if not ctx.facts["usbguard_confirmed"]:
            ctx.ui.warn("security: USBGuard not confirmed — skipped")
            return []
        return [Change("file", "/etc/usbguard/rules.conf", "policy from currently connected devices"),
                Change("service", "usbguard", "enable --now")]

    def apply(self, ctx):
        if ctx.dry_run:  # the tool may not be installed yet: record "would run", never probe it
            ctx.runner.run(["usbguard", "generate-policy"], sudo=True)
            return
        policy = ctx.runner.run(["usbguard", "generate-policy"], sudo=True, mutating=False).stdout
        if not policy.strip():
            raise RuntimeError("usbguard generate-policy returned nothing — refusing to enable an empty policy")
        ctx.files.write(Path("/etc/usbguard/rules.conf"), policy.encode(), root=True, mode=0o600)
        ctx.runner.run(["systemctl", "enable", "--now", "usbguard"], sudo=True)


class Scans(Action):
    id, title, risk, reversible = "security.scans", "Security scans (reports in the run directory)", Risk.LOW, Reversible.YES
    requires = ("packages.native",)

    def plan(self, ctx):
        return [Change("command", "scan", "arch-audit/debsecan, Lynis, rkhunter, ClamAV (home)")] if _on(ctx, "scans") else []

    def apply(self, ctx):
        out = ctx.journal.run_dir / "scans"
        out.mkdir(exist_ok=True)
        home = str(ctx.home)
        jobs = {"lynis.txt": (["lynis", "audit", "system", "--quick"], True),
                "rkhunter.txt": (["rkhunter", "--check", "--sk", "--rwo"], True),
                "clamav.txt": (["clamscan", "-r", "-i", home], False)}
        jobs["vulns.txt"] = (["arch-audit"], False) if ctx.os.family is Family.ARCH else (["debsecan"], False)
        for name, (argv, sudo) in jobs.items():
            res = ctx.runner.run(argv, sudo=sudo, check=False, timeout=7200)
            if res.executed:
                (out / name).write_text(res.stdout + res.stderr)
        ctx.ui.info(f"scan reports: {out}")


CLAMAV_DB_DIR = Path("/var/lib/clamav")
RKHUNTER_DB = Path("/var/lib/rkhunter/db/rkhunter.dat")
AUTOSTART_SRC = Path("/usr/share/applications/opensnitch_ui.desktop")


class ClamavFirstUpdate(Action):
    """One `freshclam` before the update service starts (v2.5 1557-1562). Idempotent: runs only
    while no signature database (daily.cvd / daily.cld) exists yet."""
    id, title, risk, reversible = "security.clamav-db", "ClamAV: first signature download (freshclam)", Risk.LOW, Reversible.NO
    requires = ("packages.native",)

    def plan(self, ctx):
        if not _on(ctx, "tools") or any(CLAMAV_DB_DIR.glob("daily.c[lv]d")):
            return []
        return [Change("command", "freshclam", "first signature download before the update service starts")]

    def apply(self, ctx):
        # the update daemon holds the log file; stop it for the manual run (v2.5 1559)
        ctx.runner.run(["systemctl", "stop", "clamav-freshclam"], sudo=True, check=False)
        if not ctx.runner.run(["freshclam"], sudo=True, check=False, timeout=1800).ok:
            ctx.ui.warn("security: freshclam failed (no network?) - the update service will retry")


class RkhunterBaseline(Action):
    """`rkhunter --propupd` after installation (v2.5 1564-1567). Idempotent: only while the
    file-properties database does not exist yet, so a later run never blesses changed files."""
    id, title, risk, reversible = "security.rkhunter-propupd", "rkhunter: record the file-properties baseline", Risk.LOW, Reversible.NO
    requires = ("packages.native",)

    def plan(self, ctx):
        if RKHUNTER_DB.exists():
            return []
        return [Change("command", "rkhunter --propupd", "baseline of system file properties (first install only)")]

    def apply(self, ctx):
        ctx.runner.run(["rkhunter", "--propupd"], sudo=True, check=False)


class OpensnitchAutostart(Action):
    """Copy opensnitch_ui.desktop to ~/.config/autostart (v2.5 1760-1761), backup + journal (D10)."""
    id, title, risk, reversible = "security.opensnitch-autostart", "OpenSnitch UI: start at login", Risk.LOW, Reversible.YES
    requires = ("packages.native",)

    @staticmethod
    def _dest(ctx) -> Path:
        return ctx.home / ".config" / "autostart" / AUTOSTART_SRC.name

    def plan(self, ctx):
        if not _on(ctx, "opensnitch"):
            return []
        src, dest = read_text(AUTOSTART_SRC), read_text(self._dest(ctx))
        # packages are not installed at plan time: no source yet still means "will copy"
        if dest is not None and (src is None or src == dest):
            return []
        return [Change("file", str(self._dest(ctx)), "create" if dest is None else "update (backup kept)")]

    def apply(self, ctx):
        src = read_text(AUTOSTART_SRC)
        if src is None:
            if not ctx.dry_run:
                ctx.ui.warn(f"security: {AUTOSTART_SRC} not found - OpenSnitch UI autostart skipped")
            return
        ctx.files.write(self._dest(ctx), src.encode(), mode=0o644)


def security_rows(runner, family: Family, sysctl: Path | None = None, sshd: Path | None = None) -> list[tuple[str, str]]:
    """Read-only security summary for `linop doctor` (v2.5 dashboard 1583-1594): only
    mutating=False commands and file-existence checks."""
    def active(unit: str) -> str:
        return runner.run(["systemctl", "is-active", unit], mutating=False, check=False).stdout.strip() or "unknown"

    def present(path: Path) -> str:
        return "present" if path.exists() else "absent"

    firewall = "firewalld" if family is Family.FEDORA else "ufw"
    return [("Firewall", f"{firewall}: {active(firewall)}"),
            ("Sysctl hardening", present(sysctl or SYSCTL_PATH)),
            ("SSH drop-in", present(sshd or SSHD_DROPIN)),
            ("ClamAV updates", f"clamav-freshclam: {active('clamav-freshclam')}"),
            ("OpenSnitch", f"opensnitchd: {active('opensnitchd')}"),
            ("USBGuard", f"usbguard: {active('usbguard')}")]


def _sysctl(ctx):
    ctx.runner.run(["sysctl", "--system"], sudo=True)


@register("security", "Security", order=80)
def build(ctx: Context):
    ids = []
    if _on(ctx, "tools") or _on(ctx, "scans"):
        ids += ["clamav", "rkhunter", "lynis", "firejail", "nethogs",
                "arch-audit" if ctx.os.family is Family.ARCH else "debsecan"]
        if ctx.os.family is not Family.ARCH:
            ids.append("clamav-freshclam")
    if _on(ctx, "firewall") and ctx.os.family is not Family.FEDORA:
        ids.append("ufw")
    if _on(ctx, "opensnitch"):
        ids += ["opensnitch"] + (["python3-opensnitch-ui"] if ctx.os.family is Family.DEBIAN else [])
    if _on(ctx, "usbguard"):
        ids.append("usbguard")
    request(ctx, ids=ids)
    actions = []
    if _on(ctx, "tools"):
        freshclam = EnableService("security.freshclam", "clamav-freshclam", "ClamAV signature updates")
        freshclam.requires = ("security.clamav-db",)
        actions += [ClamavFirstUpdate(), freshclam]
    if _on(ctx, "tools") or _on(ctx, "scans"):
        actions.append(RkhunterBaseline())
    if _on(ctx, "sysctl"):
        actions.append(WriteFile("security.sysctl", "Kernel/network hardening (sysctl)",
                                 SYSCTL_PATH, lambda c: SYSCTL, root=True,
                                 mode=0o644, risk=Risk.MEDIUM, after=_sysctl))
    actions += [Firewall(), SshDropIn(), UsbGuard()]
    if _on(ctx, "opensnitch"):
        actions += [EnableService("security.opensnitch", "opensnitchd", "OpenSnitch application firewall"),
                    OpensnitchAutostart()]
    actions.append(Scans())
    return actions


# ---- BlackArch (Arch only) --------------------------------------------------------------

STRAP_URL = "https://blackarch.org/strap.sh"
BLACKARCH_PREREQ = ["jdk17-openjdk", "jdk11-openjdk", "rust", "opencl-mesa"]
CORE_GROUPS = ["blackarch-webapp", "blackarch-networking", "blackarch-wireless"]


def blackarch_enabled() -> bool:
    return re.search(r"^\[blackarch\]", read_text(Path("/etc/pacman.conf")) or "", re.M) is not None


class BlackArchRepo(Action):
    id, title, risk, reversible = "blackarch.repo", "BlackArch repository (strap.sh, third-party)", Risk.HIGH, Reversible.ONE_WAY

    def plan(self, ctx):
        if ctx.profile.get("blackarch", "install") == "remove" or blackarch_enabled():
            return []
        # D14: the typed confirmation is asked up front (before the summary), never mid-run
        if "blackarch_confirmed" not in ctx.facts:
            fetched = ctx.runner.run(["curl", "-fsSL", "--max-time", "60", STRAP_URL], mutating=False, check=False)
            digest = hashlib.sha256(fetched.stdout.encode()).hexdigest() if fetched.ok and fetched.stdout else ""
            hint = (f"strap.sh SHA-256 {digest}. Compare it with blackarch.org/downloads." if digest
                    else "strap.sh could not be fetched now (no network or no curl) — it is fetched again at apply time.")
            ctx.facts["blackarch_digest"] = digest
            ctx.facts["blackarch_confirmed"] = ctx.ui.typed_confirm(
                f"BlackArch runs {STRAP_URL} as root (third-party, one-way). {hint}", "BLACKARCH")
        if not ctx.facts["blackarch_confirmed"]:
            ctx.ui.warn("blackarch: strap.sh not confirmed — skipped")
            return []
        return [Change("repo", "blackarch", f"runs {STRAP_URL} as root (SHA-256 checked against the confirmed one)")]

    def apply(self, ctx):
        if ctx.dry_run:  # record "would run" only; no download in a dry run
            ctx.runner.run(["sh", "strap.sh"], sudo=True)
            return
        if not ctx.facts.get("blackarch_confirmed"):
            raise RuntimeError("BlackArch strap.sh not confirmed")
        with tempfile.TemporaryDirectory(prefix="linop-blackarch-") as tmp:
            script = Path(tmp) / "strap.sh"
            body = ctx.runner.run(["curl", "-fsSL", "--max-time", "60", STRAP_URL], mutating=False).stdout
            script.write_text(body)
            digest = hashlib.sha256(body.encode()).hexdigest()
            ctx.journal.write("third_party_script", url=STRAP_URL, sha256=digest)
            seen = ctx.facts.get("blackarch_digest")
            if seen and seen != digest:
                raise RuntimeError("strap.sh changed since it was confirmed — aborting")
            ctx.runner.run(["sh", str(script)], sudo=True, interactive=True)


class BlackArchTools(Action):
    id, risk, reversible = "blackarch.tools", Risk.MEDIUM, Reversible.PARTIAL
    requires = ("blackarch.repo",)
    title = "BlackArch tools"

    def plan(self, ctx):
        mode = ctx.profile.get("blackarch", "install")
        if mode == "remove":
            return []
        groups = ["blackarch"] if mode == "full" else CORE_GROUPS
        return [Change("package", g, "BlackArch group (no --overwrite)") for g in groups]

    def apply(self, ctx):
        groups = ["blackarch"] if ctx.profile.get("blackarch", "install") == "full" else CORE_GROUPS
        # v2.5 used --overwrite '*' (could replace files of other packages, S-05): not any more
        ctx.runner.run(["pacman", "-S", "--needed", "--noconfirm", *groups], sudo=True, interactive=True)


class BlackArchRemove(Action):
    id, title, risk, reversible = "blackarch.remove", "Remove the BlackArch repository", Risk.MEDIUM, Reversible.YES

    def plan(self, ctx):
        if ctx.profile.get("blackarch", "install") != "remove" or not blackarch_enabled():
            return []
        return [Change("repo", "blackarch", "remove from /etc/pacman.conf (backup kept) and delete its pacman key; installed tools stay")]

    def apply(self, ctx):
        conf = read_text(Path("/etc/pacman.conf")) or ""
        new = re.sub(r"^\[blackarch\]\n(?:(?!\[).*\n)*", "", conf, flags=re.M)
        ctx.files.write(Path("/etc/pacman.conf"), new.encode(), root=True, mode=0o644)
        # v2.5 1044-1054: the repository key goes too (an absent key is not an error)
        ctx.runner.run(["pacman-key", "--delete", BLACKARCH_KEY], sudo=True, check=False)
        ctx.runner.run(["pacman", "-Syu", "--noconfirm"], sudo=True, interactive=True)


@register("blackarch", "BlackArch", order=85)
def build_blackarch(ctx: Context):
    if ctx.os.family is not Family.ARCH:
        ctx.ui.warn("blackarch: Arch only — use the `cyber` package group on this distro")
        return []
    if ctx.profile.get("blackarch", "install") == "full":
        # v2.5 996: provider-lock prerequisites; names come from the catalog, never guessed
        request(ctx, ids=BLACKARCH_PREREQ)
    return [BlackArchRepo(), BlackArchTools(), BlackArchRemove()]
