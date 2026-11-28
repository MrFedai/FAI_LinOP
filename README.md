# FAI_LinOP v3

**Set up a Linux machine from one profile — packages, GNOME, monitors, shell, gaming, security — with a plan you see first, a journal of every change and a rollback.**

[![CI](https://github.com/MrFedai/FAI_LinOP/actions/workflows/ci.yml/badge.svg)](https://github.com/MrFedai/FAI_LinOP/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/Python-3.11%2B-blue)
![Status](https://img.shields.io/badge/v3.1.0-native%20test%20pending-yellow)

## Install — one line

```bash
git clone https://github.com/MrFedai/FAI_LinOP.git ~/FAI_LinOP && ~/FAI_LinOP/setup.sh
```

- Run it as your **normal user**, not with `sudo` — FAI_LinOP asks for sudo only for the commands that need it.
- Needs `git` (`sudo pacman -S git` · `sudo apt install git` · `sudo dnf install git`).
- `setup.sh` only prepares [uv](https://docs.astral.sh/uv/) (distro package on Arch/Fedora; on Debian/Ubuntu `python3-venv` + uv in a private venv — never `curl | sh`) and starts the setup, **one module at a time: question → short summary → confirm → apply → next module**.

| Want to… | Run |
|---|---|
| see what would change first (nothing is modified) | `~/FAI_LinOP/setup.sh plan` |
| use the owner's profile | `~/FAI_LinOP/setup.sh --profile ~/FAI_LinOP/profiles/mrfedai.toml` |
| update FAI_LinOP | `git -C ~/FAI_LinOP pull` |
| undo the file and monitor-layout changes of the last run | `~/FAI_LinOP/setup.sh rollback` |

## What is FAI_LinOP?

FAI_LinOP turns a fresh Linux install into *your* machine. You describe the result once in a TOML profile — which package groups, which desktop settings, which shell, gaming or security tools — and FAI_LinOP does the rest on Arch, Debian, Ubuntu or Fedora.

v3 is a rewrite of [ArCoN v2.5](legacy/v2.5/README.md), a 1885-line Bash script, in Python. The working v2.5 stays at [MrFedai/ArCoN](https://github.com/MrFedai/ArCoN); this repository keeps its full history (tag `v2.5.0`). Every v2.5 feature is kept, fixed or explicitly marked in [docs/FEATURE_MATRIX.md](docs/FEATURE_MATRIX.md).

What makes v3 different from a setup script:

- **One module at a time.** Each module (system, packages, GNOME, …) is asked, summarised and applied before the next one is even asked about — no long questionnaire up front, no long wait afterwards. Output is short; `-v` shows every package, setting and service.
- **Journal + rollback.** Every run is logged; changed files and GNOME settings are backed up and can be restored. Snapper/Timeshift snapshots are used when available.
- **Idempotent.** Run it again and it prints "Nothing to do" — or continues where an interrupted run stopped (`linop resume`).
- **Your dotfiles stay yours.** `configs/` (GNOME `gno.conf`, Terminator, Hyprland) is deployed byte-identical in its native format; only documented substitutions (user name, wallpaper) are made.
- **Nothing is guessed.** Package names are mapped per distro (repo → AUR → Flatpak); anything missing is reported, not improvised.

### What it sets up

| Module | What it does |
|---|---|
| system | full upgrade; Arch: mirror ranking, multilib, optional keyring reset |
| packages | groups (base, essentials, media, cyber, remote, privacy, power) from the distro repos, AUR (Arch) or Flatpak fallback; size preview in the summary, per-package result, libvirtd / AnyDesk services |
| gnome | dark theme, keybindings, app folders from `configs/gno.conf`; optional debloat |
| wallpaper | solid black by default; optional private repo cloned to `~/Pictures/wallp` |
| display | detects every monitor's best resolution/refresh rate, keeps your layout, falls back if a mode does not work |
| hyprland | optional desktop with FAI_LinOP's own config and a generated monitor block |
| dotfiles | deploys `configs/`; `linop dotfiles diff\|capture` compares or copies them back |
| terminal / shell | Terminator/Kitty/Alacritty themes (incl. Kitty Cyberpunk, Alacritty Omni); Zsh + Oh-My-Zsh (pinned commits), Fish/Bash + Starship |
| gaming | Steam, GameMode, MangoHud; GPU detected automatically (NVIDIA open/DKMS, AMD, Intel) |
| security | all opt-in: firewall, sysctl hardening, SSH hardening, ClamAV, OpenSnitch, USBGuard, scans (first signature / baseline run, summary in `linop doctor`); BlackArch on Arch with its prerequisites |
| optimization / cleanup | ZRAM, SSD TRIM, Bluetooth; orphaned packages, package cache (keeps recent versions); `linop reset` also removes your extra packages and can restore bash |

## How a run works

```
for each module, in order (System, Packages, Monitors, GNOME, Hyprland, Gaming, Dotfiles, Terminal, Shell,
                           Security, BlackArch, Optimization, Cleanup):
    "want this module?" -> its own questions -> short summary of the changes -> confirm
      -> (first time only: preflight — disk, network, live ISO, pacman lock, sudo — and a Snapper/Timeshift snapshot)
      -> apply + verify each action
then: report from real results -> reboot prompt only if needed
```

A module you decline is skipped; your answers are saved after every module and are the defaults next time (Enter keeps them).
Confirming a summary is `Enter` — except when the module contains a high-risk or one-way action, where the default is "no".
`linop apply` is the unattended form: the whole saved profile, one plan, one confirmation (or `--yes`).

```
short output:   • Install packages from the distro repositories: 41 package(s) — 40 repo, 1 AUR
with -v:        the full table (every package name, setting and service, risk, reversibility)
```

- **Dry run** (`linop plan`, `-n`): read-only probes run, every change is only shown; no file is written (no profile, journal or state). GNOME monitor changes are checked by Mutter itself ("verify" mode).
- **Runs as your user** (D15): every command that changes or writes files refuses to run as root; only single commands are elevated through sudo.
- **Journal**: `~/.local/state/linop/runs/<run>/journal.jsonl` — drives `linop resume` and `linop rollback`.
- **Rollback**: files, GNOME settings and the GNOME monitor layout are restored (each item reported, failures marked FAILED); installed packages are listed, never "rolled back" silently.

## Commands

`setup.sh` passes everything to `linop`, so `~/FAI_LinOP/setup.sh plan` = `linop plan`.

| Command | What it does |
|---|---|
| `linop` | staged setup: per module ask → review → apply |
| `linop plan` / `linop apply` | dry run / apply the whole saved profile with one confirmation (unattended: `--yes`) |
| `linop wizard` | answer all questions, save the profile, apply nothing |
| `linop resume` | continue an interrupted or failed run |
| `linop rollback [RUN]` | restore files, dconf and the GNOME monitor layout changed by a run (default: the latest real run; dry runs and rollbacks are never `latest`) |
| `linop runs` | list runs |
| `linop profile init\|show\|validate\|path` | documented profile template, effective values, checks |
| `linop display show\|capture` | monitors, best modes; save the current layout into the profile |
| `linop dotfiles diff\|capture` | compare deployed dotfiles with the repo; copy them back (diff shown, one confirmation, repo file backed up first) |
| `linop reset [--uninstall] [--gnome]` | Smart Factory Reset (backup first, typed `CLEAN`) |
| `linop doctor` | detected OS, GPU, disk, kernels, snapshot tool |

Global options work before or after the command: `--profile FILE`, `-n/--dry-run`, `-y/--yes` (never answers typed confirmations), `--keep-going`, `-v` (full tables instead of the short summary).

## Profile

Your answers are saved to `~/.config/linop/profile.toml` after every module and are the defaults of the next run. `linop profile init` writes a template with every key documented ([fai_linop/data/profile.template.toml](fai_linop/data/profile.template.toml)). Unknown keys and invalid values are errors. The owner's profile: [profiles/mrfedai.toml](profiles/mrfedai.toml).

## Platform status (honest)

| Platform | Status |
|---|---|
| Arch Linux | full scope; unit tested; container CI (real run) under investigation; native test on the owner's machine pending |
| Debian / Ubuntu | full scope (one provider); real `apply` + `rollback` pass in container CI on debian:stable and ubuntu:24.04 (packages, dconf, dotfiles, shell); one-line install verified on a fresh minimal Ubuntu 24.04 |
| Fedora | full scope; unit tested; container CI (real run) under investigation |
| Derivatives (EndeavourOS, CachyOS, Mint, Nobara, …) | run as their parent family, marked *experimental* |
| Windows, macOS | not part of this project (separate repository); `linop` exits with "Linux only" |

Nothing has been run on real hardware yet (GPU drivers, monitors, Hyprland). Details and evidence: [docs/TESTING.md](docs/TESTING.md), [docs/PROGRESS.md](docs/PROGRESS.md).

## Coming from v2.5

Read [docs/MIGRATION.md](docs/MIGRATION.md). The v2.5 script is kept unchanged in `legacy/v2.5/` and at tag `v2.5.0`.

## Development

```bash
uv run pytest                                      # unit + characterization + golden tests
LINOP_REAL_RUN=1 uv run pytest tests/integration   # REAL installs — disposable container/VM only
python3 scripts/verify_catalog.py                  # check the package catalog on the current distro
```

Project rules and decisions: [CLAUDE.md](CLAUDE.md). Audit of v2.5: [docs/AUDIT.md](docs/AUDIT.md).

## License

MIT — see [LICENSE](LICENSE). Hyprland, Oh-My-Zsh, Starship and the other tools FAI_LinOP installs keep their own licences.
