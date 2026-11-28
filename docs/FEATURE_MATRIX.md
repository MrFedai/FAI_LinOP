# ArCoN v2.5 → FAI_LinOP v3 Feature Parity Matrix

Source of feature IDs: `docs/AUDIT.md` §2. Update this file in every phase.

**Action:** keep (same intent/behaviour) · replace (same intent, different mechanism) · fix (v2.5 behaviour is a bug/unsafe; not ported as-is without owner approval) · N-A (with reason) · new
**Reversible:** yes · partial · no · ONE-WAY (third-party code, D16)
**Platforms:** Linux only (D31) — the Windows / macOS columns were removed on 2026-11-28.
**Status values:** NOT MIGRATED · PARTIAL (label: what exists is tested at that level; the gap is named in the Action column; none are left in v3.1.0) · MIGRATED (label) where label = UNIT / INTEGRATION / VM / NATIVE — the highest level actually run. Core items are distro-independent, so all Linux columns carry the same label.

| ID | Feature | Target module | Action | Reversible | Arch | Debian | Ubuntu | Fedora |
|---|---|---|---|---|---|---|---|---|
| F01 | stale pacman lock removal | core/preflight.py | fix (ask, never silent) | n/a | MIGRATED (UNIT) | N-A | N-A | N-A |
| F02 | internet check | core/preflight.py | fix | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F03 | disk ≥ 10 GB | core/preflight.py | keep | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F04 | sudo check | core/preflight.py | keep | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F05 | Live-USB detection | core/preflight.py | fix (was commented out) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F06 | OS detection | platform/detect.py | fix (parse, don't source) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F07 | package-manager selection | package/providers.py | replace | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT; dry-run against real apt in Ubuntu 24.04 container) | MIGRATED (UNIT) |
| F08 | package groups (76 → 7 groups, 70 kept, 6 removed: D28) | fai_linop/data/packages.toml | replace (per-distro names) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT; dry-run against real apt in Ubuntu 24.04 container) | MIGRATED (UNIT) |
| F09 | main menu | cli.py / core/wizard.py / core/staged.py | replace (D30: staged, one module at a time — the v2.5 section-by-section rhythm) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F10 | Smart Factory Reset | recovery/reset.py + `linop reset` | fix (D19: explicit paths, protected list, verified backup); `packages.extra` + `custom_file` names join `--uninstall` (protected excluded, installed only); orphan sweep `reset.orphans` (named, no blanket autoremove); `--shell` = login shell → bash + `~/.zshrc` backed up and removed (UNIT; native NOT TESTED) | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F11 | resume | recovery/journal.py | fix (never worked) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F12 | GPG / keyring reset | system/actions.py | fix (opt-in reset) | no | MIGRATED (UNIT) | N-A | N-A | N-A |
| F13 | reflector mirror benchmark | system/actions.py | keep + backup | yes | MIGRATED (UNIT) | N-A | N-A | N-A |
| F14 | speed test | core/preflight.py | keep; v3.1.0 3.11: "< 500 KiB/s slow connection" warning (`is_slow`, unknown → no warning) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F15 | yay-bin build | package/actions.py (InstallAurHelper) | keep (temp dir) | yes | MIGRATED (UNIT) | N-A | N-A | N-A |
| F16 | deps + system upgrade | system/actions.py | fix (no partial upgrade) | no | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F17 | GNOME settings (gno.conf) | desktop/gnome.py | keep (D8; D18 default wallpaper = solid black) | yes (dconf dump) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container) | MIGRATED (UNIT) |
| F18 | GNOME debloat | desktop/gnome.py | keep | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F19 | Gaming Mode + GPU drivers | gaming/actions.py (+ system multilib) | fix (decouple from GNOME, detect GPU); v3.1.0 3.4: `nvidia_drm.modeset` check as a doctor row + run-end warning (audit only, never changes the system, D20; UNIT; NATIVE NOT TESTED, needs the owner's NVIDIA machine) | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F20 | package engine (preview, pacs.txt, AUR split) | package/resolve.py + package/actions.py | keep (batch install); v3.1.0 3.2: summary screen shows download / installed size per package and totals (unknown sizes counted, a failing query never aborts); v3.1.0 3.3: per-package install result, a bad package no longer hides the others (partial = own exit code) | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container, v3.0 code; v3.1.0 additions UNIT) | MIGRATED (UNIT) |
| F21 | BlackArch manager | security/actions.py (BlackArch*) | fix (checksum, key, no --overwrite default); v3.1.0 3.5: prerequisites (JDK / rust / opencl) for `full`, multilib enabled for BlackArch, `pacman-key --delete` on removal, keyring reset switches `[blackarch]` off and back on (restored when the rebuild fails) | partial | MIGRATED (UNIT; strap.sh run itself NOT TESTED) | N-A | N-A | N-A |
| F22 | Hyprland (FAI_LinOP own config) | desktop/hyprland.py + dotfiles/manager.py | keep optional (D12, D24); v3.1.0 3.11: `nautilus` added to the hyprland group (config launches nautilus; v2.5 used dolphin) | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F22b | Hyprland theme installers (Ax-Shell, HyDE, ML4W, JaKooLit) | — | N-A in v3.0 (D24: deferred, not in v3.1.0; would be ONE-WAY, D16) | ONE-WAY | N-A | N-A | N-A | N-A |
| F23 | Terminator config + wallpapers | dotfiles/manager.py | keep + backup/diff (D10); wallpaper repo clone/pull into `~/Pictures/wallp` (`wallpaper.repo`, desktop/wallpaper.py; skipped with a warning without git credentials; native clone NOT TESTED; GNOME wallpaper keys NATIVE NOT TESTED); relative `wallpaper.file` resolves there | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container, v3.0 code; v3.1.0 additions UNIT) | MIGRATED (UNIT) |
| F24 | terminal emulator + theme | terminal/actions.py | fix (URLs, no overwrite; v3.0.1: Alacritty import via tomlkit, Starship line only when installed, user-edited preset kept); v3.1.0 3.9: `terminal.theme` gains `cyberpunk` (Kitty only) and `omni` (Alacritty only; other terminal → plan says "theme <x> not available for <terminal>", no change); new `kitty.conf` gets `font_family JetBrainsMono Nerd Font`, an existing one is never touched (D10); the alacritty-theme URL is pinned to commit `52d05307…` and the theme names were checked against it (9e06085); the pin itself is not re-verified against upstream in CI | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F25 | shell + prompt themes | terminal/actions.py | fix (no curl-pipe-sh: pinned git clones) | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container) | MIGRATED (UNIT) |
| F26 | security tools + dashboard | security/actions.py | keep; v3.1.0 3.6: first `freshclam` (only without a database; failure warns), `rkhunter --propupd` (only without a baseline), OpenSnitch autostart copy (idempotent, backed up), read-only security summary in `linop doctor` | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F27 | optimization steps | optimization/actions.py | fix (install deps, labels) | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F28 | security scans | security/actions.py (Scans) | keep (scope C-6) | n/a | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) |
| F29 | hardening sysctl + SSH | security/actions.py | fix (drop-in + sshd -t) | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F30 | Hardened Mode (OpenSnitch, USBGuard) | security/actions.py | fix (decouple from F29) | yes | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) |
| F31 | final summary | core/engine.py (report) | fix (from journal) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F32 | cleanup (orphans, cache) | optimization/actions.py (cleanup) | fix (no -Scc default; v3.0.1: `purge` really clears, apt/dnf orphans simulated and listed first) | no | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F33 | reboot prompt | cli.py (reboot prompt) | fix (owner decision 2026-11-27: only when needed — prompt only when a flagged action ran; v2.5 asked always; code unchanged; no unit test covers the prompt in `cli.py`, hence NOT TESTED) | n/a | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) |
| F34 | enable libvirtd / AnyDesk services after install | package/actions.py (`service_actions`) | keep (v3.1.0 3.7): `libvirtd.service` when `qemu` / `virt-manager` is selected; `anydesk.service` only when AnyDesk resolves native (Arch AUR), none for Flatpak; unselected → no action | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F35 | interactive choice of terminal theme, zsh theme, Starship preset, GPU, cache cleanup, custom package file | core/wizard.py | keep (v3.1.0 3.10): the wizard asks terminal theme, zsh theme, Starship preset, `gaming.gpu`, `cleanup.cache`, `packages.custom_file`, `wallpaper.file` when the module is on (default = profile value, `-y` keeps it); keys not asked are listed in `PROFILE_ONLY` and marked "(profile only)" in the template | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| F36 | firejail `firecfg` | — | N-A (dead code in v2.5, `legacy/v2.5/setup.sh` 1569-1572) | n/a | N-A | N-A | N-A | N-A |
| N1 | monitor mode detection + layout (D13); rollback re-applies the previous GNOME layout | display/* | new | yes (GNOME, via Mutter) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| N2 | dotfile capture / diff (D10) | dotfiles/manager.py (capture, diff) | new | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| N3 | staged run: per module question → short summary → confirm → apply; answers saved after every module (D30, replaces D14); `linop apply` = batch, one confirmation | core/staged.py, core/wizard.py, core/profile.py | new | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| N4 | dry-run for every action | core/runner.py | new | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) |
| N5 | rollback (snapshot / file backup) | recovery/* | new (D6) | — | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container) | MIGRATED (UNIT) |

## v3.0.0 hardening (V300 list) — rows affected

| Item | Change | Rows |
|---|---|---|
| 1.2 / 1.11 | `dotfiles capture` shows a diff, takes one confirmation, writes bytes with backup + journal; `deploy` plan shows the diff (D10) | N2, F17, F22, F23 |
| 1.3 | a dry run writes no file (profile, journal, state) | N4 |
| 1.4 | `-y` keeps wizard defaults; opt-in sections stay off (D23 / D26) | N3 |
| 1.5 / 1.6 | a planning error is a failure (exit ≠ 0); dry run reports "would run" when a tool is missing; BlackArch confirmation in the plan | F21, F31, N4 |
| 1.7 / 1.8 | first backup of a file is never overwritten; unreadable root files are backed up via sudo; rollback survives partial failures and reports honestly (D6) | N5 |
| 1.10 | protected packages use each distro's own names (D19) | F10 |
| 1.12 | root refusal covers every file-writing sub-command (D15) | N3 |
| 1.9 | positions kept (only monitors right of a resized one move); twin monitors get distinct identities; GNOME-captured layout maps to the right Hyprland `desc:`; rollback re-applies the `display_before` layout through Mutter and reports FAILED otherwise (D13 / D6) | N1 |
| 1.13 | this matrix: gaps marked PARTIAL with their v3.1.0 item, missing v2.5 rows added | all |

## v3.1.0 (v2.5 parity gaps, items 3.1–3.12) — rows closed

| Item | Change | Rows |
|---|---|---|
| 3.1 | wallpaper repo clone/pull, relative `wallpaper.file` | F23 |
| 3.2 / 3.3 | package size preview, per-package install result | F20 |
| 3.4 | NVIDIA `nvidia_drm.modeset` audit | F19 |
| 3.5 / 3.6 | BlackArch prerequisites, first run of security tools, doctor summary | F21, F26 |
| 3.7 | libvirtd / AnyDesk services | F34 |
| 3.8 | reset parity (extra/custom packages, orphans, `--shell`) | F10 |
| 3.9 | Kitty Cyberpunk / Alacritty Omni, `kitty.conf`, pinned alacritty-theme | F24 |
| 3.10 | wizard asks the remaining profile keys | F35 |
| 3.11 | slow-connection warning, nautilus in the hyprland group, reboot prompt stays "only when needed" | F14, F22, F33 |
| 3.12 | this matrix, MIGRATION.md, CHANGELOG, README | all |

The v2.5 gaps tracked in the v3.1.0 list (items 3.1–3.11) are closed in v3.1.0. No row is PARTIAL, NOT MIGRATED or MISSING any more. Remaining honest limits are named per row: nothing here ran natively (hardware, desktop, real package installs, strap.sh), and F33 has no unit test.
