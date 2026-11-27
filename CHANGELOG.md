# Changelog

## v3.0.2: Fedora login shell fix (2026-11-27)

### Fixed
- Fedora: `chsh` comes from `util-linux` (catalog id `util-linux-user`). On Fedora 45 `util-linux-user` is only a provide of `util-linux`, so the v3.0.1 catalog check reported it missing and the login shell was not changed (CI fedora job red on the v3.0.1 tag).

### Test status
UNIT: 240 passed, 3 skipped (local `pytest`). INTEGRATION (container): GitHub CI run 46048542414 on `bd06ba6` — lint, unit, archlinux, debian:stable, ubuntu:24.04, fedora (45) all green. Fedora 44 and older NOT TESTED (`chsh` may still live in a separate `util-linux-user` there). NATIVE: NOT TESTED.

## v3.0.1: packages resolved in install order, safer shell and cleanup (2026-11-27)

Bug-fix release from the V301 review (8 items). No new features; no owner dotfile changed (D8).

### Fixed
- **Packages (D22):** a name whose source the plan cannot know without side effects — Arch multilib enabled by this run, an empty or old apt index, an AUR helper not built yet — is shown as `deferred: resolved at apply` and resolved again at apply time in D22 order (repo → AUR → Flatpak → reported). Planning never syncs a database. The AUR helper is built only when a package really needs it; names found nowhere fall back to Flatpak instead of breaking the whole yay transaction.
- **Zsh:** `plugins=(…)` is written before `source …oh-my-zsh.sh`, so autosuggestions and syntax highlighting load. Oh-My-Zsh and plugins are cloned into a temporary directory and moved into place; a half-made clone counts as missing on the next run; `verify()` checks them.
- **Alacritty:** the theme is added to `general.import` with `tomlkit` (valid TOML, comments and order kept, no duplicate key).
- **Starship:** the `starship init` line is written only when Starship is installed or will be (otherwise the plan says "unavailable"); the preset no longer overwrites a `starship.toml` the user edited.
- **Cleanup:** `purge` really empties the package cache and `verify()` checks it; apt/dnf orphans and GNOME debloat removals are simulated first and listed by name; debloat stops when the simulation would remove extra packages.
- **System update:** one `pacman -Syu` transaction (no partial sync); an unknown distro family is reported instead of skipped silently.
- **NVIDIA:** the reboot notice belongs to the driver action that needs it.
- **Prerequisites:** `util-linux-user` (Fedora `chsh`) and `ubuntu-drivers-common` (Ubuntu NVIDIA) come from the package catalog; CI no longer installs `util-linux-user` by hand.

### Test status
UNIT: 240 passed, 3 skipped (local `pytest`, commit `2912fcd`). INTEGRATION (container) runs on GitHub CI after push. NATIVE: NOT TESTED.

## v3.0.0: ArCoN v2.5 rewritten in Python as FAI_LinOP (2026-11-27)

Complete rewrite of the 1885-line ArCoN v2.5 Bash script in Python 3.11+ (`linop`). v2.5 stays in `legacy/v2.5/` and at tag `v2.5.0`.

**Renamed (2026-11-27):** ArCoN v3 is now **FAI_LinOP**. Command `arcon` → `linop`, Python package `arcon` → `fai_linop`, own directories `~/.config/arcon`, `~/.local/state/arcon` → `~/.config/linop`, `~/.local/state/linop`, environment variables `ARCON_*` → `LINOP_*`. ArCoN v2.5 keeps its name.

### New
- One profile (TOML) instead of ~40 prompts during the install; wizard asks everything first, then **one** confirmation.
- `linop plan` (dry run), `resume`, `rollback`, `runs`, `doctor`, `display show|capture`, `dotfiles diff|capture`, `profile init|show|validate`, `reset`.
- JSON-lines journal for every run; verified per-file backups; GNOME settings backed up with `dconf dump`; Snapper/Timeshift snapshot when configured.
- Monitors: best mode per monitor detected, owner's layout kept, fallback when a mode does not work (GNOME via Mutter, Hyprland generated block).
- GPU detection (NVIDIA open modules / DKMS + headers / PRIME, AMD, Intel) — no more GPU menu.
- Debian, Ubuntu and Fedora support through a per-distro package catalog with Flatpak fallback.
- Package groups reorganised: base, essentials, media, cyber, remote, privacy, power.
- One-line install: `git clone https://github.com/MrFedai/FAI_LinOP.git ~/FAI_LinOP && ~/FAI_LinOP/setup.sh`; on Debian/Ubuntu `setup.sh` installs `python3-venv` itself when it is missing.

### Fixed (v2.5 bugs)
- Resume never worked (log was never written).
- "Internet OK" printed without a check; live-USB check commented out; stray `END` command.
- Firejail step never ran; UFW and ZRAM configured without being installed.
- Alacritty/Kitty theme downloads saved 404 pages as config and overwrote `alacritty.toml`.
- Gaming only offered after GNOME settings; GameMode config written where GameMode never reads it.
- Every run deleted the pacman keyring and sync DB; `pacman -Scc` removed the downgrade path.
- Unknown package names were sent to yay; one `pacman -S` per package.
- Factory reset deleted `~/.config/<package>` for every package (incl. browser/editor data) and ignored the protected list.
- `curl | sh` installers, BlackArch without checksum and with `--overwrite '*'`, SSH edited with `sed` and no validation, UFW enabled before allowing SSH, `/etc/os-release` sourced.
- Final summary printed success unconditionally.

### Hardened before release (V300 review)
- `linop dotfiles capture` shows the diff, asks once, writes byte-exact with a backup and a journal entry; `deploy` plans show the diff (D10).
- A dry run writes no file at all (profile, journal, state); `-y` keeps wizard defaults, opt-in sections stay off.
- A planning error is a failure (exit ≠ 0, journal `run_end`); a dry run reports "would run" when a tool is missing; the BlackArch confirmation is part of the plan.
- Backups: the first backup of a file is never overwritten; root-only files are backed up through sudo. Rollback reports every item and keeps going after a failure (D6).
- Monitors (D13): positions are kept (only monitors right of a resized one move), twin monitors no longer collide, a GNOME-captured layout maps to the right Hyprland `desc:`, and `linop rollback` re-applies the previous GNOME layout through Mutter (FAILED line when it cannot).
- Factory reset protects packages by each distro's own names (D19); root refusal covers every file-writing sub-command (D15).
- `docs/FEATURE_MATRIX.md`: features with gaps against v2.5 are marked PARTIAL with their v3.1.0 item.

### Removed
- Third-party Hyprland theme installers (Ax-Shell, Hyprdots/HyDE, ML4W, JaKooLit) — deferred to v3.1.
- `wallp/` (licensing) — optional private wallpaper repository; default background is solid black.
- Packages: x11vnc, stacer, stirling-pdf, pinokio, flameshot, switcheroo.

### Unchanged on purpose
- Your dotfiles (`configs/`) — deployed byte-identical except the documented D18 substitutions.
