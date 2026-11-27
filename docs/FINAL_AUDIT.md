# FAI_LinOP v3.0 — final audit (2026-09-24)

> Audited under the former name "ArCoN v3". The project was renamed on 2026-11-27 (CLAUDE.md D29); commands below use the new name `linop`. After the rename, CI run 46033064904 (commit `29386b2`) passed: lint, unit, and the distro jobs (catalog check, dry run, real apply + rollback) in archlinux, debian:stable, ubuntu:24.04 and fedora containers. Nothing native was re-tested; every NOT TESTED / PARTIAL verdict below stands.

> **v3.0.0 re-check (2026-11-27).** A second review (V300 list, 13 items) fixed: dotfile capture without diff/backup, dry runs that wrote files, `-y` enabling opt-in sections, planning errors counted as success, overwritten first backups, rollback that stopped at the first failure or skipped the monitor layout, reset protecting Arch names only, file-writing sub-commands allowed as root, monitor layout/identity bugs. Local `pytest` on `71738dc`: 197 passed, 3 skipped (UNIT). Verdicts below are unchanged in level: nothing new ran natively or in a VM. Gaps against v2.5 are listed per feature in `docs/FEATURE_MATRIX.md` (PARTIAL → v3.1.0).

Verdicts: **PASS** (tested at the stated level) · **PARTIAL** (some paths tested) · **NOT TESTED** (implemented, never executed for real) · **FAIL**.
"Container" never validates GPU, monitors, a real desktop session or hardware.

## Summary

| Area | Verdict | Highest level | Evidence |
|---|---|---|---|
| Owner dotfiles protected (D8/D18) | PASS | INTEGRATION | sha256 manifest, owner settings, D18 checker (mutation test), golden v3 files, real dconf load in container |
| Core: runner, profile, journal, backup, rollback, engine, wizard, CLI | PASS | INTEGRATION (Ubuntu container) | 60+ unit tests; real apply → idempotent re-run → rollback |
| Resume (F11) | PASS | UNIT | failure → resume skips done actions |
| Preflight (F01–F05) | PARTIAL | UNIT | live ISO, stale lock asked; sudo/network only exercised in the real run |
| Speed test (F14) | NOT TESTED | — | implemented, never executed |
| Packages: Ubuntu | PASS | INTEGRATION | real apt install in container; catalog verified (81 ok / 7 missing → runtime fallback) |
| Packages: Arch / Debian / Fedora | PARTIAL | UNIT | FakeRunner; CI matrix configured, not run |
| AUR helper + AUR packages | NOT TESTED | UNIT (plan only) | makepkg never executed |
| Flatpak fallback | PARTIAL | UNIT + dry run | Flathub ids not verified (flathub.org unreachable) |
| System upgrade / multilib / mirrors / keyring reset | PARTIAL | UNIT | text transforms tested; commands never executed |
| GNOME settings (F17) | PASS | INTEGRATION | real dconf database via dbus-run-session; rollback restores |
| GNOME debloat (F18) | PARTIAL | UNIT | |
| Display D13 — GNOME | PARTIAL | UNIT (fake Mutter) | **no live Mutter session** — first native run must be `linop plan` (Mutter verify mode); v3.0.0: positions kept, twin monitors distinct, rollback re-applies the layout (fake Mutter only) |
| Display D13 — Hyprland | PARTIAL | UNIT | `desc:` matching not checked on real Hyprland |
| Gaming / GPU drivers (F19) | PARTIAL | UNIT | package selection per GPU tested; no driver installed anywhere |
| Dotfiles deploy/diff/capture (F23, N2) | PASS | INTEGRATION | Terminator config deployed byte-identical in the real run |
| Hyprland module (F22) | PARTIAL | UNIT | rendered files D18-valid |
| Terminal themes (F24) | PARTIAL | UNIT | kitty kitten / alacritty import never executed |
| Shell: zsh + Oh-My-Zsh (F25) | PASS | INTEGRATION | pinned clone + `.zshrc` + chsh in the real run |
| Shell: fish/bash + Starship | PARTIAL | UNIT | |
| Security: sysctl, firewall, SSH (F29) | PARTIAL | UNIT | ssh drop-in + `sshd -t` path never executed |
| Security: scans, OpenSnitch, USBGuard (F28, F30) | NOT TESTED | — | |
| BlackArch (F21) | NOT TESTED | — | |
| Optimization / cleanup (F27, F32) | PARTIAL | UNIT | |
| Factory reset (F10) | PARTIAL | UNIT | configs backup/restore tested; package removal and dconf reset only with FakeRunner |
| Reboot prompt (F33) | NOT TESTED | — | |
| Windows / macOS (D3) | PASS | UNIT | stubs refuse with exit 3 |
| CI workflow | NOT TESTED | — | needs the branch on GitHub |

No FAIL verdicts. Every v2.5 feature is in `docs/FEATURE_MATRIX.md` (keep / replace / fix / N-A); nothing was dropped silently.

## Known risks before the first native run

1. **Mutter D-Bus API** is implemented from the interface description and tested only against a fake. `linop plan` uses Mutter's *verify* method — it cannot change the screens — so run `plan` first and check the Display rows.
2. **NVIDIA:** the open-module decision uses the PCI device id (≥ 0x1E00 = Turing+). Check `linop doctor` shows "open modules ok" for your card before enabling gaming.
3. **AUR as root** fails by design (makepkg); run FAI_LinOP as your user.
4. **Catalog on Arch** is not verified yet — run `python3 scripts/verify_catalog.py` once on your machine.

## Native checklist (owner's Arch machine, NVIDIA, GNOME)

Run from the GNOME session, as your user, in the repo:

```bash
./setup.sh doctor                                    # GPU shows nvidia …(open modules ok)? kernels? snapshot tool?
python3 scripts/verify_catalog.py > /tmp/catalog.md  # Arch column: any MISSING?
./setup.sh display show                              # 2–3 monitors, current vs best mode
./setup.sh display capture --profile profiles/mrfedai.toml   # saves your layout
./setup.sh --profile profiles/mrfedai.toml plan      # read the whole plan; nothing changes
./setup.sh --profile profiles/mrfedai.toml apply     # one confirmation
./setup.sh --profile profiles/mrfedai.toml apply     # must say "Nothing to do"
./setup.sh runs                                      # and, if needed: ./setup.sh rollback
```

Report back: `linop runs`, the run's `journal.jsonl`, and anything that looked wrong. Each passing item moves from UNIT/INTEGRATION to NATIVE TESTED in `docs/FEATURE_MATRIX.md`.
