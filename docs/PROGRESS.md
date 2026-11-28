# FAI_LinOP v3 (formerly ArCoN v3) — progress log

> The entries for Phases 1–8 were written before the rename and are kept as written: `arcon` there is today's `linop` command, `arcon/` is today's `fai_linop/` package.

One entry per phase (CLAUDE.md, continuous mode). Format: done · evidence · NOT tested · risks · deviations · questions.

## Phase 1 — audit (2026-09-24) · commit `a361fa7`

- **Done:** `docs/AUDIT.md`, `docs/FEATURE_MATRIX.md`, CLAUDE.md, prior audit verified (16/17 confirmed).
- **Evidence:** `bash -n` OK; ShellCheck 0.9.0 52 findings; theme/installer URLs checked (HTTP codes in AUDIT §7); `v3.0` bats unit suite 68/68.
- **NOT tested:** BlackArch key fingerprint (site unreachable).
- **Deviations:** tag `v2.5-final` not created (`v2.5.0` already on the same commit).

## Phase 2 — characterization & golden files · commit `6a98f18`

- **Done:** recording mocks + harness running `setup.sh` from tag `v2.5.0` (Debian, Arch via mount namespace); golden snapshots; owner settings + source hash manifest; v3 golden `gno.conf` (solid black) / `hyprlock.conf`; D18 checker.
- **Evidence:** 47 tests passed; mutation check (`prefer-dark` → `default`) fails 5 tests; v3 `gno.conf` loaded into a real dconf DB and read back.
- **NOT tested:** real GNOME session, real installs.

## Decisions — commit `bea45ca`

D20–D28 recorded (Arch dual-boot + NVIDIA, English + rich CLI, Flatpak fallback, security all opt-in, Hyprland = own config only, wallpapers → private repo, owner profile, release plan, package groups).

## Phase 3 — core skeleton

- **Done:**
  - `arcon/core/runner.py` — single command gate: `SystemRunner`, `DryRunRunner` (probes run, mutations recorded), `FakeRunner`; sudo prefix, timeouts, 127 for missing commands.
  - `arcon/platform/detect.py` — os-release parsed (never sourced), family + tier (supported / experimental derivative / stub / unsupported).
  - `arcon/core/profile.py` — TOML profile, strict schema (unknown keys and bad values are errors), `tomlkit` keeps comments; `profiles/mrfedai.toml` (D26).
  - `arcon/recovery/` — JSONL journal (fsync per event, torn last line tolerated), verified per-file backup + atomic write + rollback, Snapper/Timeshift detection.
  - `arcon/core/engine.py` — plan → show (risk, reversibility, ONE-WAY/HIGH warnings) → execute → verify → report from real statuses; resume skips done actions; `requires`; `--keep-going`.
  - `arcon/core/wizard.py` — all questions up front, conditional follow-ups, "reuse previous answers".
  - `arcon/cli.py` — `arcon`, `plan`, `apply`, `wizard`, `resume`, `rollback`, `runs`, `profile`, `doctor`; refuses root for mutating commands (D15); refuses Windows/macOS (stub, exit 3) and unknown distros.
  - `setup.sh` is now the thin bootstrap (uv from distro package or a private venv — no `curl | sh`); v2.5 moved unchanged to `legacy/v2.5/`. `setup.ps1` = Windows stub.
- **Evidence:** `uv run pytest` → 82 passed (35 new unit tests); `arcon doctor`, `arcon --profile profiles/mrfedai.toml plan` run in the Ubuntu container; ShellCheck clean on `setup.sh`.
- **Bug found by tests and fixed:** run ids collided within one second → now microseconds + random suffix.
- **NOT tested:** snapshot creation (no Snapper/Timeshift here); root-owned file writes only with FakeRunner; `setup.sh` uv installation path (uv already present).
- **Risks:** no feature modules yet — `arcon plan` reports "nothing to do" until Phase 4/5.
- **Deviations:** none.

## Phase 4 — hardware, display, packages

