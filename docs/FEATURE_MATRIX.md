# ArCoN v2.5 → FAI_LinOP v3.0 Feature Parity Matrix

Source of feature IDs: `docs/AUDIT.md` §2. Update this file in every phase.

**Action:** keep (same intent/behaviour) · replace (same intent, different mechanism) · fix (v2.5 behaviour is a bug/unsafe; not ported as-is without owner approval) · N-A (with reason) · new
**Reversible:** yes · partial · no · ONE-WAY (third-party code, D16)
**Status values:** NOT MIGRATED · PARTIAL (label: what exists is tested at that level; the gap and its v3.1.0 list item are named in the Action column) · MIGRATED (label) where label = UNIT / INTEGRATION / VM / NATIVE — the highest level actually run. Core items are distro-independent, so all Linux columns carry the same label.

| ID | Feature | Target module | Action | Reversible | Arch | Debian | Ubuntu | Fedora | Windows | macOS |
|---|---|---|---|---|---|---|---|---|---|---|
| F01 | stale pacman lock removal | core/preflight.py | fix (ask, never silent) | n/a | MIGRATED (UNIT) | N-A | N-A | N-A | stub | stub |
| F02 | internet check | core/preflight.py | fix | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F03 | disk ≥ 10 GB | core/preflight.py | keep | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F04 | sudo check | core/preflight.py | keep | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F05 | Live-USB detection | core/preflight.py | fix (was commented out) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F06 | OS detection | platform/detect.py | fix (parse, don't source) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F07 | package-manager selection | package/providers.py | replace | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT; dry-run against real apt in Ubuntu 24.04 container) | MIGRATED (UNIT) | stub | stub |
| F08 | package groups (76 → 7 groups, 70 kept, 6 removed: D28) | fai_linop/data/packages.toml | replace (per-distro names) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT; dry-run against real apt in Ubuntu 24.04 container) | MIGRATED (UNIT) | stub | stub |
| F09 | main menu | cli.py / core/wizard.py | replace (D14) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F10 | Smart Factory Reset | recovery/reset.py + `linop reset` | fix (D19: explicit paths, protected list, verified backup); `packages.extra` + `custom_file` names join `--uninstall` (protected excluded, installed only); orphan sweep `reset.orphans` (named, no blanket autoremove); `--shell` = login shell → bash + `~/.zshrc` backed up and removed (UNIT; native NOT TESTED) | partial | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | stub | stub |
| F11 | resume | recovery/journal.py | fix (never worked) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F12 | GPG / keyring reset | system/actions.py | fix (opt-in reset) | no | MIGRATED (UNIT) | N-A | N-A | N-A | N-A | N-A |
| F13 | reflector mirror benchmark | system/actions.py | keep + backup | yes | MIGRATED (UNIT) | N-A | N-A | N-A | N-A | N-A |
| F14 | speed test | core/preflight.py | keep; v3.1.0 3.11: "< 500 KiB/s slow connection" warning (`is_slow`, unknown → no warning) | n/a | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | stub | stub |
| F15 | yay-bin build | package/actions.py (InstallAurHelper) | keep (temp dir) | yes | MIGRATED (UNIT) | N-A | N-A | N-A | N-A | N-A |
| F16 | deps + system upgrade | system/actions.py | fix (no partial upgrade) | no | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F17 | GNOME settings (gno.conf) | desktop/gnome.py | keep (D8; D18 default wallpaper = solid black) | yes (dconf dump) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container) | MIGRATED (UNIT) | N-A | N-A |
| F18 | GNOME debloat | desktop/gnome.py | keep | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | N-A | N-A |
| F19 | Gaming Mode + GPU drivers | gaming/actions.py (+ system multilib) | fix (decouple from GNOME, detect GPU); modeset check: doctor + run-end warning (audit only, D20; UNIT, NATIVE NOT TESTED) | partial | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | stub | stub |
| F20 | package engine (preview, pacs.txt, AUR split) | package/resolve.py + package/actions.py | keep (batch install); gap: no size preview (v3.1.0 3.2), no per-package result (v3.1.0 3.3) | partial | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (INTEGRATION: real run, Ubuntu 24.04 container) | PARTIAL (UNIT) | stub | stub |
| F21 | BlackArch manager | security/actions.py (BlackArch*) | fix (checksum, key, no --overwrite default); gap: prerequisite JDK/rust/opencl, multilib for BlackArch, `pacman-key --delete` on removal, keyring reset with `[blackarch]` off → v3.1.0 3.5 | partial | PARTIAL (NOT TESTED) | N-A | N-A | N-A | N-A | N-A |
| F22 | Hyprland (FAI_LinOP own config) | desktop/hyprland.py + dotfiles/manager.py | keep optional (D12, D24); v3.1.0 3.11: `nautilus` added to the hyprland group (config launches nautilus; v2.5 used dolphin) | yes | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | N-A | N-A |
| F22b | Hyprland theme installers (Ax-Shell, HyDE, ML4W, JaKooLit) | — | N-A in v3.0 (D24: deferred to a release after v3.1; would be ONE-WAY, D16) | ONE-WAY | N-A | N-A | N-A | N-A | N-A | N-A |
| F23 | Terminator config + wallpapers | dotfiles/manager.py | keep + backup/diff (D10); wallpaper repo clone/pull into `~/Pictures/wallp` (`wallpaper.repo`, desktop/wallpaper.py; skipped with a warning without git credentials; native clone NOT TESTED); relative `wallpaper.file` resolves there | yes | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (INTEGRATION: real run, Ubuntu 24.04 container) | PARTIAL (UNIT) | N-A | stub |
| F24 | terminal emulator + theme | terminal/actions.py | fix (URLs, no overwrite; v3.0.1: Alacritty import via tomlkit, Starship line only when installed, user-edited preset kept); v3.1.0 3.9: `terminal.theme` gains `cyberpunk` (Kitty only) and `omni` (Alacritty only; other terminal → plan says "theme <x> not available for <terminal>", no change); new `kitty.conf` gets `font_family JetBrainsMono Nerd Font`, an existing one is never touched (D10). Open: Alacritty theme URL still `master` (commit pin + theme-name check against upstream need network, NOT DONE) | yes | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | stub | stub |
| F25 | shell + prompt themes | terminal/actions.py | fix (no curl-pipe-sh: pinned git clones) | partial | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container) | MIGRATED (UNIT) | stub | stub |
| F26 | security tools + dashboard | security/actions.py | keep; gap: first `freshclam`, `rkhunter --propupd`, OpenSnitch autostart, security summary table → v3.1.0 3.6 | partial | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | stub | stub |
| F27 | optimization steps | optimization/actions.py | fix (install deps, labels) | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F28 | security scans | security/actions.py (Scans) | keep (scope C-6) | n/a | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | stub | stub |
| F29 | hardening sysctl + SSH | security/actions.py | fix (drop-in + sshd -t) | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F30 | Hardened Mode (OpenSnitch, USBGuard) | security/actions.py | fix (decouple from F29) | yes | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | MIGRATED (NOT TESTED) | stub | stub |
| F31 | final summary | core/engine.py (report) | fix (from journal) | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F32 | cleanup (orphans, cache) | optimization/actions.py (cleanup) | fix (no -Scc default; v3.0.1: `purge` really clears, apt/dnf orphans simulated and listed first) | no | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F33 | reboot prompt | cli.py (reboot prompt) | fix (owner decision 2026-11-27: only when needed — prompt only when a flagged action ran; v2.5 asked always; code unchanged) | n/a | PARTIAL (NOT TESTED) | PARTIAL (NOT TESTED) | PARTIAL (NOT TESTED) | PARTIAL (NOT TESTED) | stub | stub |
| F34 | enable libvirtd / AnyDesk services after install | system/actions.py (EnableService) | keep (v3.1.0 3.7): `libvirtd.service` when `qemu` / `virt-manager` is selected; `anydesk.service` only when AnyDesk resolves native (Arch AUR), none for Flatpak; unselected → no action | yes | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | PARTIAL (UNIT) | stub | stub |
| F35 | interactive choice of terminal theme, zsh theme, Starship preset, GPU, cache cleanup, custom package file | core/wizard.py | keep (v3.1.0 3.10): the wizard asks terminal theme, zsh theme, Starship preset, `gaming.gpu`, `cleanup.cache`, `packages.custom_file`, `wallpaper.file` when the module is on (default = profile value, `-y` keeps it); keys not asked are listed in `PROFILE_ONLY` and marked "(profile only)" in the template | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| F36 | firejail `firecfg` | — | N-A (dead code in v2.5, `legacy/v2.5/setup.sh` 1569-1572) | n/a | N-A | N-A | N-A | N-A | N-A | N-A |
| N1 | monitor mode detection + layout (D13); rollback re-applies the previous GNOME layout | display/* | new | yes (GNOME, via Mutter) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| N2 | dotfile capture / diff (D10) | dotfiles/manager.py (capture, diff) | new | yes | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| N3 | wizard → summary → single confirm, saved answers (D14) | core/wizard.py, core/profile.py | new | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| N4 | dry-run for every action | core/runner.py | new | n/a | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (UNIT) | stub | stub |
| N5 | rollback (snapshot / file backup) | recovery/* | new (D6) | — | MIGRATED (UNIT) | MIGRATED (UNIT) | MIGRATED (INTEGRATION: real run, Ubuntu 24.04 container) | MIGRATED (UNIT) | stub | stub |

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

Gaps against v2.5 are tracked in the v3.1.0 list (items 3.1–3.11) and named per row above.