- **Done:**
  - `arcon/hardware/linux.py` — GPUs from sysfs (vendor, PCI device id, boot VGA, hybrid), NVIDIA open-module capability (device id ≥ 0x1E00 = Turing+), RAM, root disk SSD/HDD, battery, installed kernel flavours (`/usr/lib/modules/*/pkgbase`), virtualization.
  - `arcon/display/` — monitor model, D13 mode ranking (resolution-first / refresh-first), layout that keeps order/y/scale and recomputes x so neighbours touch; GNOME backend over Mutter `org.gnome.Mutter.DisplayConfig` (jeepney): dry run = Mutter **verify** method, real run = persistent, per-monitor fallback to the next mode when a mode does not become active; Hyprland backend (`hyprctl monitors all -j`, `highres`/`highrr` when Hyprland is not running) and the D18 generated monitor block. `arcon display show|capture` (capture writes the current layout into the profile).
  - `arcon/data/packages.toml` — 126 logical packages (D28 groups + internal groups), explicit `aur:` markers; `scripts/verify_catalog.py`; `docs/PACKAGE_CATALOG.md`.
  - `arcon/package/` — pacman, AUR helper (yay/paru, as user), apt (Debian+Ubuntu), dnf, Flatpak; one transaction per source; resolution native → AUR (Arch) → Flatpak (D22) → reported as unavailable. User extras that exist nowhere are reported, never sent to yay (v2.5 bug #15). `packages` module: native, AUR helper bootstrap (yay-bin via makepkg in a temp dir), AUR, Flathub, Flatpak actions.
  - `tests/golden/v3/hyprland.conf` (deferred from Phase 2) — obeys D18.
- **Evidence:** `uv run pytest` → 105 passed (23 new). Ubuntu 24.04 container: `verify_catalog.py` 81 ok / 7 missing (handled at runtime); `arcon --profile profiles/mrfedai.toml plan` resolved against the real apt index (28 repo packages, Flatpak fallback for 11, 5 reported unavailable).
- **NOT tested:** real Mutter D-Bus (no GNOME session here) — the GNOME backend is UNIT TESTED against a fake Mutter only; Hyprland `desc:` matching on real Hyprland; Arch/Debian/Fedora package queries (CI, Phase 7); Flathub ids (flathub.org unreachable); AUR helper build.
- **Risks:** Mutter's API details (`ApplyMonitorsConfig` signature, variant layout) are implemented from the documented interface, not exercised against a live session — first native run must use `arcon plan` (verify method) before `apply`. NVIDIA "open capable" threshold is a PCI id heuristic.
- **Deviations:** none.
- **Intentional fix (N-06):** the Hyprland group no longer installs dolphin — the v2.5 config uses nautilus, which GNOME already provides.

## Phase 5 — feature migration

- **Done (one module per v2.5 sector, all registered explicitly in `arcon/modules.py`):**
  - `system` — full upgrade (Arch: keyring first, then `-Su`; never `-Sy` alone), opt-in reflector with mirrorlist backup, opt-in keyring reset (v2.5 behaviour, HIGH), multilib enabled only for gaming, followed by `-Syu`.
  - `gnome` — gno.conf rendered with D18 (user + wallpaper; default solid black), plan lists only the dconf keys that differ, full `dconf dump /` backup, verification of the owner keys, rollback via the dump; exact-name debloat.
  - `gaming` — GPU packages from detection: NVIDIA open modules (`nvidia-open` on the stock kernel, `-dkms` + headers for every other kernel, `nvidia-prime` on hybrid), pre-Turing NVIDIA reported (not automated), Ubuntu `ubuntu-drivers`, Debian/Fedora reported (no repo changes); GameMode config at the path GameMode reads (D-08), gamemode group.
  - `dotfiles` — deploy (D18-checked before writing), `arcon dotfiles diff|capture`; capture never brings generated parts (monitor block, arcon-colors source) into the repo.
  - `hyprland` — packages + ArCoN's config only (D24), monitor block from detection.
  - `terminal` / `shell` — Kitty themes via kitty's own kitten (config backed up), Alacritty themes imported (config never overwritten, `curl -f`), Oh-My-Zsh + plugins from pinned commits (no `curl | sh`), `.zshrc` edits only ZSH_THEME/plugins, Starship presets, chsh checked against /etc/shells with the real login shell (getent).
  - `security` (all opt-in, D23) — tools, sysctl drop-in, ufw/firewalld (SSH allowed before enabling; "inactive" ≠ active), SSH drop-in validated with `sshd -t` and removed again if invalid, USBGuard + SSH key-only behind typed confirmations, scans with reports in the run dir, OpenSnitch. BlackArch: strap.sh SHA-256 shown + typed confirmation (ONE-WAY), no `--overwrite`, removal restores pacman.conf.
  - `optimization` / `cleanup` — TRIM only on SSD, Bluetooth only with an adapter, ZRAM only when none exists, ananicy-cpp; orphans listed, `paccache -rk2` by default (purge = v2.5 `-Scc`, opt-in).
  - `arcon reset` (D19) — explicit paths, protected packages' configs kept, user data (browser/editor/chat profiles) never touched, directory backups + dconf dump, typed `CLEAN`.
  - Preflight — disk, network, live ISO, stale pacman lock (asked, never silent), sudo, optional speed test; reboot prompt only when an action needs it.
  - `wallp/` removed from the repo (D25; still in `v2.5.0`).
- **Evidence:**
  - `uv run pytest` → 130 passed, 1 skipped (the real-run test, opt-in).
  - **Real run** (`ARCON_REAL_RUN=1`, Ubuntu 24.04 container, `dbus-run-session`): `arcon apply` installed packages via apt, loaded gno.conf into a real dconf database (read back `'prefer-dark'`, picture-options `'none'`), deployed the Terminator config byte-identical, cloned Oh-My-Zsh at the pinned commit, changed the login shell; a second `apply` printed "Nothing to do"; `arcon rollback` removed the deployed files and restored dconf.
  - Dry run with `profiles/mrfedai.toml` leaves `$HOME` untouched (checked).
- **Bugs found and fixed while testing:** `$USER` unset crashed chsh/gamemode (now getent/getpass); dry run created `~/.oh-my-zsh/custom/plugins`; a broken third-party apt source aborted every install (now a warning); chsh was re-planned every run because `$SHELL` is not the login shell.
- **NOT tested:** Arch/Debian/Fedora real runs (CI Phase 7 = containers only), NVIDIA driver install, multilib, reflector, BlackArch, USBGuard, OpenSnitch, scans, firewall on a real host, Mutter display changes, Hyprland — all UNIT at most.
- **Deviations:** none.

## Phase 6 — CLI polish and migration guide

- **Done:** global options accepted before or after the command; help epilog with examples; `arcon profile init` (documented template, never overwrites); README rewritten for v3 with an honest platform table; `docs/MIGRATION.md` (every v2.5 prompt → profile key/command, every intentional behaviour change with its reason); v2.5 README kept in `legacy/v2.5/`.
- **Evidence:** 132 passed; template test checks every schema key/default; `arcon profile init` + `validate` run.
- **NOT tested:** —
- **Deviations:** none.

## Phase 7 — CI and test-status report

- **Done:** `.github/workflows/ci.yml` — lint (ShellCheck, compileall), unit (pytest as user + characterization as root for the Arch scenarios), distro matrix (archlinux, debian:stable, ubuntu:24.04, fedora): catalog verification per distro (artifact), dry run of the owner profile, real apply + rollback. The real-run test is distro-neutral now (package check through the provider; on Arch as root only the two AUR actions may fail — makepkg refuses root). `docs/TESTING.md`: level-by-level status.
- **Evidence:** workflow parses (PyYAML), ShellCheck/compileall clean locally, 132 passed; real-run test passes again on Ubuntu 24.04 after the generalisation.
- **NOT tested:** the workflow itself has **not run** — it needs the branch on GitHub. Docker Hub is blocked in this environment, so no local container matrix either.
- **Deviations:** none.

## Phase 8 — documentation and final audit

- **Done:** `CHANGELOG.md`, `docs/FINAL_AUDIT.md` (verdict per area, known risks, native checklist), CLAUDE.md status.
- **Evidence:** see FINAL_AUDIT — no FAIL; PASS areas are backed by integration runs in the Ubuntu container.
- **NOT tested:** everything marked NOT TESTED / PARTIAL in FINAL_AUDIT; no VM or native run.
- **Deviations:** none. Release (D27: merge to main, tag v3.0.0, archive the Bash branch) is **not** done — it waits for push access, a green CI run and the native checklist.

## Rename — ArCoN v3 → FAI_LinOP (2026-11-27) · commit `29386b2`

- **Done:** owner decision D29. Package `arcon/` → `fai_linop/`, command `arcon` → `linop`, own paths and file names `arcon` → `linop` (`~/.config/linop`, `~/.local/state/linop`, `configs/hypr/linop-colors.conf`, `99-linop-security.conf`, `10-linop.conf`), `ARCON_*` → `LINOP_*`, D18 monitor markers `# >>> FAI_LinOP monitors (generated) >>>`, repository URLs → `MrFedai/FAI_LinOP`. `tests/golden/v3/` and `tests/golden/sources.sha256` updated for the new marker text and the renamed colours file (its header comment changed, so its hash changed).
- **Kept as ArCoN:** `legacy/`, `tests/characterization/`, `tests/golden/v25/`, `docs/AUDIT.md`, `docs/PRIOR_AUDIT.md`, `docs/PHASE_1_AUDIT_PROMPT.md`, the phase entries above, the wallpaper repo name, the test user `arcontest`.
- **Owner dotfiles (D8):** `configs/gno.conf`, `configs/terminator/config`, `configs/hypr/hyprland.conf`, `hypridle.conf`, `hyprlock.conf` are byte-identical (`git status` shows no change; hashes in `sources.sha256` unchanged).
- **Evidence:** local `pytest`: 132 passed, 3 skipped (UNIT, Ubuntu 26.04). CI run 46033064904 on `29386b2`: lint, unit, distro × {archlinux, debian:stable, ubuntu:24.04, fedora} all `success` (INTEGRATION, container). GitHub repository renamed to `MrFedai/FAI_LinOP` by the owner; fast-forwarded into `main` and pushed.
- **NOT tested:** native run on the owner's Arch machine; `setup.sh` one-line install under the new name (CI only ShellChecks it).
- **Deviations:** D18 text changed (marker names, colours file name) — by owner instruction, recorded in D29.

## v3.0.0 hardening (V300 list, 2026-11-27) · commits `42c7400`…`71738dc`

- **Done:** 13 items from the pre-release review: 1.2/1.11 dotfile capture + deploy diff (`8a5e110`), 1.3/1.12 dry run writes nothing, root refusal per sub-command (`42c7400`), 1.4 `-y` keeps wizard defaults (`fdd3501`), 1.5/1.6 planning errors fail, dry run without tools (`69db002`), 1.7/1.8/1.10 backups, rollback, protected names (`e105e31`), 1.9 monitors + display rollback (`71738dc`), 1.13 feature matrix (`fc60f9a`). Version 3.0.0, CHANGELOG, README, TESTING, FINAL_AUDIT updated.
- **Evidence:** local `pytest` on `71738dc`: 197 passed, 3 skipped (UNIT). Lint (compileall + `bash -n`) green.
- **NOT tested:** native run on the owner's Arch machine (FINAL_AUDIT checklist); live Mutter / Hyprland for the new display code; GitHub CI on the release commit (runs on push).
- **Risks:** display rollback of runs recorded before `71738dc` reports FAILED (no modes recorded) and asks for a manual fix; Hyprland live path without a profile layout still lines monitors up left to right.
- **Deviations:** none. Owner decision 0096: rollback re-applies the monitor layout (instead of declaring the action irreversible).
- **Questions for the owner:** none.

## v3.0.1 fixes (V301 list, 2026-11-27) · commits `d771f59`…`2912fcd`

- **Done:** 8 items from the V301 review: 2.7 single `pacman -Syu` + unknown family reported, 2.8 NVIDIA reboot notice on the driver action (`d771f59`); 2.5 honest cache purge, simulated orphan/debloat removal (`f4cb193`, `9d8c29f`); 2.1 Zsh plugin order, clone via temp dir + `verify()`, 2.3 Alacritty import via tomlkit (`94a954d`); 2.2 deferred package resolution at apply, D22 order (`5d1c67a`); 2.4 Starship init/preset, 2.6 `util-linux-user` / `ubuntu-drivers-common` from the catalog (`111fad9`, `2912fcd`). Version 3.0.1, CHANGELOG, TESTING, FINAL_AUDIT, FEATURE_MATRIX, README badge.
- **Evidence:** local `pytest` on `2912fcd`: 240 passed, 3 skipped (UNIT). Lint (compileall + `bash -n`) green per task.
- **NOT tested:** GitHub CI distro matrix on these commits (runs on push; the Fedora job now relies on the catalog for `util-linux-user`); native run on the owner's Arch machine; multilib / apt-update deferral against real package databases.
- **Risks:** the apt "old index" threshold (1 day, ctime) is a heuristic — a false "old" only defers names; without a built AUR helper a misspelt name can still trigger the helper build; Fedora `dnf repoquery` may download metadata at plan time.
- **Deviations:** none. Owner decision (27.11): plan-time-unknown sources are deferred, planning stays side-effect free.
- **Questions for the owner:** none.

## v3.0.2 Fedora chsh fix (2026-11-27) · commit `bd06ba6`

- **Done:** catalog `util-linux-user` → Fedora package `util-linux` (Fedora 45 ships `chsh` there; `util-linux-user` is only a provide that `dnf repoquery` does not list). Version 3.0.2, CHANGELOG, TESTING, FINAL_AUDIT, README badge.
- **Evidence:** CI run 46047856714 on the v3.0.1 tag: fedora job failed (`util-linux-user | MISSING`, login shell stayed `/bin/bash`). CI run 46048542414 on `bd06ba6`: all six jobs green. Local `pytest`: 240 passed, 3 skipped.
- **NOT tested:** Fedora 44 and older; native run on the owner's Arch machine.
- **Deviations:** none.
- **Questions for the owner:** none.

## v3.1.0 v2.5 parity gaps (2026-11-28) · commits `8f82261`…`dd07c7b`

- **Done:** items 3.1-3.11: package size preview + per-package result (`8f82261`), BlackArch prerequisites + first run of security tools + doctor summary (`2bc94c2`), reset parity (`48b2f88`), wallpaper repo (`43305fc`), NVIDIA modeset audit (`412d164`), libvirtd / AnyDesk services, Kitty/Alacritty themes, slow-connection warning, nautilus (`4c23450`, `9e06085`), wizard questions + `PROFILE_ONLY` (`dd07c7b`). Item 3.12: FEATURE_MATRIX (no PARTIAL / NOT MIGRATED / MISSING rows left), MIGRATION, CHANGELOG, README, TESTING, FINAL_AUDIT; version 3.1.0.
- **Evidence:** local `ci` job on `dd07c7b`: 328 passed, 3 skipped (UNIT). Docs commit: ruff + `tests/unit/test_core.py`, `tests/unit/test_v310_wizard.py` green on the worktree code.
- **NOT tested:** native run on the owner's Arch + NVIDIA machine (modeset, wallpaper clone, services, BlackArch prerequisites, security first runs, `reset --shell`); F33 reboot prompt has no unit test. Container CI: run 46101718666 on `2cf6a79` green (lint, unit, 4 distros) — INTEGRATION, no hardware/desktop.
- **Risks:** size queries differ per package manager (dnf 4 vs 5) and are only parsed from fixtures; the alacritty-theme commit pin is not re-verified against upstream in CI; AnyDesk service is skipped for Flatpak by design.
- **Deviations:** none.
- **Questions for the owner:** none.

## Staged setup + Linux only (D30, D31 — owner decisions 2026-11-28) · branch `feat/kademeli-kurulum`

- **Done:** D30 (replaces D14): `linop` runs one module at a time — question → the module's own questions → short summary → confirm → apply → next (`core/staged.py`: `StagedRun`, `Stage`; `core/wizard.py`: `Wizard.ask_module`). Answers saved after every module; preflight + snapshot once, right before the first real change; `linop resume` asks only modules not asked yet (journal `stage` events); `linop apply` / `plan` keep the batch flow. Short output by default (one line per action, packages counted per source, file diffs always shown — D10), full tables with `-v`; the final report lists only failed / partial / not-run actions plus a one-line summary. D31 (replaces D3): Windows / macOS stubs and `setup.ps1` removed, `linop` exits 3 with "Linux only" elsewhere; FEATURE_MATRIX lost its Windows / macOS columns.
- **Evidence:** local `ci` job (compileall + `bash -n` + full pytest): 341 passed, 3 skipped (UNIT; the skips need a container). 13 new tests in `tests/unit/test_staged.py` (interleaving proven: module 1 is applied before module 2 is asked). Dry run of the owner profile on Ubuntu 26.04 (`linop -n`, state redirected to a scratch dir): 13 modules, 57 lines of output, exit 0.
- **NOT tested:** a real (non-dry) staged run on any machine; container CI on this branch (not pushed); native run on the owner's Arch machine; `linop resume` after a real Ctrl-C (only the failed-action path is unit tested).
- **Risks:** the short summary cuts setting / service lists after 6 entries (the full list needs `-v`); with `--yes` the "Apply <module>?" question is answered yes even for one-way actions (same as the batch flow before); BlackArch is still asked on non-Arch distros.
- **Deviations:** D14 and D3 are superseded by D30 and D31 — both by owner request, recorded in CLAUDE.md.
- **Questions for the owner:** none.
